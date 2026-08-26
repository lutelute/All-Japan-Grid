#!/usr/bin/env python3
"""偽断片スクリーニング — 跨island同座標双子による「断片=登録人工物」候補の機械列挙.

発端(2026-08-20 衛星判読パイロット c1): 甲府近郊の23ノード断片[west]は接続欠落では
なく、山梨県の東電66kV背骨が region=chubu で二重登録された人工物だった(11/23ノードに
同座標の tokyo 双子が存在し、tokyo 側は east 本系統に接続済み)。「なぜハンターが
拾わなかったか」の診断が偽断片検出器になる、の教訓を機械フィルタ化する。

オーナー方針(2026-08-20): 自動化のスコープは**候補列挙まで**。本スクリプトは正典
(built/all.json)を一切変更しない。読み取り→帳簿JSON+stdoutのみ。解消(双子への同定
/region再帰属)は1件ずつオーナー承認の別介入とする。

判定ロジック:
  - 島(4同期島)ごとの成分分解は build_fragment_worklist.py と同一の構築手順
    (k5キー・同島内の同座標はキー衝突で自然に融合)なので、(island, comp) の
    番号は worklist.json のエントリと一致する。
  - 断片内の各ノードについて、**別のisland**に同座標(k5)ノード(=双子)がいるか、
    さらにその双子が自島の本系統(最大成分)に属するかを数える。
  - twin_main(本系統接続済み双子)の比率が高い断片は「跨region二重登録による
    偽断片」候補。枝を張る前にノード衛生(同定/再帰属)を検討すべき対象。

出力:
  docs/data/fragments/false_fragment_screen.json  (候補台帳・commit対象)
  サマリはstdout。

Usage:
  PYTHONPATH=. python3 scripts/screen_false_fragments.py
  PYTHONPATH=. python3 scripts/screen_false_fragments.py --min-frac 0.2 --min-nodes 2
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# build_fragment_worklist.py と同一の island 帰属(変えると comp 番号がずれる)
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


def build_island_graph(nodes, edges, island):
    """build_fragment_worklist.py と同一手順で島グラフを構築し成分分解を返す."""
    regs = {r for r, i in ISLAND_OF.items() if i == island}
    keys = {}
    for n in nodes:
        if n.get("region") in regs:
            keys.setdefault(k5(n["lat"], n["lon"]), n)
    adj = defaultdict(set)
    for e in edges:
        ka, kb = k5(*e["a"]), k5(*e["b"])
        if ka in keys and kb in keys:
            adj[ka].add(kb)
            adj[kb].add(ka)
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
    return keys, comps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-frac", type=float, default=0.2,
                    help="候補判定: twin_main/ノード数の下限(既定0.2。c1は0.48)")
    ap.add_argument("--min-nodes", type=int, default=2,
                    help="候補判定: twin_main数の下限(既定2)")
    args = ap.parse_args()

    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    nodes, edges = built["nodes"], built["edges"]

    islands = ("hokkaido", "east", "west", "okinawa")
    keys_of, comps_of, main_of = {}, {}, {}
    for isl in islands:
        keys, comps = build_island_graph(nodes, edges, isl)
        keys_of[isl], comps_of[isl] = keys, comps
        main_of[isl] = comps[0] if comps else set()

    # 双子索引: k5座標 → {island: 代表ノード}(自島は島グラフのkeysが正)
    twin_idx = defaultdict(dict)
    for isl in islands:
        for k, n in keys_of[isl].items():
            twin_idx[k][isl] = n

    # worklist.json があれば priority を突き合わせる(無くても動く)
    prio = {}
    try:
        wl = json.loads((ROOT / "docs/data/fragments/worklist.json").read_text())
        for isl, blk in wl.get("islands", {}).items():
            for f in blk.get("fragments", []):
                prio[(isl, f["comp"])] = f.get("priority")
    except Exception:  # noqa: BLE001
        pass

    out_frags = []
    for isl in islands:
        keys, comps = keys_of[isl], comps_of[isl]
        for ci, comp in enumerate(comps[1:], 1):
            twin_main, twin_frag = [], []
            for k in comp:
                for oisl, tw in twin_idx[k].items():
                    if oisl == isl:
                        continue
                    if k in main_of[oisl]:
                        twin_main.append((k, oisl, tw))
                    else:
                        twin_frag.append((k, oisl, tw))
            if not twin_main and not twin_frag:
                continue
            frac = len(twin_main) / len(comp)
            cn = [keys[k] for k in comp]
            names = [n.get("name") for n in cn
                     if n.get("name") and "junction" not in str(n.get("name"))]
            regions = sorted({n.get("region") for n in cn})
            samples = [{"name": tw.get("name"), "kv": tw.get("kv"),
                        "frag_region": keys[k].get("region"),
                        "twin_island": oisl, "twin_region": tw.get("region"),
                        "lat": k[0], "lon": k[1]}
                       for k, oisl, tw in twin_main[:5]]
            out_frags.append({
                "island": isl, "comp": ci, "n_nodes": len(comp),
                "regions": regions,
                "names": names[:5], "n_named": len(names),
                "twin_main": len(twin_main), "twin_frag": len(twin_frag),
                "twin_main_frac": round(frac, 3),
                # 全ノードが本系統接続済み双子=断片まるごと二重登録 → 無条件候補
                # (1ノード断片の双子も k5≈1m 精度の同座標なので偶然一致はない)
                "suspect": (len(twin_main) == len(comp)
                            or (frac >= args.min_frac
                                and len(twin_main) >= args.min_nodes)),
                "worklist_priority": prio.get((isl, ci)),
                "twin_samples_main": samples,
            })

    out_frags.sort(key=lambda f: (-f["suspect"], -f["twin_main_frac"],
                                  -f["n_nodes"]))
    n_sus = sum(1 for f in out_frags if f["suspect"])
    sus_nodes = sum(f["n_nodes"] for f in out_frags if f["suspect"])

    print(f"双子を持つ断片: {len(out_frags)}件 / うち偽断片候補(suspect): "
          f"{n_sus}件 {sus_nodes}ノード "
          f"(閾値 twin_main_frac>={args.min_frac} & twin_main>={args.min_nodes})")
    for f in out_frags:
        if not (f["suspect"] or f["twin_main"] > 0):
            continue
        mark = "★" if f["suspect"] else " "
        pr = f["worklist_priority"]
        print(f" {mark} [{f['island']}] comp{f['comp']:>4} "
              f"{f['n_nodes']:>3}ノード twin_main={f['twin_main']:>3} "
              f"({f['twin_main_frac']:.0%}) twin_frag={f['twin_frag']:>3} "
              f"prio={pr if pr is not None else '-':>7} "
              f"{'/'.join(f['regions'])} {(f['names'] or ['?'])[0]}")

    out = {
        "note": ("偽断片スクリーニング(候補列挙のみ・正典不変更)。suspect=断片ノードの"
                 "twin_main_frac(別islandの本系統に接続済みの同座標双子の比率)が閾値超。"
                 "解消(双子への同定/region再帰属)は1件ずつオーナー承認の介入で行う。"
                 "発端=衛星判読パイロットc1(甲府66kV背骨のchubu二重登録, 2026-08-20)"),
        "params": {"min_frac": args.min_frac, "min_nodes": args.min_nodes},
        "n_suspect": n_sus, "n_suspect_nodes": sus_nodes,
        "fragments": out_frags,
    }
    dst = ROOT / "docs/data/fragments/false_fragment_screen.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"-> {dst.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
