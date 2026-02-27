# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Column profiling and simple dtype inference."""

from __future__ import annotations

from typing import Literal

import pandas as pd

SimpleDType = Literal["string", "number", "datetime"]


def infer_simple_dtype(series: pd.Series) -> SimpleDType:
    """Infer a coarse dtype category for UI display."""
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    non_null = series.dropna()
    if non_null.empty:
        return "string"

    sample = non_null.astype(str).head(50)
    numeric_ratio = pd.to_numeric(sample, errors="coerce").notna().mean()
    if numeric_ratio >= 0.9:
        return "number"

    datetime_ratio = pd.to_datetime(sample, errors="coerce").notna().mean()
    if datetime_ratio >= 0.9:
        return "datetime"

    return "string"


def profile_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Build a compact profile table for UI display."""
    rows: list[dict[str, object]] = []
    total_rows = len(df)
    for col in df.columns:
        s = df[col]
        inferred = infer_simple_dtype(s)
        null_count = int(s.isna().sum())
        rows.append(
            {
                "column": str(col),
                "inferred_type": inferred,
                "null_count": null_count,
                "null_ratio": (null_count / total_rows) if total_rows else 0.0,
                "nunique_preview": int(s.nunique(dropna=True)),
            }
        )
    return pd.DataFrame(rows)

