# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Join quality metrics and unmatched row extraction."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .models import JoinQualityReport


@dataclass
class JoinDiagnostics:
    """Auxiliary diagnostics derived from a merge operation."""

    report: JoinQualityReport
    unmatched_left_df: pd.DataFrame
    unmatched_right_df: pd.DataFrame


def _count_duplicate_key_rows(df: pd.DataFrame, keys: list[str]) -> int:
    if not keys or df.empty:
        return 0
    return int(df.duplicated(subset=keys, keep=False).sum())


def extract_unmatched_left(
    left_df: pd.DataFrame, right_df: pd.DataFrame, left_keys: list[str], right_keys: list[str]
) -> pd.DataFrame:
    """Return rows from left_df that do not match any row in right_df on the key mapping."""
    if left_df.empty:
        return left_df.copy()
    if right_df.empty:
        return left_df.copy().reset_index(drop=True)
    right_keys_df = right_df.loc[:, right_keys].drop_duplicates()
    merged = left_df.merge(
        right_keys_df,
        how="left",
        left_on=left_keys,
        right_on=right_keys,
        indicator=True,
        suffixes=("", "__r"),
    )
    left_only = merged[merged["_merge"] == "left_only"].copy()
    return left_only.loc[:, left_df.columns].reset_index(drop=True)


def extract_unmatched_right(
    left_df: pd.DataFrame, right_df: pd.DataFrame, left_keys: list[str], right_keys: list[str]
) -> pd.DataFrame:
    """Return rows from right_df that do not match any row in left_df on the key mapping."""
    if right_df.empty:
        return right_df.copy()
    if left_df.empty:
        return right_df.copy().reset_index(drop=True)
    left_keys_df = left_df.loc[:, left_keys].drop_duplicates()
    merged = right_df.merge(
        left_keys_df,
        how="left",
        left_on=right_keys,
        right_on=left_keys,
        indicator=True,
        suffixes=("", "__l"),
    )
    unmatched_mask = merged["_merge"] == "left_only"
    right_only = merged[unmatched_mask].copy()
    return right_only.loc[:, right_df.columns].reset_index(drop=True)


def build_join_diagnostics(
    *,
    step_id: str,
    join_type: str,
    left_df: pd.DataFrame,
    right_df: pd.DataFrame,
    merged_with_indicator: pd.DataFrame,
    left_keys: list[str],
    right_keys: list[str],
    row_explosion_warn_ratio: float,
) -> JoinDiagnostics:
    """Compute per-step quality metrics and unmatched extracts."""
    left_rows = int(len(left_df))
    right_rows = int(len(right_df))
    output_rows = int(len(merged_with_indicator))

    unmatched_left_df = extract_unmatched_left(left_df, right_df, left_keys, right_keys)
    unmatched_right_df = extract_unmatched_right(left_df, right_df, left_keys, right_keys)

    unmatched_left_rows = int(len(unmatched_left_df))
    unmatched_right_rows = int(len(unmatched_right_df))
    matched_left_rows = max(0, left_rows - unmatched_left_rows)
    matched_right_rows = max(0, right_rows - unmatched_right_rows)

    left_match_rate = (matched_left_rows / left_rows) if left_rows else None
    right_match_rate = (matched_right_rows / right_rows) if right_rows else None

    left_dup_rows = _count_duplicate_key_rows(left_df, left_keys)
    right_dup_rows = _count_duplicate_key_rows(right_df, right_keys)
    row_growth_ratio_vs_left = (output_rows / left_rows) if left_rows else None

    many_to_many_suspected = bool(
        left_dup_rows > 0 and right_dup_rows > 0 and output_rows > max(left_rows, right_rows)
    )

    warnings: list[str] = []
    if many_to_many_suspected:
        warnings.append("左右キーで重複があり、多対多結合により行数が増加している可能性があります。")
    if row_growth_ratio_vs_left is not None and row_growth_ratio_vs_left > row_explosion_warn_ratio:
        warnings.append(
            f"行数増加がしきい値を超えました: {row_growth_ratio_vs_left:.2f}x (閾値 {row_explosion_warn_ratio:.2f}x)"
        )

    report = JoinQualityReport(
        step_id=step_id,
        join_type=join_type,
        left_rows=left_rows,
        right_rows=right_rows,
        output_rows=output_rows,
        matched_left_rows=matched_left_rows,
        unmatched_left_rows=unmatched_left_rows,
        matched_right_rows=matched_right_rows,
        unmatched_right_rows=unmatched_right_rows,
        left_match_rate=left_match_rate,
        right_match_rate=right_match_rate,
        left_duplicate_key_rows=left_dup_rows,
        right_duplicate_key_rows=right_dup_rows,
        many_to_many_suspected=many_to_many_suspected,
        row_growth_ratio_vs_left=row_growth_ratio_vs_left,
        operation="join",
        algorithm="equi",
        warnings=warnings,
    )
    return JoinDiagnostics(
        report=report,
        unmatched_left_df=unmatched_left_df,
        unmatched_right_df=unmatched_right_df,
    )


def build_asof_diagnostics(
    *,
    step_id: str,
    left_df: pd.DataFrame,
    right_df: pd.DataFrame,
    output_df: pd.DataFrame,
    matched_left_mask: pd.Series,
    matched_right_row_ids: set[int],
    right_row_id_series: pd.Series,
    row_explosion_warn_ratio: float,
    direction: str,
    tolerance: str | None,
) -> JoinDiagnostics:
    """Compute quality metrics for an asof join."""
    left_rows = int(len(left_df))
    right_rows = int(len(right_df))
    output_rows = int(len(output_df))

    matched_left_rows = int(matched_left_mask.sum())
    unmatched_left_rows = max(0, left_rows - matched_left_rows)
    matched_right_rows = len(matched_right_row_ids)
    unmatched_right_rows = max(0, right_rows - matched_right_rows)

    left_match_rate = (matched_left_rows / left_rows) if left_rows else None
    right_match_rate = (matched_right_rows / right_rows) if right_rows else None
    row_growth_ratio_vs_left = (output_rows / left_rows) if left_rows else None

    unmatched_left_df = left_df.loc[~matched_left_mask].copy().reset_index(drop=True)
    unmatched_right_df = right_df.loc[~right_row_id_series.isin(matched_right_row_ids)].copy().reset_index(drop=True)

    warnings: list[str] = []
    if row_growth_ratio_vs_left is not None and row_growth_ratio_vs_left > row_explosion_warn_ratio:
        warnings.append(
            f"行数増加がしきい値を超えました: {row_growth_ratio_vs_left:.2f}x (閾値 {row_explosion_warn_ratio:.2f}x)"
        )

    report = JoinQualityReport(
        step_id=step_id,
        join_type="left",
        left_rows=left_rows,
        right_rows=right_rows,
        output_rows=output_rows,
        matched_left_rows=matched_left_rows,
        unmatched_left_rows=unmatched_left_rows,
        matched_right_rows=matched_right_rows,
        unmatched_right_rows=unmatched_right_rows,
        left_match_rate=left_match_rate,
        right_match_rate=right_match_rate,
        left_duplicate_key_rows=0,
        right_duplicate_key_rows=0,
        many_to_many_suspected=False,
        row_growth_ratio_vs_left=row_growth_ratio_vs_left,
        operation="join",
        algorithm="asof",
        warnings=warnings,
        details={"direction": direction, "tolerance": tolerance or ""},
    )
    return JoinDiagnostics(report=report, unmatched_left_df=unmatched_left_df, unmatched_right_df=unmatched_right_df)


def build_union_diagnostics(
    *,
    step_id: str,
    left_df: pd.DataFrame,
    right_df: pd.DataFrame,
    output_df: pd.DataFrame,
    mapped_columns: int,
    kept_new_columns: int,
    dropped_columns: int,
    row_explosion_warn_ratio: float,
) -> JoinDiagnostics:
    """Compute summary metrics for a union step (vertical concatenation)."""
    left_rows = int(len(left_df))
    right_rows = int(len(right_df))
    output_rows = int(len(output_df))
    row_growth_ratio_vs_left = (output_rows / left_rows) if left_rows else None

    warnings: list[str] = [
        "Unionステップではマッチ率は常に100%扱いです（縦方向連結のため、未マッチ概念は適用しません）。"
    ]
    if row_growth_ratio_vs_left is not None and row_growth_ratio_vs_left > row_explosion_warn_ratio:
        warnings.append(
            f"行数増加がしきい値を超えました: {row_growth_ratio_vs_left:.2f}x (閾値 {row_explosion_warn_ratio:.2f}x)"
        )

    report = JoinQualityReport(
        step_id=step_id,
        join_type="union",
        left_rows=left_rows,
        right_rows=right_rows,
        output_rows=output_rows,
        matched_left_rows=left_rows,
        unmatched_left_rows=0,
        matched_right_rows=right_rows,
        unmatched_right_rows=0,
        left_match_rate=1.0 if left_rows else None,
        right_match_rate=1.0 if right_rows else None,
        left_duplicate_key_rows=0,
        right_duplicate_key_rows=0,
        many_to_many_suspected=False,
        row_growth_ratio_vs_left=row_growth_ratio_vs_left,
        operation="union",
        algorithm="union",
        warnings=warnings,
        details={
            "mapped_columns": mapped_columns,
            "kept_new_columns": kept_new_columns,
            "dropped_columns": dropped_columns,
        },
    )
    return JoinDiagnostics(
        report=report,
        unmatched_left_df=left_df.head(0).copy(),
        unmatched_right_df=right_df.head(0).copy(),
    )

