"""断片解消キャンペーン第三波(scripts/hunt_fragment_third_wave.py)の構造ゲート。

合成データ(数ノード・数way)で、
  (a) 継ぎ目閾値ごとの回収 — 継ぎ目 150m の連鎖は 120m 段では拾わず 200m 段で拾う
  (b) 電圧整合ゲート — 500kV way は 66kV 断片を繋がない
  (c) 迂回係数ゲート — 実線長が直線距離の 1.5 倍を超える連鎖は棄却
  (d) 島跨ぎを作らない — 別島にも同座標ノードがある断片(登録人工物)は回収しない・
      周波数跨ぎ枝の数が仮適用で増えない
  (e) ドライランが正典を書かない — --write 無しで built ファイルのハッシュが不変
を固定する。実データ依存は無し(速い)。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "hunt_fragment_third_wave.py"


def _mod():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("frag3_ut", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


LAT0, LON0 = 35.0, 137.0
DEG_KM_LAT = 1 / 111.0                      # 1km あたりの緯度


def _node(lat, lon, kv=66.0, region="chubu", name=None, sub=1):
    return {"id": f"{region}_{lat}_{lon}", "lat": lat, "lon": lon, "kv": kv,
            "region": region, "name": name or f"{region} sub {lat:.4f}", "sub": sub,
            "main": False, "deg": 1}


def _way(coords_latlon, kv=66.0, name="way"):
    return {"type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[lo, la] for la, lo in coords_latlon]},
            "properties": {"_voltage_kv": kv, "_display_name": name}}


def _built(seam_km: float, frag_kv=66.0, way_kv=66.0, detour=False,
           twin_region=None):
    """本系統 3 ノード(縦に並ぶ)と、東へ 2km の断片 1 ノード。

    断片 → way1(東西 1km) →継ぎ目 seam_km→ way2(残り) → 本系統ノード。
    detour=True なら way2 が大きく南へ迂回する(実線長 > 直線×1.5)。
    """
    m0 = _node(LAT0, LON0, name="main A")
    m1 = _node(LAT0 + 1.0 * DEG_KM_LAT, LON0, name="main B")
    m2 = _node(LAT0 + 2.0 * DEG_KM_LAT, LON0, name="main C")
    lon_km = 1 / (111.0 * 0.8192)           # cos(35°)
    frag = _node(LAT0, LON0 + 2.0 * lon_km, kv=frag_kv, name="frag X")
    nodes = [m0, m1, m2, frag]
    if twin_region:
        nodes.append(_node(LAT0, LON0 + 2.0 * lon_km, kv=frag_kv,
                           region=twin_region, name="frag X twin"))
    edges = [{"a": [m0["lat"], m0["lon"]], "b": [m1["lat"], m1["lon"]], "kv": 66.0},
             {"a": [m1["lat"], m1["lon"]], "b": [m2["lat"], m2["lon"]], "kv": 66.0}]
    # way1: 断片から西へ 1km。way2: 継ぎ目 seam を空けて本系統 A へ
    w1 = _way([(LAT0, LON0 + 2.0 * lon_km), (LAT0, LON0 + 1.0 * lon_km)],
              kv=way_kv, name="way1")
    start2 = (LAT0, LON0 + 1.0 * lon_km - seam_km * lon_km)
    if detour:
        w2 = _way([start2, (LAT0 - 3.0 * DEG_KM_LAT, LON0 + 0.5 * lon_km),
                   (LAT0, LON0)], kv=way_kv, name="way2 detour")
    else:
        w2 = _way([start2, (LAT0, LON0)], kv=way_kv, name="way2")
    return {"nodes": nodes, "edges": edges}, [w1, w2]


def _chains_at(m, built, lines, seam_m, **kw):
    rep = m.run(built, lines, seam_stages_m=(seam_m,), disclosure_names=set(),
                verbose=False, **kw)
    return rep["islands"]["west"]["stages"][str(seam_m)], rep


def test_seam_threshold_controls_recovery():
    """(a) 継ぎ目 150m は 120m 段で拾わず、200m 段で拾う。"""
    m = _mod()
    built, lines = _built(seam_km=0.15)
    s120, _ = _chains_at(m, built, lines, 120)
    s200, rep = _chains_at(m, built, lines, 200)
    assert s120["chains"] == 0 and s120["rejected"].get("unreachable") == 1
    assert s200["chains"] == 1 and s200["nodes_joined"] == 1
    assert s200["components_after"] == 0
    c = rep["chains"][0]
    assert c["n_ways"] == 2 and 120 < c["max_seam_m"] <= 200


def test_voltage_gate_rejects_mismatched_way():
    """(b) 500kV の way は 66kV 断片を繋がない(併架・並走回廊の偶然接触)。"""
    m = _mod()
    built, lines = _built(seam_km=0.05, way_kv=500.0)
    s, _ = _chains_at(m, built, lines, 60)
    assert s["chains"] == 0


def test_detour_gate_rejects_roundabout_chain():
    """(c) 実線長が直線の 1.5 倍を超える連鎖は棄却、閾値を緩めれば通る。"""
    m = _mod()
    built, lines = _built(seam_km=0.05, detour=True)
    s, _ = _chains_at(m, built, lines, 60)
    assert s["chains"] == 0 and s["rejected"].get("detour") == 1
    s2, rep = _chains_at(m, built, lines, 60, detour_max=10.0)
    assert s2["chains"] == 1 and rep["chains"][0]["detour"] > 1.5


def test_cross_island_twin_fragment_is_not_recovered():
    """(d) 別島(tokyo=east)にも同座標ノードがある断片は回収せず再属性へ回す。"""
    m = _mod()
    built, lines = _built(seam_km=0.05, twin_region="tokyo")
    s, rep = _chains_at(m, built, lines, 60)
    assert s["chains"] == 0 and s["rejected"].get("twin_cross_island") == 1
    assert rep["islands"]["west"]["residual_classes"].get("c_cross_island_twin") == 1


def test_freq_crossing_edges_do_not_increase_on_apply():
    """(d) 仮適用の候補枝は同一島内なので周波数跨ぎ枝の数は不変。"""
    m = _mod()
    built, lines = _built(seam_km=0.05)
    rep = m.run(built, lines, seam_stages_m=(60,), disclosure_names=set(), verbose=False)
    before = rep["freq_crossing_edges_before"]
    chains = rep["_paths"]["west"][60]
    test_edges = built["edges"] + [{"a": list(c["fk"]), "b": list(c["mk"])} for c in chains]
    assert len(chains) == 1
    assert m.freq_crossing_edges(built["nodes"], test_edges) == before


def test_dry_run_does_not_write_canon(tmp_path):
    """(e) --write 無しでは built ファイルは 1 バイトも変わらない(帳簿だけ出る)。"""
    m = _mod()
    built, lines = _built(seam_km=0.15)
    bp, lp = tmp_path / "all.json", tmp_path / "lines.geojson"
    bp.write_text(json.dumps(built, ensure_ascii=False), encoding="utf-8")
    lp.write_text(json.dumps({"type": "FeatureCollection", "features": lines},
                             ensure_ascii=False), encoding="utf-8")
    h0 = hashlib.sha256(bp.read_bytes()).hexdigest()
    rc = m.main(["--built", str(bp), "--lines", str(lp), "--out-dir", str(tmp_path / "rep"),
                 "--date", "2000-01-01", "--seam-m", "200"])
    assert rc == 0
    assert hashlib.sha256(bp.read_bytes()).hexdigest() == h0, "ドライランが正典を書いた"
    assert (tmp_path / "rep" / "fragment_third_wave_2000-01-01.json").exists()
    assert (tmp_path / "rep" / "same_site_proposals_2000-01-01.yaml").exists()
    rep = json.loads((tmp_path / "rep" / "fragment_third_wave_2000-01-01.json").read_text())
    assert rep["apply_candidates"] == 1 and "_paths" not in rep


def test_write_appends_marked_edges_with_backup(tmp_path):
    """--write は recovery=osm_chain3 の枝を追記し、バックアップを残す(親専用の経路)。"""
    m = _mod()
    built, lines = _built(seam_km=0.15)
    bp, lp = tmp_path / "all.json", tmp_path / "lines.geojson"
    bp.write_text(json.dumps(built, ensure_ascii=False), encoding="utf-8")
    lp.write_text(json.dumps({"type": "FeatureCollection", "features": lines},
                             ensure_ascii=False), encoding="utf-8")
    rc = m.main(["--built", str(bp), "--lines", str(lp), "--out-dir", str(tmp_path / "rep"),
                 "--date", "2000-01-01", "--seam-m", "200", "--write"])
    assert rc == 0
    after = json.loads(bp.read_text(encoding="utf-8"))
    added = [e for e in after["edges"] if e.get("recovery") == "osm_chain3"]
    assert len(added) == 1 and len(added[0]["path"]) >= 3
    assert (tmp_path / "all.json.pre_frag3.bak").exists()


def test_same_site_requires_name_base_and_distance():
    """(b) 名前基底一致+300m 以内だけが提案になり、kv 不整合は kv_ok=false で残る。"""
    m = _mod()
    lon_km = 1 / (111.0 * 0.8192)
    a = _node(LAT0, LON0, kv=154.0, name="岡崎変電所")
    b = _node(LAT0 + 1.0 * DEG_KM_LAT, LON0, kv=154.0, name="main B")
    frag_near = _node(LAT0, LON0 + 0.2 * lon_km, kv=66.0, name="岡崎変電所_2")
    frag_far = _node(LAT0, LON0 + 2.0 * lon_km, kv=154.0, name="岡崎変電所_3")
    built = {"nodes": [a, b, frag_near, frag_far],
             "edges": [{"a": [a["lat"], a["lon"]], "b": [b["lat"], b["lon"]]}]}
    keys, comps = m.island_components(built["nodes"], built["edges"], "west")
    ss = m.same_site_candidates("west", keys, comps)
    assert [s["frag_name"] for s in ss] == ["岡崎変電所_2"]
    assert ss[0]["kv_ok"] is False and ss[0]["dist_m"] <= 300

def test_twin_on_main_endpoint_is_rejected():
    """(d) 本系統側の接触点に別島の同座標ノードがあっても回収しない(跨ぎ枝を増やさない)。"""
    m = _mod()
    built, lines = _built(seam_km=0.05)
    a = built["nodes"][0]                      # main A = 接触点
    built["nodes"].append(_node(a["lat"], a["lon"], region="tokyo", name="main A twin"))
    s, rep = _chains_at(m, built, lines, 60)
    assert s["chains"] == 0 and s["rejected"].get("twin_endpoint") == 1
    # 仮適用しても周波数跨ぎ枝は増えない(候補が無い)
    assert rep["freq_crossing_edges_before"] == m.freq_crossing_edges(
        built["nodes"], built["edges"])
