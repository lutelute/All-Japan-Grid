"""
Satellite validation figure v3 – proper contextily with Web Mercator.
6 sites: dense 500kV areas (nuclear plants, frequency converters, urban hubs).
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
from pyproj import Transformer
import contextily as ctx

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo", "sans-serif"]
else:
    try:
        import japanize_matplotlib  # noqa
    except ImportError:
        pass

DATA_DIR = "data"
OUT_DIR  = "papers/figs"
REGIONS  = ["hokkaido","tohoku","tokyo","chubu","hokuriku",
            "kansai","chugoku","shikoku","kyushu","okinawa"]

VOLT_COLORS = {500:"#ff2222", 275:"#ff9900", 154:"#ffee00",
               110:"#44ee44", 66:"#44aaff"}
VOLT_ORDER  = [500, 275, 154, 110, 66]

# (label, center_lat, center_lon, half_span_lat_deg)
# Sites chosen for dense 500kV infrastructure visible from satellite
SITES = [
    ("鹿島火力発電所\n(500kV 送電鉄塔群)",   35.983, 140.667, 0.016),
    ("嶺南変電所\n(若狭湾 500kV 集約点)",    35.520, 135.820, 0.016),
    ("川内原発\n(500kV 引込み)",             31.833, 130.186, 0.018),
    ("柏崎刈羽原発\n(世界最大 500kV)",       37.422, 138.597, 0.018),
    ("大飯原発\n(若狭湾 500kV)",             35.535, 135.658, 0.018),
    ("泊原発\n(北海道 500kV)",               43.038, 140.547, 0.018),
]

T4326_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def snap_v(v_str):
    try:
        v = int(str(v_str).split(";")[0]) // 1000
        return min([500,275,154,110,66], key=lambda c: abs(c-v))
    except Exception:
        return 66


def load_all():
    lines, subs, plants = [], [], []
    LARGE_FUELS = {"nuclear","coal","gas","lng","oil","geothermal","hydro"}
    UTIL_KW     = ["電力","電源開発","tepco","kepco","j-power","原子力"]
    for r in REGIONS:
        # lines
        p = f"{DATA_DIR}/{r}_lines.geojson"
        if os.path.exists(p):
            for feat in json.load(open(p))["features"]:
                v = snap_v(feat["properties"].get("voltage"))
                g = feat["geometry"]
                if g["type"] == "LineString":
                    lines.append((v, [c[0] for c in g["coordinates"]],
                                     [c[1] for c in g["coordinates"]]))
                elif g["type"] == "MultiLineString":
                    for part in g["coordinates"]:
                        lines.append((v, [c[0] for c in part],
                                         [c[1] for c in part]))
        # substations
        p = f"{DATA_DIR}/{r}_substations.geojson"
        if os.path.exists(p):
            for feat in json.load(open(p))["features"]:
                g = feat["geometry"]
                if g["type"] == "Point":
                    lon, lat = g["coordinates"][0], g["coordinates"][1]
                elif g["type"] == "Polygon":
                    cs = g["coordinates"][0]
                    lon = np.mean([c[0] for c in cs])
                    lat = np.mean([c[1] for c in cs])
                else:
                    continue
                v = snap_v(feat["properties"].get("voltage"))
                subs.append((lon, lat, v))
        # plants
        p = f"{DATA_DIR}/{r}_plants.geojson"
        if os.path.exists(p):
            for feat in json.load(open(p))["features"]:
                g = feat["geometry"]
                if g["type"] == "Point":
                    lon, lat = g["coordinates"][0], g["coordinates"][1]
                elif g["type"] == "Polygon":
                    cs = g["coordinates"][0]
                    lon = np.mean([c[0] for c in cs])
                    lat = np.mean([c[1] for c in cs])
                else:
                    continue
                pr = feat["properties"]
                fuel = (pr.get("fuel_type") or pr.get("plant:source") or "").lower()
                try: cap = float(pr.get("capacity_mw") or 0)
                except: cap = 0.0
                op = str(pr.get("operator") or "").lower()
                is_large = (fuel in LARGE_FUELS or
                            any(k in op for k in UTIL_KW) or cap >= 100)
                plants.append((lon, lat, cap, is_large))
    return lines, subs, plants


def draw_site(ax, lines, subs, plants, clat, clon, span_lat):
    span_lon = span_lat / 0.77   # Japan ~36deg lat correction
    lat_min, lat_max = clat - span_lat, clat + span_lat
    lon_min, lon_max = clon - span_lon, clon + span_lon

    # Convert bbox to Web Mercator
    x1, y1 = T4326_3857.transform(lon_min, lat_min)
    x2, y2 = T4326_3857.transform(lon_max, lat_max)

    ax.set_xlim(x1, x2)
    ax.set_ylim(y1, y2)
    ax.set_aspect("equal", adjustable="box")
    ax.set_facecolor("#222")

    # ── Satellite basemap ──
    try:
        ctx.add_basemap(
            ax, crs="EPSG:3857",
            source=ctx.providers.Esri.WorldImagery,
            zoom="auto", attribution=False,
        )
    except Exception as e:
        print(f"    basemap failed: {e}")

    # ── Transmission lines (transform to WebMercator) ──
    for v in VOLT_ORDER:   # draw low-V first so 500kV on top
        col = VOLT_COLORS[v]
        lw  = {500:2.8, 275:2.0, 154:1.4, 110:1.0, 66:0.7}[v]
        for volt, xs, ys in lines:
            if volt != v: continue
            # clip to bbox
            in_box = any(lon_min <= x <= lon_max and lat_min <= y <= lat_max
                         for x, y in zip(xs, ys))
            if not in_box: continue
            xm, ym = T4326_3857.transform(xs, ys)
            ax.plot(xm, ym, color=col, lw=lw, alpha=0.95, zorder=3,
                    solid_capstyle="round")

    # ── Substations ──
    for lon, lat, v in subs:
        if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
            continue
        xm, ym = T4326_3857.transform(lon, lat)
        col = VOLT_COLORS.get(v, "#888")
        sz  = {500:120, 275:60, 154:30, 110:20, 66:10}[v]
        ax.scatter(xm, ym, c=col, s=sz, marker="o", zorder=5,
                   alpha=0.95, edgecolors="white", linewidths=0.8)

    # ── Plants ──
    for lon, lat, cap, is_large in plants:
        if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
            continue
        xm, ym = T4326_3857.transform(lon, lat)
        if is_large:
            sz = max(80, min(250, cap * 0.12))
            ax.scatter(xm, ym, c="#ff4400", s=sz, marker="^", zorder=6,
                       alpha=0.95, edgecolors="white", linewidths=0.8)
        else:
            ax.scatter(xm, ym, c="#ffe000", s=15, marker=".", zorder=4,
                       alpha=0.6, linewidths=0)

    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color("#555")


def main():
    print("Loading data...")
    lines, subs, plants = load_all()
    print(f"  {len(lines):,} lines, {len(subs):,} subs, {len(plants):,} plants")

    fig, axes = plt.subplots(2, 3, figsize=(14, 9.5), facecolor="white")
    axes = axes.flatten()

    for idx, (label, clat, clon, span) in enumerate(SITES):
        ax = axes[idx]
        short = label.replace("\n", " ")
        print(f"  [{idx+1}] {short}")
        draw_site(ax, lines, subs, plants, clat, clon, span)
        ax.set_title(label, fontsize=8.5, pad=4, color="#111",
                     fontweight="bold", loc="left")

    # Shared legend
    hdls = [Line2D([0],[0], color=VOLT_COLORS[v], lw=2.5, label=f"{v} kV")
            for v in VOLT_ORDER]
    hdls += [
        mpatches.Patch(color="#ff4400", label="大型発電所 (△)"),
        mpatches.Patch(color=VOLT_COLORS[500], label="変電所 (○)"),
    ]
    fig.legend(handles=hdls, loc="lower center", ncol=7,
               fontsize=8, facecolor="white", edgecolor="#bbb",
               bbox_to_anchor=(0.5, -0.01))

    plt.suptitle(
        "衛星画像 (Esri World Imagery) との重畳照合——500 kV 密集地点の位置精度確認",
        fontsize=11, y=1.01, color="#111",
    )
    plt.tight_layout(rect=[0, 0.04, 1, 1], pad=1.2)
    out = f"{OUT_DIR}/fig_satellite_validation.png"
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
