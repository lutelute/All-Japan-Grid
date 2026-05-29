"""DEPRECATED — superseded by ``gen_satellite_v3.py`` (proper Web Mercator).

Retained only for reproducing earlier prototype results. Use v3 for new work.

Satellite validation figure for IEEJ paper.
Shows 500kV-dense sites with visible transmission towers/substations/plants.
Sites selected for dense 500kV infrastructure visible from space.
"""

import json
import os
import sys
import platform
import warnings
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

warnings.filterwarnings("ignore")

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

VOLT_COLORS = {
    500: "#ff2222",
    275: "#ff8800",
    154: "#ddcc00",
    110: "#44cc44",
    66:  "#4488ff",
}
VOLT_ORDER = [500, 275, 154, 110, 66]

# Sites: (label, center_lat, center_lon, half_span_deg)
# Selected for 500kV line density, visible towers/substations/plants
SITES = [
    ("東清水FC\n(周波数変換所)", 35.003, 138.843, 0.018),  # 0.9km
    ("新信濃FC\n(周波数変換所)", 36.218, 137.841, 0.018),
    ("若狭 大飯原発\n(500kV 引込み)", 35.540, 135.657, 0.025),
    ("川内原発\n(500kV 引込み)", 31.833, 130.186, 0.020),
    ("東京電力\n千葉火力周辺", 35.603, 140.084, 0.020),
    ("北海道 北本連系\n(本別 DC端末)", 43.085, 143.608, 0.022),
]


def snap_voltage(v_str):
    try:
        v = int(str(v_str).split(";")[0]) // 1000
        return min([500, 275, 154, 110, 66], key=lambda c: abs(c - v))
    except Exception:
        return 66


def load_all_lines():
    segs = []
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
                segs.append((v, [c[0] for c in geom["coordinates"]],
                             [c[1] for c in geom["coordinates"]]))
            elif geom["type"] == "MultiLineString":
                for part in geom["coordinates"]:
                    segs.append((v, [c[0] for c in part], [c[1] for c in part]))
    return segs


def load_all_substations():
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


def load_all_plants():
    pts = []
    LARGE = {"nuclear","coal","gas","lng","oil","geothermal","hydro"}
    UTIL_KW = ["電力","電源開発","tepco","kepco","j-power"]
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
            is_large = (fuel in LARGE or any(k in op for k in UTIL_KW) or cap >= 100)
            pts.append((lon, lat, cap, is_large))
    return pts


def draw_site(ax, lines, subs, plants, clat, clon, span):
    lat_min = clat - span * 0.8
    lat_max = clat + span * 0.8
    lon_min = clon - span
    lon_max = clon + span

    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)
    ax.set_facecolor("#e8f0e0")  # light terrain background
    ax.set_aspect(1 / 0.80, adjustable="box")
    ax.tick_params(labelsize=5.5, colors="#555")
    for sp in ax.spines.values():
        sp.set_color("#bbb")

    # Try contextily for satellite background
    try:
        import contextily as ctx
        import geopandas as gpd
        from shapely.geometry import box
        rect = gpd.GeoDataFrame(geometry=[box(lon_min, lat_min, lon_max, lat_max)],
                                crs="EPSG:4326")
        rect_web = rect.to_crs("EPSG:3857")
        bounds = rect_web.total_bounds
        ax_bounds = [bounds[0], bounds[2], bounds[1], bounds[3]]
        ctx.add_basemap(ax, crs="EPSG:3857",
                        source=ctx.providers.Esri.WorldImagery,
                        zoom="auto", attribution=False)
        # After basemap, set correct extent
        ax.set_xlim(lon_min, lon_max)
        ax.set_ylim(lat_min, lat_max)
    except Exception:
        pass  # fall back to light green background

    # Draw lines – voltage order: 66 first (bottom), 500 last (top)
    for v in VOLT_ORDER[::-1]:
        col = VOLT_COLORS[v]
        lw = {500: 2.2, 275: 1.6, 154: 1.2, 110: 0.9, 66: 0.7}[v]
        for volt, xs, ys in lines:
            if volt != v:
                continue
            clipped_x, clipped_y = [], []
            for x, y in zip(xs, ys):
                if lon_min <= x <= lon_max and lat_min <= y <= lat_max:
                    clipped_x.append(x)
                    clipped_y.append(y)
            if len(clipped_x) >= 2:
                ax.plot(xs, ys, color=col, lw=lw, alpha=0.9,
                        solid_capstyle="round", zorder=3)

    # Draw substations
    for lon, lat, v in subs:
        if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
            col = VOLT_COLORS.get(v, "#888")
            sz = {500: 60, 275: 35, 154: 18, 110: 12, 66: 8}[v]
            ax.scatter(lon, lat, c=col, s=sz, marker="o",
                       zorder=5, alpha=0.9, edgecolors="white", linewidths=0.6)

    # Draw plants
    for lon, lat, cap, is_large in plants:
        if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
            if is_large:
                sz = max(40, min(150, cap * 0.08))
                ax.scatter(lon, lat, c="#cc2200", s=sz, marker="^",
                           zorder=6, alpha=0.9, edgecolors="white", linewidths=0.6)
            else:
                ax.scatter(lon, lat, c="#f7c840", s=8, marker=".",
                           zorder=4, alpha=0.5, linewidths=0)


def main():
    print("Loading data...")
    lines = load_all_lines()
    subs  = load_all_substations()
    plants = load_all_plants()
    print(f"  {len(lines):,} lines, {len(subs):,} subs, {len(plants):,} plants")

    ncols = 3
    nrows = 2
    fig, axes = plt.subplots(nrows, ncols, figsize=(15, 10), facecolor="white")
    axes = axes.flatten()

    for idx, (label, clat, clon, span) in enumerate(SITES):
        if idx >= len(axes):
            break
        ax = axes[idx]
        print(f"  Drawing: {label.replace(chr(10), ' ')}")
        draw_site(ax, lines, subs, plants, clat, clon, span)
        ax.set_title(label, fontsize=8.5, pad=4, color="#222", fontweight="bold")

    # Hide unused axes
    for idx in range(len(SITES), len(axes)):
        axes[idx].set_visible(False)

    # Shared legend
    legend_handles = [
        Line2D([0], [0], color=VOLT_COLORS[v], lw=2.5, label=f"{v} kV")
        for v in VOLT_ORDER
    ] + [
        mpatches.Patch(color="#cc2200", label="大型発電所 △"),
        mpatches.Patch(color="#f7c840", label="分散型RE ●"),
        mpatches.Patch(color=VOLT_COLORS[500], label="変電所 ○"),
    ]
    fig.legend(handles=legend_handles, loc="lower center", ncol=8,
               fontsize=7.5, facecolor="white", edgecolor="#bbb",
               title="送電線電圧・設備種別", title_fontsize=8,
               bbox_to_anchor=(0.5, -0.01))

    plt.suptitle(
        "衛星画像（Esri World Imagery）との照合——500 kV 密集地点の位置精度確認",
        fontsize=11, y=1.01, color="#222"
    )
    plt.tight_layout(rect=[0, 0.04, 1, 1])
    out = f"{OUT_DIR}/fig_satellite_validation.png"
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
