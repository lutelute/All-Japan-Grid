#!/usr/bin/env python3
"""混在県個別化(B3)のドライラン監査 — all.json は変更しない(2026-09-02).

現ガード(UNIFORM_FREQ_PREFS)対象の周波数跨ぎ候補ノードに対し、
data/reference/freq_boundary_mixed.geojson(出典つき境界)+
freq_corridor_whitelist.json(越境幹線・FC保護)を適用した場合の
フリップ計画を作り、**島跨ぎ切断が新規に0件**であることを検証する。

拒否の2段構え:
  A) ホワイトリスト: FC名・越境幹線エッジに接するノードは拒否
  B) 切断ガード(硬い保証): 仮適用で新規の島跨ぎエッジが生じる限り、
     関与したフリップを拒否して反復 — 収束時点で新規切断は構造的に0

出力: docs/reports/mixed_pref_flip_audit_<date>.json と標準出力の要約。
Usage: PYTHONPATH=. python3 scripts/audit_mixed_pref_flip.py
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from shapely.geometry import Point, shape
from shapely.prepared import prep

from src.powerflow.region_attribution import (AREA_FREQ, UNIFORM_FREQ_PREFS,
                                              area_of_coord, prefecture_of)

BOUNDARY = "data/reference/freq_boundary_mixed.geojson"
WHITELIST = "data/reference/freq_corridor_whitelist.json"
BUILT = "docs/data/built/all.json"


def load_boundary():
    fc = json.load(open(BOUNDARY, encoding="utf-8"))
    prot = {"長野県": [], "新潟県": []}
    river = None
    for f in fc["features"]:
        p = f["properties"]
        if p["role"].startswith("protected"):
            prot[p["pref"]].append(prep(shape(f["geometry"])))
        elif p["role"] == "boundary_river":
            river = shape(f["geometry"])
    riv_pts = []
    for line in getattr(river, "geoms", [river]):
        riv_pts.extend(line.coords)
    riv_pts.sort(key=lambda xy: xy[1])          # 緯度順
    return prot, riv_pts


def river_lon_at(lat, riv_pts):
    """富士川の当該緯度における経度(最近傍頂点・範囲外は端点)."""
    lo, hi = riv_pts[0], riv_pts[-1]
    if lat <= lo[1]:
        return lo[0]
    if lat >= hi[1]:
        return hi[0]
    best = min(riv_pts, key=lambda xy: abs(xy[1] - lat))
    return best[0]


def main() -> int:
    d = json.load(open(BUILT, encoding="utf-8"))
    nodes, edges = d["nodes"], d["edges"]
    wl = json.load(open(WHITELIST, encoding="utf-8"))
    edge_pats = [e["pattern"] for e in wl["edge_name_patterns"]]
    fc_pats = [e["pattern"] for e in wl["fc_node_patterns"]]
    prot, riv_pts = load_boundary()

    # 座標→ノード索引(エッジ端点a/bはノード座標と同精度)
    by_xy = {}
    for i, n in enumerate(nodes):
        by_xy[(round(n["lat"], 5), round(n["lon"], 5))] = i
    inc = {}                                     # node idx -> [edge idx]
    for j, e in enumerate(edges):
        for end in ("a", "b"):
            k = (round(e[end][0], 5), round(e[end][1], 5))
            if k in by_xy:
                inc.setdefault(by_xy[k], []).append(j)

    # ── ガード対象と提案フリップ ──
    guarded, plan = [], {}
    for i, n in enumerate(nodes):
        src = n.get("region")
        area = area_of_coord(float(n["lat"]), float(n["lon"]))
        if not area or area == src:
            continue
        if not (src in AREA_FREQ and AREA_FREQ.get(area) is not None
                and AREA_FREQ[src] != AREA_FREQ[area]):
            continue
        pref = prefecture_of(float(n["lat"]), float(n["lon"]))
        if UNIFORM_FREQ_PREFS.get(pref) == AREA_FREQ[area]:
            continue                             # 介入#38で既に処理済みの群
        guarded.append((i, pref, src, area))
        pt = Point(n["lon"], n["lat"])
        if pref in ("長野県", "新潟県"):
            if any(g.covers(pt) for g in prot[pref]):
                continue                         # 保護ゾーン内 → ガード維持
            plan[i] = area
        elif pref == "静岡県":
            want = "tokyo" if n["lon"] >= river_lon_at(n["lat"], riv_pts) \
                else "chubu"
            if want == area and want != src:
                plan[i] = want

    # ── 拒否A: ホワイトリスト ──
    veto_wl = {}
    for i in list(plan):
        nm = nodes[i].get("name") or ""
        if any(p in nm for p in fc_pats):
            veto_wl[i] = f"FC固定: {nm[:20]}"
            del plan[i]
            continue
        for j in inc.get(i, []):
            en = edges[j].get("name") or ""
            if any(p in en for p in edge_pats):
                veto_wl[i] = f"越境幹線: {en[:26]}"
                del plan[i]
                break

    # ── 拒否B: 島跨ぎ切断ガード(反復) ──
    def freq_of(region):
        return AREA_FREQ.get(region)

    pre_cross = set()
    for j, e in enumerate(edges):
        ia = by_xy.get((round(e["a"][0], 5), round(e["a"][1], 5)))
        ib = by_xy.get((round(e["b"][0], 5), round(e["b"][1], 5)))
        if ia is None or ib is None:
            continue
        fa, fb = freq_of(nodes[ia]["region"]), freq_of(nodes[ib]["region"])
        if fa and fb and fa != fb:
            pre_cross.add(j)

    veto_cross = {}
    for _round in range(20):
        eff = {i: plan[i] for i in plan}
        new_cross = []
        for j, e in enumerate(edges):
            if j in pre_cross:
                continue
            ia = by_xy.get((round(e["a"][0], 5), round(e["a"][1], 5)))
            ib = by_xy.get((round(e["b"][0], 5), round(e["b"][1], 5)))
            if ia is None or ib is None:
                continue
            ra = eff.get(ia, nodes[ia]["region"])
            rb = eff.get(ib, nodes[ib]["region"])
            fa, fb = freq_of(ra), freq_of(rb)
            if fa and fb and fa != fb:
                new_cross.append((j, ia, ib))
        if not new_cross:
            break
        for j, ia, ib in new_cross:
            for i in (ia, ib):
                if i in plan:
                    veto_cross[i] = (edges[j].get("name") or "")[:30]
                    del plan[i]

    # 検収: 最終計画で新規切断0を確認
    eff = dict(plan)
    残 = 0
    for j, e in enumerate(edges):
        if j in pre_cross:
            continue
        ia = by_xy.get((round(e["a"][0], 5), round(e["a"][1], 5)))
        ib = by_xy.get((round(e["b"][0], 5), round(e["b"][1], 5)))
        if ia is None or ib is None:
            continue
        fa = freq_of(eff.get(ia, nodes[ia]["region"]))
        fb = freq_of(eff.get(ib, nodes[ib]["region"]))
        if fa and fb and fa != fb:
            残 += 1

    def row(i):
        n = nodes[i]
        return {"id": n.get("id"), "name": n.get("name"), "sub": n.get("sub"),
                "pref": prefecture_of(n["lat"], n["lon"]),
                "from": n.get("region"), "to": plan.get(i),
                "lat": n["lat"], "lon": n["lon"]}

    rep = {
        "date": str(datetime.date.today()),
        "note": "ドライラン監査 — all.json 無変更。適用は region_attribution 統合後",
        "guarded_total": len(guarded),
        "flip_planned": len(plan),
        "flip_by_dir": {},
        "veto_whitelist": len(veto_wl),
        "veto_crossing_guard": len(veto_cross),
        "kept_guarded": len(guarded) - len(plan) - len(veto_wl)
                        - len(veto_cross),
        "pre_existing_cross_edges": len(pre_cross),
        "new_cross_edges_after_plan": 残,
        "pass": 残 == 0,
        "flips": [row(i) for i in sorted(plan)],
        "vetoed_whitelist": [
            {**row(i), "why": w} for i, w in sorted(veto_wl.items())],
        "vetoed_crossing": [
            {**row(i), "cut_edge": w} for i, w in sorted(veto_cross.items())],
    }
    for i in plan:
        n = nodes[i]
        k = f"{prefecture_of(n['lat'], n['lon'])}:{n['region']}->{plan[i]}"
        rep["flip_by_dir"][k] = rep["flip_by_dir"].get(k, 0) + 1
    out = f"docs/reports/mixed_pref_flip_audit_{rep['date']}.json"
    json.dump(rep, open(out, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    print(f"ガード対象 {len(guarded)} / フリップ計画 {len(plan)} "
          f"(WL拒否 {len(veto_wl)}・切断ガード拒否 {len(veto_cross)}・"
          f"ガード維持 {rep['kept_guarded']})")
    print("方向別:", json.dumps(rep["flip_by_dir"], ensure_ascii=False))
    print(f"既存跨ぎ {len(pre_cross)} / 新規切断 {残} → "
          f"{'PASS' if 残 == 0 else 'FAIL'}")
    print("->", out)
    return 0 if 残 == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
