# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""PyInstaller launcher for DataStitcher (Streamlit runtime bootstrap)."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

DEFAULT_SERVER_PORT = 8501
MAX_PORT_SEARCH_ATTEMPTS = 100
BROWSER_WAIT_TIMEOUT_SECONDS = 30.0
BROWSER_WAIT_INTERVAL_SECONDS = 0.25


def _resolve_app_script_path() -> str:
    """Resolve the packaged `app.py` location."""
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(str(meipass)) / "app.py")

    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir / "app.py")
    candidates.append(exe_dir / "_internal" / "app.py")
    candidates.append(Path(__file__).resolve().with_name("app.py"))
    candidates.append(Path.cwd() / "app.py")

    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() == ".py":
            return str(candidate)

    raise FileNotFoundError(
        "アプリスクリプトが見つかりません: "
        + ", ".join(str(path) for path in candidates)
    )


def _configure_streamlit_environment() -> None:
    """Force packaged execution to use bundled static assets instead of dev mode."""
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"


def _is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if the given TCP port can be bound locally."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _select_server_port(
    preferred_port: int = DEFAULT_SERVER_PORT,
    max_attempts: int = MAX_PORT_SEARCH_ATTEMPTS,
) -> int:
    """Select the first available port from the preferred port upward."""
    for offset in range(max_attempts):
        candidate = preferred_port + offset
        if _is_port_available(candidate):
            return candidate

    raise RuntimeError(
        f"利用可能なポートが見つかりませんでした。"
        f" 開始ポート: {preferred_port}, 試行回数: {max_attempts}"
    )


def _build_local_url(port: int) -> str:
    """Build the local browser URL for the packaged app."""
    return f"http://localhost:{port}"


def _wait_for_local_server(port: int, timeout_seconds: float) -> bool:
    """Wait until the local TCP port starts accepting connections."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(BROWSER_WAIT_INTERVAL_SECONDS)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(BROWSER_WAIT_INTERVAL_SECONDS)
    return False


def _should_auto_open_browser() -> bool:
    """Return True when browser auto-open is enabled."""
    value = os.environ.get("DATASTITCHER_AUTO_OPEN_BROWSER", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _open_browser_when_ready(port: int) -> None:
    """Wait for the server to come up and open the default browser."""
    if _wait_for_local_server(port, BROWSER_WAIT_TIMEOUT_SECONDS):
        webbrowser.open(_build_local_url(port), new=1)


def _start_browser_opener(port: int) -> None:
    """Start the background browser opener thread when enabled."""
    if not _should_auto_open_browser():
        return

    thread = threading.Thread(
        target=_open_browser_when_ready,
        args=(port,),
        name="datastitcher-browser-opener",
        daemon=True,
    )
    thread.start()


def _streamlit_flags(port: int) -> dict[str, Any]:
    """Default streamlit runtime flags for packaged desktop launch."""
    return {
        "global.developmentMode": False,
        "server.headless": True,
        "server.port": port,
        "browser.serverPort": port,
        "browser.gatherUsageStats": False,
        "server.runOnSave": False,
    }


def main() -> None:
    """Start Streamlit server using the packaged app script."""
    _configure_streamlit_environment()
    from streamlit import config as streamlit_config
    from streamlit.web import bootstrap as streamlit_bootstrap

    script_path = _resolve_app_script_path()
    script_args = sys.argv[1:]
    port = _select_server_port()
    flags = _streamlit_flags(port)
    _start_browser_opener(port)

    # Replicate the essential config loading order of `streamlit run`.
    streamlit_config._main_script_path = os.path.abspath(script_path)
    streamlit_bootstrap.load_config_options(flag_options=flags)
    streamlit_bootstrap.run(
        script_path,
        is_hello=False,
        args=script_args,
        flag_options=flags,
    )


if __name__ == "__main__":
    main()
