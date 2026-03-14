# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Tests for paged table rendering helpers."""

from __future__ import annotations

import pandas as pd

from src.table_backend import normalize_table_page_current, normalize_table_page_size, slice_table_page


def test_normalize_table_page_size_and_current() -> None:
    assert normalize_table_page_size(None) == 200
    assert normalize_table_page_size("5000") == 1000
    assert normalize_table_page_current(None) == 0
    assert normalize_table_page_current("-3") == 0


def test_slice_table_page_returns_page_and_count() -> None:
    df = pd.DataFrame({"id": list(range(1, 11))})

    page_df, page_count = slice_table_page(df, page_current=1, page_size=4)

    assert page_count == 3
    assert page_df["id"].tolist() == [5, 6, 7, 8]
