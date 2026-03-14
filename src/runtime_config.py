# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Runtime configuration helpers for local execution."""

from __future__ import annotations

import os

PYTHONNET_RUNTIME_ENV_NAME = "PYTHONNET_RUNTIME"
FORCED_PYTHONNET_RUNTIME = "netfx"


def apply_pythonnet_runtime_env() -> str:
    """Force the pythonnet runtime selection for this process."""
    os.environ[PYTHONNET_RUNTIME_ENV_NAME] = FORCED_PYTHONNET_RUNTIME
    return FORCED_PYTHONNET_RUNTIME
