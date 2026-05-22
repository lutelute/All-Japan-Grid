"""
Layer figures with WHITE background for IEEJ paper.
Generates: fig_layer_network.png, fig_layer_substations.png, fig_layer_plants.png
"""

import json
import os
import sys
import platform
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo", "sans-serif"]
else:
    try:
        import japanize_matplotlib  # noqa
    except ImportError:
        pass

DATA_DIR = "data"
OUT_DIR = "papers/figs"
os.makedirs(OUT_DIR, exist_ok=True)

REGIONS = [
    "hokkaido","tohoku","tokyo","chubu","hokuriku",
    "kansai","chugoku","shikoku","kyushu","okinawa",
]

JAPAN_LON = (122.5, 148.5)
JAPAN_LAT  = (24.0,  45.5)

# Distinct colors visible on WHITE background
VOLT_COLORS = {
    500: "#cc0000",   # deep red
    275: "#e06c00",   # dark orange
    154: "#a0a000",   # olive/dark yellow
    110: "#007700",   # dark green
    66:  "#0055bb",   # dark blue
}
VOLT_ORDER = [500, 275, 154, 110, 66]


def snap_voltage(v_str):
    try:
        v = int(str(v_str).split(";")[0]) // 1000
        return min([500, 275, 154, 110, 66], key=lambda c: abs(c - v))
    except Exception:
        return 66


def draw_coastline(ax):
    coast_path = "papers/figs/ne_countries.geojson"
    if not os.path.exists(coast_path):
        return
    with open(coast_path) as f:
        coast = json.load(f)
    for feat in coast["features"]:
        geom = feat["geometry"]
        polys = ([geom["coordinates"]] if geom["type"] == "Polygon"
                 else geom["coordinates"])
        for poly in polys:
            for ring in poly:
                xs = [c[0] for c in ring]
                ys = [c[1] for c in ring]
                ax.plot(xs, ys, color="#999999", lw=0.5, zorder=1)


def setup_ax(ax, title):
    ax.set_xlim(*JAPAN_LON)
    ax.set_ylim(*JAPAN_LAT)
    ax.set_facecolor("white")
    ax.set_aspect(1 / 0.80, adjustable="box")
    # 緯度経度ラベル（主要目盛のみ）
    ax.set_xticks([125, 130, 135, 140, 145])
    ax.set_xticklabels(["125°E","130°E","135°E","140°E","145°E"], fontsize=6.5, color="#555")
    ax.set_yticks([25, 30, 35, 40, 45])
    ax.set_yticklabels(["25°N","30°N","35°N","40°N","45°N"], fontsize=6.5, color="#555")
    ax.tick_params(length=3, width=0.5, color="#aaa")
    # 薄い枠線
    for sp in ax.spines.values():
        sp.set_visible(True)
        sp.set_color("#bbbbbb")
        sp.set_linewidth(0.6)
    ax.set_title(title, fontsize=11, pad=5, color="#222")
    draw_coastline(ax)


def load_lines():
    segs = {v: [] for v in VOLT_ORDER}
    for r in REGIONS:
        path = f"{DATA_DIR}/{r}_lines.geojson"
        if not os.path.exists(path):
            continue
        with open(path) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            p = feat["properties"]
            v = snap_voltage(p.get("voltage")) if p.get("voltage") else 66
            geom = feat["geometry"]
            if geom["type"] == "LineString":
                segs[v].append(([c[0] for c in geom["coordinates"]],
                                [c[1] for c in geom["coordinates"]]))
            elif geom["type"] == "MultiLineString":
                for part in geom["coordinates"]:
                    segs[v].append(([c[0] for c in part], [c[1] for c in part]))
    return segs


def load_substations():
    pts = []
    for r in REGIONS:
        path = f"{DATA_DIR}/{r}_substations.geojson"
        if not os.path.exists(path):
            continue
        with open(path) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            geom = feat["geometry"]
            if geom["type"] == "Point":
                lon, lat = geom["coordinates"][0], geom["coordinates"][1]
            elif geom["type"] == "Polygon":
                coords = geom["coordinates"][0]
                lon = np.mean([c[0] for c in coords])
                lat = np.mean([c[1] for c in coords])
            else:
                continue
            v = snap_voltage(feat["properties"].get("voltage")) if feat["properties"].get("voltage") else 66
            pts.append((lon, lat, v))
    return pts


def load_plants():
    large, re_small = [], []
    RE_FUELS = {"solar", "wind", "biomass", "waste", "biofuel"}
    LARGE_FUELS = {"nuclear", "coal", "gas", "lng", "oil", "geothermal", "hydro"}
    UTIL_KEYWORDS = ["電力", "電源開発", "tepco", "kepco", "j-power", "原子力"]
    for r in REGIONS:
        path = f"{DATA_DIR}/{r}_plants.geojson"
        if not os.path.exists(path):
            continue
        with open(path) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            geom = feat["geometry"]
            if geom["type"] == "Point":
                lon, lat = geom["coordinates"][0], geom["coordinates"][1]
            elif geom["type"] == "Polygon":
                coords = geom["coordinates"][0]
                lon = np.mean([c[0] for c in coords])
                lat = np.mean([c[1] for c in coords])
            else:
                continue
            p = feat["properties"]
            fuel = (p.get("fuel_type") or p.get("plant:source") or "").lower()
            try:
                cap = float(p.get("capacity_mw") or 0)
            except Exception:
                cap = 0.0
            op = str(p.get("operator") or "").lower()
            is_re = fuel in RE_FUELS
            is_util = any(kw in op for kw in UTIL_KEYWORDS) or cap >= 100
            is_large_fuel = fuel in LARGE_FUELS
            if is_re:
                re_small.append((lon, lat, cap))
            elif is_large_fuel or is_util:
                large.append((lon, lat, cap))
            else:
                re_small.append((lon, lat, cap))
    return large, re_small


# ── Fig A: Network lines only ──────────────────────────────────────
def fig_network(segs):
    fig, ax = plt.subplots(figsize=(10, 9), facecolor="white")
    setup_ax(ax, "送電線ネットワーク（全国 40,077 本）")
    for v in VOLT_ORDER:
        col = VOLT_COLORS[v]
        lw = {500: 0.9, 275: 0.65, 154: 0.45, 110: 0.35, 66: 0.25}[v]
        alpha = {500: 1.0, 275: 0.95, 154: 0.85, 110: 0.75, 66: 0.65}[v]
        for xs, ys in segs[v]:
            ax.plot(xs, ys, color=col, lw=lw, alpha=alpha, zorder=2)
    legend_handles = [
        Line2D([0], [0], color=VOLT_COLORS[v], lw=2, label=f"{v} kV")
        for v in VOLT_ORDER
    ]
    ax.legend(handles=legend_handles, loc="lower right",
              facecolor="white", edgecolor="#bbb", fontsize=8,
              title="電圧クラス", title_fontsize=8)
    plt.tight_layout(pad=0.5)
    out = f"{OUT_DIR}/fig_layer_network.png"
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"Saved: {out}")


# ── Fig B: Substations only ────────────────────────────────────────
def fig_substations(pts):
    fig, ax = plt.subplots(figsize=(10, 9), facecolor="white")
    setup_ax(ax, "変電所分布（全国 6,962 箇所）")
    pts_sorted = sorted(pts, key=lambda x: x[2])
    for lon, lat, v in pts_sorted:
        col = VOLT_COLORS.get(v, "#888")
        sz = {500: 18, 275: 10, 154: 5, 110: 4, 66: 2}[v]
        ax.scatter(lon, lat, c=col, s=sz, marker="o", zorder=3,
                   alpha=0.85, linewidths=0)
    legend_handles = [
        mpatches.Patch(color=VOLT_COLORS[v], label=f"{v} kV")
        for v in VOLT_ORDER
    ]
    ax.legend(handles=legend_handles, loc="lower right",
              facecolor="white", edgecolor="#bbb", fontsize=8,
              title="電圧クラス", title_fontsize=8)
    plt.tight_layout(pad=0.5)
    out = f"{OUT_DIR}/fig_layer_substations.png"
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"Saved: {out}")


# ── Fig C: Plants – 2 categories ──────────────────────────────────
def fig_plants(large, re_small):
    fig, ax = plt.subplots(figsize=(10, 9), facecolor="white")
    setup_ax(ax, "発電所分布（大型集中電源 vs 分散型再エネ）")
    re_lons = [p[0] for p in re_small]
    re_lats = [p[1] for p in re_small]
    ax.scatter(re_lons, re_lats, c="#f0a000", s=1.5, marker=".",
               alpha=0.5, zorder=2, label=f"分散型再エネ（太陽光・風力等, {len(re_small):,}箇所）")
    for lon, lat, cap in large:
        sz = max(12, min(120, cap * 0.05))
        ax.scatter(lon, lat, c="#cc2200", s=sz, marker="^",
                   alpha=0.85, zorder=4, linewidths=0.3,
                   edgecolors="#880000")
    large_patch = mpatches.Patch(color="#cc2200",
                                  label=f"大型集中電源（原子力・火力等, {len(large):,}箇所）")
    re_patch = mpatches.Patch(color="#f0a000",
                               label=f"分散型再エネ（太陽光・風力等, {len(re_small):,}箇所）")
    ax.legend(handles=[large_patch, re_patch], loc="lower right",
              facecolor="white", edgecolor="#bbb", fontsize=8,
              title="発電所種別", title_fontsize=8)
    plt.tight_layout(pad=0.5)
    out = f"{OUT_DIR}/fig_layer_plants.png"
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"Saved: {out}")


if __name__ == "__main__":
    print("Loading data...")
    segs = load_lines()
    subs = load_substations()
    large, re_small = load_plants()
    print(f"  Lines: {sum(len(v) for v in segs.values()):,}, Subs: {len(subs):,}")
    print(f"  Large: {len(large):,}, RE: {len(re_small):,}")

    fig_network(segs)
    fig_substations(subs)
    fig_plants(large, re_small)
    print("Done.")
