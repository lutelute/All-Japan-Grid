#!/usr/bin/env python3
"""A島の接続候補worklistを生成 — 「一つずつ」レビュー用(オーナー: 100件くらいなら確認できる)。

(c)校正(island_calibration)の成果を活かす: 各A島(kv≥66・非鉄道=HV連系方針)に対し、
**校正後の地域**の主系統(main)変電所で最寄りを接続先候補とする。これにより誤タグ島
(下北→tohoku 等)の接続先を正しい地域の系統で探す。

接続先=機械推定(最寄りの main 変電所)。**確証ではない** — レビューUIで OSM 下地と照らし、
人手で承認/却下する(物理接続=真・計算は検証器・捏造禁止=偽接続3,365の教訓を回避)。

入力:
  docs/reports/island_calibration_2026-06-16.json  (855島・operator/osm_kv/region校正つき)
  docs/data/built/{region}.json                    (region-local main 節点)
出力:
  docs/data/island_candidates.json  (rank順・島+接続先候補+距離+確度ヒント)

Usage:
  PYTHONPATH=. python scripts/build_island_candidates.py --date 2026-06-16
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

BUILT_DIR = os.path.join(PROJECT_ROOT, "docs", "data", "built")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "docs", "reports")
OUT = os.path.join(PROJECT_ROOT, "docs", "data", "island_candidates.json")


def haversine_km(a_lat, a_lon, b_lat, b_lon):
    R = 6371.0
    dlat = math.radians(b_lat - a_lat)
    dlon = math.radians(b_lon - a_lon)
    x = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(a_lat))
         * math.cos(math.radians(b_lat)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))


_built_cache = {}


def main_subs(region):
    """region-local の main かつ変電所(sub=1)節点 [(lat,lon,name,kv)] を返す。"""
    if region in _built_cache:
        return _built_cache[region]
    path = os.path.join(BUILT_DIR, f"{region}.json")
    subs = []
    if os.path.exists(path):
        d = json.load(open(path, encoding="utf-8"))
        for n in d.get("nodes", []):
            if n.get("main") and n.get("sub"):
                subs.append((n["lat"], n["lon"], n.get("name") or "", n.get("kv") or 0))
    _built_cache[region] = subs
    return subs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibration", default=os.path.join(REPORTS_DIR, "island_calibration_2026-06-16.json"))
    ap.add_argument("--date", default="2026-06-16")
    ap.add_argument("--min-kv", type=float, default=66.0, help="A判定の電圧フロア(HV連系方針)")
    args = ap.parse_args()

    cal = json.load(open(args.calibration, encoding="utf-8"))
    islands = cal["islands"]

    cands = []
    skipped_railway = skipped_lowkv = no_target = 0
    for isl in islands:
        # --- A 判定(レビュー前の機械フィルタ・最終判定は人手) ---
        if isl.get("operator_kind") == "railway":
            skipped_railway += 1
            continue
        census_kv = float(isl.get("kv") or 0)
        osm_kv = float(isl.get("osm_kv") or 0)
        kv_policy = max(census_kv, osm_kv)          # 包摂的(名称/OSMのどちらかが高圧ならA候補)
        if kv_policy < args.min_kv:
            skipped_lowkv += 1
            continue
        # --- 接続先 = 校正後地域の最寄り main 変電所 ---
        region_cal = isl.get("region_calibrated") or isl["region"]
        subs = main_subs(region_cal)
        if not subs and region_cal != isl["region"]:
            subs = main_subs(isl["region"])         # 校正地域にbuiltが無ければタグ地域
        ila, ilo = isl["lat"], isl["lon"]
        # 2パス: ①同階級以上(target_kv≥島kvの0.9)を優先=電気的に妥当 ②無ければ最寄りany(階級違いをflag)
        best_cls, bestd_cls = None, 1e9
        best_any, bestd_any = None, 1e9
        for (la, lo, nm, kv) in subs:
            if nm and nm == isl["name"]:
                continue
            d = haversine_km(ila, ilo, la, lo)
            if d <= 1e-4:                           # 同一点(自分)は除外
                continue
            if d < bestd_any:
                bestd_any, best_any = d, (la, lo, nm, kv)
            if kv >= kv_policy * 0.9 and d < bestd_cls:
                bestd_cls, best_cls = d, (la, lo, nm, kv)
        # 同階級は50km以内で優先(HV系統は疎なので近すぎる別階級より同階級を採る)。
        # 50km超しか同階級が無ければ最寄りany(=幾何優先)に退避し階級違いをflagする。
        if best_cls is not None and bestd_cls <= 50.0:
            best, bestd = best_cls, bestd_cls
        elif best_any is not None:
            best, bestd = best_any, bestd_any
        else:
            best = None
        if best is None:
            no_target += 1
            target = None
        else:
            cls_ok = best[3] >= kv_policy * 0.9
            target = {"name": best[2] or "(無名 main 変電所)", "lat": round(best[0], 5),
                      "lon": round(best[1], 5), "kv": best[3], "dist_km": round(bestd, 2),
                      "kv_class_ok": cls_ok}
        cands.append({
            "island": {"name": isl["name"], "lat": round(ila, 5), "lon": round(ilo, 5),
                       "kv": census_kv, "osm_kv": osm_kv or None, "deg": isl.get("deg"),
                       "region": isl["region"], "region_calibrated": region_cal,
                       "region_mismatch": isl.get("region_mismatch", False),
                       "voltage_mismatch": isl.get("voltage_mismatch", False),
                       "operator": isl.get("operator")},
            "target": target,
            "kv_priority": kv_policy,
        })

    # 並べ: 電圧降順 → 距離昇順(近い=確度高)。接続先不明は末尾。
    cands.sort(key=lambda c: (-c["kv_priority"],
                              c["target"]["dist_km"] if c["target"] else 9e9))
    for i, c in enumerate(cands):
        c["rank"] = i + 1

    doc = {"generated": args.date, "count": len(cands),
           "min_kv": args.min_kv,
           "note": "接続先は機械推定(校正後地域の最寄りmain変電所)。確証でない=OSM下地で人手確認して承認。",
           "skipped": {"railway": skipped_railway, "low_kv": skipped_lowkv, "no_target": no_target},
           "candidates": cands}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    print(f"A候補 {len(cands)} 件 → {OUT}")
    print(f"  除外: 鉄道{skipped_railway} / 低圧(<{args.min_kv:.0f}kV){skipped_lowkv} / 接続先不明{no_target}")
    # 電圧帯分布
    from collections import Counter
    band = Counter()
    for c in cands:
        kv = c["kv_priority"]
        b = "500" if kv >= 500 else "275-220" if kv >= 220 else "187-154" if kv >= 154 \
            else "110" if kv >= 110 else "66-77"
        band[b] += 1
    print("  電圧帯:", dict(band))
    print("\n  上位12件(レビュー順):")
    for c in cands[:12]:
        isl, tg = c["island"], c["target"]
        rm = " [region校正:%s→%s]" % (isl["region"], isl["region_calibrated"]) if isl["region_mismatch"] else ""
        tgs = f"{tg['name'][:16]} ({tg['dist_km']}km)" if tg else "接続先不明"
        print(f"   #{c['rank']:>3d} {isl['kv']:>5.0f}kV {isl['name'][:20]:<20s} → {tgs}{rm}")


if __name__ == "__main__":
    main()
