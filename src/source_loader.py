# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Unified table loading helpers for file/SQL/PI sources."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pandas as pd

from .db_connectors import (
    DatabaseConfig,
    DatabaseError,
    build_select_sample_query,
    execute_query,
    list_tables,
    normalize_dbms,
    normalize_port,
)
from .errors import UserInputError
from .io_utils import load_table as load_file_table
from .io_utils import prepare_table
from .models import TableConfig
from .pi_af_sdk import PIDataError, PIQueryConfig, build_pi_query_config, fetch_pi_datalink_table
from .source_catalog import FILE_SOURCE_KINDS, PI_SOURCE_KINDS, SQL_SOURCE_KIND


def is_file_source(source_kind: str) -> bool:
    """Return whether source kind depends on uploaded bytes."""
    return source_kind in FILE_SOURCE_KINDS


def _as_string_list(value: Any) -> list[str]:
    """Normalize list-like values to list[str]."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, tuple):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    tokens = [token.strip() for token in text.replace(";", "\n").replace(",", "\n").splitlines()]
    return [token for token in tokens if token]


def _build_database_config(options: dict[str, Any]) -> DatabaseConfig:
    """Build SQL database config from source options."""
    return DatabaseConfig(
        dbms=normalize_dbms(str(options.get("dbms", "sqlserver"))),
        host=str(options.get("host", "")).strip(),
        port=normalize_port(options.get("port")),
        database=str(options.get("database", "")).strip(),
        username=str(options.get("username", "")).strip(),
        password=str(options.get("password", "")),
        sqlite_path=str(options.get("sqlite_path", "")).strip(),
        schema=str(options.get("schema", "")).strip(),
    )


def list_sql_tables_from_options(options: dict[str, Any]) -> list[str]:
    """List SQL tables by current connection options."""
    try:
        return list_tables(_build_database_config(options))
    except DatabaseError as exc:
        raise UserInputError(str(exc)) from exc


def build_sql_sample_query_from_options(options: dict[str, Any], table_name: str, top_n: int = 1000) -> str:
    """Build a DB-specific sample SELECT statement."""
    try:
        return build_select_sample_query(_build_database_config(options), table_name, top_n=top_n)
    except DatabaseError as exc:
        raise UserInputError(str(exc)) from exc


def build_pi_query_kwargs_from_source_options(source_kind: str, options: dict[str, Any]) -> dict[str, Any]:
    """Convert source options into PI query configuration kwargs."""
    return {
        "data_source": source_kind,
        "pi_server": options.get("pi_server"),
        "af_server": options.get("af_server"),
        "af_database": options.get("af_database"),
        "query_type": options.get("query_type"),
        "tags_text": options.get("tags_text"),
        "af_element": options.get("af_element"),
        "af_attributes_text": options.get("af_attributes_text"),
        "start_time": options.get("start_time"),
        "end_time": options.get("end_time"),
        "interval": options.get("interval"),
        "summary_functions": _as_string_list(options.get("summary_functions")),
        "max_rows_per_tag": options.get("max_rows_per_tag"),
        "ef_template": options.get("ef_template"),
        "ef_analyses_text": options.get("ef_analyses_text"),
    }


def _apply_preview_row_limit_to_pi_config(config: PIQueryConfig, nrows: int | None) -> PIQueryConfig:
    """Cap PI retrieval volume during preview loads."""
    if nrows is None:
        return config
    preview_limit = max(1, int(nrows))
    if int(config.max_rows_per_tag) <= preview_limit:
        return config
    return replace(config, max_rows_per_tag=preview_limit)


def load_table_from_source(
    table: TableConfig,
    *,
    uploaded_entry: dict[str, Any] | None = None,
    nrows: int | None = None,
) -> pd.DataFrame:
    """Load one table from file/SQL/PI source according to table config."""
    source_kind = str(table.source_kind)

    if source_kind in FILE_SOURCE_KINDS:
        if not uploaded_entry or "bytes" not in uploaded_entry:
            raise UserInputError(
                f"テーブル '{table.table_name}' はファイルソースです。対応ファイルをアップロードしてください。"
            )
        return load_file_table(uploaded_entry["bytes"], table, nrows=nrows)

    if source_kind == SQL_SOURCE_KIND:
        options = dict(table.source_options or {})
        query = str(options.get("query", "")).strip()
        if not query:
            raise UserInputError(f"テーブル '{table.table_name}' の SQL が未設定です。")
        try:
            raw = execute_query(_build_database_config(options), query, row_limit=nrows)
        except DatabaseError as exc:
            raise UserInputError(str(exc)) from exc
        return prepare_table(raw, table)

    if source_kind in PI_SOURCE_KINDS:
        options = dict(table.source_options or {})
        try:
            config = build_pi_query_config(**build_pi_query_kwargs_from_source_options(source_kind, options))
            config = _apply_preview_row_limit_to_pi_config(config, nrows)
            raw = fetch_pi_datalink_table(config)
        except PIDataError as exc:
            raise UserInputError(str(exc)) from exc
        if nrows is not None:
            raw = raw.head(int(nrows)).copy()
        return prepare_table(raw, table)

    raise UserInputError(f"未対応のデータソース種別です: {source_kind}")
