"""Score fragment-reconnection candidates by road-path plausibility (M9).

    PYTHONPATH=. python scripts/score_road_reconnection.py kyushu \
        --roads data/external/osm_roads/kyushu.json [--json out.json]

For every pair of 66 kV-band components whose closest endpoints sit
within ``--crow-max`` km, the score is how well a major-road path
explains the gap: ``ratio = (walk to road + road path + walk from
road) / crow distance``. The measured prior (ledger 51): 66 kV lines
follow major roads ~3x more than EHV, so a candidate whose gap is
spanned by a road path of comparable length (ratio <= --ratio-max) is
plausibly one circuit mapped in two halves along that road.

Output: the scored candidate list (best first) and the potential
largest-component cover if all accepted candidates were joined —
the decision basis for wiring road-route synthetic lines (prov=
road_route) into the builder. Road data is local-only (gitignored).
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KM = 111.32


def _xy(lat, lon):
    return (lon * KM * math.cos(math.radians(lat)), lat * KM)


def load_road_graph(path):
    import networkx as nx

    data = json.load(open(path))
    G = nx.Graph()
    for w in data.get("elements", []):
        geom = w.get("geometry") or []
        prev = None
        for p in geom:
            node = (round(p["lat"], 7), round(p["lon"], 7))
            if prev is not None:
                d = math.dist(_xy(*prev), _xy(*node))
                if d > 0:
                    G.add_edge(prev, node, weight=d)
            prev = node
    return G


def candidates(region, lo_kv=60.0, hi_kv=140.0, crow_max=3.0):
    """Closest endpoint pairs between 66-band components."""
    import networkx as nx

    from src.powerflow.snapped_topology import build_network_snapped

    net = build_network_snapped(region)
    G = nx.Graph()
    coord = {}
    for s in net.substations:
        coord[s.id] = (s.latitude, s.longitude)
    for ln in net.transmission_lines:
        if "_xfmr_" in ln.id:
            continue
        kv = float(ln.voltage_kv or 0)
        if not (lo_kv <= kv < hi_kv):
            continue
        G.add_edge(ln.from_substation_id, ln.to_substation_id)
    comps = [c for c in __import__("networkx").connected_components(G)
             if len(c) >= 2]
    comps.sort(key=len, reverse=True)
    pairs = []
    for i in range(len(comps)):
        for j in range(i + 1, len(comps)):
            best = None
            for a in comps[i]:
                if a not in coord:
                    continue
                pa = coord[a]
                for b in comps[j]:
                    if b not in coord:
                        continue
                    d = math.dist(_xy(*pa), _xy(*coord[b]))
                    if d <= crow_max and (best is None or d < best[0]):
                        best = (d, a, b)
            if best:
                pairs.append({"crow_km": round(best[0], 3),
                              "a": best[1], "b": best[2],
                              "a_ll": coord[best[1]], "b_ll": coord[best[2]],
                              "comp_i": i, "comp_j": j,
                              "size_i": len(comps[i]), "size_j": len(comps[j])})
    return net, comps, pairs


def score(pairs, road_graph, walk_max=0.3, ratio_max=1.8):
    import networkx as nx
    import numpy as np
    from scipy.spatial import cKDTree

    nodes = list(road_graph.nodes)
    tree = cKDTree(np.array([_xy(*n) for n in nodes]))

    out = []
    for p in pairs:
        xa, xb = _xy(*p["a_ll"]), _xy(*p["b_ll"])
        da, ia = tree.query(xa)
        db, ib = tree.query(xb)
        rec = dict(p, walk_a_km=round(float(da), 3),
                   walk_b_km=round(float(db), 3))
        if da > walk_max or db > walk_max:
            rec["verdict"] = "far_from_road"
            out.append(rec)
            continue
        try:
            path = nx.shortest_path_length(
                road_graph, nodes[ia], nodes[ib], weight="weight")
        except nx.NetworkXNoPath:
            rec["verdict"] = "no_road_path"
            out.append(rec)
            continue
        total = da + path + db
        ratio = total / max(p["crow_km"], 1e-3)
        rec["road_km"] = round(float(path), 3)
        rec["ratio"] = round(float(ratio), 2)
        rec["verdict"] = "accept" if ratio <= ratio_max else "detour"
        out.append(rec)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("region")
    ap.add_argument("--roads", required=True)
    ap.add_argument("--crow-max", type=float, default=3.0)
    ap.add_argument("--walk-max", type=float, default=0.3)
    ap.add_argument("--ratio-max", type=float, default=1.8)
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    print(f"  ... building {args.region}", file=sys.stderr)
    net, comps, pairs = candidates(args.region, crow_max=args.crow_max)
    print(f"  ... road graph {args.roads}", file=sys.stderr)
    rg = load_road_graph(args.roads)
    print(f"  ... scoring {len(pairs)} pairs over {rg.number_of_nodes():,} "
          f"road nodes", file=sys.stderr)
    scored = score(pairs, rg, walk_max=args.walk_max,
                   ratio_max=args.ratio_max)

    accepted = [r for r in scored if r["verdict"] == "accept"]
    # potential cover if accepted joins are applied (union-find on comps)
    parent = list(range(len(comps)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for r in accepted:
        parent[find(r["comp_i"])] = find(r["comp_j"])
    merged = defaultdict(int)
    for i, c in enumerate(comps):
        merged[find(i)] += len(c)
    n_all = sum(len(c) for c in comps)
    cover0 = max((len(c) for c in comps), default=0) / n_all
    cover1 = max(merged.values(), default=0) / n_all

    verdict_counts = defaultdict(int)
    for r in scored:
        verdict_counts[r["verdict"]] += 1
    print(f"{args.region}: {len(pairs)} candidate pairs "
          f"(crow<= {args.crow_max} km) -> {dict(verdict_counts)}")
    print(f"  66-band largest-comp cover: {cover0:.1%} -> "
          f"{cover1:.1%} if accepted joins applied")
    for r in sorted(accepted, key=lambda x: x["ratio"])[:12]:
        print(f"  accept ratio={r['ratio']:>4} crow={r['crow_km']:>5}km "
              f"road={r['road_km']:>5}km sizes={r['size_i']}+{r['size_j']}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"region": args.region, "scored": scored,
                       "cover_before": cover0, "cover_after": cover1},
                      f, indent=1, ensure_ascii=False)
        print(f"scored -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
