#!/usr/bin/env python3
"""目で確かめるための図: 地理院の地図・空中写真の上に、OSM の送電線(電圧・回線数・ケーブル数・導体数)と
モデル(正典)の枝(回線数)・変電所・発電所を重ねて描く。

    python3 inspect_map.py --root <リポジトリ> --bbox lon0 lat0 lon1 lat1 --zoom 12 --base pale --out fig.png
        [--min-kv 154] [--labels] [--model] [--plants] [--title 文字]

地図: 国土地理院の地理院タイル(標準地図 std・淡色地図 pale・全国最新写真 seamlessphoto)。出典を図に入れる。
"""
from __future__ import annotations

import argparse
import io
import json
import math
import time
import urllib.request
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402
from PIL import Image  # noqa: E402

for cand in ("Hiragino Sans", "Hiragino Maru Gothic Pro", "YuGothic", "Arial Unicode MS"):
    try:
        if fm.findfont(cand, fallback_to_default=False):
            plt.rcParams["font.family"] = cand
            break
    except Exception:  # noqa: BLE001
        pass

EXT = {"std": "png", "pale": "png", "seamlessphoto": "jpg"}
VCOL = [(500, "#e6007e"), (275, "#ff7f0e"), (220, "#b8860b"), (187, "#b8860b"), (154, "#1f77b4"),
        (110, "#2ca02c"), (77, "#2ca02c"), (66, "#17a2b8"), (0, "#666666")]
REGIONS = ("hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa")


def col(kv):
    for mn, c in VCOL:
        if kv >= mn:
            return c
    return "#666666"


def deg2num(lat, lon, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def tile(layer, z, x, y, cache: Path):
    p = cache / f"{layer}_{z}_{x}_{y}.{EXT[layer]}"
    if not p.exists():
        url = f"https://cyberjapandata.gsi.go.jp/xyz/{layer}/{z}/{x}/{y}.{EXT[layer]}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (map-inspect)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                p.write_bytes(r.read())
            time.sleep(0.05)
        except Exception:  # noqa: BLE001
            return None
    try:
        return Image.open(io.BytesIO(p.read_bytes())).convert("RGB")
    except Exception:  # noqa: BLE001
        return None


def kv_of(props):
    v = str(props.get("voltage") or "")
    try:
        return max(float(x) for x in v.replace(",", ";").split(";") if x.strip()) / 1000.0
    except ValueError:
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("LON0", "LAT0", "LON1", "LAT1"))
    ap.add_argument("--zoom", type=int, default=12)
    ap.add_argument("--base", default="pale", choices=list(EXT))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-kv", type=float, default=0)
    ap.add_argument("--labels", action="store_true", help="OSM の線に 名前・回線数・ケーブル数・導体数 を書く")
    ap.add_argument("--model", action="store_true", help="正典の枝を重ねる(回線数つき)")
    ap.add_argument("--plants", action="store_true")
    ap.add_argument("--no-osm", action="store_true")
    ap.add_argument("--title", default="")
    ap.add_argument("--cache", type=Path, default=Path("/tmp/gsi_tiles_cache"))
    a = ap.parse_args()
    lon0, lat0, lon1, lat1 = a.bbox
    z = a.zoom
    x0, y1 = deg2num(lat0, lon0, z)
    x1, y0 = deg2num(lat1, lon1, z)
    tx0, tx1, ty0, ty1 = int(x0), int(x1), int(y0), int(y1)
    a.cache.mkdir(parents=True, exist_ok=True)
    W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    img = Image.new("RGB", (W, H), (235, 235, 235))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            t = tile(a.base, z, tx, ty, a.cache)
            if t:
                img.paste(t, ((tx - tx0) * 256, (ty - ty0) * 256))

    def px(lon, lat):
        x, y = deg2num(lat, lon, z)
        return (x - tx0) * 256, (y - ty0) * 256

    cx0, cy0 = px(lon0, lat1)
    cx1, cy1 = px(lon1, lat0)
    fig_w = 16
    fig, ax = plt.subplots(figsize=(fig_w, fig_w * (cy1 - cy0) / (cx1 - cx0)), dpi=110)
    ax.imshow(img, extent=(0, W, H, 0))
    if a.base == "seamlessphoto":
        ax.imshow(Image.new("RGBA", (2, 2), (255, 255, 255, 40)), extent=(0, W, H, 0))

    def inside(lon, lat, m=0.02):
        return lon0 - m <= lon <= lon1 + m and lat0 - m <= lat <= lat1 + m

    n_osm = 0
    seen = set()
    if not a.no_osm:
        for reg in REGIONS:
            p = a.root / "data" / f"{reg}_lines.geojson"
            if not p.exists():
                continue
            for f in json.loads(p.read_text())["features"]:
                pr = f["properties"]
                oid = pr.get("osm_id")
                if oid in seen:
                    continue
                g = f["geometry"]
                cs = g["coordinates"] if g["type"] == "LineString" else [c for part in g["coordinates"] for c in part]
                if not any(inside(c[0], c[1], 0) for c in cs):
                    continue
                kv = kv_of(pr)
                if kv < a.min_kv:
                    continue
                seen.add(oid)
                n_osm += 1
                xs, ys = zip(*[px(c[0], c[1]) for c in cs])
                cab = pr.get("power") == "cable" or pr.get("location") in ("underground", "underwater")
                ax.plot(xs, ys, color=col(kv), lw=2.2 if kv >= 275 else 1.4, ls=(0, (4, 2)) if cab else "-", alpha=0.95, zorder=5)
                if a.labels:
                    mid = cs[len(cs) // 2]
                    if inside(mid[0], mid[1], 0):
                        mx, my = px(mid[0], mid[1])
                        nm = str(pr.get("name") or "")[:14]
                        tag = f"{nm} {kv:.0f}kV 回線{pr.get('circuits') or '?'} 線{pr.get('cables') or '?'} 導体{pr.get('wires') or '?'}"
                        ax.text(mx, my, tag, fontsize=6.5, color="black", zorder=9,
                                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec=col(kv), lw=0.6, alpha=0.85))
    if a.model:
        b = json.loads((a.root / "docs/data/built/all.json").read_text())
        for e in b["edges"]:
            if float(e.get("kv") or 0) < a.min_kv:
                continue
            path = e.get("path") or [e["a"], e["b"]]
            if not any(inside(q[1], q[0], 0) for q in path):
                continue
            xs, ys = zip(*[px(q[1], q[0]) for q in path])
            ax.plot(xs, ys, color="black", lw=0.9, ls=(0, (1, 2)), zorder=7)
            mid = path[len(path) // 2]
            if inside(mid[1], mid[0], 0) and a.labels:
                mx, my = px(mid[1], mid[0])
                ax.text(mx, my + 9, f"モデル {str(e.get('name') or '')[:10]} {float(e.get('kv') or 0):.0f}kV ×{e.get('par')}",
                        fontsize=6, color="white", zorder=9, bbox=dict(boxstyle="round,pad=0.12", fc="black", ec="none", alpha=0.7))
        for n in b["nodes"]:
            if inside(n["lon"], n["lat"], 0) and n.get("sub") and float(n.get("kv") or 0) >= max(a.min_kv, 0):
                x, y = px(n["lon"], n["lat"])
                ax.plot(x, y, "s", ms=5, mfc="white", mec="black", mew=1.0, zorder=8)
                ax.text(x + 5, y - 5, f"{str(n.get('name') or '')[:10]} {float(n.get('kv') or 0):.0f}", fontsize=7, color="black", zorder=9,
                        bbox=dict(boxstyle="round,pad=0.1", fc="#ffffcc", ec="none", alpha=0.85))
    if a.plants:
        got = set()
        for reg in REGIONS:
            p = a.root / "data" / f"{reg}_plants.geojson"
            if not p.exists():
                continue
            for f in json.loads(p.read_text())["features"]:
                pr = f["properties"]
                g = f["geometry"]
                c = g["coordinates"]
                while isinstance(c[0], (list, tuple)):
                    c = c[0]
                if not inside(c[0], c[1], 0):
                    continue
                try:
                    cap = float(pr.get("capacity_mw") or 0)
                except (TypeError, ValueError):
                    cap = 0.0
                nm = str(pr.get("name") or pr.get("_display_name") or "")
                if cap < 50 or (nm, round(c[0], 3)) in got:
                    continue
                got.add((nm, round(c[0], 3)))
                x, y = px(c[0], c[1])
                ax.plot(x, y, "^", ms=9, mfc="#00cc66", mec="black", zorder=8)
                ax.text(x + 6, y + 4, f"{nm[:16]} {cap:.0f}MW {pr.get('fuel_type') or pr.get('plant:source') or ''}", fontsize=7, zorder=9,
                        bbox=dict(boxstyle="round,pad=0.1", fc="#ccffdd", ec="none", alpha=0.9))
    ax.set_xlim(cx0, cx1)
    ax.set_ylim(cy1, cy0)
    ax.set_axis_off()
    ax.set_title(f"{a.title}  [OSM の線 {n_osm} 本・実線。正典の枝は黒の点線]  出典: 国土地理院 地理院タイル({a.base})・© OpenStreetMap contributors",
                 fontsize=9)
    fig.savefig(a.out, bbox_inches="tight", pad_inches=0.05)
    print(a.out, img.size, "OSM", n_osm)


if __name__ == "__main__":
    main()
