# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Tests for the PyInstaller launcher."""

from __future__ import annotations

import launcher_datastitcher


def test_streamlit_flags_disable_development_mode() -> None:
    flags = launcher_datastitcher._streamlit_flags()

    assert flags["global.developmentMode"] is False
    assert flags["server.headless"] is True
    assert flags["browser.gatherUsageStats"] is False


def test_configure_streamlit_environment_overrides_dev_mode(monkeypatch) -> None:
    monkeypatch.setenv("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "true")

    launcher_datastitcher._configure_streamlit_environment()

    assert (
        launcher_datastitcher.os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"]
        == "false"
    )
