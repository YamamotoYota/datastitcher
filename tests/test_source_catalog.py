# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Tests for source catalog defaults and metadata."""

from __future__ import annotations

from src.source_catalog import (
    SOURCE_ADD_BUTTON_SPECS,
    SQL_SOURCE_KIND,
    default_source_file_name,
    default_source_options,
    merge_source_options_with_defaults,
    source_display_label,
)


def test_default_source_options_returns_independent_copy() -> None:
    opts1 = default_source_options("pi_da_tag")
    opts2 = default_source_options("pi_da_tag")
    assert opts1 is not opts2
    opts1["summary_functions"].append("std")
    assert "std" not in opts2["summary_functions"]


def test_merge_source_options_with_defaults_keeps_defaults() -> None:
    merged = merge_source_options_with_defaults(SQL_SOURCE_KIND, {"host": "localhost", "query": "SELECT 1"})
    assert merged["dbms"] == "sqlserver"
    assert merged["host"] == "localhost"
    assert merged["query"] == "SELECT 1"


def test_source_labels_and_defaults_are_available_for_buttons() -> None:
    kinds = {kind for kind, _ in SOURCE_ADD_BUTTON_SPECS}
    for kind in kinds:
        assert source_display_label(kind)
        assert default_source_file_name(kind)
