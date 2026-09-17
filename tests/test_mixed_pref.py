"""介入#42 混在県個別化(2026-09-02)のゲート。

#6/#38 の周波数ガードは混在県(長野・新潟・静岡)の跨ぎ候補を県単位で全部保持していた。
#42 は境界資産(保護域ポリゴン・富士川実河道)+ホワイトリスト(FC・越境幹線)+切断ガード
(仮適用で新規の島跨ぎエッジが生じるフリップを拒否して反復)で、守るべきものだけを守って
残りを領土で再属性する。ここで固定するのは**構造的な主張**:
  (a) 保護域内は動かない (b) 越境幹線/FC に接するノードは拒否
  (c) 切断ガードが新規跨ぎを 0 にする (d) 静岡は富士川実河道で東西判定
  (e) edges 無しでは無効化して警告(黙ってガード無しで適用しない)
  (f) 監査スクリプトは本体へ委譲している(実装二重化の禁止)
実データ(built)の検収は built が無ければ skip。
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from src.powerflow.region_attribution import (
    MIXED_PREF_MARK,
    apply_mixed_pref_flips,
    area_of_coord,
    fujikawa_lon_at,
    in_protected_zone,
    plan_mixed_pref_flips,
    prefecture_of,
    reattribute_node_regions,
    shizuoka_side,
)

ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / "docs" / "data" / "built" / "all.json"
AUDIT = ROOT / "scripts" / "audit_mixed_pref_flip.py"

# 検証済み座標(2026-09-02 実測: prefecture_of / in_protected_zone / shizuoka_side)
MATSUMOTO = (36.238, 137.972)     # 長野・保護域(一次: 中部電力50Hz資料+N03)
IIDA = (35.515, 137.821)          # 長野・非保護(60Hz 中部電力エリア)
INA = (35.828, 137.954)           # 長野・非保護
MYOKO = (36.89, 138.25)           # 新潟・保護(60Hz 飛び地)
JOETSU = (37.148, 138.236)        # 新潟・非保護(50Hz 東北電力エリア)
NUMAZU = (35.10, 138.86)          # 静岡・富士川以東(東京電力50Hz)
HAMAMATSU = (34.71, 137.73)       # 静岡・富士川以西(中部電力60Hz)
FUJINOMIYA_UP = (35.30, 138.60)   # 静岡・上流: 定数138.62では西だが実河道(138.537)では東
MAEBASHI = (36.39, 139.06)        # 群馬・一意50Hz県


def _node(coord, region, name=None, **kw):
    lat, lon = coord
    d = {"lat": lat, "lon": lon, "region": region, "kv": 66.0, "sub": 1,
         "name": name or f"n{lat:.3f}:{lon:.3f}"}
    d.update(kw)
    return d


def _edge(n1, n2, name=None):
    return {"a": [n1["lat"], n1["lon"]], "b": [n2["lat"], n2["lon"]],
            "kv": 66.0, "name": name}


def test_coordinates_are_what_the_test_assumes():
    """座標の前提(県・領土エリア・保護域・河道側)が動いたらここで分かる。"""
    assert prefecture_of(*MATSUMOTO) == "長野県" and in_protected_zone("長野県", *MATSUMOTO)
    assert prefecture_of(*IIDA) == "長野県" and not in_protected_zone("長野県", *IIDA)
    assert prefecture_of(*MYOKO) == "新潟県" and in_protected_zone("新潟県", *MYOKO)
    assert prefecture_of(*JOETSU) == "新潟県" and not in_protected_zone("新潟県", *JOETSU)
    assert area_of_coord(*IIDA) == "chubu" and area_of_coord(*JOETSU) == "tohoku"
    assert prefecture_of(*NUMAZU) == "静岡県" and shizuoka_side(*NUMAZU) == "tokyo"
    assert prefecture_of(*HAMAMATSU) == "静岡県" and shizuoka_side(*HAMAMATSU) == "chubu"
    assert prefecture_of(*MAEBASHI) == "群馬県"


# ── (a) 保護域 ────────────────────────────────────────────────────────────
def test_protected_zone_nodes_are_not_flipped():
    nodes = [_node(MATSUMOTO, "tokyo", "松本市内50Hz変電所"),   # 東京電力PG 供給域
             _node(MYOKO, "chubu", "妙高60Hz変電所")]           # 新潟の60Hz飛び地
    mp = plan_mixed_pref_flips(nodes, [])
    assert mp["plan"] == {}
    assert mp["kept"] == {0: "protected_zone", 1: "protected_zone"}
    assert len(mp["guarded"]) == 2


def test_unprotected_mixed_pref_nodes_are_reattributed_by_territory():
    nodes = [_node(IIDA, "tokyo", "飯田の抽出こぼれ"),        # 長野南信: 60Hz 中部
             _node(JOETSU, "chubu", "上越の抽出こぼれ")]      # 新潟上越: 50Hz 東北
    res = apply_mixed_pref_flips(nodes, [])
    assert res["applied"] is True
    assert nodes[0]["region"] == "chubu" and nodes[0]["region_src"] == "tokyo"
    assert nodes[1]["region"] == "tohoku" and nodes[1]["region_src"] == "chubu"
    assert nodes[0]["mixed_pref"] == MIXED_PREF_MARK
    assert res["fixed"] == {"tokyo->chubu": 1, "chubu->tohoku": 1}
    # 冪等: 2回目は何も動かない
    res2 = apply_mixed_pref_flips(nodes, [])
    assert res2["fixed"] == {} and res2["plan"]["guarded"] == []


# ── (b) ホワイトリスト ────────────────────────────────────────────────────
def test_whitelisted_corridor_and_fc_nodes_are_vetoed():
    fc = _node(IIDA, "tokyo", "新信濃変電所")                # FC 名 → 固定
    corr = _node(INA, "tokyo", "伊那の50Hz junction")
    far = _node(MAEBASHI, "tokyo", "前橋側")
    edges = [_edge(corr, far, name="安曇幹線")]              # 越境幹線に接する
    mp = plan_mixed_pref_flips([fc, corr, far], edges)
    assert mp["plan"] == {}
    assert mp["veto_whitelist"][0].startswith("FC固定")
    assert mp["veto_whitelist"][1].startswith("越境幹線")


# ── (c) 切断ガード ────────────────────────────────────────────────────────
def test_crossing_guard_vetoes_flips_that_would_cut_the_island():
    """飯田(長野・非保護)の tokyo ノードが前橋(50Hz)と無名線で繋がっている:
    chubu(60Hz) へ倒すとその線が新規の島跨ぎになる → 拒否。"""
    a = _node(IIDA, "tokyo", "飯田側")
    b = _node(MAEBASHI, "tokyo", "前橋側")
    edges = [_edge(a, b, name="無名66kV線")]
    mp = plan_mixed_pref_flips([a, b], edges)
    assert mp["plan"] == {}
    assert 0 in mp["veto_crossing"]
    assert mp["new_cross_edges"] == 0 and mp["pre_cross_edges"] == 0


def test_pre_existing_cross_edges_are_left_alone_and_not_counted_as_new():
    """既に跨いでいる線(130本の類)は触らず、新規切断にも数えない。"""
    a = _node(IIDA, "tokyo", "飯田側")
    b = _node(HAMAMATSU, "chubu", "浜松側")        # 既に 50/60 跨ぎ
    edges = [_edge(a, b, name="既存跨ぎ線")]
    mp = plan_mixed_pref_flips([a, b], edges)
    assert mp["pre_cross_edges"] == 1
    assert mp["plan"] == {0: "chubu"}             # 倒しても跨ぎは増えない(むしろ消える)
    assert mp["new_cross_edges"] == 0


def test_guard_iterates_until_no_new_cross_edge_remains():
    """フリップ同士が連鎖する場合も収束時点で新規跨ぎ 0(検収値で保証)。"""
    a = _node(IIDA, "tokyo", "飯田A")
    c = _node(INA, "tokyo", "伊那C")
    b = _node(MAEBASHI, "tokyo", "前橋B")
    edges = [_edge(a, c, name="A-C"), _edge(c, b, name="C-B")]
    mp = plan_mixed_pref_flips([a, c, b], edges)
    # C は B(50Hz固定) と繋がるので拒否 → 次に A は C(tokyo のまま) と繋がるので拒否
    assert mp["plan"] == {} and mp["new_cross_edges"] == 0
    assert set(mp["veto_crossing"]) == {0, 1}


# ── (d) 静岡 = 富士川実河道 ───────────────────────────────────────────────
def test_shizuoka_is_split_by_the_real_fujikawa_channel():
    east = _node(NUMAZU, "chubu", "沼津の抽出こぼれ")
    west = _node(HAMAMATSU, "tokyo", "浜松の抽出こぼれ")
    res = apply_mixed_pref_flips([east, west], [])
    assert east["region"] == "tokyo" and west["region"] == "chubu"
    assert res["fixed"] == {"chubu->tokyo": 1, "tokyo->chubu": 1}


def test_river_side_and_territory_disagreement_is_kept_guarded():
    """上流で河道が定数(138.62)より西へ振れる地点: 実河道=東(tokyo)・領土定数=西(chubu)。
    判定が食い違う点は**動かさない**(保守的)。"""
    assert fujikawa_lon_at(FUJINOMIYA_UP[0]) < 138.62
    assert shizuoka_side(*FUJINOMIYA_UP) == "tokyo" and area_of_coord(*FUJINOMIYA_UP) == "chubu"
    n = _node(FUJINOMIYA_UP, "tokyo", "富士宮上流")
    mp = plan_mixed_pref_flips([n], [])
    assert mp["plan"] == {} and mp["kept"] == {0: "river_side_mismatch"}


# ── (e) edges 無しは無効化+警告 ──────────────────────────────────────────
def test_reattribute_without_edges_disables_mixed_pref_and_warns():
    nodes = [_node(IIDA, "tokyo", "飯田の抽出こぼれ")]
    with pytest.warns(RuntimeWarning, match="edges"):
        stats = reattribute_node_regions(nodes, mixed_pref=True, edges=None)
    assert nodes[0]["region"] == "tokyo", "ガード無しで適用してはいけない"
    assert stats["skipped_freq"] == {"tokyo->chubu": 1}
    assert stats["mixed_pref_fixed"] == {}
    assert stats["mixed_pref_note"].startswith("disabled")


def test_reattribute_with_edges_applies_and_discloses():
    nodes = [_node(IIDA, "tokyo", "飯田の抽出こぼれ"),
             _node(MATSUMOTO, "tokyo", "松本の50Hz(保護)")]
    with warnings.catch_warnings():
        warnings.simplefilter("error")           # 警告が出てはいけない
        stats = reattribute_node_regions(nodes, mixed_pref=True, edges=[])
    assert nodes[0]["region"] == "chubu" and nodes[1]["region"] == "tokyo"
    assert stats["mixed_pref_fixed"] == {"tokyo->chubu": 1}
    assert stats["mixed_pref_vetoed"]["protected_zone"] == 1
    assert stats["skipped_freq"] == {"tokyo->chubu": 1}   # 松本は #6 ガードのまま開示
    assert stats["changes"]["tokyo->chubu"] == 1 and stats["n_changed"] == 1
    assert stats["mixed_pref_note"] is None


def test_default_is_off_and_old_behaviour_is_unchanged():
    """既定 OFF(正典側で適用済み)。#6 ガード群は従来どおり skipped_freq に残る。"""
    nodes = [_node(IIDA, "tokyo", "飯田の抽出こぼれ")]
    stats = reattribute_node_regions(nodes)
    assert nodes[0]["region"] == "tokyo"
    assert stats["skipped_freq"] == {"tokyo->chubu": 1}
    assert stats["mixed_pref_fixed"] == {} and stats["mixed_pref_note"] is None


# ── (f) 監査スクリプトは本体へ委譲 ──────────────────────────────────────
def test_audit_script_delegates_to_the_body():
    src = AUDIT.read_text(encoding="utf-8")
    assert "plan_mixed_pref_flips(" in src, "本体へ委譲していない"
    for leaked in ("def load_boundary", "def river_lon_at", "prepared import prep",
                   "for _round in range"):
        assert leaked not in src, f"規則の写しが監査スクリプトに戻っている: {leaked}"


def test_hygiene_script_exposes_the_flag_and_delegates():
    src = (ROOT / "scripts" / "apply_node_hygiene.py").read_text(encoding="utf-8")
    assert '"--mixed-pref"' in src and "apply_mixed_pref_flips" in src
    assert "MIXED_PREF_DEFAULT" in src


# ── 実データ検収 ───────────────────────────────────────────────────────────
@pytest.mark.skipif(not BUILT.exists(), reason="built DB が無い")
def test_canon_plan_has_no_new_cross_edge_and_is_idempotent():
    """正典に対する計画は新規跨ぎ 0。適用済み正典なら計画は空(冪等)。"""
    d = json.loads(BUILT.read_text(encoding="utf-8"))
    nodes, edges = d["nodes"], d["edges"]
    mp = plan_mixed_pref_flips(nodes, edges)
    assert mp["new_cross_edges"] == 0
    n_marked = sum(1 for n in nodes if n.get("mixed_pref") == MIXED_PREF_MARK)
    ledger = ROOT / "docs" / "data" / "fragments" / "mixed_pref_ledger.json"
    if n_marked:                                   # 適用済み正典: 再計画は空・帳簿と一致
        assert mp["plan"] == {}, "適用済みなのに再フリップが計画された(冪等性の破れ)"
        assert ledger.exists(), "適用済みなのに帳簿が無い(無効化手段の欠落)"
        led = json.loads(ledger.read_text(encoding="utf-8"))
        assert len(led["flips"]) == n_marked, "帳簿のフリップ数とマーカー数が食い違う"
        for f in led["flips"]:                     # 逆再生に必要な情報が全件揃っている
            assert f["from"] and f["to"] and f["id"]
