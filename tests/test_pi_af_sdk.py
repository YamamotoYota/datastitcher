# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Tests for PI AF SDK config normalization helpers."""

from __future__ import annotations

from src.pi_af_sdk import build_pi_query_config, parse_name_list


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

