# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""PI AF SDK access helpers (PI DataLink-like table retrieval)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

SUPPORTED_PI_DATA_SOURCES: tuple[str, ...] = ("pi_da_tag", "af_attribute", "af_event_frame")
SUPPORTED_PI_QUERY_TYPES: tuple[str, ...] = ("snapshot", "recorded", "interpolated", "summary")
SUPPORTED_SUMMARY_FUNCTIONS: tuple[str, ...] = ("average", "min", "max", "sum", "count", "std")


class PIDataError(RuntimeError):
    """Raised when PI AF SDK operations fail."""


@dataclass(frozen=True)
class PIQueryConfig:
    """PI/AF query parameters for DataLink-like retrieval."""

    data_source: str = "pi_da_tag"
    pi_server: str = ""
    af_server: str = ""
    af_database: str = ""
    query_type: str = "recorded"
    tags: tuple[str, ...] = ()
    af_element: str = ""
    af_attributes: tuple[str, ...] = ()
    start_time: str = "*-1d"
    end_time: str = "*"
    interval: str = "1h"
    summary_functions: tuple[str, ...] = ("average", "min", "max")
    max_rows_per_tag: int = 10000
    ef_template: str = ""
    ef_analyses: tuple[str, ...] = ()


def normalize_pi_data_source(value: str | None) -> str:
    """Normalize PI data source mode."""
    key = str(value or "pi_da_tag").strip().lower()
    return key if key in SUPPORTED_PI_DATA_SOURCES else "pi_da_tag"


def normalize_pi_query_type(value: str | None) -> str:
    """Normalize PI query type key."""
    key = str(value or "recorded").strip().lower()
    return key if key in SUPPORTED_PI_QUERY_TYPES else "recorded"


def normalize_summary_functions(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """Normalize summary function list preserving declared order."""
    selected = {str(v or "").strip().lower() for v in (values or [])}
    normalized = tuple(fn for fn in SUPPORTED_SUMMARY_FUNCTIONS if fn in selected)
    if normalized:
        return normalized
    return ("average", "min", "max")


def parse_name_list(raw_text: str | None) -> tuple[str, ...]:
    """Parse newline/comma/semicolon separated names."""
    text = str(raw_text or "")
    if not text.strip():
        return ()
    tokens = re.split(r"[\n,;]+", text)
    parsed = [token.strip() for token in tokens if token and token.strip()]
    deduped = list(dict.fromkeys(parsed))
    return tuple(deduped)



def parse_tag_list(raw_text: str | None) -> tuple[str, ...]:
    """Backward-compatible alias for tag list parser."""
    return parse_name_list(raw_text)
def normalize_max_rows(value: int | float | str | None, default_value: int = 10000) -> int:
    """Normalize per-target maximum row count."""
    if value in (None, ""):
        return default_value
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default_value
    return max(1, min(parsed, 500_000))


def build_pi_query_config(
    *,
    data_source: str | None,
    pi_server: str | None,
    af_server: str | None,
    af_database: str | None,
    query_type: str | None,
    tags_text: str | None,
    af_element: str | None,
    af_attributes_text: str | None,
    start_time: str | None,
    end_time: str | None,
    interval: str | None,
    summary_functions: list[str] | None,
    max_rows_per_tag: int | float | str | None,
    ef_template: str | None,
    ef_analyses_text: str | None,
) -> PIQueryConfig:
    """Build normalized PI query config from raw UI inputs."""
    normalized_source = normalize_pi_data_source(data_source)
    normalized_query_type = normalize_pi_query_type(query_type)

    tags = parse_name_list(tags_text)
    attributes = parse_name_list(af_attributes_text)
    analyses = parse_name_list(ef_analyses_text)

    normalized_start = str(start_time or "*-1d").strip() or "*-1d"
    normalized_end = str(end_time or "*").strip() or "*"
    normalized_interval = str(interval or "1h").strip() or "1h"

    if normalized_source in {"pi_da_tag", "af_attribute"} and normalized_query_type in {
        "interpolated",
        "summary",
    } and not normalized_interval:
        raise PIDataError("Interpolated/Summary では集計間隔（例: 10m, 1h）が必要です。")

    config = PIQueryConfig(
        data_source=normalized_source,
        pi_server=str(pi_server or "").strip(),
        af_server=str(af_server or "").strip(),
        af_database=str(af_database or "").strip(),
        query_type=normalized_query_type,
        tags=tags,
        af_element=str(af_element or "").strip(),
        af_attributes=attributes,
        start_time=normalized_start,
        end_time=normalized_end,
        interval=normalized_interval,
        summary_functions=normalize_summary_functions(summary_functions),
        max_rows_per_tag=normalize_max_rows(max_rows_per_tag),
        ef_template=str(ef_template or "").strip(),
        ef_analyses=analyses,
    )

    _validate_query_config(config)
    return config


def _validate_query_config(config: PIQueryConfig) -> None:
    """Validate cross-field requirements by source mode."""
    if config.data_source == "pi_da_tag":
        if not config.tags:
            raise PIDataError("PIタグを1件以上入力してください。")
        return

    if config.data_source == "af_attribute":
        if not config.af_database:
            raise PIDataError("AF属性データ取得では AFデータベース名が必要です。")
        if not config.af_element:
            raise PIDataError("AF属性データ取得では エレメント名が必要です。")
        if not config.af_attributes:
            raise PIDataError("AF属性名を1件以上入力してください。")
        return

    if config.data_source == "af_event_frame":
        if not config.af_database:
            raise PIDataError("イベントフレーム取得では AFデータベース名が必要です。")
        if not config.ef_template:
            raise PIDataError("イベントフレームテンプレート名を入力してください。")
        if not config.ef_analyses:
            raise PIDataError("イベント生成分析名を1件以上入力してください。")
        return

    raise PIDataError(f"未対応のPIデータ取得モードです: {config.data_source}")


def _load_af_sdk() -> dict[str, Any]:
    """Load AF SDK types through pythonnet."""
    try:
        import clr  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise PIDataError("PI AF SDKの利用には `pythonnet` が必要です。") from exc

    try:
        clr.AddReference("OSIsoft.AFSDK")
    except Exception as exc:  # pragma: no cover
        raise PIDataError(
            "OSIsoft.AFSDK を読み込めません。PI AF Client（PI System Explorer）をインストールしてください。"
        ) from exc

    try:
        from OSIsoft.AF import AFTime, AFTimeRange, AFTimeSpan  # type: ignore
        from OSIsoft.AF.Asset import AFElement, AFElementSearch, AFServers  # type: ignore
        from OSIsoft.AF.Data import AFBoundaryType  # type: ignore
        from OSIsoft.AF.EventFrame import AFEventFrameSearch  # type: ignore
        from OSIsoft.AF.PI import PIPoint, PIServers  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise PIDataError("AF SDK API の読み込みに失敗しました。AF SDK バージョンを確認してください。") from exc

    return {
        "AFTime": AFTime,
        "AFTimeRange": AFTimeRange,
        "AFTimeSpan": AFTimeSpan,
        "AFBoundaryType": AFBoundaryType,
        "PIPoint": PIPoint,
        "PIServers": PIServers,
        "AFServers": AFServers,
        "AFElement": AFElement,
        "AFElementSearch": AFElementSearch,
        "AFEventFrameSearch": AFEventFrameSearch,
    }


def _resolve_named_server(servers: Any, server_name: str, *, kind_label: str) -> Any:
    """Resolve server by explicit name or default server."""
    if server_name:
        try:
            return servers[server_name]
        except Exception:
            for server in servers:
                if str(getattr(server, "Name", "")).strip().lower() == server_name.strip().lower():
                    return server
            raise PIDataError(f"{kind_label}サーバーが見つかりません: {server_name}")

    default_server = getattr(servers, "DefaultPIServer", None)
    if default_server is None:
        default_server = getattr(servers, "DefaultAFServer", None)
    if default_server is None:
        raise PIDataError(f"既定の{kind_label}サーバーが見つかりません。サーバー名を入力してください。")
    return default_server


def _connect_server(server: Any, *, label: str) -> None:
    """Connect PI/AF server if not connected yet."""
    try:
        connection_info = getattr(server, "ConnectionInfo", None)
        if connection_info is not None and bool(getattr(connection_info, "IsConnected", False)):
            return
    except Exception:
        pass

    try:
        server.Connect()
    except Exception as exc:
        raise PIDataError(f"{label}への接続に失敗しました: {exc}") from exc


def _resolve_af_database(af_server: Any, database_name: str) -> Any:
    """Resolve AF database from AF server."""
    if not database_name:
        raise PIDataError("AFデータベース名を入力してください。")

    databases = getattr(af_server, "Databases", None)
    if databases is None:
        raise PIDataError("AFサーバーからデータベース一覧を取得できません。")

    try:
        return databases[database_name]
    except Exception:
        for db in databases:
            if str(getattr(db, "Name", "")).strip().lower() == database_name.strip().lower():
                return db

    raise PIDataError(f"AFデータベースが見つかりません: {database_name}")


def _resolve_af_element(af_database: Any, element_name: str, sdk: dict[str, Any]) -> Any:
    """Resolve AF element by name/path."""
    if not element_name:
        raise PIDataError("AFエレメント名を入力してください。")

    AFElement = sdk["AFElement"]
    AFElementSearch = sdk["AFElementSearch"]

    try:
        return AFElement.FindElement(af_database, element_name)
    except Exception:
        pass

    elements = getattr(af_database, "Elements", None)
    if elements is not None:
        try:
            return elements[element_name]
        except Exception:
            for elem in elements:
                if str(getattr(elem, "Name", "")).strip().lower() == element_name.strip().lower():
                    return elem

    try:
        search = AFElementSearch(af_database, "insighta_element_search", f"Name:'{element_name}'")
        found = search.FindObjects(1)
        for elem in found:
            return elem
    except Exception:
        pass

    raise PIDataError(f"AFエレメントが見つかりません: {element_name}")


def _resolve_af_attribute(element: Any, attribute_name: str) -> Any:
    """Resolve AF attribute by name."""
    attributes = getattr(element, "Attributes", None)
    if attributes is None:
        raise PIDataError("AFエレメントに属性コレクションがありません。")

    try:
        return attributes[attribute_name]
    except Exception:
        for attr in attributes:
            if str(getattr(attr, "Name", "")).strip().lower() == attribute_name.strip().lower():
                return attr

    raise PIDataError(f"AF属性が見つかりません: {attribute_name}")


def _af_time_to_timestamp(value: Any) -> pd.Timestamp:
    """Convert AF timestamp-like object to pandas timestamp."""
    if value is None:
        return pd.NaT

    for attr in ("UtcTime", "LocalTime"):
        dt_like = getattr(value, attr, None)
        if dt_like is not None:
            try:
                return pd.to_datetime(dt_like)
            except Exception:
                continue

    try:
        return pd.to_datetime(value)
    except Exception:
        return pd.to_datetime(str(value), errors="coerce")


def _af_time_text_to_timestamp(sdk: dict[str, Any], time_text: str) -> pd.Timestamp | None:
    """Resolve AF relative/absolute time expression into timestamp."""
    text = str(time_text or "").strip()
    if not text:
        return None
    AFTime = sdk["AFTime"]
    try:
        af_time = AFTime(text)
        return _af_time_to_timestamp(af_time)
    except Exception:
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed


def _af_value_to_python(value: Any) -> Any:
    """Convert AF value payload to Python primitive when possible."""
    if value is None:
        return None
    candidate = getattr(value, "Value", value)
    for caster in (int, float):
        try:
            return caster(candidate)
        except Exception:
            pass
    try:
        return str(candidate)
    except Exception:
        return candidate


def _collect_snapshot(point: Any, tag: str) -> list[dict[str, Any]]:
    """Collect snapshot row for a PI point."""
    af_value = point.CurrentValue()
    return [
        {
            "tag": tag,
            "timestamp": _af_time_to_timestamp(getattr(af_value, "Timestamp", None)),
            "value": _af_value_to_python(af_value),
            "is_good": bool(getattr(af_value, "IsGood", True)),
            "source_type": "snapshot",
        }
    ]


def _collect_recorded(point: Any, tag: str, sdk: dict[str, Any], config: PIQueryConfig) -> list[dict[str, Any]]:
    """Collect recorded values for a PI point."""
    AFTime = sdk["AFTime"]
    AFTimeRange = sdk["AFTimeRange"]
    AFBoundaryType = sdk["AFBoundaryType"]
    time_range = AFTimeRange(AFTime(config.start_time), AFTime(config.end_time))
    values = point.RecordedValues(
        time_range,
        AFBoundaryType.Inside,
        "",
        False,
        int(config.max_rows_per_tag),
    )

    rows: list[dict[str, Any]] = []
    for af_value in values:
        rows.append(
            {
                "tag": tag,
                "timestamp": _af_time_to_timestamp(getattr(af_value, "Timestamp", None)),
                "value": _af_value_to_python(af_value),
                "is_good": bool(getattr(af_value, "IsGood", True)),
                "source_type": "recorded",
            }
        )
    return rows


def _collect_interpolated(point: Any, tag: str, sdk: dict[str, Any], config: PIQueryConfig) -> list[dict[str, Any]]:
    """Collect interpolated values for a PI point."""
    AFTime = sdk["AFTime"]
    AFTimeRange = sdk["AFTimeRange"]
    AFTimeSpan = sdk["AFTimeSpan"]
    time_range = AFTimeRange(AFTime(config.start_time), AFTime(config.end_time))
    try:
        interval = AFTimeSpan.Parse(config.interval)
    except Exception as exc:
        raise PIDataError(f"集計間隔の書式が不正です: {config.interval}") from exc

    values = point.InterpolatedValues(time_range, interval, "", False)
    rows: list[dict[str, Any]] = []
    for idx, af_value in enumerate(values):
        if idx >= int(config.max_rows_per_tag):
            break
        rows.append(
            {
                "tag": tag,
                "timestamp": _af_time_to_timestamp(getattr(af_value, "Timestamp", None)),
                "value": _af_value_to_python(af_value),
                "is_good": bool(getattr(af_value, "IsGood", True)),
                "source_type": "interpolated",
            }
        )
    return rows


def _summarize_rows(rows: list[dict[str, Any]], config: PIQueryConfig) -> list[dict[str, Any]]:
    """Aggregate time-series rows by interval and summary functions."""
    if not rows:
        return []

    frame = pd.DataFrame(rows)
    if frame.empty:
        return []

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"])
    if frame.empty:
        return []

    frame = frame.sort_values("timestamp").reset_index(drop=True)
    try:
        interval_td = pd.to_timedelta(config.interval)
    except Exception as exc:
        raise PIDataError(f"Summary用の集計間隔が不正です: {config.interval}") from exc
    if interval_td <= pd.Timedelta(0):
        raise PIDataError("Summary用の集計間隔は正の値を指定してください。")

    start_ts = pd.to_datetime(config.start_time, errors="coerce")
    if pd.isna(start_ts):
        start_ts = frame["timestamp"].min()

    offset = (frame["timestamp"] - start_ts) // interval_td
    frame["window_start"] = start_ts + (offset * interval_td)
    frame["window_end"] = frame["window_start"] + interval_td

    grouped = frame.groupby(["tag", "window_start", "window_end"], dropna=True)["value"]
    aggregated = grouped.agg(["mean", "min", "max", "sum", "count", "std"]).reset_index()

    rename_map = {"mean": "average", "min": "min", "max": "max", "sum": "sum", "count": "count", "std": "std"}
    out_rows: list[dict[str, Any]] = []
    for _, row in aggregated.iterrows():
        for fn in config.summary_functions:
            src_col = next((col for col, alias in rename_map.items() if alias == fn), None)
            if src_col is None:
                continue
            out_rows.append(
                {
                    "tag": row["tag"],
                    "window_start": row["window_start"],
                    "window_end": row["window_end"],
                    "summary": fn,
                    "value": row[src_col],
                    "source_type": "summary",
                }
            )
    return out_rows


def _collect_attribute_snapshot(attribute: Any, tag_name: str) -> list[dict[str, Any]]:
    """Collect snapshot-like row for AF attribute."""
    af_value = attribute.GetValue()
    return [
        {
            "tag": tag_name,
            "timestamp": _af_time_to_timestamp(getattr(af_value, "Timestamp", None)),
            "value": _af_value_to_python(af_value),
            "is_good": bool(getattr(af_value, "IsGood", True)),
            "source_type": "snapshot",
        }
    ]


def _collect_attribute_recorded(
    attribute: Any,
    tag_name: str,
    sdk: dict[str, Any],
    config: PIQueryConfig,
) -> list[dict[str, Any]]:
    """Collect recorded values for AF attribute."""
    AFTime = sdk["AFTime"]
    AFTimeRange = sdk["AFTimeRange"]
    AFBoundaryType = sdk["AFBoundaryType"]
    time_range = AFTimeRange(AFTime(config.start_time), AFTime(config.end_time))

    data = getattr(attribute, "Data", None)
    if data is None:
        raise PIDataError(f"属性データ参照に失敗しました: {tag_name}")

    values = data.RecordedValues(
        time_range,
        AFBoundaryType.Inside,
        "",
        False,
        int(config.max_rows_per_tag),
    )
    rows: list[dict[str, Any]] = []
    for af_value in values:
        rows.append(
            {
                "tag": tag_name,
                "timestamp": _af_time_to_timestamp(getattr(af_value, "Timestamp", None)),
                "value": _af_value_to_python(af_value),
                "is_good": bool(getattr(af_value, "IsGood", True)),
                "source_type": "recorded",
            }
        )
    return rows


def _collect_attribute_interpolated(
    attribute: Any,
    tag_name: str,
    sdk: dict[str, Any],
    config: PIQueryConfig,
) -> list[dict[str, Any]]:
    """Collect interpolated values for AF attribute."""
    AFTime = sdk["AFTime"]
    AFTimeRange = sdk["AFTimeRange"]
    AFTimeSpan = sdk["AFTimeSpan"]
    time_range = AFTimeRange(AFTime(config.start_time), AFTime(config.end_time))
    try:
        interval = AFTimeSpan.Parse(config.interval)
    except Exception as exc:
        raise PIDataError(f"集計間隔の書式が不正です: {config.interval}") from exc

    data = getattr(attribute, "Data", None)
    if data is None:
        raise PIDataError(f"属性データ参照に失敗しました: {tag_name}")

    values = data.InterpolatedValues(time_range, interval, "", False)
    rows: list[dict[str, Any]] = []
    for idx, af_value in enumerate(values):
        if idx >= int(config.max_rows_per_tag):
            break
        rows.append(
            {
                "tag": tag_name,
                "timestamp": _af_time_to_timestamp(getattr(af_value, "Timestamp", None)),
                "value": _af_value_to_python(af_value),
                "is_good": bool(getattr(af_value, "IsGood", True)),
                "source_type": "interpolated",
            }
        )
    return rows


def _fetch_pi_da_tag_rows(config: PIQueryConfig, sdk: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch PI Data Archive tag rows."""
    PIServers = sdk["PIServers"]
    PIPoint = sdk["PIPoint"]
    pi_server = _resolve_named_server(PIServers(), config.pi_server, kind_label="PI Data Archive")
    _connect_server(pi_server, label="PIサーバー")

    query_type = normalize_pi_query_type(config.query_type)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for tag in config.tags:
        try:
            point = PIPoint.FindPIPoint(pi_server, tag)
            if query_type == "snapshot":
                rows.extend(_collect_snapshot(point, tag))
            elif query_type == "recorded":
                rows.extend(_collect_recorded(point, tag, sdk, config))
            elif query_type == "interpolated":
                rows.extend(_collect_interpolated(point, tag, sdk, config))
            elif query_type == "summary":
                rows.extend(_summarize_rows(_collect_recorded(point, tag, sdk, config), config))
            else:
                raise PIDataError(f"未対応のPI取得種別です: {query_type}")
        except Exception as exc:
            errors.append(f"{tag}: {exc}")

    if not rows:
        detail = "; ".join(errors[:3]) if errors else "データが取得できませんでした。"
        raise PIDataError(f"PIデータ取得に失敗しました。{detail}")
    return rows


def _fetch_af_attribute_rows(config: PIQueryConfig, sdk: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch AF attribute rows in PI tag-like row format."""
    AFServers = sdk["AFServers"]
    af_server = _resolve_named_server(AFServers(), config.af_server, kind_label="AF")
    _connect_server(af_server, label="AFサーバー")
    af_database = _resolve_af_database(af_server, config.af_database)
    element = _resolve_af_element(af_database, config.af_element, sdk)

    query_type = normalize_pi_query_type(config.query_type)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for attribute_name in config.af_attributes:
        tag_name = f"{config.af_element}|{attribute_name}"
        try:
            attribute = _resolve_af_attribute(element, attribute_name)
            if query_type == "snapshot":
                attr_rows = _collect_attribute_snapshot(attribute, tag_name)
            elif query_type == "recorded":
                attr_rows = _collect_attribute_recorded(attribute, tag_name, sdk, config)
            elif query_type == "interpolated":
                attr_rows = _collect_attribute_interpolated(attribute, tag_name, sdk, config)
            elif query_type == "summary":
                attr_rows = _summarize_rows(_collect_attribute_recorded(attribute, tag_name, sdk, config), config)
            else:
                raise PIDataError(f"未対応のPI取得種別です: {query_type}")

            for row in attr_rows:
                row["element"] = config.af_element
                row["attribute"] = attribute_name
                row["source_type"] = f"af_{row.get('source_type', query_type)}"
            rows.extend(attr_rows)
        except Exception as exc:
            errors.append(f"{attribute_name}: {exc}")

    if not rows:
        detail = "; ".join(errors[:3]) if errors else "データが取得できませんでした。"
        raise PIDataError(f"AF属性データ取得に失敗しました。{detail}")
    return rows


def _list_search_results(search_obj: Any, max_rows: int) -> list[Any]:
    """Resolve AF search object results with signature fallbacks."""
    methods = [
        lambda: search_obj.FindObjects(max_rows),
        lambda: search_obj.FindObjects(),
        lambda: search_obj.FindObjects(False, max_rows),
    ]
    last_exc: Exception | None = None
    for method in methods:
        try:
            result = method()
            return [item for item in result]
        except Exception as exc:  # pragma: no cover
            last_exc = exc
    if last_exc is not None:
        raise PIDataError(f"AF検索実行に失敗しました: {last_exc}") from last_exc
    return []


def _extract_event_frame_analysis_names(event_frame: Any) -> tuple[str, ...]:
    """Extract possible analysis names from event frame metadata."""
    names: list[str] = []

    source_analysis = getattr(event_frame, "SourceAnalysis", None)
    if source_analysis is not None:
        name = str(getattr(source_analysis, "Name", "")).strip()
        if name:
            names.append(name)

    attributes = getattr(event_frame, "Attributes", None)
    if attributes is not None:
        candidates = {"analysis", "analysisname", "sourceanalysis", "source_analysis", "source"}
        for attr in attributes:
            attr_name = str(getattr(attr, "Name", "")).strip()
            if not attr_name or attr_name.lower().replace(" ", "") not in candidates:
                continue
            try:
                value = _af_value_to_python(attr.GetValue())
                text = str(value).strip()
                if text:
                    names.append(text)
            except Exception:
                continue

    unique = list(dict.fromkeys([name for name in names if name]))
    return tuple(unique)


def _match_any_analysis(required: tuple[str, ...], available: tuple[str, ...]) -> bool:
    """Return True when any required analysis name matches available names."""
    required_norm = [name.lower().strip() for name in required if name.strip()]
    available_norm = [name.lower().strip() for name in available if name.strip()]
    if not required_norm:
        return True
    if not available_norm:
        return False
    return any(req in avail or avail in req for req in required_norm for avail in available_norm)


def _fetch_af_event_frame_rows(config: PIQueryConfig, sdk: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch AF event frame rows filtered by template, time range, and analysis names."""
    AFServers = sdk["AFServers"]
    AFEventFrameSearch = sdk["AFEventFrameSearch"]

    af_server = _resolve_named_server(AFServers(), config.af_server, kind_label="AF")
    _connect_server(af_server, label="AFサーバー")
    af_database = _resolve_af_database(af_server, config.af_database)

    search_query = f"Template:'{config.ef_template}'"
    search = AFEventFrameSearch(af_database, "insighta_ef_search", search_query)
    candidates = _list_search_results(search, int(config.max_rows_per_tag))

    start_bound = _af_time_text_to_timestamp(sdk, config.start_time)
    end_bound = _af_time_text_to_timestamp(sdk, config.end_time)
    analysis_filters = tuple(config.ef_analyses)

    rows: list[dict[str, Any]] = []
    for event_frame in candidates:
        template = getattr(event_frame, "Template", None)
        template_name = str(getattr(template, "Name", "") or "")
        if template_name and template_name.strip().lower() != config.ef_template.strip().lower():
            continue

        start_ts = _af_time_to_timestamp(getattr(event_frame, "StartTime", None))
        end_ts = _af_time_to_timestamp(getattr(event_frame, "EndTime", None))
        if start_bound is not None and pd.notna(start_ts) and start_ts < start_bound:
            continue
        if end_bound is not None and pd.notna(end_ts) and start_ts > end_bound:
            continue

        analysis_names = _extract_event_frame_analysis_names(event_frame)
        if not _match_any_analysis(analysis_filters, analysis_names):
            continue

        primary_element = getattr(event_frame, "PrimaryReferencedElement", None)
        element_name = str(getattr(primary_element, "Name", "") or "")
        duration_sec: float | None = None
        if pd.notna(start_ts) and pd.notna(end_ts):
            duration_sec = float((end_ts - start_ts).total_seconds())

        rows.append(
            {
                "event_frame": str(getattr(event_frame, "Name", "") or ""),
                "template": template_name,
                "analysis": "; ".join(analysis_names),
                "analysis_count": len(analysis_names),
                "element": element_name,
                "start_time": start_ts,
                "end_time": end_ts,
                "duration_sec": duration_sec,
                "source_type": "event_frame",
            }
        )

    if not rows:
        raise PIDataError(
            "イベントフレームが取得できませんでした。テンプレート名・期間・イベント生成分析名を確認してください。"
        )
    return rows


def fetch_pi_datalink_table(config: PIQueryConfig) -> pd.DataFrame:
    """Fetch PI/AF data table based on query mode."""
    _validate_query_config(config)
    sdk = _load_af_sdk()

    if config.data_source == "pi_da_tag":
        rows = _fetch_pi_da_tag_rows(config, sdk)
    elif config.data_source == "af_attribute":
        rows = _fetch_af_attribute_rows(config, sdk)
    elif config.data_source == "af_event_frame":
        rows = _fetch_af_event_frame_rows(config, sdk)
    else:
        raise PIDataError(f"未対応のPIデータ取得モードです: {config.data_source}")

    frame = pd.DataFrame(rows)
    for col in ("timestamp", "window_start", "window_end", "start_time", "end_time"):
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col], errors="coerce")
    return frame

