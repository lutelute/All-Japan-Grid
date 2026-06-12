"""D3: OSM power=transformer node evidence vs the standard trafo ladder.

    PYTHONPATH=. python scripts/analyze_transformer_nodes.py \
        --nodes data/external/osm_roads/tokyo_xfmr_tile*.json \
        --region tokyo [--json docs/reports/d3_transformer_nodes_<date>.json]

Maps Overpass-fetched ``power=transformer`` NODES (tiled bbox JSONs,
deduped by node id) into the region's OSM substation POLYGONS, then
asks the only question that matters for the model: how many of the
substations where the pipeline inserts transformers (multi-voltage
substations — the standard ladder of ledger record) would gain
EVIDENCE (``devices`` = bank count, ``voltage:primary/secondary``,
``rating``) from these nodes?

The verdict is coverage-driven: a few percent of trafo substations
with evidence cannot replace the class-typical ladder — that is a
negative result to record honestly (the nodes stay useful as spot
checks), per the D3 acceptance rule in docs/PLAN_NEXT.md.
"""

import argparse
import datetime as dt
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_nodes(patterns):
    nodes = {}
    for pat in patterns:
        for path in glob.glob(pat):
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            for el in d.get("elements", []):
                if el.get("type") == "node":
                    nodes[el["id"]] = el
    return list(nodes.values())


def main(argv=None) -> int:
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nodes", nargs="+", required=True,
                    help="Overpass JSON file(s)/globs with transformer nodes")
    ap.add_argument("--region", default="tokyo")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    nodes = load_nodes(args.nodes)
    raw = json.load(open(f"data/{args.region}_substations.geojson"))["features"]
    polys, props = [], []
    for f in raw:
        g = f["geometry"]
        if g["type"] in ("Polygon", "MultiPolygon"):
            polys.append(shape(g))
            props.append(f["properties"])
    tree = STRtree(polys)

    # node -> containing substation polygon
    per_sub = {}          # poly index -> list of node tag dicts
    n_outside = 0
    for el in nodes:
        pt = Point(el["lon"], el["lat"])
        hit = None
        for i in tree.query(pt):
            if polys[i].covers(pt):
                hit = int(i)
                break
        if hit is None:
            n_outside += 1
            continue
        per_sub.setdefault(hit, []).append(el.get("tags", {}))

    tag_counts = Counter()
    subs_with = Counter()
    devices_vals = Counter()
    for i, tags_list in per_sub.items():
        keys = set()
        for t in tags_list:
            for k in ("devices", "voltage:primary", "voltage:secondary",
                      "rating", "phases"):
                if k in t:
                    tag_counts[k] += 1
                    keys.add(k)
            if "devices" in t:
                devices_vals[t["devices"]] += 1
        for k in keys:
            subs_with[k] += 1

    # the denominator that matters: substations where the model inserts
    # trafos = multi-voltage substations (>=2 voltage levels)
    from src.powerflow.snapped_topology import build_network_snapped
    net = build_network_snapped(args.region)
    levels = {}
    for s in net.substations:
        if "_jct_" in s.id:
            continue
        levels.setdefault(s.id.split("@")[0], set()).add(
            round(float(s.voltage_kv or 0)))
    multi_kv = {k for k, v in levels.items() if len(v - {0}) >= 2}

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"),
        "region": args.region,
        "n_nodes": len(nodes),
        "n_nodes_outside_sub_polygon": n_outside,
        "n_sub_polygons_with_nodes": len(per_sub),
        "n_sub_polygons_total": len(polys),
        "n_model_multi_kv_subs": len(multi_kv),
        "tag_node_counts": dict(tag_counts),
        "subs_with_tag": dict(subs_with),
        "devices_distribution": dict(devices_vals),
        "coverage_pct_of_trafo_subs": round(
            100.0 * len(per_sub) / max(len(multi_kv), 1), 1),
    }
    print(json.dumps(out, indent=1, ensure_ascii=False))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
        print(f"-> {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
