#!/usr/bin/env python3
"""west に対する介入#22(サイト内変圧器リンク)の断片化効果 — build+グラフ計測のみ(解かない)。

Usage: PYTHONPATH=. .venv/bin/python .../probe_west_sitetrafo.py out.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

import networkx as nx

from scripts.run_full_powerflow_from_db import BUILT, build_island_net


def measure(site_trafos):
    built = json.load(open(BUILT))
    geom = {}
    net, _bus_of, bstats = build_island_net(
        "west", built["nodes"], built["edges"], 60.0, geom,
        site_trafos=site_trafos)
    g = nx.Graph()
    g.add_nodes_from(net.bus.index)
    for _, r in net.line.iterrows():
        if r["in_service"]:
            g.add_edge(int(r["from_bus"]), int(r["to_bus"]))
    for _, r in net.trafo.iterrows():
        if r["in_service"]:
            g.add_edge(int(r["hv_bus"]), int(r["lv_bus"]))
    comps = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
    return {"site_trafos": site_trafos,
            "n_site_trafo": bstats.get("n_site_trafo", 0),
            "n_bus": len(net.bus), "n_trafo": int(len(net.trafo)),
            "n_components": len(comps), "main_comp": comps[0],
            "main_frac": round(comps[0] / len(net.bus), 4)}


def main():
    out = {"off": measure(False), "on": measure(True)}
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
