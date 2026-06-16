#!/usr/bin/env python3
"""Pre-render the built (snapped) model view to static JSON for the Pages editor.

GitHub Pages is static — the FastAPI editor's `/api/built/{region}` cannot run
there. This script runs `built_view` locally (full env: networkx/shapely) and
writes compact JSON the static editor (docs/editor.html) loads directly:

  docs/data/built/{region}.json  — per-region (region-local connectivity), WITH
                                    OSM line geometry (edge `path`) so the editor
                                    shows "OSM line visible but model islanded".
  docs/data/built/all.json       — national (global connectivity incl. 越境stitch),
                                    edges as A-B segments only (no `path`) to keep
                                    the payload loadable on mobile.
  docs/data/built/index.json     — manifest (regions + stats + generated date).

Design (matches docs/CONNECTION_EDITOR_DESIGN.md): the model view is *viewing*
only here. Editing on Pages is a client-side draft (localStorage) exported as
JSONL / proposed as a GitHub issue; actual adopt/verify stays on the local
server (:8088) where the builder runs. 物理接続=真・計算は検証器・捏造禁止.

Usage:
  PYTHONPATH=. python scripts/build_editor_data.py                 # all regions + national
  PYTHONPATH=. python scripts/build_editor_data.py okinawa shikoku # subset (national skipped)
  PYTHONPATH=. python scripts/build_editor_data.py --date 2026-06-16

Dependencies: full builder env (networkx etc.). NOT run in the pyyaml-only
Pages CI — generate locally and commit docs/data/built/*.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import networkx as nx  # noqa: E402

from src.server.built_view import REGIONS_ALL, built_view  # noqa: E402

OUT_DIR = os.path.join(PROJECT_ROOT, "docs", "data", "built")


def _compact_nodes(nodes: list) -> list:
    """Trim a built_view node list to the fields the static editor needs."""
    out = []
    for n in nodes:
        out.append({
            "id": n["id"],
            "lat": n["lat"], "lon": n["lon"],
            "kv": round(float(n.get("kv") or 0), 1),
            "main": 1 if n.get("main") else 0,
            "deg": int(n.get("deg") or 0),
            "sub": 1 if n.get("sub") else 0,
            "name": n.get("name") or "",
        })
    return out


def _compact_edges(edges: list, with_path: bool) -> list:
    """Trim built_view edges. with_path keeps OSM geometry; else A-B endpoints."""
    out = []
    for e in edges:
        a, b = e.get("a"), e.get("b")
        if not a or not b:
            continue
        rec = {
            "a": a, "b": b,
            "main": 1 if e.get("main") else 0,
            "kv": round(float(e.get("kv") or 0), 1),
            "par": int(e.get("par") or 1),
        }
        if with_path:
            path = e.get("path") or []
            # Drop a degenerate path that is just the two endpoints (the editor
            # draws A-B itself in that case) — saves bytes on straight edges.
            if len(path) > 2:
                rec["path"] = path
        out.append(rec)
    return out


def write_json(path: str, data) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    txt = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)
    return os.path.getsize(path)


def fmt(nbytes: int) -> str:
    if nbytes < 1024:
        return f"{nbytes} B"
    if nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes / (1024 * 1024):.1f} MB"


def k5(la, lo):
    return (round(la, 5), round(lo, 5))


def build_national(collected: dict) -> dict:
    """Merge per-region built views into one national view with GLOBAL main.

    Replicates src.server.built_view.built_view_all so we reuse the per-region
    builds (no second build pass): same coord-keyed graph + ~100m 越境stitch.
    """
    nodes, edges = [], []
    for region, v in collected.items():
        for n in v["nodes"]:
            m = dict(n)
            m["region"] = region
            nodes.append(m)
        edges.extend(v["edges"])

    g = nx.Graph()
    for n in nodes:
        g.add_node(k5(n["lat"], n["lon"]))
    for e in edges:
        if e.get("a") and e.get("b"):
            g.add_edge(tuple(e["a"]), tuple(e["b"]))
    # 越境stitch: ~100m cells joining nodes from different regions (same physical point)
    n_stitch = 0
    prec = 3
    cellmap = defaultdict(list)
    for n in nodes:
        cellmap[(round(n["lat"], prec), round(n["lon"], prec))].append(n)
    for grp in cellmap.values():
        if len({n["region"] for n in grp}) <= 1:
            continue
        base = k5(grp[0]["lat"], grp[0]["lon"])
        for n in grp[1:]:
            if n["region"] != grp[0]["region"]:
                kk = k5(n["lat"], n["lon"])
                if kk != base:
                    g.add_edge(base, kk)
                n_stitch += 1
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    main = set(comps[0]) if comps else set()
    for n in nodes:
        n["main"] = 1 if k5(n["lat"], n["lon"]) in main else 0
    for e in edges:
        if e.get("a") and e.get("b"):
            e["main"] = 1 if (tuple(e["a"]) in main and tuple(e["b"]) in main) else 0
    island = sum(1 for n in nodes if not n["main"])
    return {
        "region": "all",
        "stats": {
            "n_nodes": len(nodes), "n_edges": len(edges),
            "main_size": len(main), "n_components": len(comps),
            "n_island_nodes": island, "n_stitch": n_stitch,
        },
        "nodes": [{"id": n["id"], "lat": n["lat"], "lon": n["lon"],
                   "kv": n["kv"], "main": n["main"], "deg": n["deg"],
                   "sub": n["sub"], "name": n["name"], "region": n["region"]}
                  for n in nodes],
        # National: A-B segments only (no path) — keeps the payload loadable.
        "edges": [{"a": e["a"], "b": e["b"], "main": e["main"],
                   "kv": e["kv"], "par": e["par"]} for e in edges],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("regions", nargs="*", help="subset of regions (default: all + national)")
    ap.add_argument("--date", default=None, help="generated date stamp (YYYY-MM-DD)")
    ap.add_argument("--join-untagged-tips", action="store_true",
                    help="join untagged dead-end tower tips (ledger 132)")
    args = ap.parse_args()

    regions = args.regions or REGIONS_ALL
    do_national = not args.regions  # national only on a full run

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Output: {OUT_DIR}")

    collected = {}
    manifest_regions = []
    for r in regions:
        try:
            v = built_view(r, join_untagged_tips=args.join_untagged_tips)
        except Exception as ex:  # noqa: BLE001 — one region must not stop the rest
            print(f"  {r:<10s} ERROR: {ex}")
            continue
        if not v:
            print(f"  {r:<10s} (no data)")
            continue
        cnodes = _compact_nodes(v["nodes"])
        cedges = _compact_edges(v["edges"], with_path=True)
        stats = {
            "n_nodes": v["n_nodes"], "n_edges": v["n_edges"],
            "main_size": v["main_size"], "n_components": v["n_components"],
            "n_island_nodes": v["n_island_nodes"],
        }
        doc = {"region": r, "generated": args.date, "stats": stats,
               "nodes": cnodes, "edges": cedges}
        size = write_json(os.path.join(OUT_DIR, f"{r}.json"), doc)
        island_subs = sum(1 for n in cnodes if not n["main"] and n["sub"])
        print(f"  {r:<10s} {fmt(size):>9s}  nodes={stats['n_nodes']:>6d} "
              f"edges={stats['n_edges']:>6d} island_subs={island_subs:>4d}")
        # Keep the un-compacted view for the national merge (needs region-tagged copy).
        collected[r] = {"nodes": cnodes, "edges": _compact_edges(v["edges"], with_path=False)}
        manifest_regions.append({"id": r, "stats": stats})

    if do_national and collected:
        nat = build_national(collected)
        nat["generated"] = args.date
        size = write_json(os.path.join(OUT_DIR, "all.json"), nat)
        print(f"  {'all':<10s} {fmt(size):>9s}  nodes={nat['stats']['n_nodes']:>6d} "
              f"edges={nat['stats']['n_edges']:>6d} stitch={nat['stats']['n_stitch']} "
              f"islands={nat['stats']['n_island_nodes']}")
        manifest_regions.append({"id": "all", "stats": nat["stats"]})

    manifest = {"generated": args.date, "regions": manifest_regions}
    write_json(os.path.join(OUT_DIR, "index.json"), manifest)
    print("Done.")


if __name__ == "__main__":
    main()
