# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""PyInstaller launcher for DataStitcher (Streamlit runtime bootstrap)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


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


def _streamlit_flags() -> dict[str, Any]:
    """Default streamlit runtime flags for packaged desktop launch."""
    return {
        "global.developmentMode": False,
        "server.headless": True,
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
    flags = _streamlit_flags()

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
