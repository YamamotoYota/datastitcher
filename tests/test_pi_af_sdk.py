# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Tests for PI AF SDK config normalization helpers."""

from __future__ import annotations

import pandas as pd

from src.pi_af_sdk import (
    _call_interpolated_values,
    _collect_attribute_snapshot,
    _create_search_object,
    _extract_event_frame_element_name,
    build_pi_query_config,
    parse_name_list,
)


class _FakeAFValue:
    def __init__(self, value: object, timestamp: str = "2026-01-01T00:00:00") -> None:
        self.Value = value
        self.Timestamp = timestamp
        self.IsGood = True


class _FakeAttributeDataFiveArgs:
    def InterpolatedValues(
        self,
        time_range: object,
        interval: object,
        filter_expression: object,
        desired_fields: object,
        include_filtered_values: bool,
    ) -> list[str]:
        assert filter_expression is None
        assert desired_fields is None
        assert include_filtered_values is False
        return ["ok"]


class _FakeSnapshotData:
    def Snapshot(self) -> _FakeAFValue:
        return _FakeAFValue(12.5)


class _FakeAttributeWithoutGetValue:
    Data = _FakeSnapshotData()


class _FakeNamedObject:
    def __init__(self, name: str) -> None:
        self.Name = name


class _FakeEventFrameWithoutPrimaryReferencedElement:
    ReferencedElements = [_FakeNamedObject("設備A")]


class _FakeTwoArgSearch:
    def __init__(self, database: object, query: str) -> None:
        self.database = database
        self.query = query


def test_parse_name_list_accepts_japanese_delimiters_and_nfkc() -> None:
    values = parse_name_list("温度、圧力， 流量；ﾚﾍﾞﾙ\n温度")
    assert values == ("温度", "圧力", "流量", "レベル")


def test_build_pi_query_config_normalizes_japanese_fullwidth_inputs() -> None:
    cfg = build_pi_query_config(
        data_source="af_attribute",
        pi_server="",
        af_server="ＡＦサーバー１",
        af_database="設備ＤＢ",
        query_type="Recorded",
        tags_text="",
        af_element="ライン１／装置Ａ",
        af_attributes_text="温度、圧力",
        start_time="＊-１ｄ",
        end_time="＊",
        interval="１０ｍｉｎ",
        summary_functions=["Average", "MAX"],
        max_rows_per_tag="２０００",
        ef_template="",
        ef_analyses_text="",
    )
    assert cfg.af_server == "AFサーバー1"
    assert cfg.af_database == "設備DB"
    assert cfg.af_element == "ライン1/装置A"
    assert cfg.af_attributes == ("温度", "圧力")
    assert cfg.start_time == "*-1d"
    assert cfg.interval == "10min"
    assert cfg.summary_functions == ("average", "max")
    assert cfg.max_rows_per_tag == 2000


def test_call_interpolated_values_accepts_five_argument_sdk_signature() -> None:
    result = _call_interpolated_values(
        _FakeAttributeDataFiveArgs(),
        time_range=object(),
        interval=object(),
        label="AF属性 InterpolatedValues(温度)",
    )
    assert result == ["ok"]


def test_collect_attribute_snapshot_falls_back_to_data_snapshot() -> None:
    rows = _collect_attribute_snapshot(_FakeAttributeWithoutGetValue(), "温度")
    assert len(rows) == 1
    assert rows[0]["tag"] == "温度"
    assert rows[0]["value"] == 12.5
    assert pd.notna(rows[0]["timestamp"])


def test_extract_event_frame_element_name_falls_back_to_referenced_elements() -> None:
    name = _extract_event_frame_element_name(_FakeEventFrameWithoutPrimaryReferencedElement())
    assert name == "設備A"


def test_create_search_object_accepts_constructor_fallback() -> None:
    search = _create_search_object(
        _FakeTwoArgSearch,
        [(object(), "name", "query"), (object(), "query")],
        label="イベントフレーム検索",
    )
    assert isinstance(search, _FakeTwoArgSearch)
    assert search.query == "query"
