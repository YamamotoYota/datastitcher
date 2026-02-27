# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Normalization helpers."""

from __future__ import annotations

import unicodedata

import pandas as pd

from .errors import UserInputError


def normalize_text_light(value: object) -> object:
    """Apply a lightweight normalization to strings (NFKC + strip)."""
    if not isinstance(value, str):
        return value
    return unicodedata.normalize("NFKC", value).strip()


def normalize_column_name(name: object) -> str:
    """Normalize column names for consistent key selection."""
    text = "" if name is None else str(name)
    return str(normalize_text_light(text))


def normalize_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize dataframe column names and reject duplicates after normalization."""
    normalized: list[str] = []
    seen: set[str] = set()
    for col in df.columns:
        norm = normalize_column_name(col)
        if norm in seen:
            raise UserInputError(
                f"列名正規化後に重複が発生しました: '{norm}'。列名を調整するか正規化を無効にしてください。"
            )
        seen.add(norm)
        normalized.append(norm)
    result = df.copy()
    result.columns = normalized
    return result

