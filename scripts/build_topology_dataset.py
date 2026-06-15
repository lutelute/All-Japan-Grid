"""トポロジ接続データ構築: 全点(鉄塔/変電所点/線頂点)をノード、共有OSMノードを辺として
構造的な接続データを作る(オーナー方針 2026-06-16「全点を構造としてトポロジ的に接続データ化」)。

B路線の核: 生OSM(node参照)をそのまま使い、座標推測でなく **OSMノードの共有=接続** で
構築する。これが人間がOSMで見る接続と同一精度。出力は再利用可能な接続データ:
  data/topology/{region}_nodes.jsonl  : {id, lat, lon, type(tower/substation/junction), kv, comp, main}
  data/topology/{region}_edges.jsonl  : {a, b, way, power, kv}     (a,b = OSMノードid)
  data/topology/{region}_summary.json : 連結成分・未接続数

Usage:
    PYTHONPATH=. python scripts/build_topology_dataset.py --region kansai
    PYTHONPATH=. python scripts/build_topology_dataset.py --all      # 全国(背景実行向け)
"""
import argparse
import collections
import json
import os

import networkx as nx

from scripts.tower_connectivity import gather   # 取得(out body・node参照+nodeタグ・キャッシュ)

OUT = "data/topology"
REGIONS = ["okinawa", "shikoku", "hokuriku", "chugoku", "kansai",
           "kyushu", "chubu", "tohoku", "hokkaido", "tokyo"]


def build(region):
    nodes, ways = gather(region=region)
    lines = [w for w in ways if (w.get("tags") or {}).get("power")
             in ("line", "cable", "minor_line")]
    # ノード種別: tower / substation(node) / junction(線頂点でtower/subでない)
    def ntype(nid):
        t = (nodes.get(nid, {}).get("tags") or {}).get("power")
        if t == "tower":
            return "tower"
        if t == "substation":
            return "substation"
        return "vertex"

    # グラフ: 各wayの連続ノードを辺に(共有ノードでway同士が自動連結=正確トポロジ)
    g = nx.Graph()
    edges = []
    for w in lines:
        ns = [n for n in w.get("nodes", []) if n in nodes]
        kv = (w.get("tags") or {}).get("voltage")
        pw = (w.get("tags") or {}).get("power")
        for a, b in zip(ns, ns[1:]):
            if a == b:
                continue
            g.add_edge(a, b)
            edges.append({"a": a, "b": b, "way": w["id"], "power": pw, "kv": kv})
    # 線に乗らない孤立鉄塔もノードとして含める(未接続として可視化)
    for nid, n in nodes.items():
        if (n.get("tags") or {}).get("power") == "tower" and nid not in g:
            g.add_node(nid)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    main = set(comps[0]) if comps else set()
    comp_of = {}
    for i, c in enumerate(comps):
        for x in c:
            comp_of[x] = i
    os.makedirs(OUT, exist_ok=True)
    typecount = collections.Counter()
    with open(os.path.join(OUT, f"{region}_nodes.jsonl"), "w", encoding="utf-8") as fh:
        for nid in g.nodes():
            n = nodes.get(nid)
            if not n:
                continue
            tp = ntype(nid)
            typecount[tp] += 1
            fh.write(json.dumps({
                "id": nid, "lat": round(n["lat"], 6), "lon": round(n["lon"], 6),
                "type": tp, "comp": comp_of.get(nid, -1),
                "main": nid in main, "deg": g.degree(nid)}, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, f"{region}_edges.jsonl"), "w", encoding="utf-8") as fh:
        for e in edges:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    # 未接続(本系統外)を種別別に
    off = [nid for nid in g.nodes() if nid not in main]
    off_t = collections.Counter(ntype(nid) for nid in off)
    summary = {"region": region, "n_nodes": g.number_of_nodes(),
               "n_edges": g.number_of_edges(), "n_components": len(comps),
               "main_size": len(main), "node_types": dict(typecount),
               "off_main_total": len(off), "off_main_by_type": dict(off_t),
               "towers_total": typecount.get("tower", 0),
               "towers_off_main": off_t.get("tower", 0)}
    with open(os.path.join(OUT, f"{region}_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    regions = REGIONS if args.all else [args.region]
    allsum = []
    sp = os.path.join(OUT, "ALL_summary.json")
    if os.path.exists(sp):
        allsum = json.load(open(sp, encoding="utf-8"))
    done = {s["region"] for s in allsum if "region" in s}
    for r in regions:
        if r in done and args.all:
            print("skip(done)", r, flush=True)
            continue
        print(f"=== build topology {r} ===", flush=True)
        try:
            s = build(r)
        except Exception as exc:   # noqa: BLE001
            s = {"region": r, "error": str(exc)[:200]}
        allsum = [x for x in allsum if x.get("region") != r] + [s]
        os.makedirs(OUT, exist_ok=True)
        with open(sp, "w", encoding="utf-8") as fh:
            json.dump(allsum, fh, ensure_ascii=False, indent=1)
        if "error" in s:
            print(f"  {r} ERROR {s['error']}", flush=True)
        else:
            print(f"  {r}: ノード{s['n_nodes']}(鉄塔{s['towers_total']}) 辺{s['n_edges']} "
                  f"成分{s['n_components']} 本系統{s['main_size']} / 本系統外{s['off_main_total']}"
                  f"(鉄塔{s['towers_off_main']})", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
