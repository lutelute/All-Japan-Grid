#!/usr/bin/env python3
"""介入#57 で主系統から外れたバスの負荷・発電(配布ケースと同じ組み方 build_canonical_net、地点需要なし)。

    PYTHONPATH=. python3 docs/reports/junction_cuts_2026-11-07/measure_islands.py
→ docs/reports/junction_cuts_2026-11-07/islands.json
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
import networkx as nx  # noqa: E402

import src.powerflow.junction_cuts as JC  # noqa: E402
import src.powerflow.full_from_built as F  # noqa: E402
from scripts.export_matpower_canonical import build_canonical_net  # noqa: E402


def comps(net):
    g = nx.Graph()
    g.add_nodes_from(int(b) for b in net.bus.index)
    for _, r in net.line.iterrows():
        if bool(r.in_service):
            g.add_edge(int(r.from_bus), int(r.to_bus))
    for _, r in net.trafo.iterrows():
        if bool(r.in_service):
            g.add_edge(int(r.hv_bus), int(r.lv_bus))
    cs = sorted(nx.connected_components(g), key=len, reverse=True)
    return {b: i for i, c in enumerate(cs) for b in c}


def main():
    db = json.load(open(F.BUILT, encoding="utf-8"))
    out = {}
    for island in ("east", "west"):
        nets = {}
        for tag, val in (("before", "0"), ("after", "1")):
            JC.JUNCTION_CUTS_DEFAULT = (val == "1")
            nodes = json.loads(json.dumps(db["nodes"]))
            nets[tag] = build_canonical_net(island, nodes, db["edges"], F.ISLAND_FREQ[island], point_demand=False)
        JC.JUNCTION_CUTS_DEFAULT = True
        cb, ca = comps(nets["before"]), comps(nets["after"])
        na = nets["after"]
        # 前は最大の成分(0)にいて、後は外れたバス。前後は (名前, 電圧, 座標) で対応づける(同じ名前の変電所が
        # 電圧ごと・地域ごとに何個もあるので、名前だけだと取り違える)。新しく作ったバス(#57)は後だけにある
        def key(net, b):
            return (str(net.bus.at[b, "name"]), round(float(net.bus.at[b, "vn_kv"]), 1), str(net.bus.at[b, "geo"]))
        nb_ = nets["before"]
        kb = {}
        for b in nb_.bus.index:
            kb.setdefault(key(nb_, b), []).append(int(b))
        left = [b for b in na.bus.index if ca[int(b)] != 0
                and any(cb[x] == 0 for x in kb.get(key(na, b), []))]
        groups = {}
        for b in left:
            groups.setdefault(ca[int(b)], []).append(int(b))
        rows = []
        for ci, bs in sorted(groups.items()):
            allb = [b for b in na.bus.index if ca[int(b)] == ci]
            load = float(na.load[na.load.bus.isin(allb)].p_mw.sum())
            gen = float(na.gen[na.gen.bus.isin(allb)].p_mw.sum()) + float(na.sgen[na.sgen.bus.isin(allb)].p_mw.sum())
            n_ext = int(na.ext_grid.bus.isin(allb).sum())
            rows.append({"n_bus": len(allb), "buses": [str(na.bus.at[b, "name"]) for b in allb][:8],
                         "kv": sorted({float(na.bus.at[b, "vn_kv"]) for b in allb}),
                         "load_mw": round(load, 2), "gen_mw": round(gen, 2), "slack": n_ext})
        out[island] = rows
        tot_load = sum(r["load_mw"] for r in rows)
        print(f"{island}: 主系統から外れた成分 {len(rows)}・バス {sum(r['n_bus'] for r in rows)}・負荷 {tot_load:.1f} MW")
        for r in rows:
            print("   ", r)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "islands.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
