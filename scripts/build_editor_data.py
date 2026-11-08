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
        rec = {
            "id": n["id"],
            "lat": n["lat"], "lon": n["lon"],
            "kv": round(float(n.get("kv") or 0), 1),
            "main": 1 if n.get("main") else 0,
            "deg": int(n.get("deg") or 0),
            "sub": 1 if n.get("sub") else 0,
            "name": n.get("name") or "",
        }
        # 出典透過(Phase 1-B): built_view のノード出典 {field:{src,url}} を
        # 正典 docs/data/built まで運ぶ(無い節点では省略=バイト増ゼロ)。
        if n.get("src"):
            rec["src"] = n["src"]
        out.append(rec)
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
        # OSM線名を保持(系統図の線一覧/ポップアップ・SLD等で実名表示に使う)。
        # 空名は省略してバイト節約。built_view が ln.name を付与済(L128)。
        nm = e.get("name")
        if nm:
            rec["name"] = nm
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

    # Phase3: 連結性は単一権威(src.powerflow.connectivity)で計算 = built_view_all / national.py と統一。
    # 周波数島(東50/西60を別)・同電圧階級stitch(~110m)・OCCTO ACタイ。pandapower非依存。
    from src.powerflow.connectivity import compute_connectivity
    conn = compute_connectivity(nodes, edges)
    main = conn["main_keys"]
    for n in nodes:
        n["main"] = 1 if k5(n["lat"], n["lon"]) in main else 0
    for e in edges:
        if e.get("a") and e.get("b"):
            e["main"] = 1 if (tuple(e["a"]) in main and tuple(e["b"]) in main) else 0
    # ACタイを表示枝に追加(島内 region 対の物理連系)
    for ka, kb, tname in conn["tie_edges"]:
        edges.append({"a": list(ka), "b": list(kb), "par": 1, "kv": 0,
                      "main": 1 if (ka in main and kb in main) else 0,
                      "path": [list(ka), list(kb)], "tie": 1, "name": tname})
    meta = conn["meta"]
    island = sum(1 for n in nodes if not n["main"])
    return {
        "region": "all",
        "stats": {
            "n_nodes": len(nodes), "n_edges": len(edges),
            "main_size": len(main), "n_components": sum(meta["components"].values()),
            "n_island_nodes": island, "n_stitch": meta["n_stitch"],
            "n_tie": meta["n_tie"], "islands": meta["components"],
        },
        "nodes": [{"id": n["id"], "lat": n["lat"], "lon": n["lon"],
                   "kv": n["kv"], "main": n["main"], "deg": n["deg"],
                   "sub": n["sub"], "name": n["name"], "region": n["region"]}
                  | ({"src": n["src"]} if n.get("src") else {})
                  for n in nodes],
        # National: OSM幾何(path)込み — :8088の built_view_all と同一表現に統一。
        # path省略の直線(弦)描画だと長距離枝が斜めに交差して「無茶苦茶接続」に見えるため。
        "edges": [({"a": e["a"], "b": e["b"], "main": e["main"], "kv": e["kv"],
                    "par": e["par"]} | ({"path": e["path"]} if e.get("path") else {})
                   | ({"tie": 1} if e.get("tie") else {})
                   | ({"name": e["name"]} if e.get("name") else {}))
                  for e in edges],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("regions", nargs="*", help="subset of regions (default: all + national)")
    ap.add_argument("--date", default=None, help="generated date stamp (YYYY-MM-DD)")
    ap.add_argument("--join-untagged-tips", action="store_true",
                    help="join untagged dead-end tower tips (ledger 132)")
    ap.add_argument("--region-dedup", action=argparse.BooleanOptionalAction, default=None,
                    help="介入#58(案) 地域をまたぐ写し(頂点まで同じ形の枝が 2 つ以上の地域から出る)を全国でまとめる前に 1 つにする。"
                         "既定=region_dedup.REGION_DEDUP_DEFAULT(環境変数 AJG_REGION_DEDUP=1/0)")
    ap.add_argument("--region-dedup-ends", action=argparse.BooleanOptionalAction, default=None,
                    help="介入#59(案) 形が同じで端を結ぶ点だけが違う地域の写しの端の点を、#58 の前に 1 つに寄せる。"
                         "既定=region_dedup.END_ALIGN_DEFAULT(環境変数 AJG_REGION_DEDUP_ENDS=1/0)")
    ap.add_argument("--region-dedup-splits", action=argparse.BooleanOptionalAction, default=None,
                    help="介入#60(案) 区切りの違う地域の写しの区切りを #59 の前にそろえ、#58 のあとに要らなくなった区切りを戻す。"
                         "既定=region_dedup.SPLIT_ALIGN_DEFAULT(環境変数 AJG_REGION_DEDUP_SPLITS=1/0)")
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
        # Keep for the national merge (path込み = :8088と同一表現に統一)。
        collected[r] = {"nodes": cnodes, "edges": _compact_edges(v["edges"], with_path=True)}
        manifest_regions.append({"id": r, "stats": stats})

    if do_national and collected:
        # 介入#58(案): 地域をまたぐ写しを 1 つにまとめる(src/topology/region_dedup.py)。地域ごとの正典(<地域>.json)は変えない
        from src.topology.region_dedup import (END_ALIGN_DEFAULT, REGION_DEDUP_DEFAULT, SPLIT_ALIGN_DEFAULT,
                                               align_copy_ends, align_copy_splits, dedup_region_copies,
                                               heal_copy_splits)
        if args.region_dedup if args.region_dedup is not None else REGION_DEDUP_DEFAULT:
            led_ends = led_splits = None
            # 介入#60(案): 区切りの違う写しの区切りをそろえる(#59・#58 の前)
            if args.region_dedup_splits if args.region_dedup_splits is not None else SPLIT_ALIGN_DEFAULT:
                collected, led_splits = align_copy_splits(collected)
                print(f"  介入#60 region-dedup-splits: 枝 {led_splits['n_edges_split']} を {led_splits['n_pieces']} 本に区切り、"
                      f"点 {led_splits['n_nodes_made']} を作った(電圧の違う頂点 {led_splits['n_points_skipped_kv']}・"
                      f"島の違う区切り {led_splits['n_skipped_island']} は区切らない)")
            # 介入#59(案): 端を結ぶ点だけが違う写しの端の点を寄せてから、#58 でまとめる
            if args.region_dedup_ends if args.region_dedup_ends is not None else END_ALIGN_DEFAULT:
                collected, led_ends = align_copy_ends(collected)
                print(f"  介入#59 region-dedup-ends: 端の点 {led_ends['n_points_aliased']} を寄せ、枝の端 "
                      f"{led_ends['n_edge_ends_repointed']} を書き換え、両端が同じ点になった枝 {led_ends['n_edges_collapsed']} を消した")
            collected, led = dedup_region_copies(collected)
            if led_ends is not None:
                led["ends"] = led_ends
            if led_splits is not None:
                collected, led_heal = heal_copy_splits(collected)
                led_splits.update(led_heal)
                led["splits"] = led_splits
                print(f"  介入#60 region-dedup-splits: 継ぎ目 {led_heal['n_joints_healed']} をつなぎ直し、"
                      f"区切りの点 {led_heal['n_split_nodes_left']} が残った")
            lp = os.path.join(PROJECT_ROOT, "docs", "data", "fragments", "region_dedup_ledger.json")
            os.makedirs(os.path.dirname(lp), exist_ok=True)
            with open(lp, "w", encoding="utf-8") as fh:
                json.dump(led, fh, ensure_ascii=False, indent=1)
            print(f"  介入#58 region-dedup: 写し {led['n_groups']} 組・枝 {led['n_edges_dropped']}・点 {led['n_nodes_dropped']} を落とし、"
                  f"電圧を写しから補った枝 {led['n_kv_filled']}")
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
