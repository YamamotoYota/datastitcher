# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Large-table paging helpers for Streamlit rendering."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def normalize_table_page_size(value: Any) -> int:
    """Normalize page size for paged table rendering."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 200
    return max(1, min(parsed, 1000))


def normalize_table_page_current(value: Any) -> int:
    """Normalize zero-based current page index."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    return max(parsed, 0)


def slice_table_page(df: pd.DataFrame, page_current: Any, page_size: Any) -> tuple[pd.DataFrame, int]:
    """Slice one table page and return the total page count."""
    size = normalize_table_page_size(page_size)
    current = normalize_table_page_current(page_current)
    page_count = math.ceil(len(df) / size) if len(df) else 0
    start = current * size
    end = start + size
    return df.iloc[start:end].copy(), page_count
