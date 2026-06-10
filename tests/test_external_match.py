"""Unit tests for the official-line-list vs OSM matcher (synthetic data).

Real ground-truth CSVs are not redistributable, so these tests pin the
parsing / normalisation / matching mechanics on fixtures that mimic the
Kansai-TD layout (update-date preamble row, CP932, full-width digits).
"""

import json

import pytest

from src.validation.external_match import (
    _norm,
    load_official_lines,
    match_official,
)


@pytest.fixture
def official_csv(tmp_path):
    rows = [
        '"2026年06月08日更新"',
        '"送電線No","送電線名","電圧（kV）","回線数","設備容量(100%×回線数)","運用容量値(MW)"',
        '"1","播磨線","500","2","5568","3062"',
        '"2","存在しない線","275","2","1200","600"',
        '"3","Ｂ幹線","154","1","400","200"',          # full-width B
        '"4","","154","1","400","200"',                 # blank name -> skipped
    ]
    p = tmp_path / "official.csv"
    p.write_bytes("\n".join(rows).encode("cp932"))
    return str(p)


@pytest.fixture
def osm_dir(tmp_path):
    feats = [
        {"type": "Feature", "geometry": None,
         "properties": {"name": "播磨線", "voltage": "500000", "circuits": "2"}},
        {"type": "Feature", "geometry": None,
         "properties": {"name": "B幹線 支線", "voltage": "154000", "circuits": "1"}},
    ]
    p = tmp_path / "testreg_lines.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}),
                 encoding="utf-8")
    return str(tmp_path)


def test_norm_handles_fullwidth_and_spaces():
    assert _norm("Ｂ幹線") == "B幹線"
    assert _norm("播磨　線") == "播磨線"


def test_load_official_skips_preamble_and_blank(official_csv):
    lines = load_official_lines(official_csv)
    assert [o["name"] for o in lines] == ["播磨線", "存在しない線", "Ｂ幹線"]
    assert lines[0]["kv"] == 500.0
    assert lines[0]["circuits"] == 2
    assert lines[0]["capacity_mw"] == 3062.0


def test_match_exact_loose_missing(official_csv, osm_dir):
    m = match_official("testreg", official_csv, data_dir=osm_dir)
    assert m["n_official"] == 3
    assert m["n_matched_exact"] == 1        # 播磨線
    assert m["n_matched_loose"] == 1        # Ｂ幹線 ⊂ "B幹線 支線" (NFKC)
    assert m["n_missing"] == 1              # 存在しない線
    assert m["recall_exact"] == pytest.approx(1 / 3, abs=1e-4)
    assert m["recall_with_loose"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["missing_names"] == ["存在しない線 (275kV)"]
    # matched 播磨線: voltage 500 vs 500 agrees, circuits 2 vs 2 agrees
    assert m["voltage_agree"] == "1/1"
    assert m["circuits_agree"] == "1/1"
