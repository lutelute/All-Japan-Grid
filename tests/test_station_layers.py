"""SubSLD の構造 DB と node-breaker 観測層の突き合わせ(scripts/compare_station_layers.py)。"""
from pathlib import Path

from scripts.build_station_db import structure_crosswalk
from scripts.build_structures_batch import build_region
from scripts.compare_station_layers import kvi, verdict


def test_transformer_pair_verdicts():
    ladder = {(275, 154), (154, 77)}
    levels = {275, 154, 77}
    assert verdict({(275, 154), (154, 77)}, ladder, levels) == "same"
    assert verdict({(275, 154)}, ladder, levels) == "osm_partial"
    # 西濃・東清水: 梯子は 154 を経由するが、実機は 275/77 の直結
    assert verdict({(275, 154), (275, 77)}, ladder, levels) == "ladder_skips"
    # 構造 DB に無い 6 kV への実機
    assert verdict({(77, 6)}, ladder, levels) == "level_not_in_db"


def test_kv_is_truncated_like_the_structure_db():
    assert kvi(6.6) == 6 and kvi(66.0) == 66 and kvi(275) == 275


def test_crosswalk_reaches_every_structure_site_by_osm_key():
    structures, _c, _r = build_region("okinawa")
    xwalk = structure_crosswalk(Path("data"))
    sids = {sid for v in xwalk.values() for sid in v}
    assert {s.site.site_id for s in structures} <= sids


# ------------------------------------------------------------- 介入 #48
from src.model.site_transformers import link_levels  # noqa: E402


def test_no_observation_is_the_ladder():
    assert link_levels([500, 275, 154]) == [(500, 275, "ladder"), (275, 154, "ladder")]


def test_observed_skip_pair_replaces_the_rung_it_makes_redundant():
    # 西濃: 実機は 275/154 と 275/77。梯子の 154/77 は張らない
    assert link_levels([275, 154, 77], [(275, 154), (275, 77)]) == [
        (275, 154, "osm"), (275, 77, "osm")]


def test_levels_the_observation_does_not_reach_stay_on_the_ladder():
    # 東清水: 実機は 275/77 だけ。154 は孤立させず梯子でつなぐ
    assert link_levels([275, 154, 77], [(275, 77)]) == [(275, 77, "osm"), (275, 154, "ladder")]
    # 東毛: 500/275/154/66 に実機 275/66 → 500/275 と 275/154 は梯子で残す
    assert link_levels([500, 275, 154, 66], [(275, 66)]) == [
        (275, 66, "osm"), (500, 275, "ladder"), (275, 154, "ladder")]


def test_observed_pairs_outside_the_site_levels_are_ignored():
    # 6.6 kV の実機は、6 kV の階級に切り捨てで照合する。階級に無い 22 kV は無視
    assert link_levels([66, 6.6], [(66, 6.6), (66, 22)]) == [(66, 6.6, "osm")]


# ------------------------------------------------------------- 介入 #49
def test_published_pairs_take_precedence_and_keep_their_label():
    # 三河: 公表は 275/154 と 275/77。梯子の 154/77 は張らない
    assert link_levels([275, 154, 77], [(275, 154), (275, 77)], "published") == [
        (275, 154, "published"), (275, 77, "published")]


def test_published_pairs_file_holds_voltage_pairs_only():
    """公表一覧の値は転載不可の社がある。リポジトリに入れるのは電圧の組だけ(台数・容量を入れない)。"""
    import json
    from src.model.site_transformers import PUBLISHED_PATH
    d = json.load(open(PUBLISHED_PATH, encoding="utf-8"))
    allowed = {"name", "regions", "structure_sites", "lat", "lon", "pairs", "utility", "source"}
    for s in d["sites"]:
        assert set(s) <= allowed, set(s) - allowed
        assert all(len(p) == 2 and p[0] > p[1] for p in s["pairs"])


# ------------------------------------------------------------- 介入 #50・#51
def test_pair_capacity_file_holds_aggregates_only():
    """変電所ごとの容量は転載不可の社がある。組ごとの中央値と件数だけを入れる。"""
    import json
    from pathlib import Path
    d = json.load(open(Path(__file__).resolve().parents[1] / "config/transformer_capacity_by_pair.json"))
    for k, v in d["pairs"].items():
        hv, lv = (int(x) for x in k.split("/"))
        assert hv > lv and set(v) == {"median_mva", "n_sites"} and v["n_sites"] >= 5


def test_missing_levels_file_holds_voltage_pairs_only():
    import json
    from src.model.site_transformers import MISSING_LEVELS_PATH
    d = json.load(open(MISSING_LEVELS_PATH, encoding="utf-8"))
    for s in d["sites"]:
        assert set(s) <= {"name", "structure_sites", "pairs"}
        assert all(len(p) == 2 and p[0] > p[1] for p in s["pairs"])


def test_voltage_correction_follows_the_wrong_voltage_and_reverts():
    from scripts.apply_voltage_corrections import CORRECTIONS, apply, revert
    built = {"nodes": [
        {"id": "x_sub_1@500", "name": "西島根変電所 500kV", "kv": 500.0, "lat": 34.7, "lon": 131.98, "region": "chugoku"},
        {"id": "x_sub_1@275", "name": "西島根変電所 275kV", "kv": 275.0, "lat": 34.7, "lon": 131.98, "region": "chugoku"},
        {"id": "x_sub_2", "name": "三隅町岡見変電所", "kv": 275.0, "lat": 34.78, "lon": 131.92, "region": "chugoku"}],
        "edges": [{"a": [34.7, 131.98], "b": [34.78, 131.92], "kv": 275.0, "name": "西島根~三隅線"},
                  {"a": [34.7, 131.98], "b": [34.9, 132.1], "kv": 500.0, "name": "500kV の線"}]}
    import copy
    before = copy.deepcopy(built)
    assert CORRECTIONS[0]["to_kv"] == 220.0
    apply(built, write_log=lambda *_: None)
    assert [n["kv"] for n in built["nodes"]] == [500.0, 220.0, 220.0]
    assert built["nodes"][1]["id"] == "x_sub_1@220" and built["edges"][1]["kv"] == 500.0
    revert(built, write_log=lambda *_: None)
    assert built == before
