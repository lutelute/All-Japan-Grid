"""連系線容量の出典必須規約のテスト。

値を単独で持たせない（出典URL・原文引用が無ければ機械的に拒否する）ことが
この DB の存在理由なので、**拒否が実際に働くこと**を示す。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.interconnector_provenance import (
    SOURCES_PATH, load_records, validate_record, verify_file,
)

ROOT = Path(__file__).resolve().parents[1]


def _valid_record() -> dict:
    return {
        "link_key": "occto:関門連系線:順方向",
        "name": "関門連系線",
        "direction": "順方向",
        "field": "operational_capacity_mw",
        "value": 850.0,
        "unit": "MW",
        "source_type": "official",
        "source_url": "https://web-kohyo.occto.or.jp/kks-web-public/",
        "source_title": "OCCTO 系統情報公表システム 連系線関連情報",
        "quote": '"2025/04/01","00:30","関門連系線",…,順方向運用容量(MW)="850"',
        "retrieved_at": "2026-08-09",
        "confidence": "high",
        "collected_by": "test",
    }


def test_valid_record_passes():
    ok, reasons = validate_record(_valid_record())
    assert ok, reasons


@pytest.mark.parametrize("drop", ["source_url", "quote", "value", "unit", "direction"])
def test_missing_required_field_is_rejected(drop):
    """必須欄が欠けた値は入れない。ここが緩むと捏造の経路が開く。"""
    rec = _valid_record()
    del rec[drop]
    ok, reasons = validate_record(rec)
    assert not ok, f"{drop} が無いのに通ってしまった"
    assert any(drop in r for r in reasons), reasons


def test_fake_url_is_rejected():
    rec = _valid_record()
    rec["source_url"] = "OCCTO の公表資料より"      # URL でない
    ok, reasons = validate_record(rec)
    assert not ok and any("source_url" in r for r in reasons), reasons


def test_empty_quote_is_rejected():
    rec = _valid_record()
    rec["quote"] = "   "
    ok, _ = validate_record(rec)
    assert not ok, "原文引用が空の値が通ってしまった"


def test_non_numeric_value_is_rejected():
    rec = _valid_record()
    rec["value"] = "約850MW"
    ok, _ = validate_record(rec)
    assert not ok, "数値でない値が通ってしまった"


def test_wrong_field_is_rejected():
    """熱容量と運用容量は意味が違うので、field は運用容量に限定する。"""
    rec = _valid_record()
    rec["field"] = "thermal_capacity_mva"
    ok, _ = validate_record(rec)
    assert not ok, "運用容量以外の field が通ってしまった"


def test_secondary_source_is_rejected():
    """連系線の運用容量は OCCTO の一次情報のみを採る。"""
    rec = _valid_record()
    rec["source_type"] = "wikipedia"
    ok, _ = validate_record(rec)
    assert not ok, "二次情報が通ってしまった"


@pytest.mark.skipif(not Path(SOURCES_PATH).exists(), reason="正本ファイル未生成")
def test_canonical_file_is_clean():
    n, bad = verify_file()
    assert n > 0, "正本が空"
    assert not bad, f"{len(bad)}/{n} レコードが規約違反: {bad[:3]}"


@pytest.mark.skipif(not Path(SOURCES_PATH).exists(), reason="正本ファイル未生成")
def test_canonical_file_covers_both_directions():
    recs = load_records()
    by_name = {}
    for r in recs:
        by_name.setdefault(r["name"], set()).add(r["direction"])
    assert by_name, "連系線が1本も無い"
    for name, dirs in by_name.items():
        assert dirs == {"順方向", "逆方向"}, f"{name} の方向が揃っていない: {dirs}"
    # 分布が note に残っていること（単一値だけでは運用容量の変動が読めない）
    for r in recs:
        assert r["min_mw"] <= r["median_mw"] <= r["max_mw"], r["link_key"]
        assert r["value"] == r["max_mw"], "value は期間中の最大運用容量"
        assert r["observations"] > 0
