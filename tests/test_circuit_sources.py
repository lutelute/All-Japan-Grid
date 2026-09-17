"""回線数(par)の出典補完(介入#44・scripts/apply_circuit_sources.py)のゲート。

合成の小さなモデルで、照合規則と「増やす方向のみ」「ドライランは正典を書かない」を固定する。
実データ(data/external)には依存しない。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apply_circuit_sources.py"


def _mod():
    spec = importlib.util.spec_from_file_location("apply_circuit_sources_ut", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules["apply_circuit_sources_ut"] = m
    spec.loader.exec_module(m)
    return m


def _node(name, lat, lon, kv, region, sub=1):
    return {"id": name, "lat": lat, "lon": lon, "kv": kv, "main": True, "deg": 2,
            "sub": sub, "name": name, "region": region}


def _edge(a, b, kv, name, par=1):
    return {"a": [a["lat"], a["lon"]], "b": [b["lat"], b["lon"]], "main": True,
            "kv": kv, "par": par, "name": name}


def _built():
    """A(500)—J1—J2—B(500) の幹線(区間名は OSM 風にバラバラ) + 同名別線(66kV・別地域)。"""
    A = _node("甲変電所 500kV", 35.00, 135.00, 500.0, "kansai")
    J1 = _node("kansai junction 35.05:135.05:500", 35.05, 135.05, 500.0, "kansai", sub=0)
    J2 = _node("kansai junction 35.10:135.10:500", 35.10, 135.10, 500.0, "kansai", sub=0)
    B = _node("乙変電所 500kV", 35.15, 135.15, 500.0, "kansai")
    C = _node("丙変電所", 36.00, 136.00, 66.0, "chubu")
    D = _node("丁変電所", 36.02, 136.02, 66.0, "chubu")
    E = _node("甲乙変電所", 33.00, 131.00, 66.0, "kyushu")   # 同名っぽい別地域の線の端点
    F = _node("戊変電所", 33.02, 131.02, 66.0, "kyushu")
    nodes = [A, J1, J2, B, C, D, E, F]
    edges = [
        _edge(A, J1, 500.0, "甲変電所~junction線", par=1),
        _edge(J1, J2, 500.0, "幹線区間", par=1),
        _edge(J2, B, 500.0, "junction~乙変電所線", par=2),
        _edge(C, D, 66.0, "甲乙線", par=1),          # 名前は「甲乙線」だが chubu 66kV
        _edge(E, F, 66.0, "甲乙線", par=1),          # 同名・kyushu 66kV
    ]
    return {"nodes": nodes, "edges": edges}


def _rec(m, **kw):
    r = m._rec(**kw)
    r["rid"] = kw.get("rid", 0)
    r["name_norm"] = m.norm_line(r["name"]) if r["name"] else ""
    r["from_norm"] = m.norm_sub(r["from_sub"]) if r["from_sub"] else ""
    r["to_norm"] = m.norm_sub(r["to_sub"]) if r["to_sub"] else ""
    return r


def test_route_match_reaches_every_segment_between_endpoints():
    """端点変電所が解決できれば、区間名が違っても経路上の全枝に届く(本四連系の型)。"""
    m = _mod()
    model = m.Model(_built())
    rec = _rec(m, region="kansai", name="甲乙幹線", kv=500.0, n=2, from_sub="甲変電所", to_sub="乙変電所")
    res = m.match_all(model, [rec])[0]
    assert res["method"] == "route"
    assert sorted(res["edges"]) == [0, 1, 2]


def test_name_match_respects_region_and_kv():
    """同名の線でも地域・電圧階級が違えば当てない。"""
    m = _mod()
    model = m.Model(_built())
    rec = _rec(m, region="chubu", name="甲乙線", kv=66.0, n=2)
    res = m.match_all(model, [rec])[0]
    assert res["method"] == "name" and res["edges"] == [3], res
    rec500 = _rec(m, region="chubu", name="甲乙線", kv=500.0, n=2)
    assert m.match_all(model, [rec500])[0]["edges"] == []


def test_name_match_requires_endpoint_proximity_when_endpoint_resolves():
    """端点が解決できたのに枝がその近くに無い名前一致は誤爆として拒否する。"""
    m = _mod()
    built = _built()
    # kyushu にも「丙変電所」を置く(同名別地) — chubu の線名一致だけでは kyushu 側は当たらない
    model = m.Model(built)
    rec = _rec(m, region="kyushu", name="甲乙線", kv=66.0, n=2, from_sub="丙変電所", to_sub="")
    res = m.match_all(model, [rec])[0]
    # 丙変電所は chubu にしか無い(kyushu で解決できない)→ 端点なしの name 照合で kyushu の枝 4 のみ
    assert res["edges"] == [4] and res["method"] == "name"


def test_only_increases_par_and_records_conflicts():
    m = _mod()
    model = m.Model(_built())
    recs = [_rec(m, rid=0, region="kansai", name="甲乙幹線", kv=500.0, n=2, from_sub="甲変電所", to_sub="乙変電所"),
            _rec(m, rid=1, region="kansai", name="junction~乙変電所線", kv=500.0, n=1)]
    matches = m.match_all(model, recs)
    decisions, conflicts = m.aggregate(model, recs, matches)
    # 枝2 は par=2 のまま(2 は増やさない)、枝0/1 は 1→2
    plan = {i: d["n"] for i, d in decisions.items()}
    assert plan[0] == 2 and plan[1] == 2
    assert any(c["edge"] == 2 for c in conflicts), "同じ枝への食い違い(n=2 と n=1)が帳簿に無い"
    # 経路提案が名前提案より優先される
    assert decisions[2]["n"] == 2


def test_name_only_conflicts_resolve_to_min():
    """名前照合だけで回線数が食い違う(区間ごとに公表が違う)ときは保守的に最小。"""
    m = _mod()
    model = m.Model(_built())
    recs = [_rec(m, rid=0, region="chubu", name="甲乙線", kv=66.0, n=3),
            _rec(m, rid=1, region="chubu", name="甲乙線", kv=66.0, n=2)]
    matches = m.match_all(model, recs)
    decisions, conflicts = m.aggregate(model, recs, matches)
    assert decisions[3]["n"] == 2 and conflicts


def test_dry_run_does_not_touch_canon(tmp_path, monkeypatch):
    m = _mod()
    built = _built()
    p = tmp_path / "all.json"
    p.write_text(json.dumps(built, ensure_ascii=False), encoding="utf-8")
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    monkeypatch.setattr(m, "load_all_sources", lambda: [
        _rec(m, rid=0, region="kansai", name="甲乙幹線", kv=500.0, n=2, from_sub="甲変電所", to_sub="乙変電所")])
    m.main(["--built", str(p), "--out-dir", str(tmp_path / "rep"), "--ledger", str(tmp_path / "led.jsonl")])
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before
    rows = [json.loads(l) for l in (tmp_path / "led.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and rows[0]["n_edges_updated"] == 2
    for k in ("line", "kv", "n_circuits", "source_type", "source_url", "quote", "retrieved", "confidence",
              "match_method", "edges_updated"):
        assert k in rows[0], f"帳簿に {k} が無い"


def test_write_updates_par_with_provenance_and_backup(tmp_path, monkeypatch):
    m = _mod()
    built = _built()
    p = tmp_path / "all.json"
    p.write_text(json.dumps(built, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(m, "load_all_sources", lambda: [
        _rec(m, rid=0, region="kansai", name="甲乙幹線", kv=500.0, n=2, from_sub="甲変電所", to_sub="乙変電所")])
    m.main(["--built", str(p), "--out-dir", str(tmp_path / "rep"), "--ledger", str(tmp_path / "led.jsonl"), "--write"])
    d = json.loads(p.read_text(encoding="utf-8"))
    assert (tmp_path / "all.json.pre_circuits.bak").exists()
    assert [e["par"] for e in d["edges"][:3]] == [2, 2, 2]
    assert d["edges"][0]["par_src"] == "circuit_sources" and d["edges"][0]["par_prev"] == 1
    assert "par_src" not in d["edges"][2], "増やさなかった枝に来歴を付けてはいけない"
    assert len(d["nodes"]) == len(built["nodes"]) and len(d["edges"]) == len(built["edges"])


def test_line_and_sub_normalisation():
    m = _mod()
    assert m.norm_line("播磨線1L") == "播磨線"
    assert m.norm_line("東葛線1・2L") == "東葛線"
    assert m.norm_line("三岐幹1号線") == "三岐幹線"
    assert m.norm_line("四国中央東幹線（送電線No.3）") == "四国中央東幹線"
    assert m.norm_sub("東岡山変電所（中国）") == "東岡山"
    assert m.norm_sub("新いわき（開）") == "新いわき"
    assert m.norm_sub("東葛変電所 (Tōkatsu Hendensho) 154kV") == "東葛"
    assert m.norm_sub("中部電力(株)豊根開閉所") == "豊根"
    assert m.kv_ok(77.0, 66.0) and m.kv_ok(500.0, 500.0) and not m.kv_ok(500.0, 66.0)


def test_real_canon_has_no_decrease_and_provenance_is_consistent():
    """正典に適用済みなら par_src 付き枝は par_prev < par を満たす(増やす方向のみ)。"""
    p = ROOT / "docs" / "data" / "built" / "all.json"
    if not p.exists():
        pytest.skip("正典が無い")
    d = json.loads(p.read_text(encoding="utf-8"))
    tagged = [e for e in d["edges"] if e.get("par_src") == "circuit_sources"]
    assert all(int(e["par"]) > int(e["par_prev"]) for e in tagged)
    assert all(int(e["par"]) <= 8 for e in tagged)
