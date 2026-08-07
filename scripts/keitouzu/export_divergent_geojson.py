#!/usr/bin/env python3
"""keitouzu 食い違い候補を地図オーバーレイ用 GeoJSON に書き出す。

入力: docs/reports/keitouzu_crosscheck_<date>.json（crosscheck_keitouzu.py の出力）
      docs/data/built/all.json（端点座標の解決に使用）
出力: docs/data/keitouzu_divergent.geojson

端点は crosswalk で built ノードに解決済みの変電所。幾何は持たないデータなので
**両端座標を結ぶ直線**として描く（実経路ではない — プロパティにも明記）。
モデル本体（built/lines_*.geojson）には一切触れない。未採用・裁定待ちの表示専用。

usage: python3 scripts/keitouzu/export_divergent_geojson.py [--report <path>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILT = ROOT / "docs" / "data" / "built" / "all.json"
OUT = ROOT / "docs" / "data" / "keitouzu_divergent.geojson"


def latest_report() -> Path:
    reports = sorted((ROOT / "docs" / "reports").glob("keitouzu_crosscheck_*.json"))
    if not reports:
        raise SystemExit("crosscheck レポートが見つからない。先に crosscheck_keitouzu.py を走らせること。")
    return reports[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=None)
    args = ap.parse_args()
    report_path = Path(args.report) if args.report else latest_report()
    report = json.load(open(report_path))

    built = json.load(open(BUILT))
    base_coord: dict[str, tuple[float, float]] = {}
    for n in built["nodes"]:
        base_coord.setdefault(n["id"].split("@")[0], (n["lat"], n["lon"]))

    features, skipped = [], 0
    for c in report["divergent_candidates"]:
        fc = next((base_coord[t.split("@")[0]] for t in c["from"]["ajg"]
                   if t.split("@")[0] in base_coord), None)
        tc = next((base_coord[t.split("@")[0]] for t in c["to"]["ajg"]
                   if t.split("@")[0] in base_coord), None)
        if fc is None or tc is None:
            skipped += 1
            continue
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[fc[1], fc[0]], [tc[1], tc[0]]],  # lon, lat
            },
            "properties": {
                "line": c["line"],
                "voltage_kv": c["voltage_kv"],
                "region": c["region"],
                "from_name": c["from"]["name"],
                "to_name": c["to"]["name"],
                "from_alias": (c["from"]["aliases"] or [""])[0],
                "to_alias": (c["to"]["aliases"] or [""])[0],
                "confidence": c["confidence"],
                "source_ref": c["source_ref"],
                "evidence": c["evidence"],
                "keitouzu_uuid": c["keitouzu_uuid"],
                "_status": "unadopted_candidate",  # 未採用・裁定待ち
                "_geometry_note": "straight_line_between_substations_not_actual_route",
            },
        })

    out = {
        "type": "FeatureCollection",
        "name": "keitouzu_divergent_candidates",
        "_meta": {
            "source": "open-keitouzu (CC BY 4.0) crosscheck vs AGJ built",
            "report": report_path.name,
            "pinned_commit": report.get("pinned_commit"),
            "note": "公式系統図のみが主張する接続。built正典には未採用(人間判断待ち)。幾何は両端直線で実経路ではない。",
        },
        "features": features,
    }
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"{len(features)} features → {OUT.relative_to(ROOT)}" + (f"（座標未解決 {skipped} 件スキップ）" if skipped else ""))


if __name__ == "__main__":
    main()
