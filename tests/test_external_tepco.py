"""Unit tests for the TEPCO disclosure-header matcher (synthetic data).

The real CSV is not redistributable; these fixtures mimic its column
grammar ("<sub>(変) - <line>1･2L", busbar/Tr columns to be ignored) and a
tiny region where one official attachment holds in the built model, one
line exists but terminates elsewhere, and one line is absent.
"""

import json

import pytest

from src.validation.external_tepco import (
    _norm,
    match_tepco,
    parse_tepco_header,
)


@pytest.fixture
def tepco_csv(tmp_path):
    header = ",".join([
        "日時",
        "京浜(変) - 1･2B",                 # busbar -> ignored
        "京浜(変) - 1号連絡Tr",            # trafo  -> ignored
        "京浜(変) - 東京南線1･2L",          # attachment pair
        "京浜(変) - 不在線1L",              # line absent from the model
        "葛南(開) - 東京南線3･4L",          # second sub on the same line
    ])
    p = tmp_path / "jisseki.csv"
    p.write_bytes((header + "\n").encode("cp932"))
    return str(p)


@pytest.fixture
def data_dir(tmp_path):
    subs = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"name": "京浜変電所", "voltage": "275000"},
         "geometry": {"type": "Point", "coordinates": [139.60, 35.50]}},
        {"type": "Feature",
         "properties": {"name": "遠方変電所", "voltage": "275000"},
         "geometry": {"type": "Point", "coordinates": [139.90, 35.80]}},
    ]}
    lines = {"type": "FeatureCollection", "features": [
        # 東京南線: terminates at 京浜 but NOT at 葛南 (not in the model)
        {"type": "Feature",
         "properties": {"name": "東京南線", "voltage": "275000"},
         "geometry": {"type": "LineString",
                      "coordinates": [[139.60, 35.50], [139.90, 35.80]]}},
    ]}
    d = tmp_path / "data"
    d.mkdir()
    (d / "testreg_substations.geojson").write_text(json.dumps(subs))
    (d / "testreg_lines.geojson").write_text(json.dumps(lines))
    return str(d)


def test_norm_strips_class_suffix_and_facility_words():
    assert _norm("京浜変電所 275kV") == "京浜"
    assert _norm("京浜 (untyped)") == "京浜"
    assert _norm("葛南開閉所") == "葛南"


def test_parse_header_extracts_pairs_only_from_line_columns(tepco_csv):
    t = parse_tepco_header(tepco_csv)
    assert t["subs"] == {"京浜", "葛南"}
    assert t["lines"] == {"東京南線", "不在線"}
    assert ("京浜", "東京南線") in t["pairs"]
    assert ("葛南", "東京南線") in t["pairs"]
    assert len(t["pairs"]) == 3


def test_match_scores_attachments_and_missing(tepco_csv, data_dir):
    m = match_tepco("testreg", tepco_csv, data_dir=data_dir)
    assert m["truth"] == {"subs": 2, "lines": 2, "pairs": 3}
    assert m["sub_recall"] == pytest.approx(0.5)        # 京浜 only
    assert m["line_recall_exact"] == pytest.approx(0.5)  # 東京南線
    # 京浜-東京南線 attached; 葛南-東京南線 = line present, wrong end;
    # 京浜-不在線 = line missing
    assert m["pair_attached"] == 1
    assert m["pair_line_present_not_attached"] == 1
    assert m["missing_lines"] == ["不在線"]
    assert any("葛南 - 東京南線" in s for s in m["missing_pairs"])
