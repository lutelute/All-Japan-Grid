#!/usr/bin/env python3
"""接続候補ジェネレータ (接続編集ツールのバックエンド) — I6-5新方向 2026-06-14。

島(非主成分)ごとに、主系統への「物理的にありうる接続候補」を提案する。これは人間が
編集ツールで承認/却下する材料であり、**自動では繋がない**(捏造禁止・オーナー方針)。

候補の根拠(evidence)を明示:
  - line_tip_continuation : 島が線を持ち、degree-1端点(tip)の線の方位の延長上に同電圧
                            クラスの主系統ノードがある(最も確からしい=実在線の続き)
  - isolated_sub_nearest  : 島が孤立変電所(線なし・台帳112で東京105島中85島)。最寄り同電圧
                            の主系統。OSM線の証拠が無いので**人間の確認が必須**(投機的)
  - island_node_nearest   : 線ありだがtipが無い(ループ等)。最寄り同電圧

各候補に距離・方位整合(度・0=一直線)・同電圧かを付け、strength(strong/medium/weak)で
人間の判断コストを下げる。

統合先(調査済): 人間が承認した接続は `data/{region}_lines_supplement.geojson` に
LineStringとして追記(加算専用・source=manual)。`build_network_snapped` が既に取り込む。

    PYTHONPATH=. python3 scripts/connection_candidates.py --region tokyo --out docs/reports/connection_candidates_tokyo.json
"""
import sys
import json
import math
import argparse

import numpy as np
import networkx as nx
from scipy.spatial import cKDTree

from src.powerflow.snapped_topology import build_network_snapped


def _xy(lat, lon):
    return (lon * 111.0 * math.cos(math.radians(lat)), lat * 111.0)


def _bearing(a, b):
    """a→b の方位(度・0=北・時計回り)。"""
    dlon = math.radians(b[1] - a[1])
    la1, la2 = math.radians(a[0]), math.radians(b[0])
    y = math.sin(dlon) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _angdiff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _strength(rec):
    """根拠の強さ。strong=ほぼ確実、weak=人間の現地/航空写真確認が必須。"""
    ev, dist, align = rec["evidence"], rec["dist_m"], rec["bearing_align_deg"]
    if ev == "line_tip_continuation" and dist <= 500 and align is not None and align <= 30:
        return "strong"
    if ev == "line_tip_continuation" and dist <= 1500:
        return "medium"
    if ev == "isolated_sub_nearest" and dist <= 150:
        return "medium"
    return "weak"


def candidates(region, search_km=2.0):
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
    main = set(comps[0])
    islands = comps[1:]
    main_ids = sorted(n for n in main if n in pos)
    main_xy = np.array([_xy(*pos[n]) for n in main_ids])
    tree = cKDTree(main_xy)

    out = []
    for isl in islands:
        nodes = [n for n in isl if n in pos]
        if not nodes:
            continue
        has_line = any(g.degree(n) >= 1 for n in isl)
        if has_line:
            origins = [n for n in isl if g.degree(n) == 1] or nodes
        else:
            origins = nodes
        best = None
        for o in origins:
            okv = kv.get(o, 0.0)
            oxy = _xy(*pos[o])
            for i in tree.query_ball_point(oxy, search_km):
                m = main_ids[i]
                mkv = kv.get(m, 0.0)
                if okv > 0 and mkv > 0 and abs(okv - mkv) > 1:
                    continue  # 異電圧は接続候補にしない(変圧器が要る)
                dist_km = math.dist(oxy, main_xy[i])
                align = None
                tip = has_line and g.degree(o) == 1
                if tip:
                    nb = next(iter(g.neighbors(o)))
                    if nb in pos:
                        in_b = _bearing(pos[nb], pos[o])   # 線が続く向き
                        to_c = _bearing(pos[o], pos[m])     # 候補への向き
                        align = round(_angdiff(in_b, to_c), 1)
                ev = ("line_tip_continuation" if tip
                      else ("island_node_nearest" if has_line else "isolated_sub_nearest"))
                rec = {
                    "island_node": o, "kv": okv,
                    "candidate_main": m, "main_kv": mkv,
                    "dist_m": round(dist_km * 1000),
                    "bearing_align_deg": align,
                    "evidence": ev,
                    "island_pt": [round(pos[o][0], 5), round(pos[o][1], 5)],
                    "main_pt": [round(pos[m][0], 5), round(pos[m][1], 5)],
                }
                # スコア: 距離(m) + 方位ペナルティ(整合が悪いほど大・tip以外は固定)
                score = dist_km * 1000 + (align * 20 if align is not None else 300)
                if best is None or score < best[0]:
                    best = (score, rec)
        if best:
            rec = best[1]
            rec["strength"] = _strength(rec)
            out.append(rec)
    out.sort(key=lambda r: (("strong", "medium", "weak").index(r["strength"]), r["dist_m"]))
    from collections import Counter
    summary = {
        "region": region,
        "n_islands": len(islands),
        "n_with_candidate": len(out),
        "search_km": search_km,
        "by_strength": dict(Counter(r["strength"] for r in out)),
        "by_evidence": dict(Counter(r["evidence"] for r in out)),
    }
    return summary, out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="tokyo")
    ap.add_argument("--search-km", type=float, default=2.0)
    ap.add_argument("--out")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args(argv)
    res = candidates(a.region, a.search_km)
    if res is None:
        print("no network")
        return 1
    summary, out = res
    print(json.dumps(summary, ensure_ascii=False))
    print(f"\n-- strong/medium 候補 top {a.top}(人間が承認すれば supplement へ) --")
    shown = [r for r in out if r["strength"] in ("strong", "medium")][: a.top]
    for r in shown:
        al = f"align{r['bearing_align_deg']:.0f}°" if r["bearing_align_deg"] is not None else "align-"
        print(f"  [{r['strength']:6}] {r['dist_m']:5}m kv{r['kv']:.0f} {al:9} {r['evidence']:22}"
              f" {r['island_node']} -> {r['candidate_main']}")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "candidates": out}, fh,
                      ensure_ascii=False, indent=1)
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
