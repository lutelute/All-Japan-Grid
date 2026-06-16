"""島の実変電所(名前つき・本系統に未接続)を全国で census する。

オーナー観察(2026-06-16): 送電網モデルで「島」と表示される変電所の多くは、衛星確認すると
鉄道き電用・配電用・地下変電所など**別系統**のものが多い(送電網の連系欠落ではない)。
本スクリプトは島の実変電所を一覧化し、Web調査(種別分類)の入力にする。
鉄塔分岐(junction `_jct_`)は変電所でないので除外、名前つきの実変電所のみ。

Usage:
    PYTHONPATH=. python scripts/island_substations.py --out docs/reports/island_substations_<date>.json
"""
import argparse
import collections
import json

import networkx as nx

from src.powerflow.snapped_topology import build_network_snapped

REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
           "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]


def census(regions=None):
    regions = regions or REGIONS
    out = []
    for r in regions:
        try:
            net = build_network_snapped(r, db=None)
        except Exception:   # noqa: BLE001
            continue
        g = nx.Graph()
        g.add_nodes_from(s.id for s in net.substations)
        for ln in net.transmission_lines:
            g.add_edge(ln.from_substation_id, ln.to_substation_id)
        comps = sorted(nx.connected_components(g), key=len, reverse=True)
        main = set(comps[0]) if comps else set()
        for s in net.substations:
            if s.id in main or "_jct_" in s.id:
                continue                       # 本系統 or 鉄塔分岐は除外
            if not (s.name and s.name.strip()):
                continue                       # 名前つき実変電所のみ
            out.append({"region": r, "name": s.name,
                        "lat": round(s.latitude, 5), "lon": round(s.longitude, 5),
                        "kv": s.voltage_kv, "deg": g.degree(s.id)})
    out.sort(key=lambda x: -(x["kv"] or 0))     # 高電圧=送電候補を先頭に
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/reports/island_substations.json")
    args = ap.parse_args()
    rows = census()
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    print(f"島の実変電所(名前つき): {len(rows)}")
    print("地域別:", dict(collections.Counter(x["region"] for x in rows)))
    print("出力:", args.out)


if __name__ == "__main__":
    main()
