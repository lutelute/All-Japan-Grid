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
