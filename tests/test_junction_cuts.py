"""介入#57(写真で誤接続と分かった分岐点に変圧器を張らない)のゲート。

合成の系統(沖縄の陸の上の座標)で build_island_net を通し、
  - 同じ座標に電圧の違う点がある分岐点: 台帳に無ければ変圧器ができ、台帳にあればできない
  - 1 つの点に電圧の違う線がつながる分岐点: 台帳に無ければ #43a が変圧器を足し、台帳にあれば線を自分の電圧の
    バスへ分けて変圧器を作らない。電圧不明の線は同じ名前の線と同じバスへ
を確かめる。あわせて本物の台帳が正典の変電所でない点だけを指していることを確かめる。
"""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("pandapower")
nx = pytest.importorskip("networkx")

import src.powerflow.full_from_built as F  # noqa: E402
from src.powerflow import junction_cuts as JC  # noqa: E402

LAT, LON = 26.33, 127.80   # 沖縄市のあたり(陸の上。territory の再属性で okinawa のまま)


def _node(lat, lon, kv, name):
    return {"id": f"okinawa_jct_{lat:.4f}:{lon:.4f}:{kv:.0f}", "lat": lat, "lon": lon, "kv": kv, "main": True,
            "deg": 1, "sub": 0, "name": name, "region": "okinawa"}


def _edge(a, b, kv, name):
    return {"a": [a["lat"], a["lon"]], "b": [b["lat"], b["lon"]], "kv": kv, "par": 1, "main": True, "name": name,
            "path": [[a["lat"], a["lon"]], [b["lat"], b["lon"]]]}


def _toy():
    """c1 = 132 kV 線と 66 kV 線が同じ座標を通る(点は電圧ごとに別)。c2 = 132 kV の点に 66 kV の線が 2 本
    (1 本は電圧不明で、名前が 66 kV の線と同じ)がつながる(点は 1 つ)。"""
    c1h, c1l = _node(LAT, LON, 132.0, "c1h"), _node(LAT, LON, 66.0, "c1l")
    a, b = _node(LAT + 0.02, LON, 132.0, "a"), _node(LAT - 0.02, LON, 132.0, "b")
    c = _node(LAT, LON + 0.02, 66.0, "c")
    c2 = _node(LAT + 0.05, LON + 0.03, 132.0, "c2")
    d = _node(LAT + 0.07, LON + 0.03, 132.0, "d")
    e, f = _node(LAT + 0.05, LON + 0.05, 66.0, "e"), _node(LAT + 0.05, LON + 0.01, 0.0, "f")
    nodes = [c1h, c1l, a, b, c, c2, d, e, f]
    edges = [_edge(a, c1h, 132.0, "幹線"), _edge(c1h, b, 132.0, "幹線"), _edge(c1l, c, 66.0, "支線"),
             _edge(d, c2, 132.0, "幹線2"), _edge(c2, e, 66.0, "楠線"), _edge(c2, f, 0.0, "楠線")]
    return nodes, edges


def _ledger(tmp_path, pts):
    p = tmp_path / "junction_misconnects.json"
    p.write_text(json.dumps({"items": [{"no": i, "lat": la, "lon": lo, "adopt": True}
                                       for i, (la, lo) in enumerate(pts)]}), encoding="utf-8")
    return str(p)


def _build(nodes, edges, jc):
    return F.build_island_net("okinawa", json.loads(json.dumps(nodes)), edges, 60.0, {}, junction_cuts=jc,
                              nameplates=None)


def _comp_of(net):
    g = nx.Graph()
    g.add_nodes_from(int(b) for b in net.bus.index)
    for _, r in net.line.iterrows():
        g.add_edge(int(r.from_bus), int(r.to_bus))
    for _, r in net.trafo.iterrows():
        g.add_edge(int(r.hv_bus), int(r.lv_bus))
    names = net.bus["name"]
    comp = {}
    for i, cc in enumerate(nx.connected_components(g)):
        for b in cc:
            comp[str(names[b])] = i
    return comp


def test_without_ledger_both_junctions_get_transformers(tmp_path, monkeypatch):
    nodes, edges = _toy()
    monkeypatch.setattr(JC, "LEDGER_PATH", _ledger(tmp_path, []))
    net, _, st = _build(nodes, edges, True)
    assert st["n_junction_cuts"] == 0
    assert len(net.trafo) == 2                       # c1 の同じ座標の変圧器 + c2 の #43a
    assert st["n_implicit_stepdown"] == 1
    comp = _comp_of(net)
    assert comp["a"] == comp["c"]                     # c1: 132 kV と 66 kV が変圧器でつながる
    assert comp["d"] == comp["e"] == comp["f"]        # c2: #43a の変圧器でつながる


def test_ledger_points_get_no_transformer_and_lines_keep_their_voltage(tmp_path, monkeypatch):
    nodes, edges = _toy()
    monkeypatch.setattr(JC, "LEDGER_PATH", _ledger(tmp_path, [(LAT, LON), (LAT + 0.05, LON + 0.03)]))
    net, _, st = _build(nodes, edges, True)
    assert st["n_junction_cuts"] == 2
    assert len(net.trafo) == 0 and st["n_implicit_stepdown"] == 0
    comp = _comp_of(net)
    assert comp["a"] == comp["b"] != comp["c"]        # 132 kV の線は続き、66 kV の線とは切れる
    assert comp["d"] != comp["e"]                     # c2: 66 kV の線は 132 kV の点から分かれる
    assert comp["e"] == comp["f"]                     # 電圧不明の「楠線」は同じ名前の 66 kV の線と同じバス
    led = {r["lat"]: r for r in st["junction_cuts_ledger"]}
    r2 = led[round(LAT + 0.05, 5)]
    assert r2["created"] == [{"bus": r2["created"][0]["bus"], "kv": 66.0}]
    assert sorted(m["name"] for m in r2["moved"]) == ["楠線", "楠線"]
    # 線の本数は変わらない(変圧器を消すだけ)
    net0, _, _ = _build(nodes, edges, False)
    assert len(net.line) == len(net0.line)


def test_flag_off_is_the_old_builder(tmp_path, monkeypatch):
    nodes, edges = _toy()
    monkeypatch.setattr(JC, "LEDGER_PATH", _ledger(tmp_path, [(LAT, LON)]))
    net_off, _, st_off = _build(nodes, edges, False)
    monkeypatch.setattr(JC, "LEDGER_PATH", _ledger(tmp_path, []))
    net_empty, _, _ = _build(nodes, edges, True)
    assert st_off["n_junction_cuts"] == 0
    assert len(net_off.bus) == len(net_empty.bus) and len(net_off.trafo) == len(net_empty.trafo)


def test_real_ledger_points_are_canon_junctions():
    """当てる点は正典で変電所でない点(sub=1 が無い)。外した点には理由がある。"""
    pts = JC.load_cut_points()
    assert len(pts) == 13          # 写真と OSM の way で確かめた 17 か所のうち、推し量りの見かけ 3・変圧器の無い写し 1 を除く
    with open(JC.LEDGER_PATH, encoding="utf-8") as fh:
        allit = json.load(fh)["items"]
    assert all(it["kind"] in ("crossing", "duplicate") for it in pts.values())
    assert all(it.get("not_adopted_why") for it in allit if not it["adopt"])
    with open(F.BUILT, encoding="utf-8") as fh:
        db = json.load(fh)
    at = {}
    for n in db["nodes"]:
        at.setdefault((round(n["lat"], 5), round(n["lon"], 5)), []).append(n)
    for c, it in pts.items():
        here = at.get(c, [])
        assert here, it["no"]
        assert not any(n.get("sub") == 1 for n in here), it["no"]
        assert len(it["kvs"]) >= 2
        assert os.path.basename(it["photo"]).startswith(it["region"])


def test_unknown_kv_override_from_ledger(tmp_path, monkeypatch):
    """台帳の点ごとの指定(unknown_kv)が、同じ名前・一番高い電圧の決まりより先に効く。"""
    nodes, edges = _toy()
    edges = [dict(e, name=("新城線" if e["name"] == "楠線" and not e["kv"] else e["name"])) for e in edges]
    p = tmp_path / "jm.json"
    p.write_text(json.dumps({"items": [{"no": 2, "lat": LAT + 0.05, "lon": LON + 0.03, "adopt": True,
                                        "unknown_kv": {"新城線": 66.0}}]}), encoding="utf-8")
    monkeypatch.setattr(JC, "LEDGER_PATH", str(p))
    net, _, st = _build(nodes, edges, True)
    comp = _comp_of(net)
    assert comp["e"] == comp["f"] != comp["d"]        # 指定どおり 66 kV の側へ
    p.write_text(json.dumps({"items": [{"no": 2, "lat": LAT + 0.05, "lon": LON + 0.03, "adopt": True}]}),
                 encoding="utf-8")
    net2, _, _ = _build(nodes, edges, True)
    comp2 = _comp_of(net2)
    assert comp2["d"] == comp2["f"] != comp2["e"]     # 指定が無ければ一番高い電圧(132 kV)の側へ
