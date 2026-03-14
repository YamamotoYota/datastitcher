# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Process-local dataframe cache for large dataset handling."""

from __future__ import annotations

from typing import Any

import pandas as pd

_DATAFRAME_CACHE: dict[str, pd.DataFrame] = {}
_CURRENT_SLOT = "current-data"


def _build_cache_key(app_run_id: str | None, slot: str = _CURRENT_SLOT) -> str:
    run_id = str(app_run_id or "").strip() or "default"
    return f"{run_id}:{slot}"


def store_dataframe(df: pd.DataFrame, app_run_id: str | None, slot: str = _CURRENT_SLOT) -> str:
    """Store dataframe in process-local cache and return cache key."""
    cache_key = _build_cache_key(app_run_id, slot)
    _DATAFRAME_CACHE[cache_key] = df
    return cache_key


def load_dataframe(cache_key: str) -> pd.DataFrame:
    """Load dataframe from process-local cache."""
    key = str(cache_key or "").strip()
    if not key or key not in _DATAFRAME_CACHE:
        raise KeyError(key)
    return _DATAFRAME_CACHE[key]


def has_dataframe(cache_key: str | None) -> bool:
    """Return True when cache key exists in process-local cache."""
    key = str(cache_key or "").strip()
    return bool(key and key in _DATAFRAME_CACHE)


def clear_app_run_cache(app_run_id: str | None) -> None:
    """Drop cached dataframes for the given app run."""
    prefix = f"{str(app_run_id or '').strip()}:"
    if prefix == ":":
        return
    for key in [name for name in _DATAFRAME_CACHE if name.startswith(prefix)]:
        _DATAFRAME_CACHE.pop(key, None)


def cache_stats() -> dict[str, Any]:
    """Return a small cache summary for tests / diagnostics."""
    return {"entries": len(_DATAFRAME_CACHE), "keys": sorted(_DATAFRAME_CACHE.keys())}
