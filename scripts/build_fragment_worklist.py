#!/usr/bin/env python3
"""断片解消キャンペーンのワークリスト生成 — 孤立成分の素性+証拠候補の棚卸し.

オーナー方針(2026-08-20): 「孤立や島が繋がるように正典(証拠)を探しに行けると
いいね。OSMをよく見るのも、提案手法のEGGCでもいい」。

built正典のグラフを島(4同期島)ごとに成分分解し、非最大成分(=断片)について:
  - 素性: ノード数・電圧階級・代表名・重心
  - 最近傍ギャップ: 断片内ノード×本系統ノードの最短ペア(距離km・同kV優先)
    → OSM精査の照準(ギャップが短い=OSM欠測/抽出漏れの筆頭候補)
  - 証拠候補: 実証接続worklist(様式5由来)に断片ノードが現れるか
を集計し、証拠探索の優先順(サイズ×kV×ギャップ距離)で並べる。

出力:
  docs/data/fragments/worklist.json  (ビューア scripts/viz/fragment_triage.html 用)
  サマリはstdout。生成物はcommit対象(帳簿)。
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ISLAND_OF = {"hokkaido": "hokkaido", "tohoku": "east", "tokyo": "east",
             "chubu": "west", "hokuriku": "west", "kansai": "west",
             "chugoku": "west", "shikoku": "west", "kyushu": "west",
             "okinawa": "okinawa"}


def k5(lat, lon):
    return (round(lat, 5), round(lon, 5))


def hav_km(a, b):
    la1, lo1 = a
    la2, lo2 = b
    dla = math.radians(la2 - la1)
    dlo = math.radians(lo2 - lo1)
    x = (math.sin(dla / 2) ** 2 + math.cos(math.radians(la1))
         * math.cos(math.radians(la2)) * math.sin(dlo / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(x))


def main() -> int:
    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    nodes, edges = built["nodes"], built["edges"]

    # 実証接続worklist(残候補)のノードid集合
    wl_ids = defaultdict(list)
    try:
        wl = json.loads((ROOT / "docs/reports/"
                         "disclosure_connection_worklist_v2.json").read_text())
        for it in (wl.get("classes") and sum(wl["classes"].values(), [])) or []:
            pass
    except Exception:  # noqa: BLE001
        wl = {}
    # classes: {class名: [entries]} 形式/フラットlist両対応
    entries = []
    if isinstance(wl, dict):
        cl = wl.get("classes")
        if isinstance(cl, dict):
            for v in cl.values():
                entries.extend(v)
        elif isinstance(wl.get("items"), list):
            entries = wl["items"]
    for it in entries:
        for key in ("from_id", "to_id"):
            nid = it.get(key)
            if nid:
                wl_ids[nid].append(it.get("line") or it.get("class"))

    out_islands = {}
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
        # 成分分解
        seen = set()
        comps = []
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
        main_comp = comps[0]
        # 本系統ノードの粗グリッド索引
        grid = defaultdict(list)
        for k in main_comp:
            grid[(round(k[0], 1), round(k[1], 1))].append(k)

        def nearest_main(k, kv):
            best, bscore, bdist = None, 1e9, None
            g0 = (round(k[0], 1), round(k[1], 1))
            for dla in (-1, 0, 1):
                for dlo in (-1, 0, 1):
                    for m in grid.get((round(g0[0] + dla / 10.0, 1),
                                       round(g0[1] + dlo / 10.0, 1)), []):
                        d = hav_km(k, m)
                        mkv = float(keys[m].get("kv") or 0)
                        # 選定スコアのみ同kV優先(報告距離dは実距離のまま)
                        score = d - (0.5 if abs(mkv - kv)
                                     < max(kv, 1) * 0.2 else 0.0)
                        if score < bscore:
                            best, bscore, bdist = m, score, d
            return best, bdist

        frags = []
        for ci, comp in enumerate(comps[1:], 1):
            cn = [keys[k] for k in comp]
            kvs = sorted({round(float(n.get("kv") or 0)) for n in cn},
                         reverse=True)
            names = [n.get("name") for n in cn
                     if n.get("name") and "junction" not in str(n.get("name"))]
            lat = sum(n["lat"] for n in cn) / len(cn)
            lon = sum(n["lon"] for n in cn) / len(cn)
            # 断片内の各ノードから最近傍の本系統ノード
            best = None
            for k in comp:
                kv = float(keys[k].get("kv") or 0)
                m, d = nearest_main(k, kv)
                if m is not None and (best is None or d < best["gap_km"]):
                    best = {"gap_km": round(d, 2),
                            "frag_node": {"name": keys[k].get("name"),
                                          "kv": keys[k].get("kv"),
                                          "lat": k[0], "lon": k[1]},
                            "main_node": {"name": keys[m].get("name"),
                                          "kv": keys[m].get("kv"),
                                          "lat": m[0], "lon": m[1]}}
            wl_hits = sorted({ln for n in cn
                              for ln in wl_ids.get(n.get("id"), [])})
            frags.append({
                "island": island, "comp": ci, "n_nodes": len(comp),
                "kv": kvs, "centroid": [round(lat, 5), round(lon, 5)],
                "names": names[:5], "n_named": len(names),
                "nearest": best,
                "disclosure_worklist": wl_hits,
                "nodes": [{"lat": k[0], "lon": k[1],
                           "kv": keys[k].get("kv"),
                           "name": keys[k].get("name")} for k in comp],
            })
        # 優先度: 大きい×高kV×近ギャップ
        for f in frags:
            gap = (f["nearest"] or {}).get("gap_km") or 99
            f["priority"] = round(
                f["n_nodes"] * (1 + max(f["kv"] or [66]) / 200.0)
                / (1 + gap), 2)
        frags.sort(key=lambda f: -f["priority"])
        out_islands[island] = {
            "n_components": len(comps),
            "main_nodes": len(main_comp),
            "fragment_nodes": sum(len(c) for c in comps[1:]),
            "fragments": frags,
        }
        gaps = [f["nearest"]["gap_km"] for f in frags if f["nearest"]]
        near1 = sum(1 for g in gaps if g <= 1.0)
        near3 = sum(1 for g in gaps if g <= 3.0)
        wln = sum(1 for f in frags if f["disclosure_worklist"])
        print(f"[{island}] 成分{len(comps)} 本系統{len(main_comp)} "
              f"断片{len(frags)}個/{out_islands[island]['fragment_nodes']}ノード "
              f"| ギャップ≤1km:{near1} ≤3km:{near3} | worklist証拠あり:{wln}")

    out = {"generated": True,
           "note": ("断片解消キャンペーンのワークリスト。nearest=最近傍の"
                    "本系統ノード(同kV優先)。gap_kmが小さい=OSM欠測/抽出漏れ"
                    "の筆頭候補(OSM精査・EGGC照準)。disclosure_worklist="
                    "様式5実証接続の残候補に断片ノードが現れる場合の線名"),
           "islands": out_islands}
    dst = ROOT / "docs/data/fragments/worklist.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False))
    print(f"-> {dst.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
