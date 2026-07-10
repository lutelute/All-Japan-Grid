#!/usr/bin/env python3
"""介入#22の距離グレーゾーン候補リスト — 同名変電所の異電圧階級ペアで、
R=0.6km(採用済み)を超え2.0km以内のもの。人間レビュー用(自動採用しない)。

Usage: PYTHONPATH=. .venv/bin/python .../probe_sitetrafo_candidates.py out.json
"""
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from scripts.run_full_powerflow_from_db import (
    BUILT, ISLAND_OF, _haversine_km, _site_name_of_node)


def main():
    built = json.load(open(BUILT))
    nodes = built["nodes"]
    by_site = defaultdict(list)
    for n in nodes:
        if n.get("sub") != 1:
            continue
        nm = n.get("name") or ""
        if not nm:
            continue
        base = re.sub(r"_\d+$", "", _site_name_of_node(nm))
        if base:
            by_site[base].append(n)
    rows = []
    for base, ns in sorted(by_site.items()):
        kvs = {round(float(n.get("kv") or 0), 1) for n in ns}
        if len(kvs) < 2:
            continue
        # 異電圧ペアの最小距離
        for i, a in enumerate(ns):
            for b in ns[i + 1:]:
                ka, kb = float(a.get("kv") or 0), float(b.get("kv") or 0)
                if abs(ka - kb) < 0.5:
                    continue
                d = _haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
                if 0.6 < d <= 2.0:
                    isl_a = ISLAND_OF.get(a.get("region"), (None,))[0]
                    rows.append({
                        "site": base, "island": isl_a,
                        "kv_pair": sorted((ka, kb), reverse=True),
                        "dist_km": round(d, 3),
                        "regions": sorted({a.get("region"), b.get("region")}),
                        "names": [a.get("name"), b.get("name")],
                        "coords": [[round(a["lat"], 5), round(a["lon"], 5)],
                                   [round(b["lat"], 5), round(b["lon"], 5)]],
                    })
    # サイト単位で最短ペアのみ
    best = {}
    for r in rows:
        k = (r["site"], tuple(r["kv_pair"]))
        if k not in best or r["dist_km"] < best[k]["dist_km"]:
            best[k] = r
    out = sorted(best.values(), key=lambda r: r["dist_km"])
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump({"note": "R=0.6超〜2.0km・同名異電圧ペア(#22見送り分)。"
                           "人間レビュー用・自動採用禁止",
                   "n": len(out), "candidates": out}, f, indent=1,
                  ensure_ascii=False)
    print(f"{len(out)} candidates -> {sys.argv[1]}")
    for r in out[:15]:
        print(f"  {r['dist_km']:.2f}km {r['site'][:16]:16s} {r['kv_pair']} "
              f"{r['island']} {r['regions']}")


if __name__ == "__main__":
    main()
