#!/usr/bin/env python3
"""出典必須DB(generator_capacity_sources.jsonl)の容量を発電所geojsonに反映(出典付き)。

    PYTHONPATH=. python scripts/apply_capacity_sources.py

オーナー方針「嘘をつかず必ず引用」を**表示まで貫く**: 出典DBの検証済み容量を
docs/data の plants_*/generators.geojson に
  capacity_mw_sourced / capacity_source_url / capacity_source_type /
  capacity_source_conf / capacity_source_note
として付与し、grid_map の popup/CSV が「公式容量 X MW [出典リンク]」を出せるようにする。
**元の capacity_mw(OSM/P03)は保持**(比較用=OSM過小値が出典で正される様子が見える)。

突合: 発電所名の完全一致 + 正規化一致(「発電所/株式会社/空白」のみ除去。火力/水力/原子力/第一/第二は温存)。同名は
confidence 高(official>wikipedia>) を優先。出典DBに無い発電所は一切触らない(捏造しない)。
base extract(data/直下のOSM生抽出)は触らない。本スクリプトは docs/data の D層のみ更新。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from capacity_provenance import load_records  # noqa: E402

DATA = os.path.join(ROOT, "docs", "data")
TARGETS = ["generators.geojson", "plants_all.geojson", "plants_utility.geojson", "plants_ipp.geojson"]
CONF_RANK = {"high": 2, "medium": 1, "low": 0}

SOURCED_FIELDS = [
    "capacity_mw_sourced", "capacity_source_url", "capacity_source_type",
    "capacity_source_conf", "capacity_source_note",
]


def norm(s):
    # 火力/水力/原子力/第一/第二 は **除去しない**(広野火力≠広野水力、姫路第一≠第二、
    # 知多火力≠知多 等の混同=別発電所への誤反映を防ぐ)。空白と「発電所/株式会社」のみ除去。
    return re.sub(r"[\s　]|発電所|株式会社", "", s or "")


def main():
    src = load_records()
    by_name, by_norm = {}, {}
    for r in src:
        n = r["name"]
        if n not in by_name or CONF_RANK[r["confidence"]] > CONF_RANK[by_name[n]["confidence"]]:
            by_name[n] = r
    for n, r in by_name.items():
        by_norm.setdefault(norm(n), r)
    print(f"出典DB: {len(src)} 行 / ユニーク発電所 {len(by_name)}")

    for tgt in TARGETS:
        path = os.path.join(DATA, tgt)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        applied = 0
        cleared = 0
        for ft in d.get("features", []):
            p = ft.get("properties") or {}
            name = (p.get("_display_name") or p.get("name") or "").strip()
            rec = by_name.get(name) or (by_norm.get(norm(name)) if name else None)
            # 冪等性: 既存の sourced を一旦消してから(出典DB更新を反映)
            had = any(k in p for k in SOURCED_FIELDS)
            for k in SOURCED_FIELDS:
                p.pop(k, None)
            if rec and name:
                p["capacity_mw_sourced"] = rec["value"]
                p["capacity_source_url"] = rec["source_url"]
                p["capacity_source_type"] = rec["source_type"]
                p["capacity_source_conf"] = rec["confidence"]
                if rec.get("note"):
                    p["capacity_source_note"] = rec["note"]
                applied += 1
            elif had:
                cleared += 1
            ft["properties"] = p
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        # OSM/P03 値と出典値の乖離サンプル
        difs = []
        for ft in d["features"]:
            p = ft["properties"]
            if "capacity_mw_sourced" in p and isinstance(p.get("capacity_mw"), (int, float)):
                o, s = p["capacity_mw"], p["capacity_mw_sourced"]
                den = max(o, s)
                if den > 0 and abs(o - s) / den > 0.1:
                    difs.append((p.get("_display_name") or p.get("name"), o, s))
        print(f"  {tgt}: applied={applied} (cleared stale={cleared})")
        for nm, o, s in difs[:4]:
            print(f"     乖離 {nm}: OSM/P03={o} → 出典={s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
