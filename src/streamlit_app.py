# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""DataStitcher の Streamlit 画面定義。"""

from __future__ import annotations

import os
import signal
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import streamlit as st

from .column_match import suggest_union_column_mapping
from .db_connectors import SUPPORTED_DBMS, dbms_label, normalize_dbms
from .errors import DataStitcherError, UserInputError
from .io_utils import detect_csv_options, list_excel_sheets, sha256_hex
from .join_engine import PandasEquiJoinEngine, execute_join_plan
from .models import (
    UNION_DROP,
    UNION_KEEP_AS_NEW,
    CSVOptions,
    ExecutionLogEntry,
    JoinPlan,
    JoinStep,
    OutputSettings,
    Recipe,
    TableConfig,
)
from .pi_af_sdk import (
    SUPPORTED_PI_QUERY_TYPES,
    SUPPORTED_SUMMARY_FUNCTIONS,
    build_pi_query_config,
    normalize_pi_query_type,
)
from .profile import profile_dataframe
from .recipe import build_recipe, recipe_from_json, recipe_to_json
from .report import EXCEL_MAX_ROWS, append_execution_log, dataframe_to_csv_bytes, dataframe_to_excel_bytes
from .source_loader import (
    PI_SOURCE_KINDS,
    SQL_SOURCE_KIND,
    build_sql_sample_query_from_options,
    is_file_source,
    list_sql_tables_from_options,
    load_table_from_source,
)

PREVIEW_ROWS_DEFAULT = 100
PREVIEW_PLAN_ROWS = 200
LOG_PATH = Path("logs") / "execution_log.jsonl"

CSV_ENCODING_OPTIONS = ["auto", "utf-8", "utf-8-sig", "cp932", "shift_jis", "latin1"]
CSV_DELIMITER_OPTIONS = ["auto", ",", "\t", ";", "|"]
CSV_QUOTE_OPTIONS = ["auto", '"', "'", "none"]
DTYPE_OVERRIDE_OPTIONS = ["auto", "string", "number", "datetime"]
JOIN_TYPE_OPTIONS = ["inner", "left", "right", "outer"]
CONFLICT_POLICY_OPTIONS = ["left_prefer", "right_prefer", "keep_both"]
STEP_OPERATION_OPTIONS = ["join", "union"]
JOIN_ALGORITHM_OPTIONS = ["equi", "asof"]
ASOF_DIRECTION_OPTIONS = ["backward", "forward", "nearest"]
UNION_MAPPING_SPECIAL_OPTIONS = [UNION_KEEP_AS_NEW, UNION_DROP]
SQL_DB_OPTIONS = list(SUPPORTED_DBMS)
PI_QUERY_TYPE_OPTIONS = list(SUPPORTED_PI_QUERY_TYPES)
PI_SUMMARY_FUNCTION_OPTIONS = list(SUPPORTED_SUMMARY_FUNCTIONS)


def _rerun() -> None:
    """Trigger a Streamlit rerun (compatible with multiple Streamlit versions)."""
    if hasattr(st, "rerun"):
        st.rerun()
    else:  # pragma: no cover - compatibility branch
        st.experimental_rerun()


def _shutdown_app_server() -> None:
    """Terminate the current Streamlit process from the UI."""
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        os._exit(0)  # noqa: PLW1510


def _short_hash(text: str) -> str:
    return text[:10]


def _safe_table_id(file_hash: str) -> str:
    return f"tbl_{_short_hash(file_hash)}"


def _safe_step_id(index_hint: int) -> str:
    return f"step_{index_hint+1}"


def _safe_external_table_id(prefix: str) -> str:
    """Generate deterministic-enough table id for non-file sources."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _default_source_file_name(source_kind: str) -> str:
    if source_kind == SQL_SOURCE_KIND:
        return "sql_source"
    if source_kind == "pi_da_tag":
        return "pi_da_tag"
    if source_kind == "af_attribute":
        return "af_attribute"
    if source_kind == "af_event_frame":
        return "af_event_frame"
    return source_kind


def _default_source_options(source_kind: str) -> dict[str, Any]:
    """Return source option defaults for each non-file source kind."""
    if source_kind == SQL_SOURCE_KIND:
        return {
            "dbms": "sqlserver",
            "host": "",
            "port": "",
            "database": "",
            "schema": "",
            "username": "",
            "password": "",
            "sqlite_path": "",
            "query": "",
        }
    if source_kind == "pi_da_tag":
        return {
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
        }
    if source_kind == "af_attribute":
        return {
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
        }
    if source_kind == "af_event_frame":
        return {
            "af_server": "",
            "af_database": "",
            "ef_template": "",
            "ef_analyses_text": "",
            "start_time": "*-1d",
            "end_time": "*",
            "max_rows_per_tag": 10000,
        }
    return {}


def _ensure_source_options_defaults(cfg: TableConfig) -> TableConfig:
    """Fill missing source options for external sources."""
    if is_file_source(str(cfg.source_kind)):
        return cfg
    merged = _default_source_options(str(cfg.source_kind))
    merged.update(dict(cfg.source_options or {}))
    cfg.source_options = merged
    return cfg


def init_session_state() -> None:
    """Initialize all app session state keys used by the UI."""
    defaults: dict[str, Any] = {
        "table_configs": {},
        "join_plan": {"base_table_id": "", "row_explosion_warn_ratio": 10.0, "steps": []},
        "output_settings": {
            "default_format": "csv",
            "csv_encoding": "utf-8-sig",
            "excel_sheet_name": "result",
        },
        "preview_rows": PREVIEW_ROWS_DEFAULT,
        "last_execution": None,
        "recipe_import_message": None,
        "source_add_message": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _table_kind_from_filename(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".xlsx") or lower.endswith(".xls") or lower.endswith(".xlsm"):
        return "excel"
    raise UserInputError(f"未対応ファイル形式です: {name} (CSV / XLSX / XLS / XLSM のみ)")


def _table_label(table_id: str, table_cfgs: dict[str, dict[str, Any]], uploaded_map: dict[str, dict[str, Any]]) -> str:
    cfg = table_cfgs.get(table_id, {})
    display_name = str(cfg.get("table_name", table_id))
    file_name = str(cfg.get("source_file_name", ""))
    source_kind = str(cfg.get("source_kind", "csv"))
    missing = is_file_source(source_kind) and table_id not in uploaded_map
    suffix = " (未アップロード)" if missing else ""
    return f"{display_name} [{file_name}]{suffix}"


def _ensure_join_plan_shape() -> None:
    """Normalize the in-session join plan dictionary."""
    plan = st.session_state["join_plan"]
    plan.setdefault("base_table_id", "")
    plan.setdefault("row_explosion_warn_ratio", 10.0)
    plan.setdefault("steps", [])
    if not isinstance(plan["steps"], list):
        plan["steps"] = []
    for idx, step in enumerate(plan["steps"]):
        step.setdefault("step_id", _safe_step_id(idx))
        step.setdefault("right_table_id", "")
        step.setdefault("operation", "join")
        step.setdefault("join_algorithm", "equi")
        step.setdefault("join_type", "left")
        step.setdefault("left_keys", [])
        step.setdefault("right_keys", [])
        step.setdefault("left_by_keys", [])
        step.setdefault("right_by_keys", [])
        step.setdefault("asof_direction", "backward")
        step.setdefault("asof_tolerance", "")
        step.setdefault("asof_allow_exact_matches", True)
        step.setdefault("conflict_policy", "keep_both")
        step.setdefault("suffixes", ["_l", "_r"])
        step.setdefault("union_column_mapping", {})
        step.setdefault("union_right_column_suffix", "_u")
        step.setdefault("union_add_source_column", False)
        step.setdefault("union_source_column_name", "_source_table")
        step.setdefault("union_source_value", "")
        if not isinstance(step["suffixes"], list) or len(step["suffixes"]) != 2:
            step["suffixes"] = ["_l", "_r"]
        if not isinstance(step["left_keys"], list):
            step["left_keys"] = []
        if not isinstance(step["right_keys"], list):
            step["right_keys"] = []
        if not isinstance(step["left_by_keys"], list):
            step["left_by_keys"] = []
        if not isinstance(step["right_by_keys"], list):
            step["right_by_keys"] = []
        if not isinstance(step["union_column_mapping"], dict):
            step["union_column_mapping"] = {}


def _update_table_config_in_state(cfg: TableConfig) -> None:
    st.session_state["table_configs"][cfg.table_id] = cfg.to_dict()


def _sync_uploaded_files(uploaded_files: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """Sync Streamlit uploaded files with session table configs and return an in-memory file map."""
    uploaded_map: dict[str, dict[str, Any]] = {}
    table_cfgs: dict[str, dict[str, Any]] = st.session_state["table_configs"]

    hash_to_existing_id: dict[str, str] = {}
    for tid, raw_cfg in table_cfgs.items():
        file_hash = raw_cfg.get("file_hash")
        if isinstance(file_hash, str) and file_hash:
            hash_to_existing_id[file_hash] = tid

    for uploaded in uploaded_files:
        data = uploaded.getvalue()
        file_hash = sha256_hex(data)
        source_kind = _table_kind_from_filename(uploaded.name)
        table_id = hash_to_existing_id.get(file_hash, _safe_table_id(file_hash))

        uploaded_map[table_id] = {
            "table_id": table_id,
            "name": uploaded.name,
            "kind": source_kind,
            "bytes": data,
            "sha256": file_hash,
        }

        existing_cfg = table_cfgs.get(table_id)
        if existing_cfg:
            cfg = TableConfig.from_dict(existing_cfg)
            cfg.source_file_name = uploaded.name
            cfg.source_kind = source_kind  # type: ignore[assignment]
            cfg.file_hash = file_hash
        else:
            cfg = TableConfig(
                table_id=table_id,
                table_name=Path(uploaded.name).stem,
                source_file_name=uploaded.name,
                source_kind=source_kind,  # type: ignore[arg-type]
                file_hash=file_hash,
            )
            if source_kind == "csv":
                try:
                    cfg.csv_options = detect_csv_options(data)
                except Exception:
                    cfg.csv_options = CSVOptions()
            else:
                try:
                    sheets = list_excel_sheets(data, uploaded.name)
                    if sheets:
                        cfg.excel_options.sheet_name = sheets[0]
                except Exception:
                    pass
        _update_table_config_in_state(cfg)

    _ensure_join_plan_shape()
    _reconcile_plan_with_table_configs(uploaded_map)
    return uploaded_map


def _reconcile_plan_with_table_configs(uploaded_map: dict[str, dict[str, Any]]) -> None:
    """Keep base table and step table references valid when tables are added/removed."""
    table_cfgs = st.session_state["table_configs"]
    table_ids = list(table_cfgs.keys())
    if not table_ids:
        st.session_state["join_plan"]["base_table_id"] = ""
        st.session_state["join_plan"]["steps"] = []
        return

    plan = st.session_state["join_plan"]
    if plan["base_table_id"] not in table_cfgs:
        plan["base_table_id"] = table_ids[0]

    for step in plan["steps"]:
        if step.get("right_table_id") not in table_cfgs:
            step["right_table_id"] = ""


def _make_new_step(default_right_table_id: str = "") -> dict[str, Any]:
    idx = len(st.session_state["join_plan"]["steps"])
    return {
        "step_id": _safe_step_id(idx),
        "right_table_id": default_right_table_id,
        "operation": "join",
        "join_algorithm": "equi",
        "join_type": "left",
        "left_keys": [],
        "right_keys": [],
        "left_by_keys": [],
        "right_by_keys": [],
        "asof_direction": "backward",
        "asof_tolerance": "",
        "asof_allow_exact_matches": True,
        "conflict_policy": "keep_both",
        "suffixes": ["_l", "_r"],
        "union_column_mapping": {},
        "union_right_column_suffix": "_u",
        "union_add_source_column": False,
        "union_source_column_name": "_source_table",
        "union_source_value": "",
    }


def _get_table_configs_models() -> list[TableConfig]:
    return [TableConfig.from_dict(v) for v in st.session_state["table_configs"].values()]


def _get_join_plan_model() -> JoinPlan:
    _ensure_join_plan_shape()
    plan = st.session_state["join_plan"]
    return JoinPlan(
        base_table_id=str(plan.get("base_table_id", "")),
        row_explosion_warn_ratio=float(plan.get("row_explosion_warn_ratio", 10.0)),
        steps=[JoinStep.from_dict(step) for step in plan.get("steps", [])],
    )


def _get_output_settings_model() -> OutputSettings:
    settings = st.session_state["output_settings"]
    return OutputSettings.from_dict(settings)


def _current_recipe() -> Recipe:
    """Build a Recipe object from current state (validates structure)."""
    return build_recipe(
        tables=_get_table_configs_models(),
        join_plan=_get_join_plan_model(),
        output_settings=_get_output_settings_model(),
        ui_settings={
            "preview_rows": int(st.session_state["preview_rows"]),
            "row_explosion_warn_ratio": float(st.session_state["join_plan"]["row_explosion_warn_ratio"]),
        },
    )


def _apply_recipe_to_state(recipe: Recipe) -> None:
    """Apply a loaded recipe to Streamlit session state."""
    table_cfgs: dict[str, dict[str, Any]] = st.session_state["table_configs"]
    incoming_by_id = {t.table_id: t for t in recipe.tables}

    # Merge by table_id first; keep already uploaded file hash/filename if the file is currently present.
    for table_id, incoming in incoming_by_id.items():
        existing = table_cfgs.get(table_id)
        if existing:
            merged = TableConfig.from_dict(incoming.to_dict())
            existing_cfg = TableConfig.from_dict(existing)
            if existing_cfg.file_hash:
                merged.file_hash = existing_cfg.file_hash
            if existing_cfg.source_file_name:
                merged.source_file_name = existing_cfg.source_file_name
            if existing_cfg.source_kind:
                merged.source_kind = existing_cfg.source_kind
            table_cfgs[table_id] = merged.to_dict()
        else:
            table_cfgs[table_id] = incoming.to_dict()

    st.session_state["join_plan"] = recipe.join_plan.to_dict()
    st.session_state["output_settings"] = recipe.output_settings.to_dict()
    if "preview_rows" in recipe.ui_settings:
        try:
            st.session_state["preview_rows"] = max(10, int(recipe.ui_settings["preview_rows"]))
        except Exception:
            pass
    _ensure_join_plan_shape()


def _show_exception(title: str, exc: Exception) -> None:
    """Render a user-friendly error with traceback details in an expander."""
    st.error(f"{title}: {exc}")
    with st.expander("詳細エラー情報", expanded=False):
        st.code(traceback.format_exc())


def _sanitize_columns_for_table(cfg: TableConfig, available_columns: list[str]) -> TableConfig:
    """Drop stale selected columns/dtype overrides after parsing option changes."""
    available_set = set(available_columns)
    if cfg.selected_columns:
        cfg.selected_columns = [c for c in cfg.selected_columns if c in available_set]
    cfg.dtype_overrides = {k: v for k, v in cfg.dtype_overrides.items() if k in available_set}
    return cfg


def _add_external_table(source_kind: str) -> None:
    """Add a new SQL/PI table config with source-specific defaults."""
    labels = {
        SQL_SOURCE_KIND: "SQLテーブル",
        "pi_da_tag": "PI DAタグ",
        "af_attribute": "PI AF属性",
        "af_event_frame": "PI AFイベントフレーム",
    }
    table_id = _safe_external_table_id(source_kind.replace("_", ""))
    cfg = TableConfig(
        table_id=table_id,
        table_name=f"{labels.get(source_kind, source_kind)}_{len(st.session_state['table_configs']) + 1}",
        source_file_name=_default_source_file_name(source_kind),
        source_kind=source_kind,  # type: ignore[arg-type]
        source_options=_default_source_options(source_kind),
    )
    _update_table_config_in_state(cfg)
    st.session_state["source_add_message"] = ("success", f"{labels.get(source_kind, source_kind)} を追加しました。")


def _render_source_registration_sidebar() -> None:
    """Render quick-add buttons for non-file data sources."""
    st.sidebar.subheader("外部データソース追加")
    st.sidebar.caption("SQLデータベースや PI AF SDK から読み込むテーブルを追加できます。")
    st.sidebar.caption(
        "PI DA追加=PIタグ, AF属性追加=AF属性, AFイベント追加=イベントフレーム。"
        " 取得種別を変える場合は、目的の種別でテーブルを追加してください。"
    )

    c1, c2 = st.sidebar.columns(2)
    with c1:
        if st.button("SQL追加", key="add_sql_source_btn", use_container_width=True):
            _add_external_table(SQL_SOURCE_KIND)
            _rerun()
    with c2:
        if st.button("PI DA追加", key="add_pi_da_source_btn", use_container_width=True):
            _add_external_table("pi_da_tag")
            _rerun()

    c3, c4 = st.sidebar.columns(2)
    with c3:
        if st.button("AF属性追加", key="add_af_attr_source_btn", use_container_width=True):
            _add_external_table("af_attribute")
            _rerun()
    with c4:
        if st.button("AFイベント追加", key="add_af_ef_source_btn", use_container_width=True):
            _add_external_table("af_event_frame")
            _rerun()

    msg = st.session_state.get("source_add_message")
    if isinstance(msg, tuple) and len(msg) == 2:
        level, text = msg
        if level == "success":
            st.sidebar.success(str(text))
        else:
            st.sidebar.error(str(text))


def _render_sql_source_options(cfg: TableConfig, table_id: str) -> TableConfig:
    """Render SQL source settings editor."""
    options = _default_source_options(SQL_SOURCE_KIND)
    options.update(dict(cfg.source_options or {}))

    dbms_value = normalize_dbms(str(options.get("dbms", "sqlserver")))
    options["dbms"] = st.selectbox(
        "DBMS",
        options=SQL_DB_OPTIONS,
        index=SQL_DB_OPTIONS.index(dbms_value) if dbms_value in SQL_DB_OPTIONS else 0,
        key=f"sql_dbms_{table_id}",
        format_func=dbms_label,
    )
    dbms_value = str(options["dbms"])

    if dbms_value == "sqlite":
        options["sqlite_path"] = st.text_input(
            "SQLiteファイルパス",
            value=str(options.get("sqlite_path", "")),
            key=f"sql_sqlite_path_{table_id}",
        )
    else:
        col1, col2 = st.columns(2)
        with col1:
            options["host"] = st.text_input(
                "ホスト/サーバー名",
                value=str(options.get("host", "")),
                key=f"sql_host_{table_id}",
            )
            options["database"] = st.text_input(
                "データベース名（Oracleはサービス名）",
                value=str(options.get("database", "")),
                key=f"sql_database_{table_id}",
            )
            options["username"] = st.text_input(
                "ユーザー名",
                value=str(options.get("username", "")),
                key=f"sql_user_{table_id}",
            )
        with col2:
            options["port"] = st.text_input(
                "ポート（任意）",
                value=str(options.get("port", "")),
                key=f"sql_port_{table_id}",
            )
            options["schema"] = st.text_input(
                "スキーマ（任意）",
                value=str(options.get("schema", "")),
                key=f"sql_schema_{table_id}",
            )
            options["password"] = st.text_input(
                "パスワード",
                value=str(options.get("password", "")),
                key=f"sql_password_{table_id}",
                type="password",
            )

    catalog_key = f"sql_table_catalog_{table_id}"
    if catalog_key not in st.session_state:
        st.session_state[catalog_key] = []

    b1, b2 = st.columns(2)
    with b1:
        if st.button("接続してテーブル一覧取得", key=f"sql_list_tables_{table_id}", use_container_width=True):
            try:
                st.session_state[catalog_key] = list_sql_tables_from_options(options)
                st.success(f"{len(st.session_state[catalog_key])} 件のテーブルを取得しました。")
            except Exception as exc:
                st.error(f"テーブル一覧取得エラー: {exc}")
    with b2:
        sample_top_n = int(
            st.number_input(
                "サンプル件数",
                min_value=1,
                max_value=100000,
                value=1000,
                step=100,
                key=f"sql_sample_n_{table_id}",
            )
        )

    available_tables: list[str] = [str(v) for v in st.session_state.get(catalog_key, [])]
    selected_table = st.selectbox(
        "取得済みテーブル一覧（任意）",
        options=[""] + available_tables,
        index=0,
        key=f"sql_table_pick_{table_id}",
        format_func=lambda v: "(未選択)" if v == "" else v,
    )
    if st.button("SELECT文を作成", key=f"sql_build_query_{table_id}", use_container_width=False):
        if selected_table:
            try:
                options["query"] = build_sql_sample_query_from_options(options, selected_table, top_n=sample_top_n)
            except Exception as exc:
                st.error(f"SELECT文作成エラー: {exc}")
        else:
            st.warning("テーブル一覧から対象テーブルを選択してください。")

    options["query"] = st.text_area(
        "SQLクエリ",
        value=str(options.get("query", "")),
        height=140,
        key=f"sql_query_{table_id}",
        help="例: SELECT * FROM table_name",
    )
    cfg.source_options = options
    return cfg


def _render_pi_source_options(cfg: TableConfig, table_id: str) -> TableConfig:
    """Render PI AF SDK source settings editor."""
    mode_labels = {
        "pi_da_tag": "PI DAサーバーのPIタグデータ",
        "af_attribute": "PI AFサーバーのAF属性データ",
        "af_event_frame": "PI AFサーバーのイベントフレームデータ",
    }
    mode_descriptions = {
        "pi_da_tag": "PI Data Archive からタグ値（Snapshot/Recorded/Interpolated/Summary）を取得します。",
        "af_attribute": "AFデータベース内のエレメント属性値を、PIタグ相当の時系列形式で取得します。",
        "af_event_frame": "AFイベントフレームをテンプレート・期間・イベント生成分析名で抽出します。",
    }
    source_kind = str(cfg.source_kind)
    if source_kind not in mode_labels:
        source_kind = "pi_da_tag"
        cfg.source_kind = source_kind  # type: ignore[assignment]
        cfg.source_file_name = _default_source_file_name(source_kind)

    options = _default_source_options(source_kind)
    options.update(dict(cfg.source_options or {}))

    st.info(f"{mode_labels[source_kind]}: {mode_descriptions[source_kind]}")
    st.caption("取得種別はサイドバーで追加したテーブル種別で固定です。")
    st.caption("名前一覧は改行・カンマ・セミコロン・読点（、）区切りで入力できます。")

    options["max_rows_per_tag"] = int(
        st.number_input(
            "最大行数（タグ/属性/検索）",
            min_value=1,
            max_value=500000,
            value=int(options.get("max_rows_per_tag", 10000) or 10000),
            step=100,
            key=f"pi_max_rows_{table_id}",
        )
    )

    if source_kind == "pi_da_tag":
        col1, col2 = st.columns(2)
        with col1:
            options["pi_server"] = st.text_input(
                "PI DAサーバー名（任意）",
                value=str(options.get("pi_server", "")),
                key=f"pi_server_{table_id}",
            )
            options["tags_text"] = st.text_area(
                "PIタグ一覧",
                value=str(options.get("tags_text", "")),
                height=100,
                key=f"pi_tags_{table_id}",
            )
        with col2:
            query_type = normalize_pi_query_type(str(options.get("query_type", "recorded")))
            options["query_type"] = st.selectbox(
                "取得種別",
                options=PI_QUERY_TYPE_OPTIONS,
                index=PI_QUERY_TYPE_OPTIONS.index(query_type) if query_type in PI_QUERY_TYPE_OPTIONS else 0,
                key=f"pi_query_type_{table_id}",
            )
            options["start_time"] = st.text_input(
                "開始時刻",
                value=str(options.get("start_time", "*-1d")),
                key=f"pi_start_{table_id}",
            )
            options["end_time"] = st.text_input(
                "終了時刻",
                value=str(options.get("end_time", "*")),
                key=f"pi_end_{table_id}",
            )
            options["interval"] = st.text_input(
                "間隔（補間/集計）",
                value=str(options.get("interval", "1h")),
                key=f"pi_interval_{table_id}",
            )
    elif source_kind == "af_attribute":
        col1, col2 = st.columns(2)
        with col1:
            options["af_server"] = st.text_input(
                "PI AFサーバー名（任意）",
                value=str(options.get("af_server", "")),
                key=f"af_server_{table_id}",
            )
            options["af_database"] = st.text_input(
                "AFデータベース名",
                value=str(options.get("af_database", "")),
                key=f"af_database_{table_id}",
            )
            options["af_element"] = st.text_input(
                "AFエレメント名",
                value=str(options.get("af_element", "")),
                key=f"af_element_{table_id}",
            )
        with col2:
            query_type = normalize_pi_query_type(str(options.get("query_type", "recorded")))
            options["query_type"] = st.selectbox(
                "取得種別",
                options=PI_QUERY_TYPE_OPTIONS,
                index=PI_QUERY_TYPE_OPTIONS.index(query_type) if query_type in PI_QUERY_TYPE_OPTIONS else 0,
                key=f"pi_query_type_{table_id}",
            )
            options["af_attributes_text"] = st.text_area(
                "AF属性名一覧",
                value=str(options.get("af_attributes_text", "")),
                height=100,
                key=f"af_attributes_{table_id}",
            )
            options["start_time"] = st.text_input(
                "開始時刻",
                value=str(options.get("start_time", "*-1d")),
                key=f"pi_start_{table_id}",
            )
            options["end_time"] = st.text_input(
                "終了時刻",
                value=str(options.get("end_time", "*")),
                key=f"pi_end_{table_id}",
            )
            options["interval"] = st.text_input(
                "間隔（補間/集計）",
                value=str(options.get("interval", "1h")),
                key=f"pi_interval_{table_id}",
            )
    else:  # af_event_frame
        col1, col2 = st.columns(2)
        with col1:
            options["af_server"] = st.text_input(
                "PI AFサーバー名（任意）",
                value=str(options.get("af_server", "")),
                key=f"af_server_{table_id}",
            )
            options["af_database"] = st.text_input(
                "AFデータベース名",
                value=str(options.get("af_database", "")),
                key=f"af_database_{table_id}",
            )
            options["ef_template"] = st.text_input(
                "イベントフレームテンプレート",
                value=str(options.get("ef_template", "")),
                key=f"af_ef_template_{table_id}",
            )
            options["start_time"] = st.text_input(
                "開始時刻",
                value=str(options.get("start_time", "*-1d")),
                key=f"af_ef_start_{table_id}",
            )
        with col2:
            options["ef_analyses_text"] = st.text_area(
                "イベント生成分析名一覧",
                value=str(options.get("ef_analyses_text", "")),
                height=100,
                key=f"af_ef_analyses_{table_id}",
            )
            options["end_time"] = st.text_input(
                "終了時刻",
                value=str(options.get("end_time", "*")),
                key=f"af_ef_end_{table_id}",
            )

    if source_kind in {"pi_da_tag", "af_attribute"}:
        summary_default = options.get("summary_functions", ["average", "min", "max"])
        if not isinstance(summary_default, list):
            summary_default = [str(v) for v in summary_default] if isinstance(summary_default, tuple) else ["average"]
        options["summary_functions"] = st.multiselect(
            "Summary関数（summary選択時）",
            options=PI_SUMMARY_FUNCTION_OPTIONS,
            default=[v for v in summary_default if v in PI_SUMMARY_FUNCTION_OPTIONS],
            key=f"pi_summary_fns_{table_id}",
        )

    if st.button("PI設定を検証", key=f"pi_validate_{table_id}", use_container_width=False):
        try:
            _ = build_pi_query_config(
                data_source=source_kind,
                pi_server=options.get("pi_server"),
                af_server=options.get("af_server"),
                af_database=options.get("af_database"),
                query_type=options.get("query_type"),
                tags_text=options.get("tags_text"),
                af_element=options.get("af_element"),
                af_attributes_text=options.get("af_attributes_text"),
                start_time=options.get("start_time"),
                end_time=options.get("end_time"),
                interval=options.get("interval"),
                summary_functions=options.get("summary_functions"),
                max_rows_per_tag=options.get("max_rows_per_tag"),
                ef_template=options.get("ef_template"),
                ef_analyses_text=options.get("ef_analyses_text"),
            )
            st.success("PI設定は妥当です。")
        except Exception as exc:
            st.error(f"PI設定エラー: {exc}")

    cfg.source_options = options
    return cfg


def _render_table_management(
    uploaded_map: dict[str, dict[str, Any]]
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Render table configuration UI and return prepared preview tables."""
    table_cfgs = st.session_state["table_configs"]
    previews: dict[str, pd.DataFrame] = {}
    preview_errors: dict[str, str] = {}
    preview_rows = int(st.session_state["preview_rows"])

    st.subheader("入力テーブル")
    st.caption("読み込み設定（文字コード・シート・ヘッダ行・型）を調整し、結合前データを確認します。")
    if not table_cfgs:
        st.info("サイドバーから CSV/Excel をアップロードするか、外部データソース追加ボタンで SQL / PI テーブルを追加してください。")
        return previews, preview_errors

    for idx, table_id in enumerate(sorted(table_cfgs.keys())):
        cfg = TableConfig.from_dict(table_cfgs[table_id])
        cfg = _ensure_source_options_defaults(cfg)
        source_kind = str(cfg.source_kind)
        uploaded = uploaded_map.get(table_id) if is_file_source(source_kind) else None
        if is_file_source(source_kind):
            status = "アップロード済み" if uploaded else "未アップロード"
        else:
            status = "外部データソース"

        with st.expander(f"{cfg.table_name} ({cfg.source_file_name}) - {status}", expanded=idx == 0):
            cfg.table_name = st.text_input(
                "テーブル名",
                value=cfg.table_name,
                key=f"table_name_{table_id}",
            )
            cfg.normalize_columns = st.checkbox(
                "列名を正規化（前後空白除去 + NFKC）",
                value=cfg.normalize_columns,
                key=f"normalize_columns_{table_id}",
            )

            if is_file_source(source_kind) and not uploaded:
                st.warning("このテーブルに対応するファイルが現在アップロードされていません。レシピから読み込んだ可能性があります。")
                _update_table_config_in_state(cfg)
                continue

            if source_kind == "csv":
                raw_bytes = uploaded["bytes"] if uploaded else b""
                detected = detect_csv_options(raw_bytes)
                csv_col1, csv_col2 = st.columns(2)
                with csv_col1:
                    cfg.csv_options.encoding = st.selectbox(
                        "文字コード",
                        options=CSV_ENCODING_OPTIONS,
                        index=CSV_ENCODING_OPTIONS.index(cfg.csv_options.encoding)
                        if cfg.csv_options.encoding in CSV_ENCODING_OPTIONS
                        else 0,
                        key=f"csv_encoding_{table_id}",
                        help=f"auto推定: {detected.encoding}",
                    )
                    cfg.csv_options.delimiter = st.selectbox(
                        "区切り文字",
                        options=CSV_DELIMITER_OPTIONS,
                        index=CSV_DELIMITER_OPTIONS.index(cfg.csv_options.delimiter)
                        if cfg.csv_options.delimiter in CSV_DELIMITER_OPTIONS
                        else 0,
                        key=f"csv_delimiter_{table_id}",
                        format_func=lambda x: {"\t": "\\t", ",": ",", ";": ";", "|": "|", "auto": "auto"}.get(x, x),
                        help=f"auto推定: {repr(detected.delimiter)}",
                    )
                with csv_col2:
                    cfg.csv_options.quotechar = st.selectbox(
                        "引用符",
                        options=CSV_QUOTE_OPTIONS,
                        index=CSV_QUOTE_OPTIONS.index(cfg.csv_options.quotechar)
                        if cfg.csv_options.quotechar in CSV_QUOTE_OPTIONS
                        else 0,
                        key=f"csv_quotechar_{table_id}",
                        help=f"auto推定: {repr(detected.quotechar)}",
                    )
                    cfg.csv_options.header_row = int(
                        st.number_input(
                            "ヘッダ行 (1始まり)",
                            min_value=1,
                            step=1,
                            value=int(cfg.csv_options.header_row or 1),
                            key=f"csv_header_row_{table_id}",
                        )
                    )
            elif source_kind == "excel":
                raw_bytes = uploaded["bytes"] if uploaded else b""
                try:
                    sheet_names = list_excel_sheets(raw_bytes, cfg.source_file_name)
                except Exception as exc:
                    preview_errors[table_id] = str(exc)
                    _show_exception(f"Excel設定読み込みエラー ({cfg.table_name})", exc if isinstance(exc, Exception) else Exception(str(exc)))
                    _update_table_config_in_state(cfg)
                    continue
                if not sheet_names:
                    preview_errors[table_id] = "Excelにシートがありません。"
                    st.error("Excelにシートがありません。")
                    _update_table_config_in_state(cfg)
                    continue
                if cfg.excel_options.sheet_name not in sheet_names:
                    cfg.excel_options.sheet_name = sheet_names[0]
                excel_col1, excel_col2 = st.columns(2)
                with excel_col1:
                    cfg.excel_options.sheet_name = st.selectbox(
                        "シート選択",
                        options=sheet_names,
                        index=sheet_names.index(cfg.excel_options.sheet_name) if cfg.excel_options.sheet_name in sheet_names else 0,
                        key=f"excel_sheet_{table_id}",
                    )
                with excel_col2:
                    cfg.excel_options.header_row = int(
                        st.number_input(
                            "ヘッダ行 (1始まり)",
                            min_value=1,
                            step=1,
                            value=int(cfg.excel_options.header_row or 1),
                            key=f"excel_header_row_{table_id}",
                        )
                    )
            elif source_kind == SQL_SOURCE_KIND:
                st.caption("SQL接続情報とSQL文を設定します。必要に応じてテーブル一覧からSELECT文を生成できます。")
                cfg = _render_sql_source_options(cfg, table_id)
            elif source_kind in PI_SOURCE_KINDS:
                st.caption("PI AF SDK の取得条件を設定します。タグ/属性/イベントフレームのいずれかを指定してください。")
                cfg = _render_pi_source_options(cfg, table_id)
            else:
                st.error(f"未対応のデータソース種別です: {source_kind}")
                _update_table_config_in_state(cfg)
                continue

            try:
                # Build a temporary preview to derive column candidates before selection is applied.
                temp_cfg = TableConfig.from_dict(cfg.to_dict())
                temp_cfg.selected_columns = []
                normalized_preview = load_table_from_source(temp_cfg, uploaded_entry=uploaded, nrows=preview_rows)
                all_columns = [str(c) for c in normalized_preview.columns]
                cfg = _sanitize_columns_for_table(cfg, all_columns)
                if not cfg.selected_columns:
                    cfg.selected_columns = all_columns.copy()

                col_sel = st.multiselect(
                    "使用する列",
                    options=all_columns,
                    default=[c for c in cfg.selected_columns if c in all_columns],
                    key=f"selected_columns_{table_id}",
                )
                cfg.selected_columns = list(col_sel)

                profile_df = profile_dataframe(normalized_preview)
                st.caption("型推定（プレビュー基準）")
                st.dataframe(profile_df, use_container_width=True, height=220)

                with st.expander("型上書き（列ごと）", expanded=False):
                    inferred_map = {
                        str(row["column"]): str(row["inferred_type"])
                        for _, row in profile_df.iterrows()
                    }
                    for col_name in all_columns:
                        col_a, col_b = st.columns([3, 2])
                        with col_a:
                            st.text(f"{col_name} (推定: {inferred_map.get(col_name, 'string')})")
                        with col_b:
                            current_override = cfg.dtype_overrides.get(col_name, "auto")
                            selected_override = st.selectbox(
                                "型",
                                options=DTYPE_OVERRIDE_OPTIONS,
                                index=DTYPE_OVERRIDE_OPTIONS.index(current_override)
                                if current_override in DTYPE_OVERRIDE_OPTIONS
                                else 0,
                                key=f"dtype_override_{table_id}_{col_name}",
                                label_visibility="collapsed",
                            )
                            if selected_override == "auto":
                                cfg.dtype_overrides.pop(col_name, None)
                            else:
                                cfg.dtype_overrides[col_name] = selected_override  # type: ignore[assignment]

                prepared_preview = load_table_from_source(cfg, uploaded_entry=uploaded, nrows=preview_rows)
                previews[table_id] = prepared_preview
                st.caption(f"プレビュー（先頭 {preview_rows} 行）: {prepared_preview.shape[0]} 行 x {prepared_preview.shape[1]} 列")
                st.dataframe(prepared_preview.head(preview_rows), use_container_width=True, height=300)
            except Exception as exc:
                preview_errors[table_id] = str(exc)
                _show_exception(f"プレビュー読み込みエラー ({cfg.table_name})", exc if isinstance(exc, Exception) else Exception(str(exc)))

            _update_table_config_in_state(cfg)

    return previews, preview_errors


def _move_step(index: int, direction: int) -> None:
    """Move a join step up/down in the plan."""
    steps = st.session_state["join_plan"]["steps"]
    new_index = index + direction
    if new_index < 0 or new_index >= len(steps):
        return
    steps[index], steps[new_index] = steps[new_index], steps[index]
    for i, step in enumerate(steps):
        step["step_id"] = _safe_step_id(i)


def _sanitize_step_keys(step: dict[str, Any], left_columns: list[str], right_columns: list[str]) -> None:
    """Remove stale key selections after table/column changes."""
    step["left_keys"] = [c for c in step.get("left_keys", []) if c in left_columns]
    step["right_keys"] = [c for c in step.get("right_keys", []) if c in right_columns]
    step["left_by_keys"] = [c for c in step.get("left_by_keys", []) if c in left_columns]
    step["right_by_keys"] = [c for c in step.get("right_by_keys", []) if c in right_columns]


def _seed_union_mapping_suggestions(step: dict[str, Any], left_columns: list[str], right_columns: list[str]) -> None:
    """Populate missing union column mappings using heuristic suggestions."""
    existing = step.get("union_column_mapping", {})
    if not isinstance(existing, dict):
        existing = {}
    existing = {str(k): str(v) for k, v in existing.items() if str(k) in right_columns}

    suggestions = suggest_union_column_mapping(left_columns, right_columns)
    for right_col in right_columns:
        current = existing.get(right_col)
        if current and (current in left_columns or current in UNION_MAPPING_SPECIAL_OPTIONS):
            continue
        suggestion = suggestions.get(right_col)
        if suggestion and suggestion.suggested_left_column in left_columns:
            existing[right_col] = suggestion.suggested_left_column
        else:
            # Keep exact-name matches as-is if available; otherwise mark as new column.
            existing[right_col] = right_col if right_col in left_columns else UNION_KEEP_AS_NEW
    step["union_column_mapping"] = existing


def _render_union_mapping_editor(step: dict[str, Any], step_id: str, left_columns: list[str], right_columns: list[str]) -> None:
    """Render editable union column mapping with auto suggestions."""
    if not left_columns or not right_columns:
        st.caption("縦連結の列対応を表示するには、左/右テーブルのプレビューが必要です。")
        return

    _seed_union_mapping_suggestions(step, left_columns, right_columns)
    mapping = dict(step.get("union_column_mapping", {}))
    suggestions = suggest_union_column_mapping(left_columns, right_columns)

    st.caption("縦連結の列対応（右列 -> 左列 / 新規列 / 除外）")
    with st.expander("列マッピング提案を確認/修正", expanded=False):
        for right_col in right_columns:
            suggestion = suggestions.get(right_col)
            suggested_left = suggestion.suggested_left_column if suggestion else None
            score_text = f"{suggestion.score:.2f}" if suggestion else "0.00"
            reason_text = suggestion.reason if suggestion else "no suggestion"

            row1, row2 = st.columns([2, 3])
            with row1:
                st.text(f"{right_col}")
                st.caption(f"提案: {suggested_left or '新規列'} ({score_text}, {reason_text})")
            with row2:
                options = [UNION_KEEP_AS_NEW, UNION_DROP] + left_columns
                current_target = mapping.get(right_col, UNION_KEEP_AS_NEW)
                if current_target not in options:
                    current_target = UNION_KEEP_AS_NEW
                selected = st.selectbox(
                    f"target_{right_col}",
                    options=options,
                    index=options.index(current_target),
                    key=f"union_map_{step_id}_{right_col}",
                    format_func=lambda v: (
                        "新規列として保持" if v == UNION_KEEP_AS_NEW else "この列を除外" if v == UNION_DROP else v
                    ),
                    label_visibility="collapsed",
                )
                mapping[right_col] = selected

        step["union_column_mapping"] = mapping

    col_a, col_b = st.columns(2)
    with col_a:
        step["union_right_column_suffix"] = st.text_input(
            "新規列suffix（衝突時）",
            value=str(step.get("union_right_column_suffix", "_u")),
            key=f"union_suffix_{step_id}",
        )
    with col_b:
        step["union_add_source_column"] = st.checkbox(
            "出典列を追加",
            value=bool(step.get("union_add_source_column", False)),
            key=f"union_add_source_{step_id}",
        )

    if step.get("union_add_source_column", False):
        src_a, src_b = st.columns(2)
        with src_a:
            step["union_source_column_name"] = st.text_input(
                "出典列名",
                value=str(step.get("union_source_column_name", "_source_table")),
                key=f"union_source_colname_{step_id}",
            )
        with src_b:
            step["union_source_value"] = st.text_input(
                "右テーブルの出典値",
                value=str(step.get("union_source_value", "")),
                key=f"union_source_value_{step_id}",
            )


def _render_join_plan_sidebar(
    uploaded_map: dict[str, dict[str, Any]],
    table_previews: dict[str, pd.DataFrame],
) -> bool:
    """Render the join/union plan editor in the sidebar and return whether execution was requested."""
    _ensure_join_plan_shape()
    plan = st.session_state["join_plan"]
    table_cfgs = st.session_state["table_configs"]
    table_ids = list(table_cfgs.keys())

    st.sidebar.subheader("結合・縦連結の手順")
    st.sidebar.caption("手順は上から順に適用されます。ベーステーブルに対して段階的に設定してください。")
    if not table_ids:
        st.sidebar.info("テーブルを1件以上追加すると手順を編集できます。")
        return False

    base_labels = {tid: _table_label(tid, table_cfgs, uploaded_map) for tid in table_ids}
    if plan["base_table_id"] not in table_cfgs:
        plan["base_table_id"] = table_ids[0]

    plan["base_table_id"] = st.sidebar.selectbox(
        "ベーステーブル",
        options=table_ids,
        index=table_ids.index(plan["base_table_id"]) if plan["base_table_id"] in table_ids else 0,
        format_func=lambda tid: base_labels.get(tid, tid),
        key="join_plan_base_table_select",
    )
    plan["row_explosion_warn_ratio"] = float(
        st.sidebar.number_input(
            "行数増加警告しきい値 (x)",
            min_value=1.1,
            max_value=1000.0,
            value=float(plan.get("row_explosion_warn_ratio", 10.0)),
            step=0.5,
            key="row_explosion_warn_ratio_input",
        )
    )

    add_col, reset_col = st.sidebar.columns(2)
    with add_col:
        if st.button("手順追加", key="add_join_step_btn", use_container_width=True):
            default_right = next((tid for tid in table_ids if tid != plan["base_table_id"]), "")
            plan["steps"].append(_make_new_step(default_right))
            _rerun()
    with reset_col:
        if st.button("手順全削除", key="clear_join_steps_btn", use_container_width=True):
            plan["steps"] = []
            _rerun()

    current_preview = table_previews.get(plan["base_table_id"])
    preview_engine = PandasEquiJoinEngine()
    preview_step_errors: list[str | None] = []

    for idx, step in enumerate(plan["steps"]):
        if step.get("step_id") is None:
            step["step_id"] = _safe_step_id(idx)
        step_id = str(step["step_id"])

        with st.sidebar.expander(f"{step_id}", expanded=(idx == 0)):
            ctrl_cols = st.columns(3)
            with ctrl_cols[0]:
                if st.button("↑", key=f"step_up_{step_id}", use_container_width=True):
                    _move_step(idx, -1)
                    _rerun()
            with ctrl_cols[1]:
                if st.button("↓", key=f"step_down_{step_id}", use_container_width=True):
                    _move_step(idx, 1)
                    _rerun()
            with ctrl_cols[2]:
                if st.button("削除", key=f"step_del_{step_id}", use_container_width=True):
                    plan["steps"].pop(idx)
                    for i, s in enumerate(plan["steps"]):
                        s["step_id"] = _safe_step_id(i)
                    _rerun()

            step["operation"] = st.selectbox(
                "ステップ種別",
                options=STEP_OPERATION_OPTIONS,
                index=STEP_OPERATION_OPTIONS.index(step.get("operation", "join"))
                if step.get("operation", "join") in STEP_OPERATION_OPTIONS
                else 0,
                key=f"step_operation_{step_id}",
                format_func=lambda op: "結合（横方向）" if op == "join" else "縦連結（Union）",
            )

            step["right_table_id"] = st.selectbox(
                "右テーブル",
                options=[""] + table_ids,
                index=([""] + table_ids).index(step.get("right_table_id", ""))
                if step.get("right_table_id", "") in ([""] + table_ids)
                else 0,
                format_func=lambda tid: "(未選択)" if tid == "" else base_labels.get(tid, tid),
                key=f"right_table_select_{step_id}",
            )

            if step["operation"] == "join":
                step["join_algorithm"] = st.selectbox(
                    "結合方式",
                    options=JOIN_ALGORITHM_OPTIONS,
                    index=JOIN_ALGORITHM_OPTIONS.index(step.get("join_algorithm", "equi"))
                    if step.get("join_algorithm", "equi") in JOIN_ALGORITHM_OPTIONS
                    else 0,
                    key=f"join_algorithm_{step_id}",
                    format_func=lambda alg: "通常結合（equi）" if alg == "equi" else "時系列近傍結合（asof）",
                )
            else:
                step["join_algorithm"] = "equi"

            left_columns = list(current_preview.columns) if isinstance(current_preview, pd.DataFrame) else []
            right_preview = table_previews.get(step["right_table_id"]) if step.get("right_table_id") else None
            right_columns = list(right_preview.columns) if isinstance(right_preview, pd.DataFrame) else []
            _sanitize_step_keys(step, left_columns, right_columns)

            if step["operation"] == "join":
                if step.get("join_algorithm", "equi") == "equi":
                    step["join_type"] = st.selectbox(
                        "結合種別",
                        options=JOIN_TYPE_OPTIONS,
                        index=JOIN_TYPE_OPTIONS.index(step.get("join_type", "left"))
                        if step.get("join_type", "left") in JOIN_TYPE_OPTIONS
                        else JOIN_TYPE_OPTIONS.index("left"),
                        key=f"join_type_{step_id}",
                    )
                    step["left_keys"] = st.multiselect(
                        "左キー（前段結果）",
                        options=left_columns,
                        default=step.get("left_keys", []),
                        key=f"left_keys_{step_id}",
                    )
                    step["right_keys"] = st.multiselect(
                        "右キー",
                        options=right_columns,
                        default=step.get("right_keys", []),
                        key=f"right_keys_{step_id}",
                    )
                else:
                    step["join_type"] = "left"
                    st.caption("時系列近傍結合（asof）は左結合のみ対応です。")

                    left_key_current = step.get("left_keys", [None])[0] if step.get("left_keys") else None
                    right_key_current = step.get("right_keys", [None])[0] if step.get("right_keys") else None

                    left_choice = st.selectbox(
                        "asof 左キー（時刻または数値）",
                        options=[""] + left_columns,
                        index=([""] + left_columns).index(left_key_current)
                        if left_key_current in ([""] + left_columns)
                        else 0,
                        key=f"asof_left_key_{step_id}",
                    )
                    step["left_keys"] = [left_choice] if left_choice else []

                    right_choice = st.selectbox(
                        "asof 右キー（時刻または数値）",
                        options=[""] + right_columns,
                        index=([""] + right_columns).index(right_key_current)
                        if right_key_current in ([""] + right_columns)
                        else 0,
                        key=f"asof_right_key_{step_id}",
                    )
                    step["right_keys"] = [right_choice] if right_choice else []

                    step["left_by_keys"] = st.multiselect(
                        "asof 左byキー（任意）",
                        options=left_columns,
                        default=step.get("left_by_keys", []),
                        key=f"asof_left_by_keys_{step_id}",
                    )
                    step["right_by_keys"] = st.multiselect(
                        "asof 右byキー（任意）",
                        options=right_columns,
                        default=step.get("right_by_keys", []),
                        key=f"asof_right_by_keys_{step_id}",
                    )
                    step["asof_direction"] = st.selectbox(
                        "asof 方向",
                        options=ASOF_DIRECTION_OPTIONS,
                        index=ASOF_DIRECTION_OPTIONS.index(step.get("asof_direction", "backward"))
                        if step.get("asof_direction", "backward") in ASOF_DIRECTION_OPTIONS
                        else 0,
                        key=f"asof_direction_{step_id}",
                    )
                    step["asof_tolerance"] = st.text_input(
                        "asof 許容幅（例: 5min / 1D / 10）",
                        value=str(step.get("asof_tolerance", "")),
                        key=f"asof_tolerance_{step_id}",
                    )
                    step["asof_allow_exact_matches"] = st.checkbox(
                        "完全一致を許可",
                        value=bool(step.get("asof_allow_exact_matches", True)),
                        key=f"asof_exact_{step_id}",
                    )

                step["conflict_policy"] = st.selectbox(
                    "同名列衝突",
                    options=CONFLICT_POLICY_OPTIONS,
                    index=CONFLICT_POLICY_OPTIONS.index(step.get("conflict_policy", "keep_both"))
                    if step.get("conflict_policy", "keep_both") in CONFLICT_POLICY_OPTIONS
                    else CONFLICT_POLICY_OPTIONS.index("keep_both"),
                    key=f"conflict_policy_{step_id}",
                )
                suffixes = step.get("suffixes", ["_l", "_r"])
                if not isinstance(suffixes, list) or len(suffixes) != 2:
                    suffixes = ["_l", "_r"]
                suf_col1, suf_col2 = st.columns(2)
                with suf_col1:
                    suffixes[0] = st.text_input("左suffix", value=str(suffixes[0]), key=f"suffix_l_{step_id}")
                with suf_col2:
                    suffixes[1] = st.text_input("右suffix", value=str(suffixes[1]), key=f"suffix_r_{step_id}")
                step["suffixes"] = [suffixes[0], suffixes[1]]
            else:
                st.caption("縦連結では列対応を自動提案します。必要に応じて手動で修正してください。")
                _render_union_mapping_editor(step, step_id, left_columns, right_columns)

            preview_error: str | None = None
            if not isinstance(current_preview, pd.DataFrame):
                preview_error = "前段結果プレビューなし"
                current_preview = None
            elif not isinstance(right_preview, pd.DataFrame):
                preview_error = "右テーブルプレビューなし"
                current_preview = None
            else:
                if step["operation"] == "join":
                    if step.get("join_algorithm", "equi") == "equi":
                        if (
                            not step.get("left_keys")
                            or not step.get("right_keys")
                            or len(step.get("left_keys", [])) != len(step.get("right_keys", []))
                        ):
                            preview_error = "キー未設定/不一致"
                    else:
                        if len(step.get("left_keys", [])) != 1 or len(step.get("right_keys", [])) != 1:
                            preview_error = "asofキー未設定"
                        elif len(step.get("left_by_keys", [])) != len(step.get("right_by_keys", [])):
                            preview_error = "asof byキー数不一致"

                if preview_error is None:
                    try:
                        temp_step = JoinStep.from_dict(step)
                        temp_result = preview_engine.execute_step(
                            current_preview.head(PREVIEW_PLAN_ROWS),
                            right_preview.head(PREVIEW_PLAN_ROWS),
                            temp_step,
                            row_explosion_warn_ratio=float(plan.get("row_explosion_warn_ratio", 10.0)),
                        )
                        current_preview = temp_result.output_df.head(PREVIEW_PLAN_ROWS)
                    except Exception as exc:
                        preview_error = str(exc)
                        current_preview = None

            if preview_error:
                st.caption(f"プレビュー: {preview_error}")
            elif isinstance(current_preview, pd.DataFrame):
                st.caption(f"プレビュー結果: {current_preview.shape[0]} x {current_preview.shape[1]}")
            preview_step_errors.append(preview_error)

    if any(err for err in preview_step_errors):
        st.sidebar.caption("一部ステップのプレビュー推定に失敗しています。実行時に詳細エラーを表示します。")

    st.sidebar.subheader("出力設定")
    st.sidebar.caption("最終結果の保存形式を指定します。")
    output_settings = st.session_state["output_settings"]
    output_settings["default_format"] = st.sidebar.selectbox(
        "既定出力形式",
        options=["csv", "excel"],
        index=["csv", "excel"].index(output_settings.get("default_format", "csv"))
        if output_settings.get("default_format", "csv") in ["csv", "excel"]
        else 0,
        key="output_default_format",
    )
    output_settings["csv_encoding"] = st.sidebar.selectbox(
        "CSV出力エンコーディング",
        options=["utf-8-sig", "utf-8", "cp932"],
        index=["utf-8-sig", "utf-8", "cp932"].index(output_settings.get("csv_encoding", "utf-8-sig"))
        if output_settings.get("csv_encoding", "utf-8-sig") in ["utf-8-sig", "utf-8", "cp932"]
        else 0,
        key="output_csv_encoding",
    )
    output_settings["excel_sheet_name"] = st.sidebar.text_input(
        "Excelシート名",
        value=str(output_settings.get("excel_sheet_name", "result")),
        key="output_excel_sheet_name",
    )

    st.sidebar.subheader("実行")
    st.sidebar.caption("現在の手順に沿って全件処理を実行します。")
    return bool(st.sidebar.button("処理を実行", type="primary", key="run_join_plan_button", use_container_width=True))


def _render_recipe_sidebar(uploaded_map: dict[str, dict[str, Any]]) -> None:
    """Render recipe import/export controls in the sidebar."""
    st.sidebar.subheader("レシピ")
    st.sidebar.caption("現在の設定を JSON で保存し、あとで同じ手順を再利用できます。")
    try:
        recipe = _current_recipe()
        recipe_text = recipe_to_json(recipe)
        st.sidebar.download_button(
            "レシピJSONを保存",
            data=recipe_text.encode("utf-8"),
            file_name="datastitcher_recipe.json",
            mime="application/json",
            use_container_width=True,
        )
    except Exception as exc:
        st.sidebar.caption(f"レシピ保存準備エラー: {exc}")

    recipe_upload = st.sidebar.file_uploader(
        "レシピJSONを読み込む",
        type=["json"],
        accept_multiple_files=False,
        key="recipe_json_uploader",
    )
    if st.sidebar.button("レシピ適用", key="apply_recipe_button", use_container_width=True):
        if recipe_upload is None:
            st.session_state["recipe_import_message"] = ("error", "レシピJSONファイルを選択してください。")
        else:
            try:
                text = recipe_upload.getvalue().decode("utf-8")
                recipe = recipe_from_json(text)
                _apply_recipe_to_state(recipe)
                st.session_state["recipe_import_message"] = (
                    "success",
                    f"レシピを適用しました (version={recipe.version}, tables={len(recipe.tables)}, steps={len(recipe.join_plan.steps)})",
                )
                _rerun()
            except Exception as exc:
                st.session_state["recipe_import_message"] = ("error", f"レシピ適用に失敗: {exc}")

    msg = st.session_state.get("recipe_import_message")
    if isinstance(msg, tuple) and len(msg) == 2:
        level, text = msg
        if level == "success":
            st.sidebar.success(str(text))
        else:
            st.sidebar.error(str(text))


def _load_table_for_execution(
    table_id: str,
    uploaded_map: dict[str, dict[str, Any]],
    cache: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Load and cache a full prepared table for execution."""
    if table_id in cache:
        return cache[table_id]
    table_cfgs = st.session_state["table_configs"]
    if table_id not in table_cfgs:
        raise UserInputError(f"テーブル定義が見つかりません: {table_id}")
    cfg = TableConfig.from_dict(table_cfgs[table_id])
    cfg = _ensure_source_options_defaults(cfg)
    uploaded = uploaded_map.get(table_id) if is_file_source(str(cfg.source_kind)) else None
    if is_file_source(str(cfg.source_kind)) and uploaded is None:
        raise UserInputError(
            f"テーブル '{cfg.table_name}' ({cfg.source_file_name}) のファイルがアップロードされていません。"
        )
    df = load_table_from_source(cfg, uploaded_entry=uploaded, nrows=None)
    cache[table_id] = df
    return df


def _execute_plan(uploaded_map: dict[str, dict[str, Any]]) -> None:
    """Execute the current join plan and persist results in session state."""
    join_plan = _get_join_plan_model()
    recipe = _current_recipe()
    load_cache: dict[str, pd.DataFrame] = {}

    def loader(table_id: str) -> pd.DataFrame:
        return _load_table_for_execution(table_id, uploaded_map, load_cache)

    execution_result = execute_join_plan(join_plan=join_plan, load_table=loader, engine=PandasEquiJoinEngine())

    st.session_state["last_execution"] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "result": execution_result,
    }

    input_files = []
    for table_id, raw_cfg in st.session_state["table_configs"].items():
        cfg = TableConfig.from_dict(raw_cfg)
        file_meta = uploaded_map.get(table_id)
        table_df = load_cache.get(table_id)
        input_files.append(
            {
                "table_id": table_id,
                "table_name": cfg.table_name,
                "file_name": cfg.source_file_name,
                "source_kind": cfg.source_kind,
                "sha256": cfg.file_hash or (file_meta["sha256"] if file_meta else None),
                "rows": int(table_df.shape[0]) if isinstance(table_df, pd.DataFrame) else None,
                "cols": int(table_df.shape[1]) if isinstance(table_df, pd.DataFrame) else None,
            }
        )

    log_entry = ExecutionLogEntry(
        executed_at=datetime.now(timezone.utc).isoformat(),
        recipe_version=recipe.version,
        input_files=input_files,
        base_table_id=join_plan.base_table_id,
        step_reports=[s.report.to_dict() for s in execution_result.step_results],
        final_shape=(int(execution_result.final_df.shape[0]), int(execution_result.final_df.shape[1])),
        status="success",
    )
    append_execution_log(log_entry, LOG_PATH)


def _render_step_report(step_result: Any, step_index: int) -> None:
    """Render one step report and unmatched downloads."""
    report = step_result.report
    step = step_result.step

    st.markdown(
        f"**手順 {step_index+1}**: 種別=`{getattr(step, 'operation', 'join')}` / "
        f"方式=`{getattr(step, 'join_algorithm', 'equi') if getattr(step, 'operation', 'join') == 'join' else 'union'}`"
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("左入力行数", report.left_rows)
    col2.metric("右入力行数", report.right_rows)
    col3.metric("出力行数", report.output_rows)
    growth_display = (
        f"{report.row_growth_ratio_vs_left:.2f}x" if report.row_growth_ratio_vs_left is not None else "-"
    )
    col4.metric("左比行数", growth_display)

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("左マッチ行数", report.matched_left_rows)
    q2.metric("左未マッチ行数", report.unmatched_left_rows)
    q3.metric("右マッチ行数", report.matched_right_rows)
    q4.metric("右未マッチ行数", report.unmatched_right_rows)

    rate_left = f"{report.left_match_rate * 100:.1f}%" if report.left_match_rate is not None else "-"
    rate_right = f"{report.right_match_rate * 100:.1f}%" if report.right_match_rate is not None else "-"
    st.caption(
        f"マッチ率: 左 {rate_left} / 右 {rate_right} | 重複キー行数: 左 {report.left_duplicate_key_rows}, 右 {report.right_duplicate_key_rows}"
    )

    if getattr(step, "operation", "join") == "join":
        if getattr(step, "join_algorithm", "equi") == "asof":
            st.caption(
                f"asof設定: 方向={getattr(step, 'asof_direction', 'backward')}, "
                f"tolerance={getattr(step, 'asof_tolerance', '') or '(none)'}, "
                f"完全一致許可={getattr(step, 'asof_allow_exact_matches', True)}"
            )
            st.markdown(
                f"**キー**: asof 左={step.left_keys} / asof 右={step.right_keys} / by 左={getattr(step, 'left_by_keys', [])} / by 右={getattr(step, 'right_by_keys', [])}"
            )
        else:
            st.markdown(
                f"**設定**: `{step.join_type}` / 左キー={step.left_keys} / 右キー={step.right_keys} / 衝突={step.conflict_policy}"
            )
    else:
        mapping = getattr(step, "union_column_mapping", {}) or {}
        sample_mapping = list(mapping.items())[:10]
        st.caption(
            f"縦連結の列対応数: {len(mapping)} / 例: {sample_mapping if sample_mapping else 'なし'}"
        )

    if report.details:
        st.json(report.details)

    if getattr(step, "operation", "join") == "union":
        st.info("縦連結の手順では未マッチ抽出は適用しません。")
        return

    st.markdown("未マッチ抽出")
    dl1, dl2 = st.columns(2)
    left_unmatched = step_result.unmatched_left_df
    right_unmatched = step_result.unmatched_right_df
    with dl1:
        st.caption(f"左未マッチ: {left_unmatched.shape[0]} 行")
        st.dataframe(left_unmatched.head(100), use_container_width=True, height=220)
        st.download_button(
            "左未マッチCSV",
            data=dataframe_to_csv_bytes(left_unmatched, encoding="utf-8-sig"),
            file_name=f"step{step_index+1}_left_unmatched.csv",
            mime="text/csv",
            key=f"dl_left_unmatched_{step_index}",
            use_container_width=True,
        )
    with dl2:
        st.caption(f"右未マッチ: {right_unmatched.shape[0]} 行")
        st.dataframe(right_unmatched.head(100), use_container_width=True, height=220)
        st.download_button(
            "右未マッチCSV",
            data=dataframe_to_csv_bytes(right_unmatched, encoding="utf-8-sig"),
            file_name=f"step{step_index+1}_right_unmatched.csv",
            mime="text/csv",
            key=f"dl_right_unmatched_{step_index}",
            use_container_width=True,
        )


def _render_execution_result() -> None:
    """Render the latest execution result if available."""
    payload = st.session_state.get("last_execution")
    if not payload:
        st.info("処理を実行すると、最終結果と品質指標をここに表示します。")
        return

    execution_result = payload["result"]
    final_df: pd.DataFrame = execution_result.final_df
    output_settings = _get_output_settings_model()

    st.subheader("最終結果")
    st.caption("全手順を適用した最終テーブルです。内容確認後に CSV または Excel で保存できます。")
    m1, m2, m3 = st.columns(3)
    m1.metric("行数", int(final_df.shape[0]))
    m2.metric("列数", int(final_df.shape[1]))
    m3.metric("実行時刻", payload.get("executed_at", "-"))

    if len(final_df) > EXCEL_MAX_ROWS:
        st.warning(
            f"Excelの1シート上限 ({EXCEL_MAX_ROWS:,} 行) を超えています。CSV出力を推奨します。"
        )

    preview_rows = int(st.session_state["preview_rows"])
    st.caption(f"最終結果プレビュー（先頭 {preview_rows} 行）")
    st.dataframe(final_df.head(preview_rows), use_container_width=True, height=360)

    csv_bytes = dataframe_to_csv_bytes(final_df, encoding=output_settings.csv_encoding)
    excel_bytes = dataframe_to_excel_bytes(final_df, sheet_name=output_settings.excel_sheet_name)

    dlc1, dlc2 = st.columns(2)
    with dlc1:
        st.download_button(
            "CSVダウンロード",
            data=csv_bytes,
            file_name="datastitcher_result.csv",
            mime="text/csv",
            key="download_final_csv",
            use_container_width=True,
        )
    with dlc2:
        st.download_button(
            "Excelダウンロード (1シート)",
            data=excel_bytes,
            file_name="datastitcher_result.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_final_excel",
            use_container_width=True,
        )

    st.subheader("ステップ品質指標（結合・縦連結）")
    if not execution_result.step_results:
        st.info("ステップがないため、ベーステーブルをそのまま出力しています。")
        return

    tabs = st.tabs([f"手順 {i+1}" for i in range(len(execution_result.step_results))])
    for i, (tab, step_result) in enumerate(zip(tabs, execution_result.step_results)):
        with tab:
            _render_step_report(step_result, i)


def run() -> None:
    """Streamlit app entrypoint."""
    st.set_page_config(page_title="DataStitcher", layout="wide")
    init_session_state()

    st.title("DataStitcher")
    st.caption(
        "CSV / Excel / SQLデータベース / PI AF SDK のデータを多段の結合（横方向）・時系列近傍結合（asof）・縦連結（Union）で統合し、CSV / Excel として出力します。"
    )
    st.info("使い方: 1) ファイルをアップロードして設定 2) 手順を作成 3) 処理を実行して結果を保存")

    st.sidebar.header("操作メニュー")
    uploaded_files = st.sidebar.file_uploader(
        "ファイルをアップロード (CSV / XLSX / XLS / XLSM 混在可)",
        type=["csv", "xlsx", "xls", "xlsm"],
        accept_multiple_files=True,
        key="data_files_uploader",
    )
    st.session_state["preview_rows"] = int(
        st.sidebar.number_input(
            "プレビュー行数",
            min_value=10,
            max_value=500,
            value=int(st.session_state.get("preview_rows", PREVIEW_ROWS_DEFAULT)),
            step=10,
            key="preview_rows_input",
        )
    )

    uploaded_map = _sync_uploaded_files(uploaded_files or [])
    _render_source_registration_sidebar()

    st.sidebar.caption(
        f"アップロード済み: {len(uploaded_map)} 件 / テーブル定義: {len(st.session_state['table_configs'])} 件"
    )

    st.sidebar.subheader("アプリ停止")
    st.sidebar.caption("ボタンを押すと Streamlit サーバーを終了します。再開時は `streamlit run app.py` を実行してください。")
    shutdown_confirmed = st.sidebar.checkbox(
        "停止を確認しました",
        value=False,
        key="shutdown_confirm_checkbox",
    )
    if st.sidebar.button(
        "アプリを停止",
        key="shutdown_app_button",
        use_container_width=True,
        disabled=not shutdown_confirmed,
    ):
        st.sidebar.warning("アプリを停止しています...")
        time.sleep(0.15)
        _shutdown_app_server()

    table_previews, _preview_errors = _render_table_management(uploaded_map)

    run_requested = _render_join_plan_sidebar(uploaded_map, table_previews)
    _render_recipe_sidebar(uploaded_map)

    if run_requested:
        try:
            _execute_plan(uploaded_map)
            st.success("処理を実行しました。")
        except Exception as exc:
            if isinstance(exc, DataStitcherError):
                st.error(f"実行エラー: {exc}")
            else:
                _show_exception("実行エラー", exc if isinstance(exc, Exception) else Exception(str(exc)))

    _render_execution_result()


