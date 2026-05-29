"""
3-layer visualization for IEEJ paper:
  fig_layer_network.png   - transmission lines only
  fig_layer_substations.png - substations only
  fig_layer_plants.png    - power plants: large utility vs distributed RE
"""

import json
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

DATA_DIR = "data"
OUT_DIR = "papers/figs"
os.makedirs(OUT_DIR, exist_ok=True)

REGIONS = [
    "hokkaido","tohoku","tokyo","chubu","hokuriku",
    "kansai","chugoku","shikoku","kyushu","okinawa",
]

# Japanese bounding box
JAPAN_LON = (122.5, 148.5)
JAPAN_LAT  = (24.0,  45.5)

VOLT_COLORS = {
    500: "#d62728",
    275: "#ff7f0e",
    154: "#bcbd22",
    110: "#2ca02c",
    66:  "#1f77b4",
}
VOLT_ORDER = [500, 275, 154, 110, 66]

UTIL_OPS = {
    "東京電力","tepco","東北電力","北海道電力","中部電力","北陸電力",
    "関西電力","中国電力","四国電力","九州電力","沖縄電力","電源開発",
    "日本原子力","東京発電","東北発電",
}

RE_FUELS = {"solar","wind","biomass","waste","biofuel"}
LARGE_FUELS = {"nuclear","coal","gas","lng","oil","geothermal"}


def snap_voltage(v_str):
    try:
        v = int(str(v_str).split(";")[0]) // 1000
        candidates = [500, 275, 154, 110, 66]
        return min(candidates, key=lambda c: abs(c - v))
    except Exception:
        return 66


def load_lines():
    segs = {v: [] for v in VOLT_ORDER}
    for r in REGIONS:
        path = f"{DATA_DIR}/{r}_lines.geojson"
        if not os.path.exists(path):
            continue
        with open(path) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            props = feat["properties"]
            v_raw = props.get("voltage")
            v = snap_voltage(v_raw) if v_raw else 66
            geom = feat["geometry"]
            if geom["type"] == "LineString":
                coords = geom["coordinates"]
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                segs[v].append((xs, ys))
            elif geom["type"] == "MultiLineString":
                for part in geom["coordinates"]:
                    xs = [c[0] for c in part]
                    ys = [c[1] for c in part]
                    segs[v].append((xs, ys))
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
            v_raw = feat["properties"].get("voltage")
            v = snap_voltage(v_raw) if v_raw else 66
            pts.append((lon, lat, v))
    return pts


def load_plants():
    large, re_small = [], []
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
            cap = p.get("capacity_mw")
            try:
                cap = float(cap) if cap is not None else 0.0
            except Exception:
                cap = 0.0
            op = str(p.get("operator") or "").lower()
            is_re = fuel in RE_FUELS or fuel == "solar" or fuel == "wind"
            is_large_fuel = fuel in LARGE_FUELS
            is_util_op = any(u.lower() in op for u in UTIL_OPS) or cap >= 100

            if is_re:
                re_small.append((lon, lat, cap))
            elif is_large_fuel or is_util_op:
                large.append((lon, lat, cap))
            else:
                re_small.append((lon, lat, cap))  # default to RE bucket
    return large, re_small


def setup_ax(ax):
    ax.set_xlim(*JAPAN_LON)
    ax.set_ylim(*JAPAN_LAT)
    ax.set_facecolor("#0a0f1a")
    ax.set_aspect(1 / 0.80, adjustable="box")
    ax.tick_params(colors="white", labelsize=7)
    for sp in ax.spines.values():
        sp.set_color("#334")

    # Add coastline from ne_countries
    coast_path = "papers/figs/ne_countries.geojson"
    if os.path.exists(coast_path):
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
                    ax.plot(xs, ys, color="#3a4a6a", lw=0.4, zorder=1)


# ─── Figure 1: Network only ────────────────────────────────────────
def fig_network(segs):
    fig, ax = plt.subplots(figsize=(10, 9), facecolor="#0a0f1a")
    setup_ax(ax)
    ax.set_title("送電線ネットワーク（全国）", color="white", fontsize=12, pad=6)

    for v in VOLT_ORDER:
        col = VOLT_COLORS[v]
        lw = {500: 1.0, 275: 0.7, 154: 0.5, 110: 0.4, 66: 0.3}[v]
        alpha = {500: 0.95, 275: 0.90, 154: 0.80, 110: 0.75, 66: 0.65}[v]
        for xs, ys in segs[v]:
            ax.plot(xs, ys, color=col, lw=lw, alpha=alpha, zorder=2)

    legend_handles = [
        Line2D([0], [0], color=VOLT_COLORS[v], lw=2, label=f"{v} kV")
        for v in VOLT_ORDER
    ]
    ax.legend(handles=legend_handles, loc="upper right",
              facecolor="#1a2030", edgecolor="#445", labelcolor="white",
              fontsize=8, title="電圧クラス", title_fontsize=8)
    plt.tight_layout(pad=0.5)
    out = f"{OUT_DIR}/fig_layer_network.png"
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"Saved: {out}")


# ─── Figure 2: Substations only ───────────────────────────────────
def fig_substations(pts):
    fig, ax = plt.subplots(figsize=(10, 9), facecolor="#0a0f1a")
    setup_ax(ax)
    ax.set_title("変電所分布（全国 6,962箇所）", color="white", fontsize=12, pad=6)

    # Sort by voltage ascending so high-V drawn on top
    pts_sorted = sorted(pts, key=lambda x: x[2])
    for lon, lat, v in pts_sorted:
        col = VOLT_COLORS.get(v, "#888888")
        sz = {500: 12, 275: 8, 154: 5, 110: 4, 66: 2}[v]
        ax.scatter(lon, lat, c=col, s=sz, marker="o", zorder=3,
                   alpha=0.85, linewidths=0)

    legend_handles = [
        mpatches.Patch(color=VOLT_COLORS[v], label=f"{v} kV")
        for v in VOLT_ORDER
    ]
    ax.legend(handles=legend_handles, loc="upper right",
              facecolor="#1a2030", edgecolor="#445", labelcolor="white",
              fontsize=8, title="電圧クラス", title_fontsize=8)
    plt.tight_layout(pad=0.5)
    out = f"{OUT_DIR}/fig_layer_substations.png"
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"Saved: {out}")


# ─── Figure 3: Plants – large utility vs distributed RE ───────────
def fig_plants(large, re_small):
    fig, ax = plt.subplots(figsize=(10, 9), facecolor="#0a0f1a")
    setup_ax(ax)
    ax.set_title("発電所分布（大型集中電源 vs 分散型再エネ）",
                 color="white", fontsize=12, pad=6)

    # RE small (solar, wind, small) – plot first (under)
    re_lons = [p[0] for p in re_small]
    re_lats = [p[1] for p in re_small]
    ax.scatter(re_lons, re_lats, c="#f7c842", s=1.2, marker=".",
               alpha=0.5, zorder=2, label=f"分散型再エネ（太陽光・風力等, {len(re_small):,}箇所）")

    # Large utility – sized by capacity
    for lon, lat, cap in large:
        sz = max(8, min(80, cap * 0.04))
        ax.scatter(lon, lat, c="#e8534a", s=sz, marker="^",
                   alpha=0.85, zorder=4, linewidths=0.3, edgecolors="#ff9999")

    # Legend
    large_patch = mpatches.Patch(color="#e8534a",
                                  label=f"大型集中電源（原子力・火力・水力等, {len(large):,}箇所）")
    re_patch = mpatches.Patch(color="#f7c842",
                               label=f"分散型再エネ（太陽光・風力等, {len(re_small):,}箇所）")
    ax.legend(handles=[large_patch, re_patch], loc="upper right",
              facecolor="#1a2030", edgecolor="#445", labelcolor="white",
              fontsize=7.5, title="発電所種別", title_fontsize=8)

    plt.tight_layout(pad=0.5)
    out = f"{OUT_DIR}/fig_layer_plants.png"
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"Saved: {out}")


if __name__ == "__main__":
    import platform
    if platform.system() == "Darwin":
        plt.rcParams["font.family"] = ["Hiragino Sans", "Hiragino Kaku Gothic ProN",
                                        "Apple SD Gothic Neo", "sans-serif"]
    else:
        try:
            import japanize_matplotlib  # noqa: F401
        except ImportError:
            pass

    print("Loading lines...")
    segs = load_lines()
    total_segs = sum(len(v) for v in segs.values())
    print(f"  {total_segs:,} line segments")

    print("Loading substations...")
    subs = load_substations()
    print(f"  {len(subs):,} substations")

    print("Loading plants...")
    large, re_small = load_plants()
    print(f"  Large utility: {len(large):,}, RE small: {len(re_small):,}")

    print("Generating fig_layer_network.png...")
    fig_network(segs)

    print("Generating fig_layer_substations.png...")
    fig_substations(subs)

    print("Generating fig_layer_plants.png...")
    fig_plants(large, re_small)

    print("Done.")
