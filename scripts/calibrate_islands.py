#!/usr/bin/env python3
"""(c) 島変電所のデータ校正 — region/voltage の誤タグを OSM 実タグで精緻化する。

研究レポート(island_substation_research_2026-06-16.md L18)が指摘した upstream データ品質問題:
  - region 誤タグ: 近接リージョンへの取り込み誤り(下北半島=青森が hokkaido、広島山口の中国電力が
    shikoku、長野木曽が hokuriku、群馬栃木の TEPCO が tohoku/chubu)。
  - 電圧ラベル不一致: 名称「220kV」だが OSM 実値 voltage=110000(黒瀬・廿日市等)。

**基底 extract は不変**(捏造禁止・破壊的再生成禁止)。本スクリプトは派生レポートだけを書く:
島リスト(docs/reports/island_substations_*.json)を OSM フィーチャに突合し、

  - voltage校正: 名称埋め込み kV と OSM 実 voltage を比較。食い違えば OSM 優先(report と同方針)。
  - region校正: OSM operator(電力会社)→ 地域 を真の根拠とし、タグ地域と食い違えば flag。
    operator が無い/鉄道事業者の島は確信できないので region_unknown(タグ据え置き)。

出力: docs/reports/island_calibration_<date>.json(精緻化済み worklist)+ 標準出力サマリ。
この refined worklist が A 島接続作業の入力になる(正しい地域・正しい電圧で接続先を探す)。

Usage:
  PYTHONPATH=. python scripts/calibrate_islands.py \
    --islands docs/reports/island_substations_2026-06-16.json --date 2026-06-16
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.regions import REGIONS  # noqa: E402
from src.utils.voltage import parse_voltage_kv  # noqa: E402

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "docs", "reports")

# OSM operator 文字列(部分一致)→ 系統地域。電力会社=地域の一次根拠。
# ネットワーク分社(送配電/NW)も本体と同地域。J-POWER/電源開発は全国資産なので地域確定に使わない。
OPERATOR_REGION = [
    ("北海道電力", "hokkaido"), ("北海道", "hokkaido"),
    ("東北電力", "tohoku"),
    ("東京電力", "tokyo"), ("TEPCO", "tokyo"), ("東電", "tokyo"),
    ("中部電力", "chubu"),
    ("北陸電力", "hokuriku"),
    ("関西電力", "kansai"), ("関電", "kansai"),
    ("中国電力", "chugoku"),
    ("四国電力", "shikoku"),
    ("九州電力", "kyushu"),
    ("沖縄電力", "okinawa"),
]
# 鉄道事業者(き電用=B・地域の系統根拠にしない)
RAILWAY_HINTS = ("旅客鉄道", "鉄道", "電鉄", "メトロ", "JR", "ＪＲ")
# 地域確定に使わない広域事業者
NONREGIONAL_HINTS = ("電源開発", "J-POWER", "JPOWER", "Jパワー", "日本原子力", "原燃")


def operator_to_region(op: str):
    """operator 文字列を地域へ。鉄道/広域/不明は None(地域確定不能)。"""
    if not op:
        return None, "none"
    if any(h in op for h in RAILWAY_HINTS):
        return None, "railway"
    if any(h in op for h in NONREGIONAL_HINTS):
        return None, "nonregional"
    for key, region in OPERATOR_REGION:
        if key in op:
            return region, "utility"
    return None, "other"


def name_kv(name: str):
    """名称に埋め込まれた kV を返す(例 '黒瀬変電所 220kV' → 220.0)。無ければ None。"""
    if not name:
        return None
    m = re.search(r"(\d{2,3})\s*kv", name, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _centroid(geom):
    t = geom.get("type")
    c = geom.get("coordinates")
    if t == "Point":
        return c[1], c[0]
    if t == "Polygon" and c and c[0]:
        ring = c[0]
        return (sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring))
    if t == "MultiPolygon" and c and c[0] and c[0][0]:
        ring = c[0][0]
        return (sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring))
    return None


def _norm(name: str) -> str:
    """突合用に名称を正規化(空白・電圧表記・全角を除去)。"""
    if not name:
        return ""
    s = re.sub(r"\s+", "", name)
    s = re.sub(r"\d{2,3}\s*kv", "", s, flags=re.IGNORECASE)
    return s


def load_osm_features():
    """全地域の substation フィーチャを (norm_name, lat, lon, name, operator, voltage, power, region) で読む。"""
    feats = []
    by_name = {}
    for region in REGIONS:
        path = os.path.join(DATA_DIR, f"{region}_substations.geojson")
        if not os.path.exists(path):
            continue
        fc = json.load(open(path, encoding="utf-8"))
        for f in fc.get("features", []):
            p = f.get("properties", {})
            cen = _centroid(f.get("geometry", {}))
            if not cen:
                continue
            name = p.get("name") or p.get("name:ja") or ""
            rec = {"region": region, "name": name, "lat": cen[0], "lon": cen[1],
                   "operator": p.get("operator") or "", "voltage": p.get("voltage"),
                   "power": p.get("power") or ""}
            feats.append(rec)
            nn = _norm(name)
            if nn:
                by_name.setdefault(nn, []).append(rec)
    return feats, by_name


def _haversine_km(a_lat, a_lon, b_lat, b_lon):
    R = 6371.0
    dlat = math.radians(b_lat - a_lat)
    dlon = math.radians(b_lon - a_lon)
    x = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(a_lat))
         * math.cos(math.radians(b_lat)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def match_island(isl, feats, by_name):
    """島を OSM フィーチャへ突合: 正規化名一致(最寄り) → 近接座標(<300m)。"""
    nn = _norm(isl["name"])
    cands = by_name.get(nn, [])
    if cands:
        best = min(cands, key=lambda r: _haversine_km(isl["lat"], isl["lon"], r["lat"], r["lon"]))
        d = _haversine_km(isl["lat"], isl["lon"], best["lat"], best["lon"])
        if d < 1.0:
            return best, "name", d
    # 名称不一致 → 最寄り(<300m)
    best, bestd = None, 0.3
    for r in feats:
        d = _haversine_km(isl["lat"], isl["lon"], r["lat"], r["lon"])
        if d < bestd:
            bestd, best = d, r
    if best:
        return best, "coord", bestd
    return None, "none", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", default=os.path.join(REPORTS_DIR, "island_substations_2026-06-16.json"))
    ap.add_argument("--date", default="2026-06-16")
    args = ap.parse_args()

    islands = json.load(open(args.islands, encoding="utf-8"))
    feats, by_name = load_osm_features()
    print(f"島 {len(islands)} 件 / OSM変電所 {len(feats)} 件を突合")

    out = []
    n_volt, n_region, n_unmatched, n_railway = 0, 0, 0, 0
    for isl in islands:
        feat, how, dist = match_island(isl, feats, by_name)
        rec = dict(isl)
        rec["match"] = how
        if feat is None:
            n_unmatched += 1
            rec["osm_kv"] = None
            rec["operator"] = None
            rec["region_calibrated"] = isl["region"]
            rec["region_mismatch"] = False
            rec["voltage_mismatch"] = False
            out.append(rec)
            continue
        # --- voltage校正 ---
        osm_v = parse_voltage_kv(feat["voltage"]) if feat["voltage"] else None
        nm_kv = name_kv(isl["name"])
        rec["osm_kv"] = round(osm_v, 1) if osm_v is not None else None
        rec["name_kv"] = nm_kv
        vmis = (osm_v is not None and nm_kv is not None and abs(osm_v - nm_kv) > 1.0)
        # 島census kv(=isl['kv'])が OSM実値と食い違う場合も校正対象
        cens_mis = (osm_v is not None and abs(float(isl.get("kv") or 0) - osm_v) > 1.0)
        rec["voltage_mismatch"] = bool(vmis or cens_mis)
        # 解決(どの値が正か)は別問題: OSM が既定の一次根拠だが、レポートで web 検証済みの
        # 値(例 東通村154kV [verified])は OSM(66kV)より優先される。ここでは不一致の
        # 「検出」に徹し、権威的な単一値は断定しない(name_kv / osm_kv を併記し人手解決)。
        if rec["voltage_mismatch"]:
            n_volt += 1
        # --- region校正 ---
        op = feat["operator"]
        rec["operator"] = op or None
        op_region, op_kind = operator_to_region(op)
        rec["operator_kind"] = op_kind
        if op_kind == "railway":
            n_railway += 1
        if op_region and op_region != isl["region"]:
            rec["region_calibrated"] = op_region
            rec["region_mismatch"] = True
            n_region += 1
        else:
            rec["region_calibrated"] = isl["region"]
            rec["region_mismatch"] = False
        out.append(rec)

    # 出力
    os.makedirs(REPORTS_DIR, exist_ok=True)
    doc = {"generated": args.date, "source_islands": os.path.basename(args.islands),
           "method": "OSM operator→region (utility一次根拠) / name-kV vs OSM-voltage (OSM優先)",
           "summary": {"total": len(islands), "voltage_mismatch": n_volt,
                       "region_mismatch_operator": n_region, "railway_operator": n_railway,
                       "unmatched": n_unmatched},
           "islands": out}
    outpath = os.path.join(REPORTS_DIR, f"island_calibration_{args.date}.json")
    json.dump(doc, open(outpath, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"\n=== 校正サマリ ===")
    print(f"  電圧不一致(名称/census vs OSM): {n_volt}")
    print(f"  region誤タグ(operator根拠):      {n_region}")
    print(f"  鉄道operator(B寄り):             {n_railway}")
    print(f"  OSM未突合:                       {n_unmatched}")
    print(f"  → {outpath}")

    # region誤タグの内訳(タグ→校正後)
    from collections import Counter
    flow = Counter()
    for r in out:
        if r.get("region_mismatch"):
            flow[(r["region"], r["region_calibrated"])] += 1
    if flow:
        print("\n  region誤タグ内訳(タグ → operator根拠の正地域):")
        for (a, b), c in sorted(flow.items(), key=lambda x: -x[1]):
            print(f"    {a:>9s} → {b:<9s} {c}")
    # 高電圧の電圧不一致サンプル
    vsamp = [r for r in out if r.get("voltage_mismatch") and (r.get("name_kv") or 0) >= 110]
    if vsamp:
        print(f"\n  電圧不一致サンプル(名称≥110kV, 計{len(vsamp)}):")
        for r in sorted(vsamp, key=lambda x: -(x.get("name_kv") or 0))[:12]:
            print(f"    {r['region']:>8s} {r['name'][:22]:<22s} 名称{r.get('name_kv')}kV → OSM{r.get('osm_kv')}kV")


if __name__ == "__main__":
    main()
