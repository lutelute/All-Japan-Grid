"""
Layer figures with WHITE background for IEEJ paper.
Generates: fig_layer_combined.png  (3-panel subplots, equal axes size)
"""

import json
import os
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

VOLT_COLORS = {
    500: "#cc0000",
    275: "#e06c00",
    154: "#a0a000",
    110: "#007700",
    66:  "#0055bb",
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
                ax.plot(xs, ys, color="#999999", lw=2.0, zorder=1)


def setup_ax(ax, title, show_ylabels=True):
    """共通軸設定。フォント・線幅は 0.325\textwidth (~55mm) 表示を想定して4倍スケール。"""
    ax.set_xlim(*JAPAN_LON)
    ax.set_ylim(*JAPAN_LAT)
    ax.set_facecolor("white")
    ax.set_aspect(1 / 0.80, adjustable="box")
    ax.set_xticks([125, 130, 135, 140, 145])
    ax.set_xticklabels(["125°E","130°E","135°E","140°E","145°E"], fontsize=24, color="#555")
    ax.set_yticks([25, 30, 35, 40, 45])
    if show_ylabels:
        ax.set_yticklabels(["25°N","30°N","35°N","40°N","45°N"], fontsize=24, color="#555")
    else:
        ax.set_yticklabels([])
    ax.tick_params(length=10, width=2.0, color="#aaa")
    for sp in ax.spines.values():
        sp.set_visible(True)
        sp.set_color("#888888")
        sp.set_linewidth(2.5)
    ax.set_title(title, fontsize=38, pad=8, color="#222")
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


if __name__ == "__main__":
    print("Loading data...")
    segs = load_lines()
    subs = load_substations()
    large, re_small = load_plants()
    print(f"  Lines: {sum(len(v) for v in segs.values()):,}, Subs: {len(subs):,}")
    print(f"  Large: {len(large):,}, RE: {len(re_small):,}")

    # ── 3パネル統合図（サイズ完全一致） ──────────────────
    fig, axes = plt.subplots(1, 3, figsize=(30, 10), facecolor="white",
                              gridspec_kw={"wspace": 0.12})
    ax_a, ax_b, ax_c = axes

    setup_ax(ax_a, "(a) 送電線ネットワーク", show_ylabels=True)
    setup_ax(ax_b, "(b) 変電所分布",         show_ylabels=False)
    setup_ax(ax_c, "(c) 発電所分布",         show_ylabels=False)

    # (a) 送電線
    for v in VOLT_ORDER:
        col = VOLT_COLORS[v]
        lw  = {500: 3.5, 275: 2.5, 154: 1.7, 110: 1.3, 66: 0.9}[v]
        alpha = {500: 1.0, 275: 0.95, 154: 0.85, 110: 0.75, 66: 0.65}[v]
        for xs, ys in segs[v]:
            ax_a.plot(xs, ys, color=col, lw=lw, alpha=alpha, zorder=2)
    leg_net = [Line2D([0], [0], color=VOLT_COLORS[v], lw=7, label=f"{v} kV")
               for v in VOLT_ORDER]
    ax_a.legend(handles=leg_net, loc="lower right",
                facecolor="white", edgecolor="#888", fontsize=24,
                title="電圧クラス", title_fontsize=22)

    # (b) 変電所
    for lon, lat, v in sorted(subs, key=lambda x: x[2]):
        col = VOLT_COLORS.get(v, "#888")
        sz  = {500: 80, 275: 45, 154: 20, 110: 14, 66: 6}[v]
        ax_b.scatter(lon, lat, c=col, s=sz, marker="o", zorder=3,
                     alpha=0.85, linewidths=0)
    leg_sub = [mpatches.Patch(color=VOLT_COLORS[v], label=f"{v} kV")
               for v in VOLT_ORDER]
    ax_b.legend(handles=leg_sub, loc="lower right",
                facecolor="white", edgecolor="#888", fontsize=24,
                title="電圧クラス", title_fontsize=22)

    # (c) 発電所
    ax_c.scatter([p[0] for p in re_small], [p[1] for p in re_small],
                 c="#f0a000", s=6, marker=".", alpha=0.5, zorder=2)
    for lon, lat, cap in large:
        sz = max(50, min(500, cap * 0.20))
        ax_c.scatter(lon, lat, c="#cc2200", s=sz, marker="^",
                     alpha=0.85, zorder=4, linewidths=1.2, edgecolors="#880000")
    leg_plt = [
        mpatches.Patch(color="#cc2200", label=f"大型集中電源（{len(large):,}箇所）"),
        mpatches.Patch(color="#f0a000", label=f"分散型再エネ（{len(re_small):,}箇所）"),
    ]
    ax_c.legend(handles=leg_plt, loc="lower right",
                facecolor="white", edgecolor="#888", fontsize=24,
                title="発電所種別", title_fontsize=22)

    out = f"{OUT_DIR}/fig_layer_combined.png"
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"Saved: {out}")
