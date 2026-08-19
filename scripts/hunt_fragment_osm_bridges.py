#!/usr/bin/env python3
"""断片解消キャンペーン第一波 — OSM実線ブリッジの検出と回収.

原則(捏造ゼロ): 接続を「作る」のではなく、**OSMに実在する線(lines_all
40,087本)のうち、断片ノードと本系統ノードの両方に物理的に接触しているのに
built抽出で枝にならなかったもの**だけを、実線形ごと回収する。

判定: 同一featureのポリラインが
  - 断片ノードから TH_FRAG(80m) 以内 かつ
  - 本系統ノードから TH_MAIN(80m) 以内
を両方満たす(=その線が現に両者を跨いでいる)。電圧はfeature側が優先、
無タグなら端点ノードのkvを継承。1断片につき最良1本(距離和最小)。

併せて same_site 候補(断片ノード名の基底=本系統ノード名の基底・300m以内)を
**提案として**列挙する(適用はしない=判読/承認待ち)。

usage:
  PYTHONPATH=. python3 scripts/hunt_fragment_osm_bridges.py           # 検出のみ
  PYTHONPATH=. python3 scripts/hunt_fragment_osm_bridges.py --write   # 回収適用
出力: docs/data/fragments/evidence.json / --write時 all.json 追記
      (バックアップ=all.json.pre_frag.bak・介入#34)
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ISLAND_OF = {"hokkaido": "hokkaido", "tohoku": "east", "tokyo": "east",
             "chubu": "west", "hokuriku": "west", "kansai": "west",
             "chugoku": "west", "shikoku": "west", "kyushu": "west",
             "okinawa": "okinawa"}
TH_FRAG = 0.08   # km
TH_MAIN = 0.08   # km
CELL = 0.05      # deg


def k5(lat, lon):
    return (round(lat, 5), round(lon, 5))


def dist_km(a, b):
    return math.hypot((a[0] - b[0]) * 111.0,
                      (a[1] - b[1]) * 111.0 * math.cos(math.radians(a[0])))


def pt_seg_km(p, a, b):
    """点p と 線分ab の最短距離(km・小域近似)。座標=(lat,lon)。"""
    cx = math.cos(math.radians(p[0])) * 111.0
    px, py = p[1] * cx, p[0] * 111.0
    ax, ay = a[1] * cx, a[0] * 111.0
    bx, by = b[1] * cx, b[0] * 111.0
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def min_dist_to_path(p, path):
    return min(pt_seg_km(p, path[i], path[i + 1])
               for i in range(len(path) - 1)) if len(path) > 1 else \
        dist_km(p, path[0])


def norm_base(s):
    s = unicodedata.normalize("NFKC", str(s or "")).replace(" ", "")
    s = re.sub(r"(_\d+|\s*\d+kV)$", "", s)
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    nodes, edges = built["nodes"], built["edges"]
    lines = json.loads((ROOT / "docs/data/lines_all.geojson").read_text())["features"]

    # feature索引(セルグリッド)。geometryはLineString/MultiLineString
    feat_paths = []
    grid = defaultdict(list)
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
            cells = {(round(p[0] / CELL) * CELL, round(p[1] / CELL) * CELL)
                     for p in path}
            for c in cells:
                grid[(round(c[0], 2), round(c[1], 2))].append(pid)

    def cand_pids(p):
        c0 = (round(p[0] / CELL) * CELL, round(p[1] / CELL) * CELL)
        out = set()
        for dla in (-1, 0, 1):
            for dlo in (-1, 0, 1):
                out |= set(grid.get((round(c0[0] + dla * CELL, 2),
                                     round(c0[1] + dlo * CELL, 2)), []))
        return out

    existing = {frozenset((k5(*e["a"]), k5(*e["b"]))) for e in edges}

    bridges, same_site, summary = [], [], {}
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

        def near_main(path):
            """path上に本系統ノードがTH_MAIN以内にあるか → (main_k, d)"""
            best, bd = None, TH_MAIN
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

        n_br = n_ss = 0
        # 名前基底→本系統ノード索引(same_site用)
        mnames = defaultdict(list)
        for k in main_set:
            b = norm_base(keys[k].get("name"))
            if b and "junction" not in b:
                mnames[b].append(k)

        for comp in comps[1:]:
            best = None
            for fk in comp:
                fn = keys[fk]
                for pid in cand_pids(fk):
                    fi, path = feat_paths[pid]
                    d1 = min_dist_to_path(fk, path)
                    if d1 > TH_FRAG:
                        continue
                    mk, d2 = near_main(path)
                    if mk is None:
                        continue
                    if frozenset((fk, mk)) in existing:
                        continue
                    props = lines[fi].get("properties", {})
                    fkv = props.get("_voltage_kv")
                    # 電圧整合ゲート: 線kvが判明していて、断片/本系統ノードの
                    # kv(判明分)と>25%乖離なら除外 — 併架・並走回廊の偶然接触
                    # (500kV線が66kV断片に0mで触れる等)を回収しない
                    def _mis(nkv):
                        return (fkv and nkv and
                                abs(float(fkv) - float(nkv))
                                > max(float(nkv), 1.0) * 0.25)
                    if _mis(fn.get("kv")) or _mis(keys[mk].get("kv")):
                        continue
                    score = d1 + d2
                    if best is None or score < best["score"]:
                        best = {"score": round(score, 4), "island": island,
                                "frag": {"k": fk, "name": fn.get("name"),
                                         "kv": fn.get("kv")},
                                "main": {"k": mk, "name": keys[mk].get("name"),
                                         "kv": keys[mk].get("kv")},
                                "line_name": props.get("_display_name"),
                                "line_kv": fkv, "d_frag_m": round(d1 * 1000),
                                "d_main_m": round(d2 * 1000),
                                "path": path, "n_frag_nodes": len(comp)}
            if best:
                bridges.append(best)
                n_br += 1
            # same_site提案
            for fk in comp:
                b = norm_base(keys[fk].get("name"))
                if not b or "junction" in b:
                    continue
                for mk in mnames.get(b, []):
                    d = dist_km(fk, mk)
                    if d <= 0.3:
                        same_site.append({
                            "island": island, "frag_name": keys[fk].get("name"),
                            "main_name": keys[mk].get("name"),
                            "dist_m": round(d * 1000),
                            "frag_k": fk, "main_k": mk,
                            "n_frag_nodes": len(comp)})
                        n_ss += 1
        summary[island] = {"fragments": len(comps) - 1,
                           "osm_bridges": n_br, "same_site": n_ss}
        print(f"[{island}] 断片{len(comps)-1} → OSM実線ブリッジ{n_br} / "
              f"同一サイト提案{n_ss}")

    out = {"note": ("第一波の証拠: osm_bridges=OSM実在線が断片と本系統の両方に"
                    f"接触(≤{TH_FRAG*1000:.0f}m)しているのに枝が無い=抽出回収候補"
                    "(実線形つき)。same_site=名前基底一致・300m以内の同定提案"
                    "(適用は承認待ち)"),
           "summary": summary,
           "osm_bridges": [{k: v for k, v in b.items() if k != "path"}
                           for b in bridges],
           "same_site": same_site}
    dst = ROOT / "docs/data/fragments/evidence.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=list))
    print(f"-> {dst.relative_to(ROOT)}")

    if args.write and bridges:
        bak = ROOT / "docs/data/built/all.json.pre_frag.bak"
        bak.write_text(json.dumps(built, ensure_ascii=False))
        for b in bridges:
            fk, mk = b["frag"]["k"], b["main"]["k"]
            kv = b["line_kv"] or b["frag"]["kv"] or b["main"]["kv"] or 66.0
            path = [[fk[0], fk[1]]] + [[p[0], p[1]] for p in b["path"]] + \
                   [[mk[0], mk[1]]]
            built["edges"].append({
                "a": [fk[0], fk[1]], "b": [mk[0], mk[1]], "main": True,
                "par": 1, "kv": float(kv),
                "name": b["line_name"] or "OSM回収線",
                "path": path,
                "disclosure": ("OSM実線回収(fragment campaign 第一波 "
                               f"2026-08-20): 実在線が断片({b['d_frag_m']}m)と"
                               f"本系統({b['d_main_m']}m)の両方に接触"),
                "recovery": "osm_bridge"})
        (ROOT / "docs/data/built/all.json").write_text(
            json.dumps(built, ensure_ascii=False))
        print(f"★正典適用: {len(bridges)}本を回収 "
              f"(バックアップ={bak.name}・介入#34)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
