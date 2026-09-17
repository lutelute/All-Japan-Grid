"""介入#38 の正典化(2026-09-03)のゲート。

#38(周波数跨ぎ再属性の精緻化)は**潮流を組むときだけ**効いていて、正典
docs/data/built/all.json のラベルは古いままだった(実測 253 ノード)。地図・エディタ・
輸出は正典を直接読むので、群馬の設備が「中部」と着色される実害が残っていた。
混在県(長野・新潟・静岡)は #42 の担当で、ここでは触らない。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / "docs" / "data" / "built" / "all.json"


def _plan():
    from src.powerflow.region_attribution import plan_uniform_freq_flips
    return plan_uniform_freq_flips


def test_plan_only_touches_uniform_frequency_prefectures():
    """混在県のノードは計画に入らない(#42 の担当・#6 のガード維持)。"""
    from src.powerflow.region_attribution import prefecture_of
    nodes = [
        # 群馬(50Hz 一意)座標なのに region=chubu → 是正対象
        {"id": "a", "lat": 36.3900, "lon": 139.0600, "kv": 66.0, "region": "chubu"},
        # 長野(混在県)座標で region=tokyo → 触らない
        {"id": "b", "lat": 36.3480, "lon": 138.5960, "kv": 66.0, "region": "tokyo"},
        # 既に正しい
        {"id": "c", "lat": 35.6900, "lon": 139.7000, "kv": 66.0, "region": "tokyo"},
    ]
    assert prefecture_of(36.39, 139.06) == "群馬県"
    p = _plan()(nodes, [])
    assert set(p["plan"]) == {0}, p["plan"]
    assert p["plan"][0] == "tokyo"


def test_guard_refuses_a_plan_that_adds_island_crossings():
    """島跨ぎエッジが増える計画は適用しない(#42 と同じ切断ガードの考え方)。"""
    from src.powerflow.region_attribution import apply_uniform_freq_flips
    nodes = [{"id": "a", "lat": 36.3900, "lon": 139.0600, "kv": 66.0, "region": "chubu"},
             {"id": "b", "lat": 36.3901, "lon": 139.0601, "kv": 66.0, "region": "chubu"}]
    # a-b は同じ島(west)なので跨がない。a だけ tokyo へ飛ぶと跨ぎが 0→1 に増える
    edges = [{"a": [36.3900, 139.0600], "b": [36.3901, 139.0601], "kv": 66.0}]
    p = _plan()(nodes, edges)
    if p["cross_edges_after"] > p["cross_edges_before"]:
        res = apply_uniform_freq_flips(nodes, edges)
        assert res["applied"] is False
        assert all(n["region"] == "chubu" for n in nodes), "拒否したのに書き換えた"


def test_canon_is_already_flipped_and_the_stage_is_idempotent():
    """正典は適用済みで、再計画が 0 件になる（regen の段として再実行できる）。"""
    if not BUILT.exists():
        pytest.skip("正典が無い")
    with open(BUILT, encoding="utf-8") as f:
        d = json.load(f)
    marked = sum(1 for n in d["nodes"] if n.get("freq_fix") == "intervention38")
    assert marked >= 200, f"#38 の正典化マーカーが少なすぎる: {marked}"
    p = _plan()(d["nodes"], d["edges"])
    assert p["plan"] == {}, f"再計画が残っている: {len(p['plan'])} 件"


def test_ledger_can_reverse_every_flip():
    """帳簿だけで to→from の逆再生ができる（無効化手段の存在）。"""
    led = ROOT / "docs" / "data" / "fragments" / "uniform_freq_ledger.json"
    if not led.exists():
        pytest.skip("帳簿が無い")
    with open(led, encoding="utf-8") as f:
        d = json.load(f)
    assert d["marker"] == "intervention38"
    assert d["cross_edges_after"] <= d["cross_edges_before"]
    for f_ in d["flips"]:
        for k in ("id", "from", "to", "lat", "lon"):
            assert k in f_, f"逆再生に必要なキーが無い: {k}"
        assert f_["from"] != f_["to"]
