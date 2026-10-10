#!/usr/bin/env python3
"""「日本の送電網、いま」用の軽い断面 pulse.json / pulse.png を書き出す.

flow_map の基準線形(flows_<isl>.geojson)と日付別断面(days/<date>.json)から、
187kV 以上の線に 24 時刻の潮流を付け、110kV 以上の線を下地として残し、形を間引いて
1/1000 度の整数にする。docs/pulse.html と docs/js/pulse.js(どこにでも貼れる表示部品)が読む。

realtime_cycle.sh の slim_flow_map.py のあとに実行(失敗しても毎時の更新は止めない)。冪等。

使い方: python3 scripts/export_pulse.py [--date 20261010]
出力:   docs/data/flow_map/pulse.json(約 430KB・gzip 約 140KB)
        docs/data/flow_map/pulse.png (いまの時刻の静止画・OGP 用。Pillow が無ければ作らない)

pulse.json の形:
  {date, hours, now_hour, fetched_at, zones_now:{zone:MW}, cross:{fc:[24], hokuhon:[24]},
   q:1000, okinawa_shift:[dlon,dlat], stale_islands:[...],
   lines:[[kv, [x0,y0,x1,y1,...], [p0..p23]]], silhouette:[[kv, [x0,y0,...]]]}
  座標は 経度・緯度 × q の整数。p>0 は座標の並び順の向き(flow_map.html と同じ)。
  cross.fc>0 は東京→中部(50Hz→60Hz)、cross.hokuhon>0 は北海道→東北(export_day_flows.py と同じ)。
  沖縄は日本海の左上に差し込み図として移してある(okinawa_shift)。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FM = ROOT / "docs" / "data" / "flow_map"
ISLANDS = ["hokkaido", "east", "west", "okinawa"]
FLOW_KV = 187            # これ以上の線に潮流を付ける
SILHOUETTE_KV = 110      # これ以上の線を下地にする
OKINAWA_KV = 60          # 沖縄は系統が小さいので低い電圧まで含める
OKINAWA_SHIFT = (2.6, 16.6)
Q = 1000
TOL_DEG = 0.004          # 間引きの許容(約 400m)。表紙の縮尺では見分けがつかない


def simplify(pts, tol):
    """Douglas–Peucker(度単位・反復版)"""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1e-12
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            x0, y0 = pts[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / n
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def encode(coords, island):
    pts = [(lon, lat) for lon, lat in coords]
    if island == "okinawa":
        pts = [(lon + OKINAWA_SHIFT[0], lat + OKINAWA_SHIFT[1]) for lon, lat in pts]
    flat = []
    for lon, lat in simplify(pts, TOL_DEG):
        q = [round(lon * Q), round(lat * Q)]
        if flat[-2:] != q:
            flat += q
    return flat


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def latest_day():
    days = sorted(FM.glob("days/2*.json"))
    return days[-1].stem if days else None


def build(date):
    meta = load(FM / "meta.json")
    now_meta = load(FM / "now_meta.json") if (FM / "now_meta.json").exists() else {}
    day = load(FM / "days" / f"{date}.json")

    lines, silhouette, stale = [], [], []
    for isl in ISLANDS:
        geo = load(FM / f"flows_{isl}.geojson")["features"]
        dayisl = (day.get("islands") or {}).get(isl) or {}
        ok = dayisl.get("base_sig") == (meta.get(isl) or {}).get("sig") and len(dayisl.get("p") or []) == len(geo)
        if not ok:
            stale.append(isl)   # 線構成が古い断面は潮流を付けず、形だけ出す
        min_kv = OKINAWA_KV if isl == "okinawa" else SILHOUETTE_KV
        flow_kv = OKINAWA_KV if isl == "okinawa" else FLOW_KV
        for i, f in enumerate(geo):
            kv = f["properties"].get("kv") or 0
            g = f.get("geometry") or {}
            if kv < min_kv or g.get("type") != "LineString":
                continue
            xy = encode(g["coordinates"], isl)
            if len(xy) < 4:
                continue
            row = dayisl["p"][i] if ok else None
            if kv >= flow_kv and row:
                p = [None if v is None else int(round(v)) for v in row]
                if any(p):
                    lines.append([kv, xy, p])
                    continue
            silhouette.append([kv, xy])

    hours = day.get("available_hours") or []
    zones_now = {z: v["mw"] for z, v in (now_meta.get("zone_hour") or {}).items()
                 if str(v.get("date", "")).replace("/", "") == date}
    cross = {k: [None if v is None else round(v) for v in vals]
             for k, vals in (day.get("cross_island_mw") or {}).items()}
    return {
        "source": "All-Japan-Grid flow_map (estimated, not operational values)",
        "date": date,
        "hours": hours,
        "now_hour": hours[-1] if hours else None,
        "fetched_at": now_meta.get("fetched_at"),
        "zones_now": zones_now,
        "cross": cross,
        "q": Q,
        "okinawa_shift": OKINAWA_SHIFT,
        "stale_islands": stale,
        "lines": lines,
        "silhouette": silhouette,
    }


# ---------- 静止画(pulse.js の投影と同じ) ----------

LON0, LON1, LAT0, LAT1 = 128.3, 146.0, 30.8, 45.7
KX = math.cos(math.radians(37))
CAP = {500: 3000, 275: 1200, 220: 900, 187: 500, 154: 400}


def render_png(data, path, W=1200, H=1200):
    from PIL import Image, ImageDraw
    pad = 40
    s = min((W - 2 * pad) / ((LON1 - LON0) * KX), (H - 2 * pad) / (LAT1 - LAT0))
    ox = (W - (LON1 - LON0) * KX * s) / 2
    oy = (H - (LAT1 - LAT0) * s) / 2

    def proj(x, y):
        return ox + (x / Q - LON0) * KX * s, oy + (LAT1 - y / Q) * s

    img = Image.new("RGB", (W, H), (8, 16, 22))
    d = ImageDraw.Draw(img, "RGBA")
    for _, xy in data["silhouette"]:
        d.line([proj(xy[i], xy[i + 1]) for i in range(0, len(xy), 2)], fill=(90, 130, 150, 70), width=1)
    h = data["hours"].index(data["now_hour"]) if data["now_hour"] in data["hours"] else -1
    for kv, xy, p in sorted(data["lines"], key=lambda r: r[0]):
        v = p[h] if 0 <= h < len(p) else None
        i = min(1.0, abs(v or 0) / CAP.get(kv, 300))
        col = (int(70 + 185 * i), int(205 - 60 * i), int(190 - 140 * i), int(110 + 145 * i))
        d.line([proj(xy[k], xy[k + 1]) for k in range(0, len(xy), 2)], fill=col, width=3 if kv >= 500 else 2)
    img.save(path, optimize=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYYMMDD(省略時は days/ の最新)")
    args = ap.parse_args()
    date = args.date or latest_day()
    if not date:
        print("pulse: days/ に断面がない", file=sys.stderr)
        return 1
    data = build(date)
    out = FM / "pulse.json"
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"pulse: {date} {data['hours'][:1]}..{data['hours'][-1:]}時 "
          f"潮流線 {len(data['lines'])} / 下地 {len(data['silhouette'])} / "
          f"{out.stat().st_size // 1024}KB stale={data['stale_islands']}")
    try:
        render_png(data, FM / "pulse.png")
    except ImportError:
        print("pulse: Pillow が無いので pulse.png は作らない", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
