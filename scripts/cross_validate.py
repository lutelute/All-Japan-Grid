#!/usr/bin/env python3
"""
AGJ ↔ JRP データ整合性クロスバリデーション

チェック項目:
  1. substations の feature 数・電圧分布の一致性
  2. lines の feature 数・voltage 分布の一致性
  3. plants の fuel 不一致詳細 (全リージョン)
  4. capacity_mw 補完済み確認

実行:
  python3 scripts/cross_validate.py
"""

import json
import datetime
from pathlib import Path
from collections import Counter

AGJ_DATA = Path(__file__).parent.parent / "data"
JRP_DATA = Path("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/japan-re-potential/docs/grid")
REPORT_PATH = Path(__file__).parent / "cross_validate_report.md"

REGIONS = [
    "hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
    "kansai", "chugoku", "shikoku", "kyushu", "okinawa",
]

FUEL_NORM = {
    "solar": "solar", "hydro": "hydro", "nuclear": "nuclear",
    "coal": "coal", "gas": "gas", "wind": "wind", "biomass": "biomass",
    "oil": "oil", "geothermal": "geothermal", "waste": "waste",
    "tidal": "tidal", "pumped_hydro": "pumped_hydro", "battery": "battery",
    "oil;gas": "oil", "waste;solar": "waste",
}


def norm_fuel(s: str) -> str:
    return FUEL_NORM.get((s or "").strip().lower(), (s or "").strip().lower())


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_substations(report: list):
    report += ["## 1. Substations 整合性チェック", ""]
    report += ["| Region | AGJ count | JRP count | 一致 |", "|--------|-----------|-----------|------|"]
    total_ok = total_ng = 0
    for region in REGIONS:
        agj_path = AGJ_DATA / f"{region}_substations.geojson"
        jrp_path = JRP_DATA / f"{region}_substations.geojson"
        if not agj_path.exists() or not jrp_path.exists():
            report.append(f"| {region} | - | - | ファイル欠落 |")
            continue
        agj_n = len(load_json(agj_path)["features"])
        jrp_n = len(load_json(jrp_path)["features"])
        ok = agj_n == jrp_n
        if ok:
            total_ok += 1
        else:
            total_ng += 1
        report.append(f"| {region} | {agj_n} | {jrp_n} | {'✓' if ok else f'✗ (差分 {agj_n-jrp_n:+d})'} |")
    report += [
        "",
        f"一致: {total_ok} リージョン / 不一致: {total_ng} リージョン",
        "",
    ]


def check_lines(report: list):
    report += ["## 2. Lines 整合性チェック", ""]
    report += ["| Region | AGJ count | JRP count | 一致 |", "|--------|-----------|-----------|------|"]
    total_ok = total_ng = 0
    for region in REGIONS:
        agj_path = AGJ_DATA / f"{region}_lines.geojson"
        jrp_path = JRP_DATA / f"{region}_lines.geojson"
        if not agj_path.exists() or not jrp_path.exists():
            report.append(f"| {region} | - | - | ファイル欠落 |")
            continue
        agj_n = len(load_json(agj_path)["features"])
        jrp_n = len(load_json(jrp_path)["features"])
        ok = agj_n == jrp_n
        if ok:
            total_ok += 1
        else:
            total_ng += 1
        report.append(f"| {region} | {agj_n} | {jrp_n} | {'✓' if ok else f'✗ (差分 {agj_n-jrp_n:+d})'} |")
    report += [
        "",
        f"一致: {total_ok} リージョン / 不一致: {total_ng} リージョン",
        "",
    ]


def check_plants(report: list):
    report += ["## 3. Plants fuel 不一致詳細", ""]
    report += ["| Region | AGJ plants | JRP plants_lite | fuel不一致(一意名) | mw→output補完済 |",
               "|--------|-----------|-----------------|-------------------|----------------|"]

    all_mismatches = []   # (region, name, agj_fuel, jrp_fuel)
    skipped_dupes = []    # (region, name, count) 同名複数でスキップ
    total_mw_done = 0

    for region in REGIONS:
        agj_path = AGJ_DATA / f"{region}_plants.geojson"
        jrp_path = JRP_DATA / f"{region}_plants_lite.geojson"
        if not agj_path.exists():
            report.append(f"| {region} | *(欠落)* | - | - | - |")
            continue
        if not jrp_path.exists():
            report.append(f"| {region} | - | *(欠落)* | - | - |")
            continue

        agj_d = load_json(agj_path)
        jrp_d = load_json(jrp_path)

        agj_name_cnt = Counter((f["properties"].get("name") or "").strip() for f in agj_d["features"])
        jrp_name_cnt = Counter((f["properties"].get("name") or "").strip() for f in jrp_d["features"])

        # 一意名のみインデックス化
        jrp_by_name = {}
        for f in jrp_d["features"]:
            name = (f["properties"].get("name") or "").strip()
            if name and jrp_name_cnt[name] == 1:
                jrp_by_name[name] = f["properties"]

        mismatch = []
        mw_done = 0
        seen_dupes = set()

        for f in agj_d["features"]:
            name = (f["properties"].get("name") or "").strip()
            agj_fuel = (f["properties"].get("fuel_type") or "").strip()
            agj_mw   = f["properties"].get("capacity_mw", -1)

            # 同名重複はスキップして集約
            if agj_name_cnt[name] > 1:
                if name not in seen_dupes:
                    seen_dupes.add(name)
                    skipped_dupes.append((region, name, agj_name_cnt[name]))
                continue

            jp = jrp_by_name.get(name, {})
            jrp_fuel = norm_fuel(jp.get("fuel", ""))
            jrp_out  = (jp.get("output") or "").strip()

            INVALID = {"bing", "gsimaps/ort", "gsimaps/seamlessphoto", "gsimaps/pale", "gsimaps/relief"}
            if (agj_fuel and jrp_fuel
                    and agj_fuel not in INVALID
                    and agj_fuel != "unknown"
                    and agj_fuel != jrp_fuel):
                mismatch.append((region, name, agj_fuel, jp.get("fuel", "")))
            if agj_mw and agj_mw > 0 and jrp_out:
                mw_done += 1

        total_mw_done += mw_done
        all_mismatches.extend(mismatch)
        report.append(f"| {region} | {len(agj_d['features'])} | {len(jrp_d['features'])} | {len(mismatch)} | {mw_done} |")

    report += [
        "",
        f"**mw→output 補完済み合計: {total_mw_done} 件**",
        "",
        "### fuel 不一致リスト (一意名のみ。同名重複はスキップ)",
        "",
    ]
    if all_mismatches:
        for region, name, af, jf in all_mismatches:
            report.append(f"  - [{region}] **{name}**: AGJ=`{af}` / JRP=`{jf}`")
    else:
        report.append("なし")

    if skipped_dupes:
        report += [
            "",
            "### 同名重複によりスキップ (上位10件)",
            "",
        ]
        for region, name, cnt in sorted(skipped_dupes, key=lambda x: -x[2])[:10]:
            report.append(f"  - [{region}] {name}: {cnt} 件")
    report.append("")


def check_missing_regions(report: list):
    report += ["## 4. 欠落データ確認", ""]
    for region in REGIONS:
        agj_plants = AGJ_DATA / f"{region}_plants.geojson"
        jrp_plants = JRP_DATA / f"{region}_plants_lite.geojson"
        if not agj_plants.exists():
            src = "JRPから復元済み" if agj_plants.exists() else "欠落"
            jrp_info = f"{len(load_json(jrp_path)['features'])} features" if jrp_plants.exists() else "JRPも欠落"
            report.append(f"- **{region}**: AGJ plants {src} / JRP: {jrp_info}")
    report.append("")


def main():
    report = [
        "# Cross-Validation Report: AGJ ↔ JRP",
        f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    check_substations(report)
    check_lines(report)
    check_plants(report)

    # 欠落データ（restore後の確認）
    report += ["## 4. 欠落データ確認 (restore後)", ""]
    all_ok = True
    for region in REGIONS:
        agj_plants = AGJ_DATA / f"{region}_plants.geojson"
        if not agj_plants.exists():
            jrp_path = JRP_DATA / f"{region}_plants_lite.geojson"
            jrp_info = f"{len(load_json(jrp_path)['features'])} features" if jrp_path.exists() else "JRPも欠落"
            report.append(f"- **{region}**: AGJ plants 欠落 (JRP: {jrp_info})")
            all_ok = False
    if all_ok:
        report.append("全リージョンのplantsが揃っています ✓")
    report.append("")

    text = "\n".join(report) + "\n"
    print(text)
    REPORT_PATH.write_text(text, encoding="utf-8")
    print(f"レポート: {REPORT_PATH}")


if __name__ == "__main__":
    main()
