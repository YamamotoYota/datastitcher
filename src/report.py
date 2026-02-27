# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Output generation and execution logging."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pandas as pd

from .models import ExecutionLogEntry

EXCEL_MAX_ROWS = 1_048_576


def dataframe_to_csv_bytes(df: pd.DataFrame, encoding: str = "utf-8-sig") -> bytes:
    """Serialize a dataframe to CSV bytes."""
    return df.to_csv(index=False).encode(encoding, errors="replace")


def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "result") -> bytes:
    """Serialize a dataframe to a one-sheet Excel file."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name[:31] or "result", index=False)
    buffer.seek(0)
    return buffer.read()


def append_execution_log(entry: ExecutionLogEntry, log_path: str | Path) -> None:
    """Append an execution log entry to a JSONL file."""
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry.to_dict(), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

