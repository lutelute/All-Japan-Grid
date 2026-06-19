#!/usr/bin/env python3
"""SLD(単線結線図 force-graph)データを **正典 built + powerflow_full** から生成 (idempotent)。

    PYTHONPATH=. python scripts/gen_sld_from_built.py

背景
----
`docs/js/sld.js`(系統図の「SLD」タブ = Obsidian 風 force-directed グラフ)は
`docs/data/powerflow/sld_data.json` を読んでいた。これは psdat 縮約モデル由来で、
DB 更新前の旧世代。per-region/"all"/national_backbone が正典化された今、SLD だけ
旧縮約に取り残されていた([[project_agj_pages_canon_audit]] の③)。

本スクリプトは SLD データを正典トポロジ `docs/data/built/all.json`(17,333ノード)から
生成する。**全電圧を収録**し、sld.js 側の電圧帯フィルタ + グリッド近似 force-sim で
表示制御する(オーナー選択「全電圧・フィルタ制御」)。枝の loading は powerflow_full
(全規模 AC)の line から端点ペア突合で付与(縮約でない実潮流率)。

入力 (読み取り専用)
-------------------
docs/data/built/all.json                           : nodes(bus) + edges(branch)
docs/data/powerflow_full/{region}_ac_lines.geojson : loading_pct(端点突合で枝へ付与)
docs/data/generators.geojson                       : 発電機接続(座標突合で bus.gen)

出力 (上書き)
-------------
docs/data/powerflow_full/sld_data.json
  { buses:[{id,name,kv,lon,lat,gen}], branches:[{from,to,loading,xfmr}] }
  branches: built edge(xfmr=false) + 同一地点異電圧ペア(xfmr=true=変圧器)。

捏造防止: loading が引けない枝は 0(=未計算扱い・太さ最小)。vm/Pd は built に無く
sld.js も非表示(flat-start を計算結果に見せない)。gen は generators 実在座標のみ。
"""
import glob
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILT_ALL = os.path.join(ROOT, "docs", "data", "built", "all.json")
FULL = os.path.join(ROOT, "docs", "data", "powerflow_full")
GEN = os.path.join(ROOT, "docs", "data", "generators.geojson")
OUT = os.path.join(FULL, "sld_data.json")

COORD_PRECISION = 4


def r(x):
    return round(float(x), COORD_PRECISION)


def bracket(kv):
    """実 kv を sld.js の表示帯(500/275/154/110/77/66・不明=0)へ丸める(grid_map 同様)。
    220/187kV→154帯, 132kV→110帯 等。実 kv は bus.kv に保持(tooltip 用)。"""
    kv = float(kv)
    if kv >= 500:
        return 500
    if kv >= 275:
        return 275
    if kv >= 154:
        return 154
    if kv >= 110:
        return 110
    if kv >= 77:
        return 77
    if kv >= 22:
        return 66
    return 0


def main():
    if not os.path.exists(BUILT_ALL):
        print(f"ERROR: {BUILT_ALL} not found", file=sys.stderr)
        return 1
    with open(BUILT_ALL, encoding="utf-8") as f:
        built = json.load(f)
    nodes = built["nodes"]
    edges = built["edges"]

    # node id index: (lat4, lon4, kv) -> id (変圧器ペアは異 kv なので衝突しない)
    nid = {}
    for n in nodes:
        nid[(r(n["lat"]), r(n["lon"]), round(float(n["kv"])))] = n["id"]

    # loading 供給: powerflow_full line の端点ペアキー -> loading_pct(max)
    edge_load = {}
    n_pf_line = 0
    for lf in sorted(glob.glob(os.path.join(FULL, "*_ac_lines.geojson"))):
        if os.path.basename(lf).startswith("national_overview"):
            continue
        with open(lf, encoding="utf-8") as f:
            for ft in json.load(f)["features"]:
                c = (ft.get("geometry") or {}).get("coordinates")
                if not c or len(c) < 2:
                    continue
                n_pf_line += 1
                a = (r(c[0][1]), r(c[0][0]))     # geojson [lon,lat] -> (lat,lon)
                b = (r(c[-1][1]), r(c[-1][0]))
                key = tuple(sorted([a, b]))
                ld = ft["properties"].get("loading_pct")
                if ld is not None:
                    edge_load[key] = max(edge_load.get(key, 0.0), float(ld))

    # gen: generators 座標(4桁) 集合 -> bus.gen
    gen_coords = set()
    if os.path.exists(GEN):
        with open(GEN, encoding="utf-8") as f:
            for ft in json.load(f)["features"]:
                c = (ft.get("geometry") or {}).get("coordinates")
                if c and len(c) >= 2:
                    gen_coords.add((round(float(c[1]), 3), round(float(c[0]), 3)))

    # buses: 全ノード
    buses = []
    n_gen = 0
    for n in nodes:
        is_gen = (round(float(n["lat"]), 3), round(float(n["lon"]), 3)) in gen_coords
        if is_gen:
            n_gen += 1
        buses.append({
            "id": n["id"],
            "name": n.get("name") or n["id"],
            "kv": round(float(n["kv"])),
            "tier": bracket(n["kv"]),
            "lon": round(float(n["lon"]), 5),
            "lat": round(float(n["lat"]), 5),
            "gen": is_gen,
        })

    # branches: built edge(線) + loading 突合
    branches = []
    n_unmatched_end = n_load_hit = 0
    for e in edges:
        a = (r(e["a"][0]), r(e["a"][1]))
        b = (r(e["b"][0]), r(e["b"][1]))
        kv = round(float(e["kv"]))
        fr = nid.get((a[0], a[1], kv))
        to = nid.get((b[0], b[1], kv))
        if not fr or not to:
            n_unmatched_end += 1
            continue
        key = tuple(sorted([a, b]))
        ld = edge_load.get(key, 0.0)
        if ld:
            n_load_hit += 1
        branches.append({"from": fr, "to": to, "loading": round(ld, 1), "xfmr": False})

    # 変圧器枝: 同一座標(4桁)異電圧ノードを kv 昇順で隣接接続
    bycoord = defaultdict(list)
    for n in nodes:
        bycoord[(r(n["lat"]), r(n["lon"]))].append(n)
    n_xfmr = 0
    for group in bycoord.values():
        if len(group) < 2:
            continue
        gs = sorted(group, key=lambda x: float(x["kv"]))
        for i in range(len(gs) - 1):
            if round(float(gs[i]["kv"])) != round(float(gs[i + 1]["kv"])):
                branches.append({"from": gs[i]["id"], "to": gs[i + 1]["id"],
                                 "loading": 0, "xfmr": True})
                n_xfmr += 1

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"buses": buses, "branches": branches},
                  f, ensure_ascii=False, separators=(",", ":"))

    print("=== SLD data (正典 built + powerflow_full 由来) ===")
    print(f"buses: {len(buses)} (gen={n_gen})")
    print(f"branches: {len(branches)} (line={len(branches) - n_xfmr}, xfmr={n_xfmr})")
    print(f"  loading 付与(powerflow_full {n_pf_line} line): hit={n_load_hit} "
          f"/ {len(branches) - n_xfmr} line branches")
    print(f"  edge 端点 unmatched(skip): {n_unmatched_end}")
    # 電圧帯別 bus 数(force-sim の表示制御の目安)
    from collections import Counter
    kvc = Counter(b["kv"] for b in buses)
    print("  bus kv 分布:", dict(sorted(kvc.items(), reverse=True)))
    # JSON 妥当性
    try:
        with open(OUT, encoding="utf-8") as f:
            d = json.load(f)
        assert "buses" in d and "branches" in d
        print(f"  JSON valid: True  ({os.path.getsize(OUT) // 1024} KB)")
    except Exception as exc:  # noqa: BLE001
        print(f"  JSON INVALID: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
