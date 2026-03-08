# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Unit tests for join plan execution and recipe serialization."""

from __future__ import annotations

import pandas as pd
import pytest

from src.join_engine import PandasEquiJoinEngine, execute_join_plan
from src.errors import UserInputError
from src.models import UNION_KEEP_AS_NEW, JoinPlan, JoinStep, OutputSettings, TableConfig
from src.recipe import build_recipe, recipe_from_json, recipe_to_json


def test_composite_key_left_join_left_prefer_conflict_resolution() -> None:
    base = pd.DataFrame(
        {
            "id": ["A", "A", "B"],
            "sub_id": [1, 2, 1],
            "name": ["x-left", "y-left", "z-left"],
            "amount": [100, 200, 300],
        }
    )
    right = pd.DataFrame(
        {
            "id": ["A", "A", "C"],
            "sub_id": [1, 2, 9],
            "name": ["x-right", "y-right", "c-right"],
            "category": ["cat1", "cat2", "cat3"],
        }
    )

    join_plan = JoinPlan(
        base_table_id="base",
        steps=[
            JoinStep(
                step_id="step_1",
                right_table_id="dim",
                join_type="left",
                left_keys=["id", "sub_id"],
                right_keys=["id", "sub_id"],
                conflict_policy="left_prefer",
                suffixes=("_l", "_r"),
            )
        ],
    )

    table_map = {"base": base, "dim": right}
    result = execute_join_plan(join_plan=join_plan, load_table=lambda tid: table_map[tid], engine=PandasEquiJoinEngine())

    final_df = result.final_df
    assert final_df.shape[0] == 3
    assert "name" in final_df.columns
    assert "name_l" not in final_df.columns
    assert "name_r" not in final_df.columns
    assert list(final_df["name"]) == ["x-left", "y-left", "z-left"]
    assert list(final_df["category"].fillna("")) == ["cat1", "cat2", ""]

    report = result.step_results[0].report
    assert report.left_rows == 3
    assert report.right_rows == 3
    assert report.output_rows == 3
    assert report.unmatched_left_rows == 1
    assert report.unmatched_right_rows == 1


def test_outer_join_keep_both_unmatched_extracts() -> None:
    left = pd.DataFrame({"key": [1, 2], "v": ["a", "b"]})
    right = pd.DataFrame({"key": [2, 3], "v": ["bb", "cc"]})

    join_plan = JoinPlan(
        base_table_id="l",
        steps=[
            JoinStep(
                step_id="step_1",
                right_table_id="r",
                join_type="outer",
                left_keys=["key"],
                right_keys=["key"],
                conflict_policy="keep_both",
                suffixes=("_L", "_R"),
            )
        ],
    )
    table_map = {"l": left, "r": right}
    result = execute_join_plan(join_plan=join_plan, load_table=lambda tid: table_map[tid], engine=PandasEquiJoinEngine())
    step_result = result.step_results[0]

    assert step_result.output_df.shape[0] == 3
    assert "v_L" in step_result.output_df.columns
    assert "v_R" in step_result.output_df.columns
    assert step_result.unmatched_left_df["key"].tolist() == [1]
    assert step_result.unmatched_right_df["key"].tolist() == [3]


def test_recipe_roundtrip() -> None:
    tables = [
        TableConfig(
            table_id="tbl_a",
            table_name="A",
            source_file_name="a.csv",
            source_kind="csv",
            normalize_columns=True,
            selected_columns=["id", "v"],
            dtype_overrides={"id": "string"},
        ),
        TableConfig(
            table_id="tbl_b",
            table_name="B",
            source_file_name="b.xlsx",
            source_kind="excel",
            normalize_columns=False,
            selected_columns=["id", "name"],
        ),
    ]
    join_plan = JoinPlan(
        base_table_id="tbl_a",
        steps=[
            JoinStep(
                step_id="step_1",
                right_table_id="tbl_b",
                join_type="left",
                left_keys=["id"],
                right_keys=["id"],
                conflict_policy="keep_both",
                suffixes=("_x", "_y"),
            )
        ],
    )
    recipe = build_recipe(tables=tables, join_plan=join_plan, output_settings=OutputSettings(default_format="csv"))
    text = recipe_to_json(recipe)
    restored = recipe_from_json(text)

    assert restored.version == "1.0"
    assert restored.join_plan.base_table_id == "tbl_a"
    assert len(restored.tables) == 2
    assert restored.tables[0].source_file_name == "a.csv"
    assert restored.join_plan.steps[0].suffixes == ("_x", "_y")


def test_asof_join_backward_with_by_key() -> None:
    left = pd.DataFrame(
        {
            "customer_id": ["A", "A", "B"],
            "ts": pd.to_datetime(["2024-01-01 10:00:00", "2024-01-01 10:06:00", "2024-01-01 10:03:00"]),
            "qty": [1, 2, 1],
        }
    )
    right = pd.DataFrame(
        {
            "customer_code": ["A", "A", "B"],
            "rate_ts": pd.to_datetime(["2024-01-01 09:59:00", "2024-01-01 10:05:00", "2024-01-01 10:10:00"]),
            "price": [100, 120, 999],
        }
    )

    join_plan = JoinPlan(
        base_table_id="left",
        steps=[
            JoinStep(
                step_id="step_1",
                right_table_id="right",
                operation="join",
                join_algorithm="asof",
                join_type="left",
                left_keys=["ts"],
                right_keys=["rate_ts"],
                left_by_keys=["customer_id"],
                right_by_keys=["customer_code"],
                asof_direction="backward",
                asof_tolerance="10min",
                conflict_policy="keep_both",
                suffixes=("_l", "_r"),
            )
        ],
    )
    table_map = {"left": left, "right": right}
    result = execute_join_plan(join_plan=join_plan, load_table=lambda tid: table_map[tid], engine=PandasEquiJoinEngine())
    out = result.final_df.sort_values(["customer_id", "ts"]).reset_index(drop=True)

    assert out.shape[0] == 3
    assert out["price"].tolist() == [100, 120, None] or out["price"].fillna(-1).tolist() == [100, 120, -1]
    report = result.step_results[0].report
    assert report.algorithm == "asof"
    assert report.unmatched_left_rows == 1
    assert report.matched_left_rows == 2


def test_union_with_column_mapping_and_new_column() -> None:
    left = pd.DataFrame(
        {
            "customer_id": ["A1", "A2"],
            "order_date": ["2024-01-01", "2024-01-02"],
            "amount": [100, 200],
        }
    )
    right = pd.DataFrame(
        {
            "cust_id": ["A3"],
            "date": ["2024-01-03"],
            "amt": [300],
            "note": ["campaign"],
        }
    )

    join_plan = JoinPlan(
        base_table_id="left",
        steps=[
            JoinStep(
                step_id="step_1",
                right_table_id="right",
                operation="union",
                union_column_mapping={
                    "cust_id": "customer_id",
                    "date": "order_date",
                    "amt": "amount",
                    "note": UNION_KEEP_AS_NEW,
                },
                union_right_column_suffix="_u",
            )
        ],
    )
    table_map = {"left": left, "right": right}
    result = execute_join_plan(join_plan=join_plan, load_table=lambda tid: table_map[tid], engine=PandasEquiJoinEngine())
    out = result.final_df

    assert out.shape[0] == 3
    assert "note" in out.columns
    assert out.loc[2, "customer_id"] == "A3"
    assert int(out.loc[2, "amount"]) == 300
    assert out.loc[2, "note"] == "campaign"
    report = result.step_results[0].report
    assert report.operation == "union"
    assert report.details["mapped_columns"] == 3


def test_equi_join_with_right_pre_aggregation_weighted_mean() -> None:
    left = pd.DataFrame({"product_lot": ["A", "B"], "product_quality": [1.2, 1.8]})
    right = pd.DataFrame(
        {
            "product_lot_ref": ["A", "A", "B"],
            "raw_lot": ["A-1", "A-2", "B-1"],
            "feed_kg": [100, 200, 50],
            "raw_quality": [10.0, 40.0, 90.0],
        }
    )

    join_plan = JoinPlan(
        base_table_id="left",
        steps=[
            JoinStep(
                step_id="step_1",
                right_table_id="right",
                operation="join",
                join_algorithm="equi",
                join_type="left",
                left_keys=["product_lot"],
                right_keys=["product_lot_ref"],
                right_pre_agg_enabled=True,
                right_pre_agg_group_keys=["product_lot_ref"],
                right_pre_agg_weight_col="feed_kg",
                right_pre_agg_rules={
                    "raw_quality": {"method": "weighted_mean", "formula": ""},
                },
                conflict_policy="keep_both",
            )
        ],
    )
    table_map = {"left": left, "right": right}
    result = execute_join_plan(join_plan=join_plan, load_table=lambda tid: table_map[tid], engine=PandasEquiJoinEngine())
    out = result.final_df.sort_values("product_lot").reset_index(drop=True)

    assert out.shape[0] == 2
    assert out.loc[0, "raw_quality"] == pytest.approx(30.0)  # (10*100 + 40*200) / 300
    assert out.loc[1, "raw_quality"] == pytest.approx(90.0)
    details = result.step_results[0].report.details["right_pre_aggregation"]
    assert details["input_rows"] == 3
    assert details["output_rows"] == 2


def test_equi_join_with_right_pre_aggregation_requires_weight_for_weighted_mean() -> None:
    left = pd.DataFrame({"k": ["A"]})
    right = pd.DataFrame({"k2": ["A"], "v": [10.0]})
    join_plan = JoinPlan(
        base_table_id="left",
        steps=[
            JoinStep(
                step_id="step_1",
                right_table_id="right",
                operation="join",
                join_algorithm="equi",
                join_type="left",
                left_keys=["k"],
                right_keys=["k2"],
                right_pre_agg_enabled=True,
                right_pre_agg_group_keys=["k2"],
                right_pre_agg_weight_col="",
                right_pre_agg_rules={"v": {"method": "weighted_mean", "formula": ""}},
            )
        ],
    )

    with pytest.raises(UserInputError):
        execute_join_plan(
            join_plan=join_plan,
            load_table=lambda tid: {"left": left, "right": right}[tid],
            engine=PandasEquiJoinEngine(),
        )

