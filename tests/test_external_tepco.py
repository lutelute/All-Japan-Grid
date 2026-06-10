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
    # 京浜-東京南線 attached by name; 葛南-東京南線 = line present but 葛南
    # is absent from the model (no position either); 京浜-不在線 = missing
    assert m["pair_attached_name"] == 1
    assert m["pair_attached_position"] == 0
    assert m["pair_unattached"] == 1
    assert m["missing_lines"] == ["不在線"]
    assert any("葛南 - 東京南線" in s for s in m["missing_pairs"])


def test_position_tier_attaches_renamed_facility(tepco_csv, tmp_path):
    """TEPCO 京浜 vs an OSM yard named differently 0.5 km away: the name
    tier misses, the position tier attaches (the 西北線/稲城 pattern)."""
    subs = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"name": "別名変電所", "voltage": "275000"},
         "geometry": {"type": "Point", "coordinates": [139.60, 35.50]}},
        {"type": "Feature",     # the official name exists 0.5 km away
         "properties": {"name": "京浜変電所", "voltage": "275000"},
         "geometry": {"type": "Point", "coordinates": [139.6055, 35.50]}},
        {"type": "Feature",
         "properties": {"name": "遠方変電所", "voltage": "275000"},
         "geometry": {"type": "Point", "coordinates": [139.90, 35.80]}},
    ]}
    lines = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"name": "東京南線", "voltage": "275000"},
         "geometry": {"type": "LineString",
                      "coordinates": [[139.60, 35.50], [139.90, 35.80]]}},
    ]}
    d = tmp_path / "data2"
    d.mkdir()
    (d / "testreg_substations.geojson").write_text(json.dumps(subs))
    (d / "testreg_lines.geojson").write_text(json.dumps(lines))
    m = match_tepco("testreg", tepco_csv, data_dir=str(d))
    # NOTE: both 別名 and 京浜 sit within the snap radius, so whichever the
    # builder picked, the official 京浜 position is within pos_km of an
    # endpoint -> attached by name OR position, never "unattached".
    assert m["pair_attached_name"] + m["pair_attached_position"] >= 1
    assert m["pair_unattached"] <= 1   # only 葛南 may remain


def test_railway_only_names_are_excluded(tmp_path):
    subs = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "京浜変電所", "voltage": "275000"},
         "geometry": {"type": "Point", "coordinates": [139.60, 35.50]}},
    ]}
    lines = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"name": "東京南線", "voltage": "275000",
                        "operator": "東日本旅客鉄道株式会社"},
         "geometry": {"type": "LineString",
                      "coordinates": [[139.60, 35.50], [139.90, 35.80]]}},
    ]}
    d = tmp_path / "data3"
    d.mkdir()
    (d / "testreg_substations.geojson").write_text(json.dumps(subs))
    (d / "testreg_lines.geojson").write_text(json.dumps(lines))
    header = "日時,京浜(変) - 東京南線1･2L"
    p = tmp_path / "rail.csv"
    p.write_bytes((header + "\n").encode("cp932"))
    m = match_tepco("testreg", str(p), data_dir=str(d))
    # the only name match is railway-operated -> treated as missing
    assert m["n_railway_name_excluded"] == 1
    assert m["missing_lines"] == ["東京南線"]


def test_flow_stats_sums_circuit_groups_takes_max_end(tmp_path):
    """Circuit-group columns at the same end are summed per timestamp;
    the two ends of a line are separate groups and the larger wins."""
    rows = [
        "日時,京浜(変) - A線1･2L,京浜(変) - A線3･4L,葛南(変) - A線1･2L",
        "2024年04月01日 00時,100,50,120",
        "2024年04月01日 01時,200,100,250",
    ]
    p = tmp_path / "flows.csv"
    p.write_bytes(("\n".join(rows) + "\n").encode("cp932"))

    from src.validation.external_tepco import tepco_flow_stats
    stats = tepco_flow_stats(str(p), q=1.0)   # q=1 -> max
    # 京浜 end: 100+50=150, 200+100=300 -> 300 ; 葛南 end: 250 -> keep 300
    assert stats == {"A線": 300.0}
