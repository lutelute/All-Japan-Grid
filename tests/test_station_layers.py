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
