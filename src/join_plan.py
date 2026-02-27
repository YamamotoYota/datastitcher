# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Join plan execution facade (separate from engine for future extensibility)."""

from __future__ import annotations

from typing import Callable

import pandas as pd

from .join_engine import JoinEngine, execute_join_plan
from .models import JoinExecutionResult, JoinPlan

__all__ = ["execute_plan"]


def execute_plan(
    *,
    join_plan: JoinPlan,
    load_table: Callable[[str], pd.DataFrame],
    engine: JoinEngine | None = None,
) -> JoinExecutionResult:
    """Execute a join plan using the provided engine (default: pandas equi-join)."""
    return execute_join_plan(join_plan=join_plan, load_table=load_table, engine=engine)

