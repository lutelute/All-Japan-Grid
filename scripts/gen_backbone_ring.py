"""500/275kV バックボーンのリング構造を検出し、GeoJSONとして出力する。

networkx の二重連結成分（biconnected components）によりループ形成枝を特定し、
OSMルートGeoJSONにring属性を付与して backbone_ring.geojson を生成する。

Usage:
    python scripts/gen_backbone_ring.py
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

import networkx as nx
import numpy as np
from scipy.spatial import KDTree

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.matpower.exporter import build_matpower_case

ROUTE_DIR  = ROOT / "docs/data/powerflow"
BUS_GEOJSON = ROOT / "docs/data/powerflow/all_ac_buses.geojson"
OUT_FILE    = ROOT / "docs/data/powerflow/backbone_ring.geojson"

MATCH_DEG = 0.40   # °  endpoint matching radius

def build_graph(case, kv_min: int, kv_max: int):
    buses = case["BUS"]
    branches = case["BRANCH"]
    bus_ids = buses[:, 0].astype(int)
    bus_kv  = buses[:, 9]

    node_set = set(bus_ids[(bus_kv >= kv_min) & (bus_kv < kv_max)])
    frm = branches[:, 0].astype(int)
    to  = branches[:, 1].astype(int)
    edges = [(f, t, {"idx": i}) for i, (f, t) in enumerate(zip(frm, to))
             if f in node_set and t in node_set]

    G = nx.Graph()
    G.add_nodes_from(node_set)
    G.add_edges_from(edges)
    return G, node_set


def ring_edges(G) -> set[tuple[int, int]]:
    """Return all edges that participate in at least one simple cycle (non-bridges)."""
    bridges = set(nx.bridges(G))
    all_edges = {(u, v) for u, v, _ in G.edges(data=True)}
    return {(min(u, v), max(u, v)) for u, v in all_edges - bridges}


def bus_coords_map(case, bus_geojson: Path) -> dict[int, tuple[float, float]]:
    """Map bus_id (1-indexed matpower) -> (lon, lat) from all_ac_buses.geojson."""
    buses = case["BUS"]
    bnames = case["bus_names"]
    bus_ids = buses[:, 0].astype(int)
    bus_kv  = buses[:, 9]

    with open(bus_geojson) as f:
        geo = json.load(f)

    # name -> [lon, lat]
    name_to_coord: dict[str, list[float]] = {}
    for feat in geo["features"]:
        p = feat["properties"]
        name_to_coord[p["name"]] = feat["geometry"]["coordinates"]

    coords: dict[int, tuple[float, float]] = {}
    for i, (bid, bname) in enumerate(zip(bus_ids, bnames)):
        if bname in name_to_coord:
            lon, lat = name_to_coord[bname]
            coords[int(bid)] = (lon, lat)
    return coords


def match_ring_routes(ring_edge_set: set, bus_coords: dict, route_file: Path) -> list[dict]:
    """For each ring edge, find matching OSM route segments by endpoint proximity."""
    if not ring_edge_set:
        return []

    with open(route_file) as f:
        routes = json.load(f)

    features = routes["features"]

    # Build KDTree on route endpoints (first + last coordinate)
    ep_pts = []   # (lon, lat) of each endpoint
    ep_feat_idx = []
    for i, feat in enumerate(features):
        coords = feat["geometry"]["coordinates"]
        ep_pts.append(coords[0])   # start
        ep_feat_idx.append(i)
        ep_pts.append(coords[-1])  # end
        ep_feat_idx.append(i)

    if not ep_pts:
        return []

    tree = KDTree(ep_pts)

    ring_route_ids: set[int] = set()

    for (from_id, to_id) in ring_edge_set:
        fc = bus_coords.get(from_id)
        tc = bus_coords.get(to_id)
        if fc is None or tc is None:
            continue

        # Query: find route endpoints near from_bus AND to_bus
        idxs_f = tree.query_ball_point(fc, MATCH_DEG)
        idxs_t = tree.query_ball_point(tc, MATCH_DEG)

        feat_ids_f = {ep_feat_idx[i] for i in idxs_f}
        feat_ids_t = {ep_feat_idx[i] for i in idxs_t}
        matched = feat_ids_f & feat_ids_t  # routes that touch BOTH buses

        ring_route_ids |= matched

    return list(ring_route_ids)


def main():
    print("Building matpower case...")
    case = build_matpower_case(voltage_levels=[500, 275, 154, 110, 77, 66],
                               load_factor=0.20, hv_hops=4)

    bus_coords = bus_coords_map(case, BUS_GEOJSON)
    print(f"  bus coordinates loaded: {len(bus_coords)} buses")

    results = []

    for kv_label, kv_min, kv_max, col, wt in [
        (500, 490, 9999, "#cc0000", 4.0),
        (275, 260,  490, "#0044cc", 2.5),
    ]:
        G, _ = build_graph(case, kv_min, kv_max)
        n_comp = nx.number_connected_components(G)
        re = ring_edges(G)
        print(f"  {kv_label}kV: {G.number_of_nodes()} buses, "
              f"{G.number_of_edges()} branches, "
              f"{n_comp} components, {len(re)} ring edges")

        route_file = ROUTE_DIR / f"routes_{kv_label}kv.geojson"
        if not route_file.exists():
            print(f"    WARNING: {route_file} not found, skipping")
            continue

        matched_ids = match_ring_routes(re, bus_coords, route_file)
        print(f"  {kv_label}kV ring routes matched: {len(matched_ids)}")

        with open(route_file) as f:
            routes = json.load(f)

        for i in matched_ids:
            feat = routes["features"][i]
            p = feat["properties"]
            results.append({
                "type": "Feature",
                "geometry": feat["geometry"],
                "properties": {
                    "kv":      kv_label,
                    "name":    p.get("name", ""),
                    "region":  p.get("region", ""),
                    "loading": p.get("loading", 0.0),
                    "ring":    True,
                    "col":     col,
                    "wt":      wt,
                },
            })

    fc = {"type": "FeatureCollection", "features": results}
    with open(OUT_FILE, "w") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nSaved {len(results)} ring route segments → {OUT_FILE}")
    print("  Run → Visualize in 潮流解析 tab to see backbone ring overlay")


if __name__ == "__main__":
    main()
