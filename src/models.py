# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Data models used by the application and recipe serialization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

JoinType = Literal["inner", "left", "right", "outer"]
ConflictPolicy = Literal["left_prefer", "right_prefer", "keep_both"]
SourceKind = Literal["csv", "excel", "sql", "pi_da_tag", "af_attribute", "af_event_frame"]
SimpleDType = Literal["auto", "string", "number", "datetime"]
StepOperation = Literal["join", "union"]
JoinAlgorithm = Literal["equi", "asof"]
AsofDirection = Literal["backward", "forward", "nearest"]

UNION_KEEP_AS_NEW = "__KEEP_AS_NEW__"
UNION_DROP = "__DROP__"


@dataclass
class CSVOptions:
    """CSV parsing options (supports auto-detection)."""

    encoding: str = "auto"
    delimiter: str = "auto"
    quotechar: str = "auto"
    header_row: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CSVOptions":
        if not data:
            return cls()
        return cls(
            encoding=str(data.get("encoding", "auto")),
            delimiter=str(data.get("delimiter", "auto")),
            quotechar=str(data.get("quotechar", "auto")),
            header_row=int(data.get("header_row", 1)),
        )


@dataclass
class ExcelOptions:
    """Excel parsing options."""

    sheet_name: str | None = None
    header_row: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ExcelOptions":
        if not data:
            return cls()
        sheet_name = data.get("sheet_name")
        return cls(
            sheet_name=str(sheet_name) if sheet_name is not None else None,
            header_row=int(data.get("header_row", 1)),
        )


@dataclass
class TableConfig:
    """User-configured table settings for one uploaded file."""

    table_id: str
    table_name: str
    source_file_name: str
    source_kind: SourceKind
    file_hash: str | None = None
    csv_options: CSVOptions = field(default_factory=CSVOptions)
    excel_options: ExcelOptions = field(default_factory=ExcelOptions)
    source_options: dict[str, Any] = field(default_factory=dict)
    normalize_columns: bool = True
    selected_columns: list[str] = field(default_factory=list)
    dtype_overrides: dict[str, SimpleDType] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TableConfig":
        return cls(
            table_id=str(data["table_id"]),
            table_name=str(data.get("table_name", data.get("source_file_name", data["table_id"]))),
            source_file_name=str(data.get("source_file_name", "")),
            source_kind=str(data.get("source_kind", "csv")),  # type: ignore[arg-type]
            file_hash=data.get("file_hash"),
            csv_options=CSVOptions.from_dict(data.get("csv_options")),
            excel_options=ExcelOptions.from_dict(data.get("excel_options")),
            source_options={str(k): v for k, v in data.get("source_options", {}).items()}
            if isinstance(data.get("source_options", {}), dict)
            else {},
            normalize_columns=bool(data.get("normalize_columns", True)),
            selected_columns=[str(v) for v in data.get("selected_columns", [])],
            dtype_overrides={str(k): str(v) for k, v in data.get("dtype_overrides", {}).items()},
        )


@dataclass
class JoinStep:
    """One sequential join step: previous result JOIN right_table."""

    step_id: str
    right_table_id: str
    operation: StepOperation = "join"
    join_algorithm: JoinAlgorithm = "equi"
    join_type: JoinType = "left"
    left_keys: list[str] = field(default_factory=list)
    right_keys: list[str] = field(default_factory=list)
    left_by_keys: list[str] = field(default_factory=list)
    right_by_keys: list[str] = field(default_factory=list)
    asof_direction: AsofDirection = "backward"
    asof_tolerance: str | None = None
    asof_allow_exact_matches: bool = True
    conflict_policy: ConflictPolicy = "keep_both"
    suffixes: tuple[str, str] = ("_l", "_r")
    right_pre_agg_enabled: bool = False
    right_pre_agg_group_keys: list[str] = field(default_factory=list)
    right_pre_agg_weight_col: str = ""
    right_pre_agg_rules: dict[str, dict[str, str]] = field(default_factory=dict)
    union_column_mapping: dict[str, str] = field(default_factory=dict)
    union_right_column_suffix: str = "_u"
    union_add_source_column: bool = False
    union_source_column_name: str = "_source_table"
    union_source_value: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["suffixes"] = list(self.suffixes)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JoinStep":
        suffixes_raw = data.get("suffixes", ["_l", "_r"])
        if not isinstance(suffixes_raw, (list, tuple)) or len(suffixes_raw) != 2:
            suffixes = ("_l", "_r")
        else:
            suffixes = (str(suffixes_raw[0]), str(suffixes_raw[1]))
        return cls(
            step_id=str(data["step_id"]),
            right_table_id=str(data.get("right_table_id", "")),
            operation=str(data.get("operation", "join")),  # type: ignore[arg-type]
            join_algorithm=str(data.get("join_algorithm", "equi")),  # type: ignore[arg-type]
            join_type=str(data.get("join_type", "left")),  # type: ignore[arg-type]
            left_keys=[str(v) for v in data.get("left_keys", [])],
            right_keys=[str(v) for v in data.get("right_keys", [])],
            left_by_keys=[str(v) for v in data.get("left_by_keys", [])],
            right_by_keys=[str(v) for v in data.get("right_by_keys", [])],
            asof_direction=str(data.get("asof_direction", "backward")),  # type: ignore[arg-type]
            asof_tolerance=(
                str(data.get("asof_tolerance"))
                if data.get("asof_tolerance") not in (None, "")
                else None
            ),
            asof_allow_exact_matches=bool(data.get("asof_allow_exact_matches", True)),
            conflict_policy=str(data.get("conflict_policy", "keep_both")),  # type: ignore[arg-type]
            suffixes=suffixes,
            right_pre_agg_enabled=bool(data.get("right_pre_agg_enabled", False)),
            right_pre_agg_group_keys=[str(v) for v in data.get("right_pre_agg_group_keys", [])],
            right_pre_agg_weight_col=str(data.get("right_pre_agg_weight_col", "")),
            right_pre_agg_rules={
                str(col): {
                    "method": str(spec.get("method", "first")),
                    "formula": str(spec.get("formula", "")),
                }
                for col, spec in dict(data.get("right_pre_agg_rules", {})).items()
                if isinstance(spec, dict)
            }
            if isinstance(data.get("right_pre_agg_rules", {}), dict)
            else {},
            union_column_mapping={
                str(k): str(v) for k, v in dict(data.get("union_column_mapping", {})).items()
            }
            if isinstance(data.get("union_column_mapping", {}), dict)
            else {},
            union_right_column_suffix=str(data.get("union_right_column_suffix", "_u")),
            union_add_source_column=bool(data.get("union_add_source_column", False)),
            union_source_column_name=str(data.get("union_source_column_name", "_source_table")),
            union_source_value=str(data.get("union_source_value", "")),
        )


@dataclass
class JoinPlan:
    """Sequential join plan starting from a base table."""

    base_table_id: str
    steps: list[JoinStep] = field(default_factory=list)
    row_explosion_warn_ratio: float = 10.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_table_id": self.base_table_id,
            "row_explosion_warn_ratio": self.row_explosion_warn_ratio,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JoinPlan":
        return cls(
            base_table_id=str(data.get("base_table_id", "")),
            row_explosion_warn_ratio=float(data.get("row_explosion_warn_ratio", 10.0)),
            steps=[JoinStep.from_dict(v) for v in data.get("steps", [])],
        )


@dataclass
class OutputSettings:
    """Output preferences stored in a recipe."""

    default_format: str = "csv"
    csv_encoding: str = "utf-8-sig"
    excel_sheet_name: str = "result"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OutputSettings":
        if not data:
            return cls()
        return cls(
            default_format=str(data.get("default_format", "csv")),
            csv_encoding=str(data.get("csv_encoding", "utf-8-sig")),
            excel_sheet_name=str(data.get("excel_sheet_name", "result")),
        )


@dataclass
class Recipe:
    """Serializable configuration for reproducible joins."""

    version: str
    created_at: str
    tables: list[TableConfig]
    join_plan: JoinPlan
    output_settings: OutputSettings = field(default_factory=OutputSettings)
    ui_settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        tables: list[TableConfig],
        join_plan: JoinPlan,
        output_settings: OutputSettings | None = None,
        ui_settings: dict[str, Any] | None = None,
        version: str = "1.0",
    ) -> "Recipe":
        created_at = datetime.now(timezone.utc).isoformat()
        return cls(
            version=version,
            created_at=created_at,
            tables=tables,
            join_plan=join_plan,
            output_settings=output_settings or OutputSettings(),
            ui_settings=ui_settings or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "tables": [t.to_dict() for t in self.tables],
            "join_plan": self.join_plan.to_dict(),
            "output_settings": self.output_settings.to_dict(),
            "ui_settings": self.ui_settings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Recipe":
        return cls(
            version=str(data.get("version", "1.0")),
            created_at=str(data.get("created_at", "")),
            tables=[TableConfig.from_dict(v) for v in data.get("tables", [])],
            join_plan=JoinPlan.from_dict(data.get("join_plan", {})),
            output_settings=OutputSettings.from_dict(data.get("output_settings")),
            ui_settings=dict(data.get("ui_settings", {})),
        )


@dataclass
class JoinQualityReport:
    """Per-step join quality metrics shown in the UI."""

    step_id: str
    join_type: str
    left_rows: int
    right_rows: int
    output_rows: int
    matched_left_rows: int
    unmatched_left_rows: int
    matched_right_rows: int
    unmatched_right_rows: int
    left_match_rate: float | None
    right_match_rate: float | None
    left_duplicate_key_rows: int
    right_duplicate_key_rows: int
    many_to_many_suspected: bool
    row_growth_ratio_vs_left: float | None
    operation: str = "join"
    algorithm: str = "equi"
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JoinStepResult:
    """Result bundle for one executed join step."""

    step: JoinStep
    output_df: Any
    report: JoinQualityReport
    unmatched_left_df: Any
    unmatched_right_df: Any
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class JoinExecutionResult:
    """Full join plan execution output."""

    final_df: Any
    step_results: list[JoinStepResult]


@dataclass
class ExecutionLogEntry:
    """Execution log entry written to a local JSONL file."""

    executed_at: str
    recipe_version: str
    input_files: list[dict[str, Any]]
    base_table_id: str
    step_reports: list[dict[str, Any]]
    final_shape: tuple[int, int]
    status: str = "success"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["final_shape"] = list(self.final_shape)
        return data

