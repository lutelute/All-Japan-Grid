#!/usr/bin/env python3
"""D4 island audit — 小規模islandを物理接続の観点で判定する(計測のみ・本番不変)。

物理接続=真の原則(owner directive 2026-06-13「真や正は計算ではなく物理接続。
そこからおかしいと判断されるところは接続方法や計算で確かめる」)。

各島(最大連結成分=主系統 以外の連結成分)について、主系統への最寄り距離を測り
  - near (<= near_km)      : 物理的に近接 — snap/join調整 or 既存データ内の実在線で
                             救える候補(「おかしい」= 近いのに切れている → 接続方法で確認)
  - mid  (near_km..far_km) : 中距離 — OSM続線取得(I3)で実在線を探す候補
  - far  (> far_km)        : 遠隔 — 真の孤立の可能性(捏造禁止、離島/山間は個別確認)
に分類してJSON出力する。

さらに near 島は「島側電圧クラス × 主系統側最寄りノード電圧クラス」のペアで層別する:
  - same  (同クラス, kv>0): 同電圧で近接して切れている = 接続方法のバグ候補(物理接続すべき)
  - cross (異クラス, 両kv>0): 異電圧の近接 = 変電所(要変圧器) か 立体交差(繋いではいけない)
  - unk   (どちらか kv=0)  : 電圧不明が絡む — 名称/ポリゴン証拠での判定行き

    PYTHONPATH=. python3 scripts/d4_island_audit.py --region tokyo --out docs/reports/island_audit_tokyo.json
"""
import sys
import json
import math
import argparse
from collections import Counter

import numpy as np
import networkx as nx
from scipy.spatial import cKDTree

from src.powerflow.snapped_topology import build_network_snapped


def _to_xy(lat: float, lon: float):
    """局所平面近似(km)。日本緯度帯で最寄り距離の比較に十分。"""
    return (lon * 111.0 * math.cos(math.radians(lat)), lat * 111.0)


def _pair_kind(ikv, mkv) -> str:
    if not ikv or not mkv:
        return "unk"
    return "same" if abs(ikv - mkv) < 1e-6 else "cross"


def audit(region: str, near_km: float = 1.5, far_km: float = 5.0):
    net = build_network_snapped(region)
    if net is None:
        return None
    pos = {s.id: (s.latitude, s.longitude) for s in net.substations}
    kv = {s.id: float(s.voltage_kv) for s in net.substations}
    g = nx.Graph()
    g.add_nodes_from(s.id for s in net.substations)
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    if not comps:
        return None
    main = comps[0]
    islands = comps[1:]
    # ソートで決定化(connected_components の set 順序依存のタイブレークを排除)
    main_ids = sorted(n for n in main if n in pos)
    main_xy = np.array([_to_xy(*pos[n]) for n in main_ids])
    tree = cKDTree(main_xy)

    buckets = {"near": [], "mid": [], "far": []}
    for isl in islands:
        ids = [n for n in isl if n in pos]
        if not ids:
            continue
        ixy = np.array([_to_xy(*pos[n]) for n in ids])
        d, idx = tree.query(ixy)
        k = int(d.argmin())
        mind = float(d[k])
        main_node = main_ids[idx[k]]
        ml = main_xy[idx[k]]
        main_lat = ml[1] / 111.0
        main_lon = ml[0] / (111.0 * math.cos(math.radians(main_lat)))
        ikv = kv.get(ids[k])
        mkv = kv.get(main_node)
        n_real = sum(1 for n in isl if "_jct_" not in n)
        rec = {
            "n_nodes": len(isl),
            "n_real_subs": n_real,
            "min_km_to_main": round(mind, 3),
            "island_pt": [round(pos[ids[k]][0], 5), round(pos[ids[k]][1], 5)],
            "main_pt": [round(main_lat, 5), round(main_lon, 5)],
            "island_kv": ikv,
            "main_kv": mkv,
            "pair": _pair_kind(ikv, mkv),
            "sample_id": ids[k],
            "main_id": main_node,
        }
        b = "near" if mind <= near_km else ("mid" if mind <= far_km else "far")
        buckets[b].append(rec)
    for b in buckets:
        buckets[b].sort(key=lambda r: r["min_km_to_main"])

    near_pairs = Counter(r["pair"] for r in buckets["near"])
    near_kv_pairs = Counter(
        (r["island_kv"], r["main_kv"]) for r in buckets["near"]
    )
    summary = {
        "region": region,
        "n_components": len(comps),
        "main_size": len(main),
        "n_islands": len(islands),
        "near_km": near_km,
        "far_km": far_km,
        "counts": {b: len(v) for b, v in buckets.items()},
        "island_nodes_total": sum(len(c) for c in islands),
        "island_real_subs_total": sum(
            1 for c in islands for n in c if "_jct_" not in n
        ),
        "near_pair_kinds": dict(near_pairs),
        "near_kv_pairs": {f"{i}->{m}": n for (i, m), n in near_kv_pairs.most_common()},
    }
    return summary, buckets


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="tokyo")
    ap.add_argument("--near-km", type=float, default=1.5)
    ap.add_argument("--far-km", type=float, default=5.0)
    ap.add_argument("--out")
    ap.add_argument("--top", type=int, default=15, help="print N nearest islands")
    a = ap.parse_args(argv)
    res = audit(a.region, a.near_km, a.far_km)
    if res is None:
        print("no network")
        return 1
    summary, buckets = res
    print(json.dumps(summary, ensure_ascii=False))
    print(f"\n-- near (<= {a.near_km}km) 電圧ペア層別 --")
    print(f"   same(同電圧で切断=接続バグ候補): {summary['near_pair_kinds'].get('same', 0)}")
    print(f"   cross(異電圧=変電所/立体交差): {summary['near_pair_kinds'].get('cross', 0)}")
    print(f"   unk(電圧不明絡み): {summary['near_pair_kinds'].get('unk', 0)}")
    print(f"\n-- same(同電圧)近接島 top {a.top}: 物理接続すべき最有力 --")
    same = [r for r in buckets["near"] if r["pair"] == "same"]
    for r in same[: a.top]:
        print(
            f"  {r['min_km_to_main']:.3f}km  kv={r['island_kv']:.0f}  nodes={r['n_nodes']}"
            f"  island@{r['island_pt']} -> main@{r['main_pt']}  {r['sample_id']}"
        )
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "buckets": buckets}, fh,
                      ensure_ascii=False, indent=1)
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
