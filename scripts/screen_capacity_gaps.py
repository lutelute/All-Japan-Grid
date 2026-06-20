#!/usr/bin/env python3
"""発電量・容量が「上手く入っていない」発電所をスクリーニングし収集worklistを出す。

    PYTHONPATH=. python scripts/screen_capacity_gaps.py

オーナー指示(2026-06-20)の前段: web 収集の前に、何を埋めるべきかを機械的に洗い出す。
2 種の gap を対象にする:
  - missing  : capacity_mw が null/0 (値が無い)
  - no_source: capacity_mw はあるが出典(generator_capacity_sources.jsonl)が無い
               = 値の根拠が辿れない(P03/OSM 由来だが引用が記録されていない)

優先度: 系統寄与の大きい utility 大規模(原子力>火力>水力…)を上位に。少数実証は
ここ上位から WebSearch で出典収集する。既に出典DBにある発電所は worklist から除く。

入力(読取専用): docs/data/plants_utility.geojson / generators.geojson
出力: docs/reports/capacity_worklist_<date>.json (収集対象・優先順)
      ※ 日付は再現性のため引数 or 環境変数で渡す(スクリプトは時刻を生成しない)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from capacity_provenance import load_records  # noqa: E402

DATA = os.path.join(ROOT, "docs", "data")

# 系統寄与の大きい順(小さいほど高優先)。utility 大規模を上位に。
FUEL_RANK = {
    "nuclear": 0, "coal": 1, "gas": 1, "lng": 1, "oil": 2,
    "hydro": 2, "pumped_hydro": 2, "geothermal": 3, "biomass": 4,
    "waste": 5, "wind": 6, "solar": 7, "unknown": 8,
}


def plant_key(src, name, lat, lon):
    return f"{src}:{name}:{round(float(lat), 3)},{round(float(lon), 3)}"


def screen(out_date):
    have = {r["plant_key"] for r in load_records()}
    items = []

    # plants_utility (OSM・大規模在来電源)
    pu_path = os.path.join(DATA, "plants_utility.geojson")
    with open(pu_path, encoding="utf-8") as f:
        for ft in json.load(f)["features"]:
            p = ft["properties"]
            c = (ft.get("geometry") or {}).get("coordinates")
            if not c or len(c) < 2:
                continue
            name = (p.get("_display_name") or p.get("name") or "").strip()
            if not name:
                continue
            fuel = p.get("fuel_type") or "unknown"
            cap = p.get("capacity_mw")
            key = plant_key("osm", name, c[1], c[0])
            if key in have:
                continue
            has_cap = isinstance(cap, (int, float)) and cap > 0
            items.append({
                "plant_key": key, "name": name, "fuel_type": fuel,
                "region": p.get("_region") or "", "lat": round(c[1], 5), "lon": round(c[0], 5),
                "current_capacity_mw": cap if has_cap else None,
                "gap": "no_source" if has_cap else "missing",
                "src": "plants_utility",
            })

    # generators (P03・容量はあるが出典が無い=no_source 全件)
    g_path = os.path.join(DATA, "generators.geojson")
    with open(g_path, encoding="utf-8") as f:
        for ft in json.load(f)["features"]:
            p = ft["properties"]
            c = (ft.get("geometry") or {}).get("coordinates")
            if not c or len(c) < 2:
                continue
            name = (p.get("name") or "").strip()
            if not name:
                continue
            fuel = p.get("fuel_type") or "unknown"
            cap = p.get("capacity_mw")
            key = plant_key("p03", name, c[1], c[0])
            if key in have:
                continue
            has_cap = isinstance(cap, (int, float)) and cap > 0
            items.append({
                "plant_key": key, "name": name, "fuel_type": fuel,
                "region": p.get("region") or "", "lat": round(c[1], 5), "lon": round(c[0], 5),
                "current_capacity_mw": cap if has_cap else None,
                "gap": "no_source" if has_cap else "missing",
                "src": "generators_p03",
            })

    # 優先度ソート: fuel rank → 既存容量の大きい順(大規模優先) → 名前
    def sort_key(it):
        rank = FUEL_RANK.get(it["fuel_type"], 8)
        cap = it["current_capacity_mw"] or 0
        return (rank, -cap, it["name"])

    items.sort(key=sort_key)

    out = {
        "_meta": {
            "generated": out_date,
            "purpose": "発電量/容量の出典収集worklist(嘘をつかないDB=必ず引用)",
            "gap_types": {"missing": "値が無い", "no_source": "値はあるが出典が無い"},
            "total": len(items),
        },
        "items": items,
    }
    out_path = os.path.join(ROOT, "docs", "reports", f"capacity_worklist_{out_date}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # サマリ表示
    from collections import Counter
    print(f"worklist: {len(items)} 件 -> {os.path.relpath(out_path, ROOT)}")
    bygap = Counter(it["gap"] for it in items)
    print(f"  gap: {dict(bygap)}")
    byfuel = Counter(it["fuel_type"] for it in items)
    print(f"  fuel(上位): {dict(sorted(byfuel.items(), key=lambda kv: FUEL_RANK.get(kv[0], 8))[:8])}")
    print("\n  === 少数実証の最優先候補(utility大規模・上位12) ===")
    for it in items[:12]:
        caps = f"{it['current_capacity_mw']}MW" if it["current_capacity_mw"] else "—(欠損)"
        print(f"   [{it['fuel_type']:8}] {it['name'][:28]:28} {caps:10} {it['gap']} ({it['region']})")
    return out_path


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WORKLIST_DATE", "2026-06-20")
    screen(date)
