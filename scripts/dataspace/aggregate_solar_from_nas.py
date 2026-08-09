#!/usr/bin/env python3
"""研究室 NAS の気象データを、電力エリア別の日射時系列に集約する（源泉側で実行）。

データスペース方針（`docs/DATA_SPACE.md`・オーナー指示 2026-06-11）:
**全部持ってくるのはナンセンス。集約は源泉に近い場所で行い、AGJ へは集約結果だけ渡す。**
本スクリプトは NAS をマウントした pws-160core 側で走らせ、
152 地点 × 8,760 時間の ERA5 実況（178MB）を **10 エリア × 8,760 時間**（約 2MB）に畳む。

なぜ ERA5（`openmeteo_raw`）を使うか:
- 各地点の CSV ヘッダに**緯度経度が入っている**ため、地点 ID の対応表なしで
  地理的にエリアへ割り当てられる（`msm_stations` の 47xxx は対応表が NAS 上に無く、
  名称を推測すると捏造になる）
- 実況ベースなので「その時刻に実際どれだけ日射があったか」を表す。
  予測（MSM）は予測誤差の評価に使うもので、資源量の時系列には実況が適切

エリア割当: 地点座標が `regions_bbox.json` のどの領域に入るかで決める。
複数に入る場合は領域中心が最も近いものを採る（bbox は境界で重なるため）。

usage（pws-160core 上で）:
    python3 aggregate_solar_from_nas.py --year 2025 --out /tmp/solar_by_area_2025.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_SRC = Path("/mnt/nas03/openmeteo_raw")
# STC（1,000 W/m²）で定格出力になるとした素朴な変換。実際の PV は温度・角度・損失で
# これより低いが、係数は使う側で決められるよう生の日射も残す。
STC_WM2 = 1000.0


def load_bboxes(path: Path) -> dict:
    return json.load(open(path))["regions"]


def assign_region(lat: float, lon: float, bboxes: dict) -> str | None:
    """座標をエリアに割り当てる。bbox が重なる場合は中心が近い方を採る。"""
    hits = []
    for name, b in bboxes.items():
        if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]:
            cy = (b["lat_min"] + b["lat_max"]) / 2
            cx = (b["lon_min"] + b["lon_max"]) / 2
            hits.append((math.dist((lat, lon), (cy, cx)), name))
    if hits:
        return min(hits)[1]
    # どの bbox にも入らない離島等は、最も近い領域中心に寄せる
    best = None
    for name, b in bboxes.items():
        cy = (b["lat_min"] + b["lat_max"]) / 2
        cx = (b["lon_min"] + b["lon_max"]) / 2
        d = math.dist((lat, lon), (cy, cx))
        if best is None or d < best[0]:
            best = (d, name)
    return best[1] if best else None


def read_station(csv_path: Path) -> tuple[float, float, list[tuple[str, float]]]:
    """ERA5 CSV から (lat, lon, [(time, ghi_wm2), ...]) を読む。

    ファイル先頭に緯度経度のヘッダ行があり、空行を挟んで本体が続く形式。
    """
    lat = lon = None
    rows: list[tuple[str, float]] = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        meta_hdr = next(r, None)
        if meta_hdr and "latitude" in meta_hdr:
            meta = next(r, None)
            if meta:
                lat = float(meta[meta_hdr.index("latitude")])
                lon = float(meta[meta_hdr.index("longitude")])
        # 本体ヘッダまで読み飛ばす
        body_hdr = None
        for row in r:
            if row and row[0] == "time":
                body_hdr = row
                break
        if not body_hdr:
            return lat, lon, rows
        ghi_col = next((i for i, c in enumerate(body_hdr)
                        if c.startswith("shortwave_radiation")), None)
        if ghi_col is None:
            return lat, lon, rows
        for row in r:
            if len(row) <= ghi_col or not row[0]:
                continue
            try:
                rows.append((row[0], float(row[ghi_col])))
            except ValueError:
                continue
    return lat, lon, rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--bbox", type=Path, required=True,
                    help="regions_bbox.json（AGJ から持ち込む）")
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stations-out", type=Path, default=None,
                    help="地点→エリアの割当表（監査用）")
    args = ap.parse_args()

    bboxes = load_bboxes(args.bbox)
    # time -> region -> [ghi]
    acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    assign_rows = []
    n_ok = n_skip = 0

    for d in sorted(args.src.iterdir()):
        if not d.is_dir():
            continue
        f = d / f"era5_{args.year}.csv"
        if not f.exists():
            n_skip += 1
            continue
        lat, lon, rows = read_station(f)
        if lat is None or not rows:
            n_skip += 1
            continue
        region = assign_region(lat, lon, bboxes)
        assign_rows.append({"station_dir": d.name, "lat": lat, "lon": lon,
                            "region": region, "n_hours": len(rows)})
        for t, v in rows:
            acc[t][region].append(v)
        n_ok += 1

    regions = sorted({r for m in acc.values() for r in m})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time"] + [f"{r}_ghi_wm2" for r in regions]
                   + [f"{r}_cf" for r in regions])
        for t in sorted(acc):
            means = [(sum(acc[t][r]) / len(acc[t][r])) if acc[t].get(r) else ""
                     for r in regions]
            cfs = [f"{m / STC_WM2:.4f}" if m != "" else "" for m in means]
            w.writerow([t] + [f"{m:.1f}" if m != "" else "" for m in means] + cfs)

    if args.stations_out:
        with open(args.stations_out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["station_dir", "lat", "lon", "region", "n_hours"])
            w.writeheader()
            w.writerows(assign_rows)

    per_region = defaultdict(int)
    for a in assign_rows:
        per_region[a["region"]] += 1
    print(f"地点 {n_ok} 件を集約（スキップ {n_skip}）→ {args.out}")
    print("エリア別の地点数: " + " / ".join(f"{k} {v}" for k, v in sorted(per_region.items())))
    print(f"時刻数 {len(acc):,} / 出力サイズ {args.out.stat().st_size/1e6:.1f} MB")


if __name__ == "__main__":
    main()
