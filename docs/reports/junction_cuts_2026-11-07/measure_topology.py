#!/usr/bin/env python3
"""介入#57 の前と後: 潮流計算の網(build_island_net)の変圧器・分岐点の変圧器・連結成分を比べる。

    PYTHONPATH=. python3 docs/reports/junction_cuts_2026-11-07/measure_topology.py
→ docs/reports/junction_cuts_2026-11-07/topology.json
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
import networkx as nx  # noqa: E402
import src.powerflow.full_from_built as F  # noqa: E402


def graph(net):
    g = nx.Graph()
    g.add_nodes_from(int(b) for b in net.bus.index)
    for _, r in net.line.iterrows():
        if bool(r.in_service):
            g.add_edge(int(r.from_bus), int(r.to_bus))
    for _, r in net.trafo.iterrows():
        if bool(r.in_service):
            g.add_edge(int(r.hv_bus), int(r.lv_bus))
    return g


def measure(net, st):
    bt = net.bus["type"]
    nn = sum(1 for _, r in net.trafo.iterrows() if bt[int(r.hv_bus)] == "n" and bt[int(r.lv_bus)] == "n")
    g = graph(net)
    comps = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
    return {"buses": len(net.bus), "lines": len(net.line), "trafos": len(net.trafo), "junction_trafos": nn,
            "implicit_stepdown": st.get("n_implicit_stepdown", 0), "junction_cuts": st.get("n_junction_cuts", 0),
            "components": len(comps), "largest": comps[0] if comps else 0,
            "outside_largest": sum(comps[1:]), "singletons": sum(1 for c in comps if c == 1)}


def main():
    db = json.load(open(F.BUILT, encoding="utf-8"))
    out = {}
    for island in ("hokkaido", "east", "west", "okinawa"):
        row = {}
        for tag, jc in (("before", False), ("after", True)):
            nodes = json.loads(json.dumps(db["nodes"]))
            net, _b, st = F.build_island_net(island, nodes, db["edges"], F.ISLAND_FREQ[island], {}, junction_cuts=jc)
            row[tag] = measure(net, st)
            if jc:
                row["ledger"] = st.get("junction_cuts_ledger", [])
        out[island] = row
        b, a = row["before"], row["after"]
        print(f"{island:8s} 変圧器 {b['trafos']}→{a['trafos']}  分岐点の変圧器 {b['junction_trafos']}→{a['junction_trafos']}"
              f"  #43a {b['implicit_stepdown']}→{a['implicit_stepdown']}  成分 {b['components']}→{a['components']}"
              f"  最大 {b['largest']}→{a['largest']}  最大の外 {b['outside_largest']}→{a['outside_largest']}")
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topology.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("→", p)


if __name__ == "__main__":
    main()
