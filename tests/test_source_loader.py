# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Unit tests for source loading helpers (SQL)."""

from __future__ import annotations

import importlib.util
import sqlite3

import pandas as pd
import pytest

from src import source_loader
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


def test_pi_preview_limit_caps_max_rows_per_tag(monkeypatch) -> None:
    captured: dict[str, int] = {}

    def fake_fetch(config):
        captured["max_rows_per_tag"] = int(config.max_rows_per_tag)
        return pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-01-01 00:00:00", "2026-01-01 01:00:00"]),
                "sinusoid": [1.0, 2.0],
            }
        )

    monkeypatch.setattr(source_loader, "fetch_pi_datalink_table", fake_fetch)

    cfg = TableConfig(
        table_id="pi_1",
        table_name="pi_table",
        source_file_name="pi_da_tag",
        source_kind="pi_da_tag",
        source_options={
            "pi_server": "PISRV01",
            "query_type": "recorded",
            "tags_text": "sinusoid",
            "start_time": "*-1d",
            "end_time": "*",
            "interval": "1h",
            "summary_functions": ["average"],
            "max_rows_per_tag": 10000,
        },
    )

    df = load_table_from_source(cfg, nrows=25)

    assert captured["max_rows_per_tag"] == 25
    assert df.shape == (2, 2)
