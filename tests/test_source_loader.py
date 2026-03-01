# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Unit tests for source loading helpers (SQL)."""

from __future__ import annotations

import importlib.util
import sqlite3

import pytest

from src.models import TableConfig
from src.source_loader import (
    build_sql_sample_query_from_options,
    list_sql_tables_from_options,
    load_table_from_source,
)


def _has_sqlalchemy() -> bool:
    return importlib.util.find_spec("sqlalchemy") is not None


@pytest.mark.skipif(not _has_sqlalchemy(), reason="sqlalchemy が未インストールのためスキップ")
def test_sqlite_table_list_and_query_preview(tmp_path) -> None:
    db_path = tmp_path / "sample.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sales (id INTEGER, customer TEXT, amount INTEGER)")
        conn.execute("INSERT INTO sales VALUES (1, 'A', 100)")
        conn.execute("INSERT INTO sales VALUES (2, 'B', 200)")
        conn.execute("INSERT INTO sales VALUES (3, 'C', 300)")
        conn.commit()

    source_options = {
        "dbms": "sqlite",
        "sqlite_path": str(db_path),
        "query": "SELECT * FROM sales ORDER BY id",
    }

    tables = list_sql_tables_from_options(source_options)
    assert "sales" in tables

    sample_query = build_sql_sample_query_from_options(source_options, "sales", top_n=2)
    assert "sales" in sample_query.lower()

    cfg = TableConfig(
        table_id="sql_1",
        table_name="sales_table",
        source_file_name="sql_source",
        source_kind="sql",
        source_options=source_options,
        normalize_columns=True,
        selected_columns=["id", "customer", "amount"],
    )
    df = load_table_from_source(cfg, nrows=2)
    assert df.shape == (2, 3)
    assert df["id"].tolist() == [1, 2]
    assert df["customer"].tolist() == ["A", "B"]

