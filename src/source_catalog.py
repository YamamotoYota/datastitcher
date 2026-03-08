# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Centralized metadata/defaults for supported data source kinds."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

FILE_SOURCE_KINDS: frozenset[str] = frozenset({"csv", "excel"})
SQL_SOURCE_KIND = "sql"
PI_SOURCE_KINDS: frozenset[str] = frozenset({"pi_da_tag", "af_attribute", "af_event_frame"})
EXTERNAL_SOURCE_KINDS: tuple[str, ...] = (SQL_SOURCE_KIND, "pi_da_tag", "af_attribute", "af_event_frame")
SOURCE_ADD_BUTTON_SPECS: tuple[tuple[str, str], ...] = (
    (SQL_SOURCE_KIND, "SQL追加"),
    ("pi_da_tag", "PI DA追加"),
    ("af_attribute", "AF属性追加"),
    ("af_event_frame", "AFイベント追加"),
)

_SOURCE_TABLE_LABELS: dict[str, str] = {
    SQL_SOURCE_KIND: "SQLテーブル",
    "pi_da_tag": "PI DAタグ",
    "af_attribute": "PI AF属性",
    "af_event_frame": "PI AFイベントフレーム",
}

_SOURCE_PANEL_LABELS: dict[str, str] = {
    "pi_da_tag": "PI DAサーバーのPIタグデータ",
    "af_attribute": "PI AFサーバーのAF属性データ",
    "af_event_frame": "PI AFサーバーのイベントフレームデータ",
}

_SOURCE_DESCRIPTIONS: dict[str, str] = {
    "pi_da_tag": "PI Data Archive からタグ値（Snapshot/Recorded/Interpolated/Summary）を取得します。",
    "af_attribute": "AFデータベース内のエレメント属性値を、PIタグ相当の時系列形式で取得します。",
    "af_event_frame": "AFイベントフレームをテンプレート・期間・イベント生成分析名で抽出します。",
}

_DEFAULT_SOURCE_FILE_NAMES: dict[str, str] = {
    SQL_SOURCE_KIND: "sql_source",
    "pi_da_tag": "pi_da_tag",
    "af_attribute": "af_attribute",
    "af_event_frame": "af_event_frame",
}

_DEFAULT_SOURCE_OPTIONS: dict[str, dict[str, Any]] = {
    SQL_SOURCE_KIND: {
        "dbms": "sqlserver",
        "host": "",
        "port": "",
        "database": "",
        "schema": "",
        "username": "",
        "password": "",
        "sqlite_path": "",
        "query": "",
    },
    "pi_da_tag": {
        "pi_server": "",
        "af_server": "",
        "af_database": "",
        "query_type": "recorded",
        "tags_text": "",
        "start_time": "*-1d",
        "end_time": "*",
        "interval": "1h",
        "summary_functions": ["average", "min", "max"],
        "max_rows_per_tag": 10000,
    },
    "af_attribute": {
        "pi_server": "",
        "af_server": "",
        "af_database": "",
        "query_type": "recorded",
        "af_element": "",
        "af_attributes_text": "",
        "start_time": "*-1d",
        "end_time": "*",
        "interval": "1h",
        "summary_functions": ["average", "min", "max"],
        "max_rows_per_tag": 10000,
    },
    "af_event_frame": {
        "af_server": "",
        "af_database": "",
        "ef_template": "",
        "ef_analyses_text": "",
        "start_time": "*-1d",
        "end_time": "*",
        "max_rows_per_tag": 10000,
    },
}


def source_display_label(source_kind: str) -> str:
    """Return short user-facing source label."""
    kind = str(source_kind)
    return _SOURCE_TABLE_LABELS.get(kind, kind)


def source_panel_label(source_kind: str) -> str:
    """Return detailed panel title for source-specific configuration."""
    kind = str(source_kind)
    return _SOURCE_PANEL_LABELS.get(kind, source_display_label(kind))


def source_description(source_kind: str) -> str:
    """Return source-specific user guidance text."""
    kind = str(source_kind)
    return _SOURCE_DESCRIPTIONS.get(kind, "")


def default_source_file_name(source_kind: str) -> str:
    """Return default placeholder source file name for non-file sources."""
    kind = str(source_kind)
    return _DEFAULT_SOURCE_FILE_NAMES.get(kind, kind)


def default_source_options(source_kind: str) -> dict[str, Any]:
    """Return deep-copied default source options for one source kind."""
    kind = str(source_kind)
    return deepcopy(_DEFAULT_SOURCE_OPTIONS.get(kind, {}))


def merge_source_options_with_defaults(
    source_kind: str,
    source_options: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge user source options onto defaults while keeping map mutable."""
    merged = default_source_options(source_kind)
    if isinstance(source_options, dict):
        merged.update(source_options)
    return merged

