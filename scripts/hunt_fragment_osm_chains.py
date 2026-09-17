#!/usr/bin/env python3
"""断片解消キャンペーン第二波 — OSM way連鎖の追跡回収.

オーナー観察(2026-08-20): 「断片化しているところはOSMをよく見るとカクカクの
線(実線形)が見えるところも多い。つまり線は存在している。ただしkm離れた
ところを(直線で)接続するのは良くない」。

第一波(hunt_fragment_osm_bridges)は「1本のOSM線が断片と本系統の両方に接触」
のみ回収した。第二波は**複数のOSM way に分かれた実線形の連鎖**を辿る:

  断片ノード →(≤80m)→ way1 →(継ぎ目≤60m)→ way2 → … →(≤80m)→ 本系統ノード

- 辿るのは lines_all の実線形のみ。継ぎ目(way端点間・T字接触)は各≤60m
  = km級の直線ジャンプは構造的に発生しない(総延長が長くても実線)
- 電圧整合ゲート: 連鎖中のkv判明wayが断片/本系統ノードkvと>25%乖離なら棄却
- 連鎖は最大6way・1断片につき最良1本(way数→総継ぎ目長の順で最小)

usage:
  PYTHONPATH=. python3 scripts/hunt_fragment_osm_chains.py           # 検出のみ
  PYTHONPATH=. python3 scripts/hunt_fragment_osm_chains.py --write   # 回収適用
出力: docs/data/fragments/evidence_chains.json / --write時 all.json 追記
      (recovery="osm_chain"・バックアップ=all.json.pre_frag2.bak・介入#34追補)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.hunt_fragment_osm_bridges import (  # noqa: E402
    ISLAND_OF, clip_path, dist_km, k5, min_dist_to_path, nearest_vertex_idx)

TH_NODE = 0.08    # ノード⇔way接触 km
TH_JOIN = 0.06    # way⇔way継ぎ目 km
MAX_WAYS = 6
CELL = 0.05


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    nodes, edges = built["nodes"], built["edges"]
    lines = json.loads((ROOT / "docs/data/lines_all.geojson").read_text())["features"]

    feat_paths = []           # (feature_idx, path[(lat,lon)])
    grid = defaultdict(list)  # path cell -> pid
    for fi, f in enumerate(lines):
        g = f.get("geometry") or {}
        cc = g.get("coordinates") or []
        parts = [cc] if g.get("type") == "LineString" else cc
        for part in parts:
            path = [(c[1], c[0]) for c in part if isinstance(c, (list, tuple))]
            if len(path) < 2:
                continue
            pid = len(feat_paths)
            feat_paths.append((fi, path))
            cells = {(round(p[0], 2), round(p[1], 2)) for p in path}
            for c in cells:
                grid[c].append(pid)

    def cand_pids(p):
        out = set()
        c0 = (round(p[0], 2), round(p[1], 2))
        for dla in range(-3, 4):
            for dlo in range(-3, 4):
                out |= set(grid.get((round(c0[0] + dla / 100.0, 2),
                                     round(c0[1] + dlo / 100.0, 2)), []))
        return out

    def way_kv(pid):
        v = lines[feat_paths[pid][0]].get("properties", {}).get("_voltage_kv")
        try:
            return float(v) if v else None
        except (TypeError, ValueError):
            return None

    # way⇔way隣接(端点が相手のpathに≤TH_JOIN) — 端点のみで判定(T字含む)
    print("way連鎖グラフ構築中...", flush=True)
    way_adj = defaultdict(dict)   # pid -> {pid2: (anchor_self, anchor_other, gap_km)}
    for pid, (_, path) in enumerate(feat_paths):
        for ep in (path[0], path[-1]):
            for pid2 in cand_pids(ep):
                if pid2 == pid or pid2 in way_adj[pid]:
                    continue
                p2 = feat_paths[pid2][1]
                d = min_dist_to_path(ep, p2)
                if d <= TH_JOIN:
                    j = nearest_vertex_idx(ep, p2)
                    way_adj[pid][pid2] = (ep, p2[j], round(d * 1000))
                    way_adj[pid2][pid] = (p2[j], ep, round(d * 1000))
    print(f"way {len(feat_paths)}本 / 隣接ペア {sum(len(v) for v in way_adj.values())//2}", flush=True)

    existing = {frozenset((k5(*e["a"]), k5(*e["b"]))) for e in edges}

    chains, summary = [], {}
    for island in ("hokkaido", "east", "west", "okinawa"):
        regs = {r for r, i in ISLAND_OF.items() if i == island}
        isl_nodes = [n for n in nodes if n.get("region") in regs]
        keys = {}
        for n in isl_nodes:
            keys.setdefault(k5(n["lat"], n["lon"]), n)
        adj = defaultdict(set)
        for e in edges:
            ka, kb = k5(*e["a"]), k5(*e["b"])
            if ka in keys and kb in keys:
                adj[ka].add(kb)
                adj[kb].add(ka)
        seen, comps = set(), []
        for k in keys:
            if k in seen:
                continue
            stack, comp = [k], set()
            while stack:
                c = stack.pop()
                if c in comp:
                    continue
                comp.add(c)
                stack.extend(adj[c] - comp)
            seen |= comp
            comps.append(comp)
        comps.sort(key=len, reverse=True)
        main_set = comps[0]
        mgrid = defaultdict(list)
        for k in main_set:
            mgrid[(round(k[0], 1), round(k[1], 1))].append(k)

        def main_contact(path):
            best, bd = None, TH_NODE
            cells = {(round(p[0], 1), round(p[1], 1)) for p in path}
            cand = set()
            for c in cells:
                for dla in (-1, 0, 1):
                    for dlo in (-1, 0, 1):
                        cand |= set(mgrid.get((round(c[0] + dla / 10, 1),
                                               round(c[1] + dlo / 10, 1)), []))
            for m in cand:
                d = min_dist_to_path(m, path)
                if d < bd:
                    best, bd = m, d
            return best, bd

        def kv_ok(pid, nkv):
            wkv = way_kv(pid)
            return not (wkv and nkv and
                        abs(wkv - float(nkv)) > max(float(nkv), 1.0) * 0.25)

        n_found = 0
        for comp in comps[1:]:
            best = None
            for fk in comp:
                fkv = keys[fk].get("kv")
                seeds = []
                for pid in cand_pids(fk):
                    d = min_dist_to_path(fk, feat_paths[pid][1])
                    if d <= TH_NODE and kv_ok(pid, fkv):
                        seeds.append((pid, d))
                if not seeds:
                    continue
                # BFS(way数最小)
                from collections import deque
                q = deque()
                visited = {}
                for pid, d in sorted(seeds, key=lambda x: x[1]):
                    q.append((pid, [pid], 0.0))
                    visited[pid] = 0
                while q:
                    pid, route, stitch = q.popleft()
                    if len(route) > MAX_WAYS:
                        continue
                    mk, dmain = main_contact(feat_paths[pid][1])
                    if mk is not None and frozenset((fk, mk)) not in existing \
                            and kv_ok(pid, keys[mk].get("kv")):
                        cand = {"n_ways": len(route), "stitch_m": round(stitch * 1000),
                                "route": route, "fk": fk, "mk": mk,
                                "d_frag_m": round(min_dist_to_path(
                                    fk, feat_paths[route[0]][1]) * 1000),
                                "d_main_m": round(dmain * 1000)}
                        if best is None or (cand["n_ways"], cand["stitch_m"]) < \
                                (best["n_ways"], best["stitch_m"]):
                            best = cand
                        break   # このseedの最短で十分(BFS=way数最小)
                    for pid2, (a1, a2, gap) in way_adj[pid].items():
                        if pid2 in visited or not kv_ok(pid2, fkv):
                            continue
                        visited[pid2] = len(route)
                        q.append((pid2, route + [pid2], stitch + gap / 1000.0))
            if best and best["n_ways"] >= 2:      # 1way=第一波の領分
                fi0 = feat_paths[best["route"][0]][0]
                names = [lines[feat_paths[p][0]]["properties"].get("_display_name")
                         for p in best["route"]]
                # 経路構築: way連鎖を接触点間で切り出して連結
                fk, mk = best["fk"], best["mk"]
                pts = []
                anchor = fk
                for i, pid in enumerate(best["route"]):
                    path = feat_paths[pid][1]
                    if i < len(best["route"]) - 1:
                        nxt = way_adj[pid][best["route"][i + 1]][0]
                    else:
                        j = nearest_vertex_idx(mk, path)
                        nxt = path[j]
                    seg = clip_path(path, anchor, nxt)
                    pts.extend(seg)
                    anchor = nxt
                chains.append({**{k: v for k, v in best.items() if k != "route"},
                               "island": island,
                               "names": names,
                               "frag_name": keys[fk].get("name"),
                               "frag_kv": keys[fk].get("kv"),
                               "main_name": keys[mk].get("name"),
                               "main_kv": keys[mk].get("kv"),
                               "n_frag_nodes": len(comp),
                               "path": pts})
                n_found += 1
        summary[island] = n_found
        print(f"[{island}] 連鎖回収候補 {n_found}", flush=True)

    out = {"note": ("第二波: 複数OSM wayの実線形連鎖(継ぎ目各≤60m・最大6way・"
                    "電圧整合ゲート)で断片→本系統。直線ジャンプなし"),
           "summary": summary,
           "chains": [{k: v for k, v in c.items() if k != "path"}
                      for c in chains]}
    (ROOT / "docs/data/fragments/evidence_chains.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=list))
    print("-> docs/data/fragments/evidence_chains.json")

    if args.write and chains:
        bak = ROOT / "docs/data/built/all.json.pre_frag2.bak"
        bak.write_text(json.dumps(built, ensure_ascii=False))
        for c in chains:
            fk, mk = c["fk"], c["mk"]
            kv = c["frag_kv"] or c["main_kv"] or 66.0
            path = [[fk[0], fk[1]]] + [[p[0], p[1]] for p in c["path"]] + \
                   [[mk[0], mk[1]]]
            nm = " / ".join(str(n) for n in c["names"] if n)[:60]
            built["edges"].append({
                "a": [fk[0], fk[1]], "b": [mk[0], mk[1]], "main": True,
                "par": 1, "kv": float(kv), "name": nm or "OSM連鎖回収線",
                "path": path,
                "disclosure": (f"OSM実線連鎖回収(第二波): {c['n_ways']}way・"
                               f"継ぎ目計{c['stitch_m']}m・"
                               f"接触{c['d_frag_m']}m/{c['d_main_m']}m"),
                "recovery": "osm_chain"})
        (ROOT / "docs/data/built/all.json").write_text(
            json.dumps(built, ensure_ascii=False))
        print(f"★正典適用: {len(chains)}本(連鎖)を回収 (バックアップ={bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
