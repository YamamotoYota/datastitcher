# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""File I/O for CSV/Excel, including CSV option auto-detection."""

from __future__ import annotations

import csv as pycsv
import hashlib
from io import BytesIO
from typing import Any

import pandas as pd
from charset_normalizer import from_bytes

from .errors import FileReadError, UserInputError
from .models import CSVOptions, TableConfig
from .normalization import normalize_dataframe_columns

DEFAULT_CSV_ENCODINGS = ["utf-8", "utf-8-sig", "cp932", "shift_jis", "latin1"]
DEFAULT_DELIMITERS = [",", "\t", ";", "|"]


def sha256_hex(data: bytes) -> str:
    """Return SHA-256 hex digest for file identity/logging."""
    return hashlib.sha256(data).hexdigest()


def detect_csv_options(data: bytes) -> CSVOptions:
    """Best-effort detection of CSV encoding, delimiter, and quote char."""
    encoding = "utf-8"
    try:
        best = from_bytes(data).best()
        if best and best.encoding:
            encoding = best.encoding
    except Exception:
        encoding = "utf-8"

    preview_text: str | None = None
    for enc in [encoding, *[e for e in DEFAULT_CSV_ENCODINGS if e != encoding]]:
        try:
            preview_text = data.decode(enc, errors="strict")
            encoding = enc
            break
        except Exception:
            continue
    if preview_text is None:
        preview_text = data.decode("utf-8", errors="replace")
        encoding = "utf-8"

    delimiter = ","
    quotechar = '"'
    try:
        sample = "\n".join(preview_text.splitlines()[:10])
        dialect = pycsv.Sniffer().sniff(sample, delimiters="".join(DEFAULT_DELIMITERS))
        delimiter = getattr(dialect, "delimiter", ",") or ","
        quotechar = getattr(dialect, "quotechar", '"') or '"'
    except Exception:
        pass

    return CSVOptions(encoding=encoding, delimiter=delimiter, quotechar=quotechar, header_row=1)


def list_excel_sheets(data: bytes) -> list[str]:
    """Return Excel sheet names."""
    try:
        with pd.ExcelFile(BytesIO(data), engine="openpyxl") as xls:
            return [str(s) for s in xls.sheet_names]
    except Exception as exc:
        raise FileReadError(f"Excelシート一覧の取得に失敗しました: {exc}") from exc


def _read_csv_with_options(data: bytes, options: CSVOptions, nrows: int | None = None) -> pd.DataFrame:
    detected = detect_csv_options(data)
    encoding = detected.encoding if options.encoding == "auto" else options.encoding
    delimiter = detected.delimiter if options.delimiter == "auto" else options.delimiter
    quotechar = detected.quotechar if options.quotechar == "auto" else options.quotechar
    header_idx = max(0, int(options.header_row) - 1)

    kwargs: dict[str, Any] = {
        "sep": delimiter,
        "encoding": encoding,
        "header": header_idx,
    }
    if nrows is not None:
        kwargs["nrows"] = nrows
    if options.quotechar == "none":
        kwargs["quoting"] = pycsv.QUOTE_NONE
    elif quotechar:
        kwargs["quotechar"] = quotechar

    try:
        return pd.read_csv(BytesIO(data), **kwargs)
    except UnicodeDecodeError as exc:
        raise FileReadError(
            f"CSVの文字コード解釈に失敗しました (encoding={encoding})。文字コード指定を変更してください。"
        ) from exc
    except Exception as exc:
        raise FileReadError(
            f"CSV読み込みに失敗しました (delimiter={delimiter}, encoding={encoding}, header_row={options.header_row}): {exc}"
        ) from exc


def _read_excel_with_options(data: bytes, table: TableConfig, nrows: int | None = None) -> pd.DataFrame:
    header_idx = max(0, int(table.excel_options.header_row) - 1)
    try:
        with pd.ExcelFile(BytesIO(data), engine="openpyxl") as xls:
            sheet_name = table.excel_options.sheet_name or str(xls.sheet_names[0])
            if sheet_name not in [str(s) for s in xls.sheet_names]:
                raise UserInputError(f"Excelシート '{sheet_name}' が見つかりません。")
            return pd.read_excel(
                xls,
                sheet_name=sheet_name,
                header=header_idx,
                nrows=nrows,
                engine="openpyxl",
            )
    except UserInputError:
        raise
    except Exception as exc:
        raise FileReadError(
            f"Excel読み込みに失敗しました (sheet={table.excel_options.sheet_name}, header_row={table.excel_options.header_row}): {exc}"
        ) from exc


def read_raw_table(data: bytes, table: TableConfig, nrows: int | None = None) -> pd.DataFrame:
    """Read the uploaded table without selection/type coercion."""
    if table.source_kind == "csv":
        return _read_csv_with_options(data, table.csv_options, nrows=nrows)
    if table.source_kind == "excel":
        return _read_excel_with_options(data, table, nrows=nrows)
    raise UserInputError(f"未対応のファイル種別です: {table.source_kind}")


def _apply_dtype_overrides(df: pd.DataFrame, dtype_overrides: dict[str, str]) -> pd.DataFrame:
    result = df.copy()
    for col, dtype_name in dtype_overrides.items():
        if col not in result.columns:
            continue
        if dtype_name in ("", "auto"):
            continue
        if dtype_name == "string":
            result[col] = result[col].astype("string")
        elif dtype_name == "number":
            result[col] = pd.to_numeric(result[col], errors="coerce")
        elif dtype_name == "datetime":
            result[col] = pd.to_datetime(result[col], errors="coerce")
        else:
            raise UserInputError(f"未対応の型指定です: {dtype_name} (column={col})")
    return result


def prepare_table(df: pd.DataFrame, table: TableConfig) -> pd.DataFrame:
    """Apply normalization, column selection, and dtype overrides."""
    result = df.copy()
    if table.normalize_columns:
        result = normalize_dataframe_columns(result)

    if table.selected_columns:
        missing = [c for c in table.selected_columns if c not in result.columns]
        if missing:
            raise UserInputError(
                f"選択列が見つかりません ({table.table_name}): {', '.join(missing)}。列名正規化の設定やヘッダ行を確認してください。"
            )
        result = result.loc[:, table.selected_columns].copy()

    result = _apply_dtype_overrides(result, table.dtype_overrides)
    return result


def load_table(data: bytes, table: TableConfig, nrows: int | None = None) -> pd.DataFrame:
    """Read and prepare a table in one call."""
    raw_df = read_raw_table(data, table, nrows=nrows)
    return prepare_table(raw_df, table)

