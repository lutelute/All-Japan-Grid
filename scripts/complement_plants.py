#!/usr/bin/env python3
"""
AGJ ↔ JRP 発電所データ相互補完スクリプト

処理:
  1. AGJ capacity_mw → JRP output  (JRPの欠損を埋める)
  2. JRP fuel → AGJ fuel_type       (AGJのunknown/空を埋める)
  3. fuel 不一致レポート生成

マッチング: 発電所名 (完全一致)

実行:
  python3 scripts/complement_plants.py [--dry-run]
"""

import json
import sys
import datetime
from pathlib import Path

AGJ_DATA = Path(__file__).parent.parent / "data"
JRP_DATA = Path("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/japan-re-potential/docs/grid")
REPORT_PATH = Path(__file__).parent / "complement_report.md"

DRY_RUN = "--dry-run" in sys.argv

# AGJ の fuel_type として不正な値 (OSM タグミス等)
INVALID_FUEL_TYPES = {
    "bing", "gsimaps/ort", "gsimaps/seamlessphoto",
    "gsimaps/pale", "gsimaps/relief", "",
}

REGIONS = [
    "hokkaido", "tohoku", "tokyo", "chubu",
    "hokuriku", "kansai", "chugoku", "shikoku",
]

# JRP.fuel -> AGJ.fuel_type 正規化マップ
FUEL_NORM = {
    "solar": "solar",
    "hydro": "hydro",
    "nuclear": "nuclear",
    "coal": "coal",
    "gas": "gas",
    "wind": "wind",
    "biomass": "biomass",
    "oil": "oil",
    "geothermal": "geothermal",
    "waste": "waste",
    "tidal": "tidal",
    "pumped_hydro": "pumped_hydro",
    "battery": "battery",
    # 複合値は最初の燃料種別を採用
    "oil;gas": "oil",
    "waste;solar": "waste",
}

def normalize_fuel(raw: str) -> str:
    raw = (raw or "").strip().lower()
    return FUEL_NORM.get(raw, "")


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    if DRY_RUN:
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def main():
    report = [
        "# Plants Cross-Complement Report",
        f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Mode: {'dry-run' if DRY_RUN else 'write'}",
        "",
        "| Region | MW→output | fuel補完(AGJ) | fuel不一致 |",
        "|--------|-----------|--------------|-----------|",
    ]

    total_mw = total_fuel = total_mismatch = 0
    mismatch_details = []

    for region in REGIONS:
        agj_path = AGJ_DATA / f"{region}_plants.geojson"
        jrp_path = JRP_DATA / f"{region}_plants_lite.geojson"
        if not agj_path.exists() or not jrp_path.exists():
            continue

        agj_d = load_json(agj_path)
        jrp_d = load_json(jrp_path)

        from collections import Counter

        # 名前が重複しているフィーチャーは座標で区別できないためスキップ
        agj_name_cnt = Counter((f["properties"].get("name") or "").strip() for f in agj_d["features"])
        jrp_name_cnt = Counter((f["properties"].get("name") or "").strip() for f in jrp_d["features"])

        # 一意名のみインデックス化
        jrp_idx = {}
        for i, f in enumerate(jrp_d["features"]):
            name = (f["properties"].get("name") or "").strip()
            if name and jrp_name_cnt[name] == 1:
                jrp_idx[name] = i

        mw_count = fuel_count = mismatch_count = 0
        agj_modified = jrp_modified = False

        for agj_f in agj_d["features"]:
            p = agj_f["properties"]
            name = (p.get("name") or "").strip()
            # 名前が重複している場合はスキップ
            if not name or agj_name_cnt[name] > 1 or name not in jrp_idx:
                continue

            ji = jrp_idx[name]
            jp = jrp_d["features"][ji]["properties"]

            agj_fuel = (p.get("fuel_type") or "").strip()
            agj_mw = p.get("capacity_mw")
            jrp_fuel = normalize_fuel(jp.get("fuel", ""))
            jrp_out = (jp.get("output") or "").strip()

            # 1. AGJ capacity_mw → JRP output
            if agj_mw and agj_mw > 0 and not jrp_out:
                jrp_d["features"][ji]["properties"]["output"] = str(agj_mw)
                mw_count += 1
                jrp_modified = True

            # 2. JRP fuel → AGJ fuel_type
            #    (a) AGJ が不正値 (bing, gsimaps/...) → JRP で置き換え
            #    (b) AGJ が unknown/空 → JRP で補完
            should_fill = agj_fuel in INVALID_FUEL_TYPES or agj_fuel == "unknown"
            if jrp_fuel and should_fill:
                agj_f["properties"]["fuel_type"] = jrp_fuel
                fuel_count += 1
                agj_modified = True

            # 3. 不一致記録 (両方に正常値があり異なる場合)
            elif (agj_fuel and jrp_fuel
                  and agj_fuel not in INVALID_FUEL_TYPES
                  and agj_fuel != "unknown"
                  and agj_fuel != jrp_fuel):
                mismatch_count += 1
                mismatch_details.append(
                    f"  - [{region}] {name}: AGJ=`{agj_fuel}` / JRP=`{jp.get('fuel','')}`"
                )

        if agj_modified:
            save_json(agj_path, agj_d)
        if jrp_modified:
            save_json(jrp_path, jrp_d)

        total_mw += mw_count
        total_fuel += fuel_count
        total_mismatch += mismatch_count
        report.append(f"| {region:<10} | {mw_count:>9} | {fuel_count:>12} | {mismatch_count:>10} |")

    report += [
        f"| **合計** | **{total_mw}** | **{total_fuel}** | **{total_mismatch}** |",
        "",
        "## fuel 不一致詳細 (AGJ優先、JRPは変更なし)",
        "",
    ]
    if mismatch_details:
        report += mismatch_details
    else:
        report.append("なし")

    report_text = "\n".join(report) + "\n"
    print(report_text)
    if not DRY_RUN:
        REPORT_PATH.write_text(report_text, encoding="utf-8")
        print(f"レポート: {REPORT_PATH}")


if __name__ == "__main__":
    main()
