"""介入#35 の追記(2026-11-09): 線の上の双子。

完全双子が 1 つしかない東の切れ端でも、残りの分岐点が西の線の頂点の上にあり、切れ端の線がすべて西の線の
上にあれば、点と線を消す(佐久の勝間~小海町変電所線の東京の写し)。作り物の小さな正典で確かめる。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import apply_node_hygiene as h  # noqa: E402


def _node(i, lat, lon, region, name=None, sub=0, kv=77.0):
    return {"id": i, "lat": lat, "lon": lon, "kv": kv, "main": True, "deg": 1, "sub": sub,
            "name": name or f"{region} junction {lat}:{lon}:77", "region": region}


def _edge(a, b, path=None, name="線", kv=77.0):
    return {"a": list(a), "b": list(b), "path": [list(p) for p in (path or [a, b])], "kv": kv, "name": name}


# 西(中部): 変電所 A — 頂点 v1, v2, v3 — 変電所 B の 1 本の線と、A — C の線(本系統)
A, B, C = (36.0, 138.0), (36.0, 138.4), (36.2, 138.0)
V1, V2, V3 = (36.0, 138.1), (36.0, 138.2), (36.0, 138.3)
# 東(東京): 本系統は群馬側に 3 点
E1, E2, E3 = (36.5, 139.0), (36.5, 139.1), (36.6, 139.1)


def _canon(fragment_on_path=True):
    nodes = [_node("chubu_sub_A", *A, "chubu", "A変電所", sub=1), _node("chubu_sub_B", *B, "chubu", "B変電所", sub=1),
             _node("chubu_sub_C", *C, "chubu", "C変電所", sub=1),
             _node("tokyo_sub_E1", *E1, "tokyo", "E1変電所", sub=1), _node("tokyo_sub_E2", *E2, "tokyo", "E2変電所", sub=1),
             _node("tokyo_sub_E3", *E3, "tokyo", "E3変電所", sub=1)]
    edges = [_edge(A, B, [A, V1, V2, V3, B], "A~B線"), _edge(A, C, None, "A~C線"),
             _edge(E1, E2, None, "E1~E2線"), _edge(E2, E3, None, "E2~E3線")]
    # 東の切れ端: B と同じ座標の東京の変電所 T と、線の頂点の上の分岐点 J。T—J は西の線の一部の写し
    jx = V2 if fragment_on_path else (36.05, 138.2)
    nodes += [_node("tokyo_sub_T", *B, "tokyo", "B変電所_2", sub=1), _node("tokyo_jct_J", *jx, "tokyo")]
    edges += [_edge(jx, B, [jx, V3, B] if fragment_on_path else [jx, B], "A~B線")]
    return {"nodes": nodes, "edges": edges}


def _run(tmp_path, monkeypatch, canon, *flags):
    (tmp_path / "docs/data/built").mkdir(parents=True)
    (tmp_path / "docs/data/fragments").mkdir(parents=True)
    p = tmp_path / "docs/data/built/all.json"
    p.write_text(json.dumps(canon, ensure_ascii=False))
    monkeypatch.setattr(h, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["apply_node_hygiene.py", "--write", "--no-mixed-pref", "--no-freq-fix", *flags])
    h.main()
    return json.loads(p.read_text())


def test_fragment_on_twin_line_is_removed(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, _canon())
    ids = {n["id"] for n in out["nodes"]}
    assert "tokyo_sub_T" not in ids and "tokyo_jct_J" not in ids
    # 西の点と線、東の本系統はそのまま
    assert {"chubu_sub_A", "chubu_sub_B", "chubu_sub_C", "tokyo_sub_E1"} <= ids
    assert sorted(e["name"] for e in out["edges"]) == ["A~B線", "A~C線", "E1~E2線", "E2~E3線"]
    led = json.loads((tmp_path / "docs/data/fragments/node_hygiene_ledger.json").read_text())
    assert [f.get("kind") for f in led["fragments"]] == ["on_path_twin"]
    assert [e.get("why") for e in led["removed_edges"]] == ["on_path_twin"]


def test_switch_off_keeps_fragment(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, _canon(), "--no-on-path-twins")
    assert {"tokyo_sub_T", "tokyo_jct_J"} <= {n["id"] for n in out["nodes"]}
    assert len(out["edges"]) == 5


def test_junction_off_twin_line_is_kept(tmp_path, monkeypatch):
    """分岐点が西の線の頂点の上に無ければ、同じ線の写しと言えないので消さない。"""
    out = _run(tmp_path, monkeypatch, _canon(fragment_on_path=False))
    assert {"tokyo_sub_T", "tokyo_jct_J"} <= {n["id"] for n in out["nodes"]}
    assert len(out["edges"]) == 5


@pytest.mark.parametrize("env,expect", [("0", False), ("1", True)])
def test_env_default(monkeypatch, env, expect):
    import importlib
    monkeypatch.setenv("AJG_HYGIENE_ON_PATH", env)
    m = importlib.reload(h)
    assert m.ON_PATH_DEFAULT is expect
    monkeypatch.delenv("AJG_HYGIENE_ON_PATH")
    importlib.reload(h)
