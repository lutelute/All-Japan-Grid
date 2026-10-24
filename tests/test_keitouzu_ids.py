"""open-keitouzu の対応表の id を、版の座標と名前から今の正典の id へ引き直す(2026-10-24)。"""
import json
from pathlib import Path

import pytest

from src.topology.keitouzu_ids import IdRebaser, anchor_path, load_anchor, norm_name

ROOT = Path(__file__).resolve().parents[1]
VERSION = "ajg-v1.6.0"


def _node(i, lat, lon, kv, region, name):
    return {"id": i, "lat": lat, "lon": lon, "kv": kv, "region": region, "name": name}


def test_norm_name_drops_company_kv_and_suffix():
    assert norm_name("九州電力 到津変電所") == norm_name("到津変電所 66kV") == "到津"
    assert norm_name("電力設備訓練施設 275kV") != norm_name("北相模変電所 275kV")


def test_name_wins_over_a_closer_other_facility(monkeypatch):
    # 取り直しで重心が 340 m 動いた変電所。18 m 先の別の施設ではなく、同じ名前を選ぶ
    anchor = {"tokyo_sub_20@275": {"lat": 35.53448, "lon": 139.36807, "kv": 275.0,
                                   "region": "tokyo", "name": "北相模変電所 275kV"}}
    monkeypatch.setattr("src.topology.keitouzu_ids.load_anchor", lambda v: anchor)
    nodes = [_node("tokyo_sub_496@275", 35.53464, 139.36809, 275.0, "tokyo", "電力設備訓練施設 275kV"),
             _node("tokyo_sub_535@275", 35.53257, 139.36508, 275.0, "tokyo", "北相模変電所 275kV"),
             _node("tokyo_sub_535@66", 35.53257, 139.36508, 66.0, "tokyo", "北相模変電所 66kV")]
    rb = IdRebaser(nodes)
    assert rb.resolve("tokyo_sub_20@275", VERSION) == "tokyo_sub_535@275"


def test_same_region_twin_preferred(monkeypatch):
    anchor = {"kyushu_sub_1": {"lat": 33.0, "lon": 130.0, "kv": 66.0, "region": "kyushu", "name": "X変電所"}}
    monkeypatch.setattr("src.topology.keitouzu_ids.load_anchor", lambda v: anchor)
    nodes = [_node("chugoku_sub_9@66", 33.0, 130.0, 66.0, "chugoku", "X変電所 66kV"),
             _node("kyushu_sub_7@66", 33.0, 130.0, 66.0, "kyushu", "X変電所 66kV")]
    assert IdRebaser(nodes).resolve("kyushu_sub_1", VERSION) == "kyushu_sub_7@66"


def test_without_anchor_falls_back_to_same_id(monkeypatch):
    monkeypatch.setattr("src.topology.keitouzu_ids.load_anchor", lambda v: {})
    rb = IdRebaser([_node("a", 0.0, 0.0, 66.0, "r", "A")])
    assert rb.resolve("a", "other") == "a" and rb.resolve("zz", "other") is None


@pytest.mark.skipif(not anchor_path(VERSION).exists(), reason="版の座標の表が無い")
def test_anchor_rebases_every_id_onto_the_same_named_node():
    nodes = json.loads((ROOT / "docs/data/built/all.json").read_text(encoding="utf-8"))["nodes"]
    by_id = {n["id"]: n for n in nodes}
    anchor = load_anchor(VERSION)
    rb = IdRebaser(nodes)
    same = 0
    for old, a in anchor.items():
        cur = rb.resolve(old, VERSION)
        assert cur is not None, old
        same += norm_name(a["name"]) == norm_name(by_id[cur].get("name"))
    # 名前が合わないのは表記の違い(多摩/多磨・英語名・括弧の読み)だけ。10-24 時点で 650/657
    assert same >= 0.97 * len(anchor)
