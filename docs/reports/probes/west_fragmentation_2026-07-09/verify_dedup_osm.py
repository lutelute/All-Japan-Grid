#!/usr/bin/env python3
"""west 重複ノードが「同一OSMオブジェクトの二重抽出」か照合する.

built の重複ノード(同一座標+kv・別region)について、各regionの生OSM
substations.geojson を引き、同一 osm_id に対応するか確認する。
同一osm_id なら「除去」が妥当(無理な接続でない)。
  .venv/bin/python verify_dedup_osm.py <out.json>
"""
from __future__ import annotations
import json, os, statistics, sys
from collections import defaultdict
REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
os.chdir(REPO)
WEST = ["chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu"]


def flat(c):
    out = []
    def rec(x):
        if isinstance(x, (int, float)): return
        if len(x) == 2 and all(isinstance(v, (int, float)) for v in x):
            out.append(x); return
        for y in x: rec(y)
    rec(c); return out


def load_osm_subs():
    """region -> list of (osm_id, name, clat, clon, voltage)."""
    subs = {}
    for r in WEST:
        p = f"data/{r}_substations.geojson"
        if not os.path.exists(p):
            subs[r] = []; continue
        d = json.load(open(p))
        lst = []
        for f in d["features"]:
            pr = f.get("properties", {})
            oid = pr.get("osm_id") or pr.get("@id") or pr.get("id")
            pts = flat(f["geometry"]["coordinates"])
            if not pts: continue
            clat = statistics.mean(p[1] for p in pts)
            clon = statistics.mean(p[0] for p in pts)
            lst.append((str(oid), pr.get("name"), clat, clon))
        subs[r] = lst
    return subs


def nearest_osm(subs_r, lat, lon, tol_km=0.3):
    import math
    best = None; bestd = tol_km
    for oid, nm, clat, clon in subs_r:
        d = math.hypot((clat-lat)*111, (clon-lon)*91)  # 粗い近似km
        if d < bestd:
            bestd = d; best = (oid, nm, round(d*1000))
    return best


def main():
    out_path = sys.argv[1]
    built = json.load(open("docs/data/built/all.json"))
    osm = load_osm_subs()

    # west 完全一致(座標+kv)・別region・変電所重複グループ
    key = defaultdict(list)
    for n in built["nodes"]:
        if n.get("region") in WEST and n.get("sub") == 1:
            key[(n["lat"], n["lon"], round(float(n.get("kv") or 0), 1))].append(n)
    dup = [(k, v) for k, v in key.items()
           if len({x.get("region") for x in v}) > 1]

    same_osm = 0; diff_osm = 0; unresolved = 0
    examples = []
    for (lat, lon, kv), v in dup:
        regs = sorted({x.get("region") for x in v})
        oids = {}
        for r in regs:
            hit = nearest_osm(osm.get(r, []), lat, lon)
            oids[r] = hit[0] if hit else None
        resolved = [o for o in oids.values() if o]
        if len(resolved) < 2:
            unresolved += 1
        elif len(set(resolved)) == 1:
            same_osm += 1
            if len(examples) < 15:
                examples.append({"kv": kv, "regions": regs, "osm_id": resolved[0],
                                 "name": next((x.get("name") for x in v if x.get("name")), None)})
        else:
            diff_osm += 1
    rep = {"n_crossregion_sub_dup_groups": len(dup),
           "same_osm_id": same_osm, "diff_osm_id": diff_osm,
           "unresolved(名前/座標でOSM引けず)": unresolved,
           "same_osm_frac": round(same_osm/max(same_osm+diff_osm, 1), 4),
           "examples_same_osm": examples}
    json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
