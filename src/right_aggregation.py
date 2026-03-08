# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Right-table aggregation helpers for one-to-many / many-to-many join scenarios."""

from __future__ import annotations

import ast
from typing import Any

import pandas as pd

from .errors import UserInputError

SUPPORTED_RIGHT_PRE_AGG_METHODS: tuple[str, ...] = (
    "first",
    "last",
    "sum",
    "mean",
    "min",
    "max",
    "count",
    "weighted_sum",
    "weighted_mean",
    "formula",
)


def _first_non_null(series: pd.Series) -> Any:
    non_null = series[series.notna()]
    if non_null.empty:
        return pd.NA
    return non_null.iloc[0]


def _last_non_null(series: pd.Series) -> Any:
    non_null = series[series.notna()]
    if non_null.empty:
        return pd.NA
    return non_null.iloc[-1]


def _numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _safe_eval_formula(expression: str, context: dict[str, float], *, step_id: str, column_name: str) -> float:
    """Evaluate arithmetic-only expression with a restricted AST."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UserInputError(f"{step_id}: 数式の構文エラー ({column_name}): {expression}") from exc

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in context:
                raise UserInputError(
                    f"{step_id}: 数式で未定義の変数を参照しています ({column_name}): {node.id}"
                )
            return float(context[node.id])
        if isinstance(node, ast.UnaryOp):
            value = _eval(node.operand)
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.USub):
                return -value
            raise UserInputError(f"{step_id}: 数式で未対応の単項演算です ({column_name})")
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise UserInputError(f"{step_id}: 数式でゼロ除算が発生しました ({column_name})")
                return left / right
            raise UserInputError(f"{step_id}: 数式で未対応の演算子です ({column_name})")
        raise UserInputError(f"{step_id}: 数式に未対応の構文があります ({column_name})")

    return _eval(tree)


def _aggregate_one_column(
    *,
    step_id: str,
    group_df: pd.DataFrame,
    column_name: str,
    method: str,
    formula: str,
    weight_column: str,
) -> Any:
    values_raw = group_df[column_name]
    values_num = _numeric_series(values_raw)
    has_weight = bool(weight_column)
    weights_num = _numeric_series(group_df[weight_column]) if has_weight else pd.Series(index=group_df.index, dtype=float)

    if method == "first":
        return _first_non_null(values_raw)
    if method == "last":
        return _last_non_null(values_raw)
    if method == "count":
        return int(values_raw.notna().sum())
    if method == "sum":
        return values_num.sum(min_count=1)
    if method == "mean":
        return values_num.mean()
    if method == "min":
        return values_num.min()
    if method == "max":
        return values_num.max()

    if method in {"weighted_sum", "weighted_mean", "formula"} and not has_weight:
        raise UserInputError(f"{step_id}: 重みを使う集約には重み列の指定が必要です。({column_name})")

    valid_mask = values_num.notna() & weights_num.notna()
    sum_vw = float((values_num[valid_mask] * weights_num[valid_mask]).sum()) if valid_mask.any() else 0.0
    sum_w = float(weights_num[valid_mask].sum()) if valid_mask.any() else 0.0

    if method == "weighted_sum":
        return sum_vw
    if method == "weighted_mean":
        if sum_w == 0:
            return pd.NA
        return sum_vw / sum_w

    # formula
    context = {
        "sum_v": float(values_num.sum(min_count=1)) if values_num.notna().any() else 0.0,
        "mean_v": float(values_num.mean()) if values_num.notna().any() else 0.0,
        "min_v": float(values_num.min()) if values_num.notna().any() else 0.0,
        "max_v": float(values_num.max()) if values_num.notna().any() else 0.0,
        "count_v": float(values_num.notna().sum()),
        "sum_w": sum_w,
        "mean_w": float(weights_num[valid_mask].mean()) if valid_mask.any() else 0.0,
        "sum_vw": sum_vw,
    }
    if not formula.strip():
        raise UserInputError(f"{step_id}: 数式が空です。({column_name})")
    return _safe_eval_formula(formula, context, step_id=step_id, column_name=column_name)


def aggregate_right_table_for_join(
    right_df: pd.DataFrame,
    *,
    step_id: str,
    group_keys: list[str],
    fallback_group_keys: list[str],
    weight_column: str,
    rules: dict[str, dict[str, str]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Aggregate right table before equi join."""
    resolved_group_keys = [str(k) for k in (group_keys or fallback_group_keys) if str(k)]
    if not resolved_group_keys:
        raise UserInputError(f"{step_id}: 右テーブル事前集約のグループキーが未設定です。")

    missing_group_keys = [key for key in resolved_group_keys if key not in right_df.columns]
    if missing_group_keys:
        raise UserInputError(
            f"{step_id}: 右テーブル事前集約のグループキーが右テーブルに存在しません: {', '.join(missing_group_keys)}"
        )

    normalized_rules = {
        str(col): {
            "method": str(spec.get("method", "first")),
            "formula": str(spec.get("formula", "")),
        }
        for col, spec in (rules or {}).items()
        if isinstance(spec, dict)
    }
    if not normalized_rules:
        raise UserInputError(f"{step_id}: 右テーブル事前集約ルールが未設定です。")

    for column_name, spec in normalized_rules.items():
        if column_name not in right_df.columns:
            raise UserInputError(f"{step_id}: 集約対象列が右テーブルに存在しません: {column_name}")
        if column_name in resolved_group_keys:
            raise UserInputError(f"{step_id}: 集約対象列にグループキーは指定できません: {column_name}")
        method = str(spec.get("method", ""))
        if method not in SUPPORTED_RIGHT_PRE_AGG_METHODS:
            raise UserInputError(f"{step_id}: 未対応の集約方式です: {method} ({column_name})")

    normalized_weight_column = str(weight_column or "")
    if normalized_weight_column and normalized_weight_column not in right_df.columns:
        raise UserInputError(f"{step_id}: 重み列が右テーブルに存在しません: {normalized_weight_column}")

    rows: list[dict[str, Any]] = []
    grouped = right_df.groupby(resolved_group_keys, dropna=False, sort=False)
    for group_values, group_df in grouped:
        row: dict[str, Any] = {}
        key_values = group_values if isinstance(group_values, tuple) else (group_values,)
        for key, value in zip(resolved_group_keys, key_values):
            row[key] = value
        for column_name, spec in normalized_rules.items():
            row[column_name] = _aggregate_one_column(
                step_id=step_id,
                group_df=group_df,
                column_name=column_name,
                method=spec["method"],
                formula=spec["formula"],
                weight_column=normalized_weight_column,
            )
        rows.append(row)

    output_columns = [*resolved_group_keys, *normalized_rules.keys()]
    aggregated = pd.DataFrame(rows, columns=output_columns)
    details = {
        "enabled": True,
        "group_keys": resolved_group_keys,
        "weight_column": normalized_weight_column,
        "rules": normalized_rules,
        "input_rows": int(len(right_df)),
        "output_rows": int(len(aggregated)),
    }
    return aggregated, details

