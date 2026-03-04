# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""PyInstaller launcher for DataStitcher (Streamlit runtime bootstrap)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from streamlit.web.bootstrap import run as streamlit_bootstrap_run

import app as datastitcher_app


def _resolve_app_script_path() -> str:
    """Resolve the packaged `app.py` location."""
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(str(meipass)) / "app.py")

    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir / "app.py")
    candidates.append(exe_dir / "_internal" / "app.py")

    module_file = Path(datastitcher_app.__file__).resolve()
    candidates.append(module_file)
    if module_file.suffix.lower() == ".pyc":
        candidates.append(module_file.with_suffix(".py"))

    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() == ".py":
            return str(candidate)

    raise FileNotFoundError(
        "アプリスクリプトが見つかりません: "
        + ", ".join(str(path) for path in candidates)
    )


def _streamlit_flags() -> dict[str, Any]:
    """Default streamlit runtime flags for packaged desktop launch."""
    return {
        "server.headless": True,
        "browser.gatherUsageStats": False,
        "server.runOnSave": False,
    }


def main() -> None:
    """Start Streamlit server using the packaged app script."""
    script_args = sys.argv[1:]
    streamlit_bootstrap_run(
        _resolve_app_script_path(),
        is_hello=False,
        args=script_args,
        flag_options=_streamlit_flags(),
    )


if __name__ == "__main__":
    main()
