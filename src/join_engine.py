"""Join engine abstraction and pandas implementation for join/union steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import pandas as pd

from .errors import UserInputError
from .join_report import build_asof_diagnostics, build_join_diagnostics, build_union_diagnostics
from .models import (
    UNION_DROP,
    UNION_KEEP_AS_NEW,
    JoinExecutionResult,
    JoinPlan,
    JoinStep,
    JoinStepResult,
)

_TMP_LEFT_ROW_ID = "__ds_left_row_id__"
_TMP_RIGHT_ROW_ID = "__ds_right_row_id__"


class JoinEngine(Protocol):
    """Protocol for pluggable join engines (e.g., asof/range/fuzzy later)."""

    def execute_step(
        self,
        left_df: pd.DataFrame,
        right_df: pd.DataFrame,
        step: JoinStep,
        row_explosion_warn_ratio: float,
    ) -> JoinStepResult:
        """Execute one join/union step."""


@dataclass
class PandasEquiJoinEngine:
    """Default pandas-based engine for equi/asof joins and union."""

    def execute_step(
        self,
        left_df: pd.DataFrame,
        right_df: pd.DataFrame,
        step: JoinStep,
        row_explosion_warn_ratio: float,
    ) -> JoinStepResult:
        if step.operation == "union":
            return _execute_union_step(left_df, right_df, step, row_explosion_warn_ratio)

        if step.join_algorithm == "asof":
            return _execute_asof_join_step(left_df, right_df, step, row_explosion_warn_ratio)

        return _execute_equi_join_step(left_df, right_df, step, row_explosion_warn_ratio)


def _execute_equi_join_step(
    left_df: pd.DataFrame,
    right_df: pd.DataFrame,
    step: JoinStep,
    row_explosion_warn_ratio: float,
) -> JoinStepResult:
    _validate_equi_step_inputs(left_df, right_df, step)

    merged = pd.merge(
        left_df,
        right_df,
        how=step.join_type,
        left_on=step.left_keys,
        right_on=step.right_keys,
        suffixes=step.suffixes,
        indicator=True,
    )
    diagnostics = build_join_diagnostics(
        step_id=step.step_id,
        join_type=step.join_type,
        left_df=left_df,
        right_df=right_df,
        merged_with_indicator=merged,
        left_keys=step.left_keys,
        right_keys=step.right_keys,
        row_explosion_warn_ratio=row_explosion_warn_ratio,
    )
    output_df = _resolve_conflicts(merged, left_df, right_df, step)
    return JoinStepResult(
        step=step,
        output_df=output_df,
        report=diagnostics.report,
        unmatched_left_df=diagnostics.unmatched_left_df,
        unmatched_right_df=diagnostics.unmatched_right_df,
    )


def _execute_asof_join_step(
    left_df: pd.DataFrame,
    right_df: pd.DataFrame,
    step: JoinStep,
    row_explosion_warn_ratio: float,
) -> JoinStepResult:
    _validate_asof_step_inputs(left_df, right_df, step)

    left_key = step.left_keys[0]
    right_key = step.right_keys[0]
    left_by = step.left_by_keys or None
    right_by = step.right_by_keys or None

    left_work = left_df.copy().reset_index(drop=True)
    right_work = right_df.copy().reset_index(drop=True)
    left_work[_TMP_LEFT_ROW_ID] = range(len(left_work))
    right_work[_TMP_RIGHT_ROW_ID] = range(len(right_work))

    _coerce_asof_key_columns(left_work, right_work, left_key, right_key)

    # pandas.merge_asof requires the "on" key to be globally sorted.
    # Sort by the asof key first, then by group keys.
    left_sort_cols = [left_key, *(left_by or [])]
    right_sort_cols = [right_key, *(right_by or [])]
    left_sorted = left_work.sort_values(left_sort_cols, kind="mergesort").reset_index(drop=True)
    right_sorted = right_work.sort_values(right_sort_cols, kind="mergesort").reset_index(drop=True)

    tolerance = _parse_asof_tolerance(step.asof_tolerance, left_sorted[left_key])

    try:
        merged = pd.merge_asof(
            left_sorted,
            right_sorted,
            left_on=left_key,
            right_on=right_key,
            left_by=left_by,
            right_by=right_by,
            direction=step.asof_direction,
            tolerance=tolerance,
            allow_exact_matches=step.asof_allow_exact_matches,
            suffixes=step.suffixes,
        )
    except Exception as exc:
        raise UserInputError(
            f"{step.step_id}: asof join の実行に失敗しました。キーの型・ソート可能性・NULL値・tolerance設定を確認してください: {exc}"
        ) from exc

    matched_left_mask = merged[_TMP_RIGHT_ROW_ID].notna()
    matched_left_ids = set(merged.loc[matched_left_mask, _TMP_LEFT_ROW_ID].astype(int).tolist())
    matched_right_ids = set(merged.loc[matched_left_mask, _TMP_RIGHT_ROW_ID].astype(int).tolist())

    # Unmatched extracts should use original (non-sorted) row order.
    left_unmatched_mask_original = ~left_work[_TMP_LEFT_ROW_ID].isin(matched_left_ids)
    diagnostics = build_asof_diagnostics(
        step_id=step.step_id,
        left_df=left_work.drop(columns=[_TMP_LEFT_ROW_ID]),
        right_df=right_work.drop(columns=[_TMP_RIGHT_ROW_ID]),
        output_df=merged.drop(columns=[_TMP_LEFT_ROW_ID]),
        matched_left_mask=~left_unmatched_mask_original.reset_index(drop=True),
        matched_right_row_ids=matched_right_ids,
        right_row_id_series=right_work[_TMP_RIGHT_ROW_ID],
        row_explosion_warn_ratio=row_explosion_warn_ratio,
        direction=step.asof_direction,
        tolerance=step.asof_tolerance,
    )

    output_df = merged.drop(columns=[_TMP_LEFT_ROW_ID, _TMP_RIGHT_ROW_ID], errors="ignore")
    output_df = _resolve_conflicts(output_df, left_df, right_df, step)
    return JoinStepResult(
        step=step,
        output_df=output_df,
        report=diagnostics.report,
        unmatched_left_df=diagnostics.unmatched_left_df,
        unmatched_right_df=diagnostics.unmatched_right_df,
        details={"operation": "join", "algorithm": "asof"},
    )


def _execute_union_step(
    left_df: pd.DataFrame,
    right_df: pd.DataFrame,
    step: JoinStep,
    row_explosion_warn_ratio: float,
) -> JoinStepResult:
    _validate_union_step_inputs(right_df, step)

    left_cols = [str(c) for c in left_df.columns]
    right_cols = [str(c) for c in right_df.columns]
    mapping = {str(k): str(v) for k, v in step.union_column_mapping.items()}

    mapped_targets: dict[str, str] = {}
    rename_map: dict[str, str] = {}
    drop_cols: list[str] = []
    kept_new_columns = 0
    dropped_columns = 0

    right_work = right_df.copy()
    for col in right_cols:
        target = mapping.get(col, "")
        if target in ("", None):
            target = col if col in left_cols else UNION_KEEP_AS_NEW

        if target == UNION_DROP:
            drop_cols.append(col)
            dropped_columns += 1
            continue

        if target == UNION_KEEP_AS_NEW:
            final_name = _make_safe_union_new_column_name(col, left_cols, rename_map.values(), step.union_right_column_suffix)
            if final_name != col:
                rename_map[col] = final_name
            kept_new_columns += 1
            continue

        if target not in left_cols:
            raise UserInputError(f"{step.step_id}: 縦連結の列対応先が左側に存在しません: {col} -> {target}")
        if target in mapped_targets:
            raise UserInputError(
                f"{step.step_id}: 縦連結の列対応で複数の右列が同じ左列に割り当てられています: {mapped_targets[target]}, {col} -> {target}"
            )
        mapped_targets[target] = col
        if col != target:
            rename_map[col] = target

    if drop_cols:
        right_work = right_work.drop(columns=drop_cols, errors="ignore")
    if rename_map:
        right_work = right_work.rename(columns=rename_map)

    if step.union_add_source_column:
        source_col = step.union_source_column_name or "_source_table"
        right_value = step.union_source_value or (step.right_table_id or "right")
        left_value = "current_result"
        # Avoid colliding with existing columns by suffixing once if needed.
        if source_col in left_df.columns or source_col in right_work.columns:
            source_col = _make_safe_union_new_column_name(source_col, left_cols, right_work.columns, "_src")
        left_work = left_df.copy()
        left_work[source_col] = left_value
        right_work = right_work.copy()
        right_work[source_col] = right_value
    else:
        left_work = left_df.copy()

    union_columns = list(left_work.columns)
    for col in right_work.columns:
        if col not in union_columns:
            union_columns.append(str(col))

    left_aligned = left_work.reindex(columns=union_columns)
    right_aligned = right_work.reindex(columns=union_columns)
    output_df = pd.concat([left_aligned, right_aligned], ignore_index=True, sort=False)

    mapped_columns = len(mapped_targets)
    diagnostics = build_union_diagnostics(
        step_id=step.step_id,
        left_df=left_df,
        right_df=right_df,
        output_df=output_df,
        mapped_columns=mapped_columns,
        kept_new_columns=kept_new_columns,
        dropped_columns=dropped_columns,
        row_explosion_warn_ratio=row_explosion_warn_ratio,
    )
    return JoinStepResult(
        step=step,
        output_df=output_df,
        report=diagnostics.report,
        unmatched_left_df=diagnostics.unmatched_left_df,
        unmatched_right_df=diagnostics.unmatched_right_df,
        details={
            "operation": "union",
            "mapped_columns": mapped_columns,
            "kept_new_columns": kept_new_columns,
            "dropped_columns": dropped_columns,
        },
    )


def _make_safe_union_new_column_name(
    col: str, left_cols: list[str], existing_new_names: object, suffix: str
) -> str:
    existing = set(str(v) for v in existing_new_names)
    candidate = col
    if candidate not in left_cols and candidate not in existing:
        return candidate
    base = f"{col}{suffix or '_u'}"
    candidate = base
    counter = 2
    while candidate in left_cols or candidate in existing:
        candidate = f"{base}{counter}"
        counter += 1
    return candidate


def _validate_step_inputs(left_df: pd.DataFrame, right_df: pd.DataFrame, step: JoinStep) -> None:
    if step.operation == "union":
        _validate_union_step_inputs(right_df, step)
        return
    if step.join_algorithm == "asof":
        _validate_asof_step_inputs(left_df, right_df, step)
        return
    _validate_equi_step_inputs(left_df, right_df, step)


def _validate_equi_step_inputs(left_df: pd.DataFrame, right_df: pd.DataFrame, step: JoinStep) -> None:
    if step.operation != "join":
        raise UserInputError(f"{step.step_id}: この検証関数は join ステップ専用です。")
    if not step.left_keys or not step.right_keys:
        raise UserInputError(f"{step.step_id}: キー列を1つ以上選択してください。")
    if len(step.left_keys) != len(step.right_keys):
        raise UserInputError(f"{step.step_id}: 左右のキー列数が一致していません。")
    missing_left = [c for c in step.left_keys if c not in left_df.columns]
    missing_right = [c for c in step.right_keys if c not in right_df.columns]
    if missing_left:
        raise UserInputError(f"{step.step_id}: 左キー列が見つかりません: {', '.join(missing_left)}")
    if missing_right:
        raise UserInputError(f"{step.step_id}: 右キー列が見つかりません: {', '.join(missing_right)}")
    if step.join_type not in {"inner", "left", "right", "outer"}:
        raise UserInputError(f"{step.step_id}: 未対応の結合種別です: {step.join_type}")


def _validate_asof_step_inputs(left_df: pd.DataFrame, right_df: pd.DataFrame, step: JoinStep) -> None:
    if step.operation != "join":
        raise UserInputError(f"{step.step_id}: asof join は join ステップとして設定してください。")
    if step.join_type != "left":
        raise UserInputError(f"{step.step_id}: asof join は left join のみ対応です。")
    if len(step.left_keys) != 1 or len(step.right_keys) != 1:
        raise UserInputError(f"{step.step_id}: asof join は時間キーを左右1列ずつ指定してください。")
    if len(step.left_by_keys) != len(step.right_by_keys):
        raise UserInputError(f"{step.step_id}: asof join の by キー列数が左右で一致していません。")
    missing_left = [c for c in [*step.left_keys, *step.left_by_keys] if c not in left_df.columns]
    missing_right = [c for c in [*step.right_keys, *step.right_by_keys] if c not in right_df.columns]
    if missing_left:
        raise UserInputError(f"{step.step_id}: 左列が見つかりません: {', '.join(missing_left)}")
    if missing_right:
        raise UserInputError(f"{step.step_id}: 右列が見つかりません: {', '.join(missing_right)}")
    if step.asof_direction not in {"backward", "forward", "nearest"}:
        raise UserInputError(f"{step.step_id}: 未対応の asof direction です: {step.asof_direction}")


def _validate_union_step_inputs(right_df: pd.DataFrame, step: JoinStep) -> None:
    if not step.right_table_id:
        raise UserInputError(f"{step.step_id}: Unionする右テーブルが未選択です。")
    unknown_map_cols = [c for c in step.union_column_mapping.keys() if c not in right_df.columns]
    if unknown_map_cols:
        # Non-fatal in many UI flows; keep it strict at execution for predictable behavior.
        raise UserInputError(
            f"{step.step_id}: 縦連結の列対応に右テーブルに存在しない列が含まれています: {', '.join(unknown_map_cols)}"
        )


def _coerce_asof_key_columns(
    left_df: pd.DataFrame,
    right_df: pd.DataFrame,
    left_key: str,
    right_key: str,
) -> None:
    """Coerce asof key columns to a compatible type (numeric or datetime)."""
    left_s = left_df[left_key]
    right_s = right_df[right_key]

    if pd.api.types.is_datetime64_any_dtype(left_s) and pd.api.types.is_datetime64_any_dtype(right_s):
        return

    if pd.api.types.is_numeric_dtype(left_s) and pd.api.types.is_numeric_dtype(right_s):
        return

    # Try numeric first if both are mostly numeric strings.
    left_num = pd.to_numeric(left_s, errors="coerce")
    right_num = pd.to_numeric(right_s, errors="coerce")
    if left_num.notna().sum() >= max(1, int(left_s.notna().sum() * 0.8)) and right_num.notna().sum() >= max(
        1, int(right_s.notna().sum() * 0.8)
    ):
        left_df[left_key] = left_num
        right_df[right_key] = right_num
        return

    left_dt = pd.to_datetime(left_s, errors="coerce")
    right_dt = pd.to_datetime(right_s, errors="coerce")
    left_non_null = int(left_s.notna().sum())
    right_non_null = int(right_s.notna().sum())
    if (left_non_null and left_dt.notna().sum() == 0) or (right_non_null and right_dt.notna().sum() == 0):
        raise UserInputError(
            f"asof join のキー列を日時/数値として解釈できません: left={left_key}, right={right_key}. 型上書きを確認してください。"
        )
    left_df[left_key] = left_dt
    right_df[right_key] = right_dt


def _parse_asof_tolerance(value: str | None, sample_series: pd.Series) -> object | None:
    """Parse asof tolerance from text."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    if pd.api.types.is_datetime64_any_dtype(sample_series):
        try:
            return pd.Timedelta(text)
        except Exception as exc:
            raise UserInputError(f"asof tolerance を Timedelta として解釈できません: '{text}'") from exc
    try:
        return float(text)
    except ValueError as exc:
        raise UserInputError(f"asof tolerance を数値として解釈できません: '{text}'") from exc


def _resolve_conflicts(merged: pd.DataFrame, left_df: pd.DataFrame, right_df: pd.DataFrame, step: JoinStep) -> pd.DataFrame:
    """Resolve overlapping column conflicts according to policy."""
    result = merged.copy()
    if "_merge" in result.columns:
        result = result.drop(columns=["_merge"])

    if step.conflict_policy == "keep_both":
        return result

    left_suffix, right_suffix = step.suffixes
    left_key_set = set(step.left_keys) | set(step.left_by_keys)
    right_key_set = set(step.right_keys) | set(step.right_by_keys)

    overlapping_non_keys = {
        col
        for col in left_df.columns
        if col in right_df.columns and col not in left_key_set and col not in right_key_set
    }

    for base_col in overlapping_non_keys:
        left_col = f"{base_col}{left_suffix}"
        right_col = f"{base_col}{right_suffix}"
        if left_col not in result.columns or right_col not in result.columns:
            continue
        if step.conflict_policy == "left_prefer":
            result[base_col] = result[left_col].combine_first(result[right_col])
        elif step.conflict_policy == "right_prefer":
            result[base_col] = result[right_col].combine_first(result[left_col])
        else:
            raise UserInputError(f"{step.step_id}: 未対応の衝突ポリシーです: {step.conflict_policy}")
        result = result.drop(columns=[left_col, right_col])

    return result


def execute_join_plan(
    *,
    join_plan: JoinPlan,
    load_table: Callable[[str], pd.DataFrame],
    engine: JoinEngine | None = None,
) -> JoinExecutionResult:
    """Execute a sequential plan by loading tables on demand."""
    if not join_plan.base_table_id:
        raise UserInputError("ベーステーブルが未選択です。")

    step_results: list[JoinStepResult] = []
    current_df = load_table(join_plan.base_table_id)
    active_engine: JoinEngine = engine or PandasEquiJoinEngine()

    for step in join_plan.steps:
        if not step.right_table_id:
            raise UserInputError(f"{step.step_id}: 実行対象の右テーブルが未選択です。")
        right_df = load_table(step.right_table_id)
        step_result = active_engine.execute_step(
            current_df,
            right_df,
            step,
            row_explosion_warn_ratio=join_plan.row_explosion_warn_ratio,
        )
        current_df = step_result.output_df
        step_results.append(step_result)

    return JoinExecutionResult(final_df=current_df, step_results=step_results)
