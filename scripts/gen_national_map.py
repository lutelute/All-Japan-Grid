"""
全国送電網トポロジ図 (fig_national_all.png)
・海：薄青、陸地：薄クリーム、送電線：電圧クラス別色
・軸ラベルなし・枠なし・凡例右下
"""
import json, os, sys, platform
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection

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

LON_MIN, LON_MAX = 127.0, 146.5
LAT_MIN, LAT_MAX = 25.5,  46.0

# 送電線の色・太さ
VOLT_COLORS = {500:"#d62728", 275:"#ff7f0e", 154:"#9B8B00",
               110:"#2ca02c",  66:"#1f77b4"}
VOLT_LW    = {500:1.6, 275:1.1, 154:0.75, 110:0.55, 66:0.35}
VOLT_ORDER = [66, 110, 154, 275, 500]
VOLT_LABEL = {500:"500 kV", 275:"275 kV", 154:"154 kV",
              110:"110 kV",  66:"66 kV"}

COLOR_OCEAN = "#d8eaf8"   # 海：薄青
COLOR_LAND  = "#f7f4ee"   # 陸：薄クリーム
COLOR_COAST = "#999999"   # 海岸線


def snap_v(v_str):
    try:
        v = int(str(v_str).split(";")[0]) // 1000
        return min(VOLT_ORDER, key=lambda c: abs(c - v))
    except:
        return 66


# ── 国境・海岸線の読み込み ─────────────────────────────
def load_land_polygons():
    """ne_countries.geojson から陸地ポリゴンを返す（bbox内のみ）"""
    p = "papers/figs/ne_countries.geojson"
    polys = []
    if not os.path.exists(p):
        return polys
    with open(p) as f:
        fc = json.load(f)
    for feat in fc["features"]:
        g = feat["geometry"]
        rings = []
        if g["type"] == "Polygon":
            rings = [g["coordinates"][0]]
        elif g["type"] == "MultiPolygon":
            rings = [part[0] for part in g["coordinates"]]
        for ring in rings:
            xs = [c[0] for c in ring]
            ys = [c[1] for c in ring]
            # バウンディングボックスで大まかにフィルタ
            if (max(xs) < LON_MIN - 5 or min(xs) > LON_MAX + 5 or
                max(ys) < LAT_MIN - 5 or min(ys) > LAT_MAX + 5):
                continue
            polys.append(list(zip(xs, ys)))
    return polys


# ── 送電線の読み込み ──────────────────────────────────
def load_lines():
    lines = {v: [] for v in VOLT_ORDER}
    for r in REGIONS:
        p = f"{DATA_DIR}/{r}_lines.geojson"
        if not os.path.exists(p):
            continue
        with open(p) as f:
            feats = json.load(f)["features"]
        for feat in feats:
            v = snap_v(feat["properties"].get("voltage"))
            g = feat["geometry"]
            segs = ([g["coordinates"]] if g["type"] == "LineString"
                    else g["coordinates"] if g["type"] == "MultiLineString"
                    else [])
            for seg in segs:
                xs = [c[0] for c in seg]
                ys = [c[1] for c in seg]
                if any(LON_MIN-2 <= x <= LON_MAX+2 and LAT_MIN-2 <= y <= LAT_MAX+2
                       for x, y in zip(xs, ys)):
                    lines[v].append((xs, ys))
    return lines


print("データ読み込み中...")
land_polys = load_land_polygons()
lines_by_v = load_lines()
print(f"  陸地ポリゴン: {len(land_polys)}件, 送電線: {sum(len(v) for v in lines_by_v.values()):,}本")

# ── 描画 ─────────────────────────────────────────────
# アスペクト比：緯度35°中心補正（lon/lat ≈ 1/cos(35°) ≈ 1.22）
lat_center = (LAT_MIN + LAT_MAX) / 2
aspect = 1.0 / np.cos(np.radians(lat_center))
fig, ax = plt.subplots(figsize=(8.5, 9.0), facecolor="white")
ax.set_facecolor(COLOR_OCEAN)

# 陸地塗りつぶし
for pts in land_polys:
    poly = MplPolygon(pts, closed=True,
                      facecolor=COLOR_LAND, edgecolor=COLOR_COAST,
                      linewidth=0.5, zorder=2)
    ax.add_patch(poly)

# 送電線（低圧→高圧の順）
for v in VOLT_ORDER:
    col = VOLT_COLORS[v]
    lw  = VOLT_LW[v]
    alpha = 0.75 if v <= 110 else 0.90
    for xs, ys in lines_by_v[v]:
        ax.plot(xs, ys, color=col, lw=lw, alpha=alpha,
                solid_capstyle="round", zorder=3 + VOLT_ORDER.index(v))

# 範囲・見た目
ax.set_xlim(LON_MIN, LON_MAX)
ax.set_ylim(LAT_MIN, LAT_MAX)
ax.set_aspect(aspect)
ax.set_xticks([])
ax.set_yticks([])
for sp in ax.spines.values():
    sp.set_visible(False)

# 凡例（右下）
legend_handles = [
    Line2D([0], [0], color=VOLT_COLORS[v], lw=2.8, label=VOLT_LABEL[v])
    for v in reversed(VOLT_ORDER)
]
leg = ax.legend(handles=legend_handles,
                loc="lower right",
                fontsize=9.5,
                frameon=True,
                facecolor="white",
                edgecolor="#aaaaaa",
                framealpha=0.92,
                borderpad=0.7,
                handlelength=2.2,
                labelspacing=0.4,
                title="電圧クラス",
                title_fontsize=9.5)
leg.get_frame().set_linewidth(0.8)

plt.tight_layout(pad=0.1)
out = f"{OUT_DIR}/fig_national_all.png"
plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
plt.close()
print(f"Saved: {out}")
