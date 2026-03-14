# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Tests for process-local dataframe cache."""

from __future__ import annotations

import pandas as pd

from src.server_cache import cache_stats, clear_app_run_cache, has_dataframe, load_dataframe, store_dataframe


def teardown_function() -> None:
    clear_app_run_cache("test-run")


def test_store_and_load_dataframe() -> None:
    df = pd.DataFrame({"id": [1, 2], "value": ["a", "b"]})

    cache_key = store_dataframe(df, "test-run", slot="execution-final")

    assert cache_key == "test-run:execution-final"
    assert has_dataframe(cache_key) is True
    restored = load_dataframe(cache_key)
    assert restored.equals(df)
    assert cache_stats()["entries"] == 1


def test_clear_app_run_cache_drops_all_slots() -> None:
    store_dataframe(pd.DataFrame({"id": [1]}), "test-run", slot="execution-final")
    store_dataframe(pd.DataFrame({"id": [2]}), "test-run", slot="step-1-left-unmatched")

    clear_app_run_cache("test-run")

    assert has_dataframe("test-run:execution-final") is False
    assert has_dataframe("test-run:step-1-left-unmatched") is False
