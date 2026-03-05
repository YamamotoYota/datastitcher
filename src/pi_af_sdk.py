# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""PI AF SDK access helpers (PI DataLink-like table retrieval)."""

from __future__ import annotations

import importlib
import json
import os
import platform
import re
import struct
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

SUPPORTED_PI_DATA_SOURCES: tuple[str, ...] = ("pi_da_tag", "af_attribute", "af_event_frame")
SUPPORTED_PI_QUERY_TYPES: tuple[str, ...] = ("snapshot", "recorded", "interpolated", "summary")
SUPPORTED_SUMMARY_FUNCTIONS: tuple[str, ...] = ("average", "min", "max", "sum", "count", "std")

_NAME_SPLIT_PATTERN = re.compile(r"[\n\r\t,;、，；]+")


class PIDataError(RuntimeError):
    """Raised when PI AF SDK operations fail."""


def _normalize_user_text(value: Any) -> str:
    """Normalize user-provided text (NFKC + trim + common JP symbol normalization)."""
    text = str(value or "")
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("¥", "\\").replace("￥", "\\")
    return text.strip()


def _normalize_user_key(value: Any) -> str:
    """Normalize string for insensitive equality checks."""
    return _normalize_user_text(value).casefold()


def _same_name(left: Any, right: Any) -> bool:
    """Return True when two names are equivalent after normalization."""
    return _normalize_user_key(left) == _normalize_user_key(right)


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
    text = _normalize_user_text(raw_text or "")
    if not text.strip():
        return ()
    tokens = _NAME_SPLIT_PATTERN.split(text)
    parsed = [_normalize_user_text(token) for token in tokens if _normalize_user_text(token)]

    deduped: list[str] = []
    seen: set[str] = set()
    for token in parsed:
        key = _normalize_user_key(token)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(token)
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

    normalized_start = _normalize_user_text(start_time or "*-1d") or "*-1d"
    normalized_end = _normalize_user_text(end_time or "*") or "*"
    normalized_interval = _normalize_user_text(interval or "1h") or "1h"

    if normalized_source in {"pi_da_tag", "af_attribute"} and normalized_query_type in {
        "interpolated",
        "summary",
    } and not normalized_interval:
        raise PIDataError("Interpolated/Summary では集計間隔（例: 10m, 1h）が必要です。")

    config = PIQueryConfig(
        data_source=normalized_source,
        pi_server=_normalize_user_text(pi_server or ""),
        af_server=_normalize_user_text(af_server or ""),
        af_database=_normalize_user_text(af_database or ""),
        query_type=normalized_query_type,
        tags=tags,
        af_element=_normalize_user_text(af_element or ""),
        af_attributes=attributes,
        start_time=normalized_start,
        end_time=normalized_end,
        interval=normalized_interval,
        summary_functions=normalize_summary_functions(summary_functions),
        max_rows_per_tag=normalize_max_rows(max_rows_per_tag),
        ef_template=_normalize_user_text(ef_template or ""),
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


def _python_bitness() -> int:
    """Return current Python process bitness."""
    return struct.calcsize("P") * 8


def _runtime_name(runtime_info: Any) -> str:
    """Best-effort runtime name extraction from pythonnet runtime info."""
    if runtime_info is None:
        return ""

    for attr in ("name", "runtime", "kind"):
        try:
            value = getattr(runtime_info, attr, None)
        except Exception:
            value = None
        if value:
            return str(value).strip().lower()

    text = str(runtime_info).strip().lower()
    if "coreclr" in text:
        return "coreclr"
    if "netfx" in text or ".net framework" in text:
        return "netfx"
    return ""


def _afsdk_dll_candidates() -> list[Path]:
    """Build candidate paths for OSIsoft.AFSDK.dll."""
    roots: list[Path] = []

    def _add_root(raw: str | None) -> None:
        if not raw:
            return
        path = Path(str(raw)).expanduser()
        if path not in roots:
            roots.append(path)

    _add_root(os.environ.get("PIPC"))
    _add_root(os.environ.get("PIHOME"))
    _add_root(os.environ.get("PIHOME64"))
    _add_root(os.environ.get("ProgramFiles"))
    _add_root(os.environ.get("ProgramFiles(x86)"))

    for known_root in (
        Path(r"C:\Program Files\PIPC"),
        Path(r"C:\Program Files (x86)\PIPC"),
        Path(r"C:\Program Files\OSIsoft"),
        Path(r"C:\Program Files (x86)\OSIsoft"),
        Path(r"C:\Program Files\AVEVA\PI System"),
        Path(r"C:\Program Files (x86)\AVEVA\PI System"),
    ):
        _add_root(str(known_root))

    candidates: list[Path] = []

    def _add_candidate(path: Path) -> None:
        try:
            exists = path.exists() and path.is_file()
        except Exception:
            exists = False
        if exists and path not in candidates:
            candidates.append(path)

    for root in roots:
        _add_candidate(root / "AF" / "PublicAssemblies" / "4.0" / "OSIsoft.AFSDK.dll")
        _add_candidate(root / "PIPC" / "AF" / "PublicAssemblies" / "4.0" / "OSIsoft.AFSDK.dll")
        _add_candidate(root / "OSIsoft" / "AF" / "PublicAssemblies" / "4.0" / "OSIsoft.AFSDK.dll")
        _add_candidate(root / "AVEVA" / "PI System" / "AF" / "PublicAssemblies" / "4.0" / "OSIsoft.AFSDK.dll")

    return candidates


def _infer_pipc_root_from_dll(dll_path: Path) -> Path | None:
    """Infer PIPC root directory from AFSDK DLL path."""
    lowered_parts = [part.lower() for part in dll_path.parts]
    if "pipc" not in lowered_parts:
        return None
    idx = lowered_parts.index("pipc")
    if idx < 0:
        return None
    try:
        return Path(*dll_path.parts[: idx + 1])
    except Exception:
        return None


def _prepare_afsdk_environment() -> None:
    """Prepare process-level env vars for robust AF SDK loading."""
    if not os.environ.get("PYTHONNET_RUNTIME"):
        os.environ["PYTHONNET_RUNTIME"] = "netfx"

    candidates = _afsdk_dll_candidates()
    parent_dirs = [str(path.parent) for path in candidates if path.parent]

    current_path = os.environ.get("PATH", "")
    parts = [part for part in current_path.split(os.pathsep) if part]
    lowered = {part.lower() for part in parts}

    for directory in parent_dirs:
        if directory.lower() in lowered:
            continue
        parts.insert(0, directory)
        lowered.add(directory.lower())

    if parts:
        os.environ["PATH"] = os.pathsep.join(parts)

    if not os.environ.get("PIPC"):
        for dll_path in candidates:
            pipc_root = _infer_pipc_root_from_dll(dll_path)
            if pipc_root is not None:
                os.environ["PIPC"] = str(pipc_root)
                break


def _import_afsdk_symbol(
    symbol_name: str,
    namespaces: tuple[str, ...],
    *,
    required: bool = True,
) -> Any:
    """Import AF SDK symbol from candidate namespaces."""
    errors: list[str] = []
    for module_name in namespaces:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")
            continue

        symbol = getattr(module, symbol_name, None)
        if symbol is not None:
            return symbol
        errors.append(f"{module_name}: {symbol_name} が見つかりません")

    if not required:
        return None

    detail = " | ".join(errors[:4]) if errors else "候補namespaceなし"
    raise PIDataError(
        f"AF SDK型の読み込みに失敗しました: {symbol_name}. "
        f"候補={', '.join(namespaces)}. 詳細={detail}"
    )


def _add_afsdk_reference(clr: Any, runtime_info: Any) -> str:
    """Add AF SDK assembly reference with absolute-path fallback."""
    try:
        clr.AddReference("OSIsoft.AFSDK")
        return "OSIsoft.AFSDK"
    except Exception as short_exc:
        short_detail = f"{type(short_exc).__name__}: {short_exc}"

    candidates = _afsdk_dll_candidates()
    fallback_errors: list[str] = []

    for dll_path in candidates:
        try:
            clr.AddReference(str(dll_path))
            return str(dll_path)
        except Exception as exc:
            fallback_errors.append(f"{dll_path} -> {type(exc).__name__}: {exc}")

    lines: list[str] = [
        "OSIsoft.AFSDK の参照に失敗しました。",
        f"- 短縮名参照エラー: {short_detail}",
        f"- Python実行ファイル: {sys.executable}",
        f"- Pythonビット数: {_python_bitness()}bit",
        f"- OS: {platform.platform()}",
        f"- pythonnet runtime: {runtime_info}",
    ]

    if candidates:
        lines.append("- 探索した DLL パス:")
        lines.extend([f"  - {path}" for path in candidates])
    else:
        lines.append("- OSIsoft.AFSDK.dll の候補パスが見つかりませんでした。")

    if fallback_errors:
        lines.append("- DLL直接参照のエラー（先頭3件）:")
        lines.extend([f"  - {err}" for err in fallback_errors[:3]])

    lines.append("- 対処: PI AF Client導入、x64/x86一致、`PYTHONNET_RUNTIME=netfx` を確認してください。")
    raise PIDataError("\n".join(lines))


def _python_executable_for_subprocess() -> str | None:
    """Return a python interpreter path when available (None for bundled exe runtime)."""
    exe = Path(sys.executable).resolve()
    name = exe.name.casefold()
    if "python" in name:
        return str(exe)
    return None


def _runtime_name_from_pythonnet() -> str:
    """Read current pythonnet runtime name without initializing new runtime when possible."""
    try:
        from pythonnet import get_runtime_info
    except Exception:
        return ""
    try:
        info = get_runtime_info()
    except Exception:
        return ""
    return _runtime_name(info)


def _config_to_payload(config: PIQueryConfig) -> dict[str, Any]:
    """Serialize PIQueryConfig to subprocess-safe payload."""
    return {
        "data_source": config.data_source,
        "pi_server": config.pi_server,
        "af_server": config.af_server,
        "af_database": config.af_database,
        "query_type": config.query_type,
        "tags": list(config.tags),
        "af_element": config.af_element,
        "af_attributes": list(config.af_attributes),
        "start_time": config.start_time,
        "end_time": config.end_time,
        "interval": config.interval,
        "summary_functions": list(config.summary_functions),
        "max_rows_per_tag": int(config.max_rows_per_tag),
        "ef_template": config.ef_template,
        "ef_analyses": list(config.ef_analyses),
    }


def _config_from_payload(payload: dict[str, Any]) -> PIQueryConfig:
    """Deserialize PIQueryConfig payload."""
    return PIQueryConfig(
        data_source=str(payload.get("data_source", "pi_da_tag")),
        pi_server=str(payload.get("pi_server", "")),
        af_server=str(payload.get("af_server", "")),
        af_database=str(payload.get("af_database", "")),
        query_type=str(payload.get("query_type", "recorded")),
        tags=tuple(str(v) for v in payload.get("tags", [])),
        af_element=str(payload.get("af_element", "")),
        af_attributes=tuple(str(v) for v in payload.get("af_attributes", [])),
        start_time=str(payload.get("start_time", "*-1d")),
        end_time=str(payload.get("end_time", "*")),
        interval=str(payload.get("interval", "1h")),
        summary_functions=tuple(str(v) for v in payload.get("summary_functions", [])) or ("average", "min", "max"),
        max_rows_per_tag=int(payload.get("max_rows_per_tag", 10000)),
        ef_template=str(payload.get("ef_template", "")),
        ef_analyses=tuple(str(v) for v in payload.get("ef_analyses", [])),
    )


def _run_fetch_in_netfx_subprocess(config: PIQueryConfig) -> pd.DataFrame:
    """Execute PI fetch in isolated python process with PYTHONNET_RUNTIME=netfx."""
    python_exe = _python_executable_for_subprocess()
    if not python_exe:
        raise PIDataError(
            "現在の実行環境では netfx 強制の子プロセスを起動できません。"
            " Python実行環境（python.exe）から起動してください。"
        )

    payload_json = json.dumps(_config_to_payload(config), ensure_ascii=False)
    runner = (
        "import json\n"
        "import sys\n"
        "import traceback\n"
        "from pathlib import Path\n"
        "from src.pi_af_sdk import _config_from_payload, _fetch_pi_datalink_table_in_process\n"
        "payload = json.loads(sys.argv[1])\n"
        "out_path = Path(sys.argv[2])\n"
        "err_path = Path(sys.argv[3])\n"
        "try:\n"
        "    cfg = _config_from_payload(payload)\n"
        "    df = _fetch_pi_datalink_table_in_process(cfg)\n"
        "    df.to_pickle(out_path)\n"
        "except Exception as exc:\n"
        "    err = {'error': str(exc), 'traceback': traceback.format_exc()}\n"
        "    err_path.write_text(json.dumps(err, ensure_ascii=False), encoding='utf-8')\n"
        "    raise\n"
    )

    with tempfile.TemporaryDirectory(prefix="datastitcher_pi_") as tmp_dir:
        out_path = Path(tmp_dir) / "pi_result.pkl"
        err_path = Path(tmp_dir) / "pi_error.json"

        env = os.environ.copy()
        env["PYTHONNET_RUNTIME"] = "netfx"
        env["DATASTITCHER_PI_NETFX_CHILD"] = "1"

        proc = subprocess.run(
            [python_exe, "-c", runner, payload_json, str(out_path), str(err_path)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            if err_path.exists():
                try:
                    err_payload = json.loads(err_path.read_text(encoding="utf-8"))
                    detail = str(err_payload.get("error", detail))
                except Exception:
                    pass
            raise PIDataError(
                "pythonnet runtime を netfx で強制した子プロセス実行に失敗しました。"
                f" 詳細: {detail}"
            )

        if not out_path.exists():
            raise PIDataError("PI取得結果ファイルが生成されませんでした。")
        return pd.read_pickle(out_path)


def _load_af_sdk() -> dict[str, Any]:
    """Load AF SDK types through pythonnet with netfx and path fallback."""
    _prepare_afsdk_environment()

    try:
        from pythonnet import get_runtime_info, load
    except ImportError as exc:  # pragma: no cover
        raise PIDataError("PI AF SDKの利用には `pythonnet` が必要です。") from exc

    runtime_info: Any = None
    try:
        runtime_info = get_runtime_info()
    except Exception:
        runtime_info = None

    if runtime_info is None:
        try:
            load("netfx")
        except Exception as exc:  # pragma: no cover
            raise PIDataError(
                "pythonnet runtime の初期化に失敗しました。`netfx` (.NET Framework) で実行できる環境か確認してください。"
                f" 詳細: {type(exc).__name__}: {exc}"
            ) from exc
        try:
            runtime_info = get_runtime_info()
        except Exception:
            runtime_info = "netfx (runtime info unavailable)"

    runtime_name = _runtime_name(runtime_info)
    if runtime_name and runtime_name != "netfx":
        # Runtime is already initialized with non-netfx in this process.
        # We keep going and attempt AFSDK loading anyway to avoid hard-failing here.
        try:
            load("netfx")
            runtime_info = get_runtime_info()
            runtime_name = _runtime_name(runtime_info)
        except Exception:
            pass

    try:
        import clr  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise PIDataError("PI AF SDKの利用には `pythonnet` が必要です。") from exc

    reference_hint = _add_afsdk_reference(clr, runtime_info)

    try:
        AFTime = _import_afsdk_symbol("AFTime", ("OSIsoft.AF.Time", "OSIsoft.AF"))
        AFTimeRange = _import_afsdk_symbol("AFTimeRange", ("OSIsoft.AF.Time", "OSIsoft.AF"))
        AFTimeSpan = _import_afsdk_symbol("AFTimeSpan", ("OSIsoft.AF.Time", "OSIsoft.AF"))
        AFElement = _import_afsdk_symbol("AFElement", ("OSIsoft.AF.Asset",))
        AFElementSearch = _import_afsdk_symbol("AFElementSearch", ("OSIsoft.AF.Search", "OSIsoft.AF.Asset"))
        AFBoundaryType = _import_afsdk_symbol("AFBoundaryType", ("OSIsoft.AF.Data",))
        AFEventFrameSearch = _import_afsdk_symbol("AFEventFrameSearch", ("OSIsoft.AF.Search", "OSIsoft.AF.EventFrame"))
        PIPoint = _import_afsdk_symbol("PIPoint", ("OSIsoft.AF.PI",))
        PIServers = _import_afsdk_symbol("PIServers", ("OSIsoft.AF.PI",))

        PISystems = _import_afsdk_symbol("PISystems", ("OSIsoft.AF",), required=False)
        AFServers = _import_afsdk_symbol("AFServers", ("OSIsoft.AF", "OSIsoft.AF.Asset"), required=False)

        if PISystems is not None:
            af_server_collection_factory = PISystems
            af_server_collection_name = "PISystems"
        elif AFServers is not None:
            af_server_collection_factory = AFServers
            af_server_collection_name = "AFServers"
        else:
            raise PIDataError(
                "AFサーバー集合型が見つかりませんでした。PISystems/AFServers のいずれも利用不可です。"
            )

    except Exception as exc:  # pragma: no cover
        raise PIDataError(
            "AF SDK API の読み込みに失敗しました。"
            f" 参照元={reference_hint}, runtime={runtime_info}, 詳細={type(exc).__name__}: {exc}"
        ) from exc

    return {
        "AFTime": AFTime,
        "AFTimeRange": AFTimeRange,
        "AFTimeSpan": AFTimeSpan,
        "AFBoundaryType": AFBoundaryType,
        "PIPoint": PIPoint,
        "PIServers": PIServers,
        "AFServerCollectionFactory": af_server_collection_factory,
        "AFServerCollectionName": af_server_collection_name,
        "AFElement": AFElement,
        "AFElementSearch": AFElementSearch,
        "AFEventFrameSearch": AFEventFrameSearch,
    }

def _resolve_named_server(servers: Any, server_name: str, *, kind_label: str) -> Any:
    """Resolve server by explicit name or default server."""
    normalized_server_name = _normalize_user_text(server_name)
    if normalized_server_name:
        try:
            return servers[normalized_server_name]
        except Exception:
            for server in servers:
                if _same_name(getattr(server, "Name", ""), normalized_server_name):
                    return server
            raise PIDataError(f"{kind_label}サーバーが見つかりません: {normalized_server_name}")

    default_server: Any = None
    for attr in ("DefaultPIServer", "DefaultAFServer", "DefaultPISystem", "Default"):
        default_server = getattr(servers, attr, None)
        if default_server is not None:
            break

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
    normalized_database_name = _normalize_user_text(database_name)
    if not normalized_database_name:
        raise PIDataError("AFデータベース名を入力してください。")

    databases = getattr(af_server, "Databases", None)
    if databases is None:
        raise PIDataError("AFサーバーからデータベース一覧を取得できません。")

    try:
        return databases[normalized_database_name]
    except Exception:
        for db in databases:
            if _same_name(getattr(db, "Name", ""), normalized_database_name):
                return db

    raise PIDataError(f"AFデータベースが見つかりません: {normalized_database_name}")


def _resolve_af_element(af_database: Any, element_name: str, sdk: dict[str, Any]) -> Any:
    """Resolve AF element by name/path."""
    normalized_element_name = _normalize_user_text(element_name)
    if not normalized_element_name:
        raise PIDataError("AFエレメント名を入力してください。")

    AFElement = sdk["AFElement"]
    AFElementSearch = sdk["AFElementSearch"]

    candidate_names: list[str] = [normalized_element_name]
    alt_name = normalized_element_name.replace("/", "\\")
    if alt_name not in candidate_names:
        candidate_names.append(alt_name)

    for candidate in candidate_names:
        try:
            return AFElement.FindElement(af_database, candidate)
        except Exception:
            pass

    elements = getattr(af_database, "Elements", None)
    if elements is not None:
        for candidate in candidate_names:
            try:
                return elements[candidate]
            except Exception:
                pass
        for elem in elements:
            if _same_name(getattr(elem, "Name", ""), normalized_element_name):
                return elem

    try:
        escaped = normalized_element_name.replace("'", "''")
        search = AFElementSearch(af_database, "insighta_element_search", f"Name:'{escaped}'")
        for elem in search.FindObjects(1):
            return elem
    except Exception:
        pass

    raise PIDataError(f"AFエレメントが見つかりません: {normalized_element_name}")


def _resolve_af_attribute(element: Any, attribute_name: str) -> Any:
    """Resolve AF attribute by name."""
    normalized_attribute_name = _normalize_user_text(attribute_name)
    attributes = getattr(element, "Attributes", None)
    if attributes is None:
        raise PIDataError("AFエレメントに属性コレクションがありません。")

    try:
        return attributes[normalized_attribute_name]
    except Exception:
        for attr in attributes:
            if _same_name(getattr(attr, "Name", ""), normalized_attribute_name):
                return attr

    raise PIDataError(f"AF属性が見つかりません: {normalized_attribute_name}")


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
    af_server_collection_factory = sdk["AFServerCollectionFactory"]
    af_server = _resolve_named_server(af_server_collection_factory(), config.af_server, kind_label="AF")
    _connect_server(af_server, label="AFサーバー")
    af_database = _resolve_af_database(af_server, config.af_database)
    element = _resolve_af_element(af_database, config.af_element, sdk)

    query_type = normalize_pi_query_type(config.query_type)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for attribute_name in config.af_attributes:
        tag_name = attribute_name
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
        raise PIDataError(
            "AF属性データ取得に失敗しました。"
            f" database={config.af_database}, element={config.af_element}, attributes={list(config.af_attributes)}. "
            f"{detail}"
        )
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
        name = _normalize_user_text(getattr(source_analysis, "Name", ""))
        if name:
            names.append(name)

    attributes = getattr(event_frame, "Attributes", None)
    if attributes is not None:
        candidates = {"analysis", "analysisname", "sourceanalysis", "source_analysis", "source"}
        for attr in attributes:
            attr_name = _normalize_user_text(getattr(attr, "Name", ""))
            if not attr_name or _normalize_user_key(attr_name).replace(" ", "") not in candidates:
                continue
            try:
                value = _af_value_to_python(attr.GetValue())
                text = _normalize_user_text(value)
                if text:
                    names.append(text)
            except Exception:
                continue

    unique = list(dict.fromkeys([name for name in names if name]))
    return tuple(unique)


def _match_any_analysis(required: tuple[str, ...], available: tuple[str, ...]) -> bool:
    """Return True when any required analysis name matches available names."""
    required_norm = [_normalize_user_key(name) for name in required if _normalize_user_text(name)]
    available_norm = [_normalize_user_key(name) for name in available if _normalize_user_text(name)]
    if not required_norm:
        return True
    if not available_norm:
        return False
    return any(req in avail or avail in req for req in required_norm for avail in available_norm)


def _fetch_af_event_frame_rows(config: PIQueryConfig, sdk: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch AF event frame rows filtered by template, time range, and analysis names."""
    af_server_collection_factory = sdk["AFServerCollectionFactory"]
    AFEventFrameSearch = sdk["AFEventFrameSearch"]

    af_server = _resolve_named_server(af_server_collection_factory(), config.af_server, kind_label="AF")
    _connect_server(af_server, label="AFサーバー")
    af_database = _resolve_af_database(af_server, config.af_database)

    escaped_template = _normalize_user_text(config.ef_template).replace("'", "''")
    search_query = f"Template:'{escaped_template}'"
    search = AFEventFrameSearch(af_database, "insighta_ef_search", search_query)
    candidates = _list_search_results(search, int(config.max_rows_per_tag))

    start_bound = _af_time_text_to_timestamp(sdk, config.start_time)
    end_bound = _af_time_text_to_timestamp(sdk, config.end_time)
    analysis_filters = tuple(config.ef_analyses)

    rows: list[dict[str, Any]] = []
    for event_frame in candidates:
        template = getattr(event_frame, "Template", None)
        template_name = _normalize_user_text(getattr(template, "Name", "") or "")
        if template_name and not _same_name(template_name, config.ef_template):
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
        element_name = _normalize_user_text(getattr(primary_element, "Name", "") or "")
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
            "イベントフレームが取得できませんでした。"
            f" database={config.af_database}, template={config.ef_template}, analyses={list(config.ef_analyses)}. "
            "テンプレート名・期間・イベント生成分析名を確認してください。"
        )
    return rows


def _to_wide_series_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert long PI/AF rows (`tag`, `value`) into wide table (columns by tag/attribute)."""
    if frame.empty or "tag" not in frame.columns or "value" not in frame.columns:
        return frame

    if "timestamp" in frame.columns:
        index_cols = ["timestamp"]
    elif "window_start" in frame.columns:
        index_cols = [col for col in ("window_start", "window_end", "summary") if col in frame.columns]
    else:
        return frame

    work = frame.copy()
    work["tag"] = work["tag"].astype(str)
    work = work[index_cols + ["tag", "value"]]

    wide = work.pivot_table(
        index=index_cols,
        columns="tag",
        values="value",
        aggfunc="first",
    ).reset_index()

    if isinstance(wide.columns, pd.MultiIndex):
        wide.columns = [
            str(col[-1]) if isinstance(col, tuple) else str(col)
            for col in wide.columns
        ]

    return wide


def _fetch_pi_datalink_table_in_process(config: PIQueryConfig) -> pd.DataFrame:
    """Fetch PI/AF data table in current process."""
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

    if config.data_source in {"pi_da_tag", "af_attribute"}:
        frame = _to_wide_series_table(frame)

    return frame


def fetch_pi_datalink_table(config: PIQueryConfig) -> pd.DataFrame:
    """Fetch PI/AF data table with netfx-enforced fallback."""
    _validate_query_config(config)

    runtime_name = _runtime_name_from_pythonnet()
    if runtime_name and runtime_name != "netfx" and os.environ.get("DATASTITCHER_PI_NETFX_CHILD") != "1":
        return _run_fetch_in_netfx_subprocess(config)

    return _fetch_pi_datalink_table_in_process(config)


