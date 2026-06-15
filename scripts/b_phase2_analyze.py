"""B Phase2 分析: node-topology(共有ノード=正確な線接続)+ 変電所束縛(point-in-polygon)で
島数を測り、現モデル(snapped・座標推測)とA/Bする。「Bが島=繋ぎ落としを減らすか」の評価。

判定(両者で同一の変電所集合 data/{region}_substations.geojson を使う):
- B島     = どのnode-topology線にも(構内に)繋がらない変電所
- 現モデル島 = build_network_snapped で本系統外の変電所

これは分析(本番builderの近似)であり、確定A/B(ρ/AC含む)はPhase3のbuilder統合で行う。
本番モデル/スコアカードには非接触。

Usage:
    PYTHONPATH=. python scripts/b_phase2_analyze.py --region shikoku
    PYTHONPATH=. python scripts/b_phase2_analyze.py --all --out docs/reports/b_phase2_2026-06-15.json
"""
import argparse
import collections
import glob
import json
import os

import networkx as nx

REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
           "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]


def load_region_nodes(region):
    seen = set()
    ways = []
    nodes = {}
    for f in sorted(glob.glob(f"data/osm_raw/power_nodes_{region}_t*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for e in d["elements"]:
            if e["type"] == "way" and e["id"] not in seen:
                seen.add(e["id"])
                ways.append(e)
            elif e["type"] == "node":
                nodes[e["id"]] = (e["lon"], e["lat"])
    return ways, nodes


def current_islands(region):
    from src.powerflow.snapped_topology import build_network_snapped
    net = build_network_snapped(region)
    g = nx.Graph()
    g.add_nodes_from(s.id for s in net.substations)
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    big = len(comps[0]) if comps else 0
    return {"subs": len(net.substations), "components": len(comps),
            "islands": len(net.substations) - big}


def analyze(region):
    from shapely.geometry import shape, Point
    from shapely.strtree import STRtree
    ways, nodes = load_region_nodes(region)
    subs = json.load(open(f"data/{region}_substations.geojson", encoding="utf-8"))
    geoms, sidx = [], []
    for i, f in enumerate(subs["features"]):
        g = f.get("geometry")
        if not g:
            continue
        try:
            gm = shape(g)
            if gm.geom_type == "Point":
                gm = gm.buffer(0.0014)   # ~150m: 点変電所は近傍束縛
            geoms.append(gm)
            sidx.append(i)
        except Exception:   # noqa: BLE001
            continue
    tree = STRtree(geoms)
    G = nx.Graph()
    # 線way: 連続ノードを辺に(共有ノードでway同士が自動連結=正確)
    for w in ways:
        if (w.get("tags") or {}).get("power") not in ("line", "cable", "minor_line"):
            continue
        ns = w.get("nodes", [])
        for a, b in zip(ns, ns[1:]):
            G.add_edge(("n", a), ("n", b))
    # 変電所束縛: 線ノードが変電所polygon内なら接続
    bound = 0
    for nid, (lon, lat) in nodes.items():
        if ("n", nid) not in G:
            continue
        p = Point(lon, lat)
        for gi in tree.query(p):
            gi = int(gi)
            if geoms[gi].covers(p):
                G.add_edge(("n", nid), ("s", sidx[gi]))
                bound += 1
                break
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    main = comps[0] if comps else set()
    nsub = len(sidx)
    sub_in_main = sum(1 for si in sidx if ("s", si) in main)
    cur = current_islands(region)
    return {"region": region, "subs_polygons": nsub,
            "b_subs_in_main": sub_in_main, "b_islands": nsub - sub_in_main,
            "b_components": len(comps),
            "current_subs": cur["subs"], "current_islands": cur["islands"],
            "delta_islands_vs_current": (nsub - sub_in_main) - cur["islands"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()
    regions = REGIONS if args.all else [args.region]
    results = []
    for r in regions:
        if not glob.glob(f"data/osm_raw/power_nodes_{r}_t*.json"):
            print(f"{r}: node-refデータ無し(skip)")
            continue
        try:
            res = analyze(r)
        except Exception as exc:   # noqa: BLE001
            res = {"region": r, "error": str(exc)[:200]}
        results.append(res)
        if "error" in res:
            print(f"{r}: ERROR {res['error']}")
        else:
            print(f"{r:9} B島 {res['b_islands']:4} / 現モデル島 {res['current_islands']:4} "
                  f"(Δ{res['delta_islands_vs_current']:+}) ・変電所{res['subs_polygons']}")
    if args.out and results:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
        print("出力:", args.out)


if __name__ == "__main__":
    main()
