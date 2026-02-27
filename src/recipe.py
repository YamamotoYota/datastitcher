# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Recipe JSON serialization and validation."""

from __future__ import annotations

import json
from typing import Any

from .errors import UserInputError
from .models import JoinPlan, OutputSettings, Recipe, TableConfig

SUPPORTED_RECIPE_VERSION = "1.0"


def recipe_to_json(recipe: Recipe, indent: int = 2) -> str:
    """Serialize a recipe to JSON text."""
    return json.dumps(recipe.to_dict(), ensure_ascii=False, indent=indent)


def recipe_from_json(text: str) -> Recipe:
    """Deserialize and validate a recipe."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UserInputError(f"レシピJSONの解析に失敗しました: {exc}") from exc
    recipe = Recipe.from_dict(payload)
    validate_recipe(recipe)
    return recipe


def validate_recipe(recipe: Recipe) -> None:
    """Validate a recipe with lightweight schema checks."""
    if recipe.version != SUPPORTED_RECIPE_VERSION:
        raise UserInputError(
            f"未対応のレシピversionです: {recipe.version} (対応: {SUPPORTED_RECIPE_VERSION})"
        )
    if not recipe.tables:
        raise UserInputError("レシピにテーブル定義がありません。")
    table_ids = [t.table_id for t in recipe.tables]
    if len(table_ids) != len(set(table_ids)):
        raise UserInputError("レシピ内でtable_idが重複しています。")
    table_id_set = set(table_ids)
    if recipe.join_plan.base_table_id and recipe.join_plan.base_table_id not in table_id_set:
        raise UserInputError("join_plan.base_table_id が tables に存在しません。")
    for step in recipe.join_plan.steps:
        if step.right_table_id not in table_id_set:
            raise UserInputError(f"JoinStep {step.step_id} の right_table_id が tables に存在しません。")
        if step.operation == "union":
            continue
        if step.join_algorithm == "asof":
            if len(step.left_keys) != 1 or len(step.right_keys) != 1:
                raise UserInputError(f"JoinStep {step.step_id} (asof) は左右1つずつのキーが必要です。")
            if len(step.left_by_keys) != len(step.right_by_keys):
                raise UserInputError(f"JoinStep {step.step_id} (asof) で左右byキー数が一致していません。")
            continue
        if len(step.left_keys) != len(step.right_keys):
            raise UserInputError(f"JoinStep {step.step_id} で左右キー数が一致していません。")


def build_recipe(
    *,
    tables: list[TableConfig],
    join_plan: JoinPlan,
    output_settings: OutputSettings | None = None,
    ui_settings: dict[str, Any] | None = None,
) -> Recipe:
    """Build and validate a new recipe from current app state."""
    recipe = Recipe.new(
        tables=tables,
        join_plan=join_plan,
        output_settings=output_settings,
        ui_settings=ui_settings,
        version=SUPPORTED_RECIPE_VERSION,
    )
    validate_recipe(recipe)
    return recipe


def clone_table_configs(tables: list[TableConfig]) -> list[TableConfig]:
    """Deep-ish clone via dict roundtrip."""
    return [TableConfig.from_dict(t.to_dict()) for t in tables]


def clone_join_plan(join_plan: JoinPlan) -> JoinPlan:
    """Clone join plan via dict roundtrip."""
    return JoinPlan.from_dict(join_plan.to_dict())

