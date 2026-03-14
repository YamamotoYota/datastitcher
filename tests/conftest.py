# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Shared pytest configuration for stable local imports."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
