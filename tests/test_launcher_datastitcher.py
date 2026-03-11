# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Tests for the PyInstaller launcher."""

from __future__ import annotations

import launcher_datastitcher


def test_streamlit_flags_disable_development_mode() -> None:
    flags = launcher_datastitcher._streamlit_flags(8502)

    assert flags["global.developmentMode"] is False
    assert flags["server.headless"] is True
    assert flags["server.port"] == 8502
    assert flags["browser.serverPort"] == 8502
    assert flags["browser.gatherUsageStats"] is False


def test_configure_streamlit_environment_overrides_dev_mode(monkeypatch) -> None:
    monkeypatch.setenv("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "true")

    launcher_datastitcher._configure_streamlit_environment()

    assert (
        launcher_datastitcher.os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"]
        == "false"
    )


def test_select_server_port_skips_busy_ports(monkeypatch) -> None:
    def fake_is_port_available(port: int, host: str = "127.0.0.1") -> bool:
        return port >= 8503

    monkeypatch.setattr(launcher_datastitcher, "_is_port_available", fake_is_port_available)

    assert launcher_datastitcher._select_server_port(8501, 5) == 8503


def test_build_local_url() -> None:
    assert launcher_datastitcher._build_local_url(8510) == "http://localhost:8510"


def test_should_auto_open_browser_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DATASTITCHER_AUTO_OPEN_BROWSER", "false")

    assert launcher_datastitcher._should_auto_open_browser() is False


def test_open_browser_when_ready(monkeypatch) -> None:
    opened: list[tuple[str, int]] = []

    monkeypatch.setattr(
        launcher_datastitcher,
        "_wait_for_local_server",
        lambda port, timeout_seconds: True,
    )
    monkeypatch.setattr(
        launcher_datastitcher.webbrowser,
        "open",
        lambda url, new=0: opened.append((url, new)),
    )

    launcher_datastitcher._open_browser_when_ready(8504)

    assert opened == [("http://localhost:8504", 1)]


def test_start_browser_opener_starts_thread(monkeypatch) -> None:
    started: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class DummyThread:
        def __init__(self, *args: object, **kwargs: object) -> None:
            started.append((args, kwargs))

        def start(self) -> None:
            started.append((("started",), {}))

    monkeypatch.setattr(launcher_datastitcher, "_should_auto_open_browser", lambda: True)
    monkeypatch.setattr(launcher_datastitcher.threading, "Thread", DummyThread)

    launcher_datastitcher._start_browser_opener(8505)

    assert started[0][1]["args"] == (8505,)
    assert started[0][1]["daemon"] is True
    assert started[0][1]["name"] == "datastitcher-browser-opener"
    assert started[1][0] == ("started",)
