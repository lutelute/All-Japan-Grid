"""
10地域別送電網トポロジ図 (fig_regional_networks.png)
・2行×5列サブプロット
・緯度経度ラベルなし・枠線なし
・電圧クラス別色分け、陸地塗りつぶし
"""
import json, os, sys, platform
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon as MplPolygon

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

DATA_DIR = "data"
OUT_DIR  = "papers/figs"
os.makedirs(OUT_DIR, exist_ok=True)

REGIONS = ["hokkaido","tohoku","tokyo","chubu","hokuriku",
           "kansai","chugoku","shikoku","kyushu","okinawa"]
REGION_JP = {"hokkaido":"北海道","tohoku":"東北","tokyo":"東京",
             "chubu":"中部","hokuriku":"北陸","kansai":"関西",
             "chugoku":"中国","shikoku":"四国","kyushu":"九州","okinawa":"沖縄"}

# 各地域のバウンディングボックス（lon_min, lon_max, lat_min, lat_max）
REGION_BBOX = {
    "hokkaido": (139.3, 145.8, 41.3, 45.5),
    "tohoku":   (139.5, 142.0, 36.8, 41.5),
    "tokyo":    (138.7, 141.0, 34.8, 37.5),
    "chubu":    (136.0, 138.8, 34.5, 37.2),
    "hokuriku": (135.7, 137.8, 35.8, 37.5),
    "kansai":   (134.5, 136.5, 33.8, 35.8),
    "chugoku":  (131.0, 134.5, 33.5, 35.5),
    "shikoku":  (132.5, 134.8, 32.8, 34.2),
    "kyushu":   (129.5, 132.0, 31.0, 34.0),
    "okinawa":  (122.8, 131.5, 24.0, 28.5),
}

VOLT_COLORS = {500:"#d62728", 275:"#ff7f0e", 154:"#9B8B00",
               110:"#2ca02c",  66:"#1f77b4"}
VOLT_LW     = {500:1.5, 275:1.0, 154:0.7, 110:0.5, 66:0.3}
VOLT_ORDER  = [66, 110, 154, 275, 500]
VOLT_LABEL  = {500:"500 kV", 275:"275 kV", 154:"154 kV",
               110:"110 kV",  66:"66 kV"}
COLOR_OCEAN = "#d8eaf8"
COLOR_LAND  = "#f7f4ee"
COLOR_COAST = "#aaaaaa"


def snap_v(v_str):
    try:
        v = int(str(v_str).split(";")[0]) // 1000
        return min(VOLT_ORDER, key=lambda c: abs(c - v))
    except:
        return 66


def load_land():
    p = "papers/figs/ne_countries.geojson"
    polys = []
    if not os.path.exists(p): return polys
    with open(p) as f: fc = json.load(f)
    for feat in fc["features"]:
        g = feat["geometry"]
        rings = ([g["coordinates"][0]] if g["type"]=="Polygon"
                 else [p[0] for p in g["coordinates"]] if g["type"]=="MultiPolygon"
                 else [])
        for ring in rings:
            polys.append([(c[0], c[1]) for c in ring])
    return polys


print("データ読み込み中...")
land_polys = load_land()

# 地域別に送電線を読み込み
region_lines = {}
for r in REGIONS:
    lines = {v: [] for v in VOLT_ORDER}
    p = f"{DATA_DIR}/{r}_lines.geojson"
    if os.path.exists(p):
        with open(p) as f: feats = json.load(f)["features"]
        for feat in feats:
            v = snap_v(feat["properties"].get("voltage"))
            g = feat["geometry"]
            segs = ([g["coordinates"]] if g["type"]=="LineString"
                    else g["coordinates"] if g["type"]=="MultiLineString" else [])
            for seg in segs:
                lines[v].append(([c[0] for c in seg], [c[1] for c in seg]))
    region_lines[r] = lines
    total = sum(len(lines[v]) for v in VOLT_ORDER)
    print(f"  {REGION_JP[r]}: {total}本")

# ── 描画 ─────────────────────────────────────────────
fig, axes = plt.subplots(2, 5, figsize=(16, 7), facecolor="white",
                          gridspec_kw={"hspace":0.08, "wspace":0.05})
axes_flat = axes.flatten()

for idx, r in enumerate(REGIONS):
    ax = axes_flat[idx]
    lon0, lon1, lat0, lat1 = REGION_BBOX[r]
    lat_c = (lat0 + lat1) / 2
    aspect = 1.0 / np.cos(np.radians(lat_c))

    ax.set_facecolor(COLOR_OCEAN)

    # 陸地塗りつぶし（bbox内のみ）
    margin = max((lon1-lon0), (lat1-lat0)) * 0.3
    for pts in land_polys:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if (max(xs) < lon0-margin or min(xs) > lon1+margin or
            max(ys) < lat0-margin or min(ys) > lat1+margin):
            continue
        poly = MplPolygon(pts, closed=True,
                          facecolor=COLOR_LAND, edgecolor=COLOR_COAST,
                          linewidth=0.4, zorder=2)
        ax.add_patch(poly)

    # 送電線
    for v in VOLT_ORDER:
        col = VOLT_COLORS[v]
        lw  = VOLT_LW[v]
        for xs, ys in region_lines[r][v]:
            ax.plot(xs, ys, color=col, lw=lw, alpha=0.88,
                    solid_capstyle="round", zorder=3+VOLT_ORDER.index(v))

    ax.set_xlim(lon0, lon1)
    ax.set_ylim(lat0, lat1)
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)

    # 地域名ラベル（左上）
    ax.text(0.04, 0.97, REGION_JP[r],
            transform=ax.transAxes,
            fontsize=10, fontweight="bold",
            va="top", ha="left",
            color="#222222",
            bbox=dict(facecolor="white", edgecolor="none",
                      alpha=0.75, pad=1.5))

# 共通凡例（下中央）
legend_handles = [
    Line2D([0],[0], color=VOLT_COLORS[v], lw=2.5, label=VOLT_LABEL[v])
    for v in reversed(VOLT_ORDER)
]
fig.legend(handles=legend_handles,
           loc="lower center", ncol=5,
           fontsize=9, facecolor="white", edgecolor="#bbb",
           bbox_to_anchor=(0.5, -0.02), framealpha=0.92,
           handlelength=2.2, labelspacing=0.4,
           borderpad=0.6)

plt.tight_layout(rect=[0, 0.05, 1, 1], pad=0.3)
out = f"{OUT_DIR}/fig_regional_networks.png"
plt.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
plt.close()
print(f"Saved: {out}")
