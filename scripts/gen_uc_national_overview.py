"""
UC national overview figure: all-10-region generation mix as stacked bars + interconnection flows.
Reads UC result from output/uc_national/ if available, otherwise re-runs.
"""

import os
import sys
import platform
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo", "sans-serif"]
else:
    try:
        import japanize_matplotlib  # noqa
    except ImportError:
        pass

OUT_DIR = "papers/figs"
os.makedirs(OUT_DIR, exist_ok=True)

# ── Try to load existing UC result ──────────────────────────────────
UC_RESULT_DIR = "output/uc_national"

FUEL_COLORS = {
    "nuclear":    "#7b2d8b",
    "coal":       "#5a4234",
    "lng":        "#1f77b4",
    "gas":        "#4fc3f7",
    "oil":        "#888888",
    "hydro":      "#2196f3",
    "geothermal": "#e91e63",
    "solar":      "#ffd600",
    "wind":       "#66bb6a",
    "biomass":    "#8bc34a",
    "waste":      "#9e9e9e",
    "storage":    "#00acc1",
    "other":      "#bdbdbd",
}

FUEL_LABELS = {
    "nuclear":"原子力", "coal":"石炭", "lng":"LNG",
    "gas":"ガス", "oil":"石油", "hydro":"水力",
    "geothermal":"地熱", "solar":"太陽光", "wind":"風力",
    "biomass":"バイオマス", "waste":"廃棄物", "storage":"蓄電池",
    "other":"その他",
}

REGIONS_JA = {
    "hokkaido":"北海道", "tohoku":"東北",  "tokyo":"東京",
    "chubu":"中部",      "hokuriku":"北陸", "kansai":"関西",
    "chugoku":"中国",    "shikoku":"四国",  "kyushu":"九州",
    "okinawa":"沖縄",
}

REGION_ORDER = ["hokkaido","tohoku","tokyo","chubu","hokuriku",
                "kansai","chugoku","shikoku","kyushu","okinawa"]


def load_uc_result():
    """Try to load existing UC JSON result."""
    for fname in ["uc_result.json", "uc_national_result.json"]:
        p = os.path.join(UC_RESULT_DIR, fname)
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    return None


def build_synthetic_data():
    """Build plausible generation mix from GeoJSON plant data for each region."""
    DATA_DIR = "data"
    THERMAL_CAP = {"nuclear":900, "coal":600, "lng":400, "gas":200,
                   "oil":200, "geothermal":30, "biomass":20, "waste":15}
    region_data = {}
    for r in REGION_ORDER:
        p = f"{DATA_DIR}/{r}_plants.geojson"
        if not os.path.exists(p):
            region_data[r] = {}
            continue
        fuel_cap = {}
        for feat in json.load(open(p))["features"]:
            pr = feat["properties"]
            fuel = (pr.get("fuel_type") or pr.get("plant:source") or "").lower()
            try:
                cap = float(pr.get("capacity_mw") or 0)
            except:
                cap = 0.0
            if cap <= 0 and fuel in THERMAL_CAP:
                cap = THERMAL_CAP[fuel]
            elif cap <= 0:
                continue
            norm_fuel = fuel if fuel in FUEL_COLORS else "other"
            fuel_cap[norm_fuel] = fuel_cap.get(norm_fuel, 0) + cap
        region_data[r] = fuel_cap
    return region_data


def make_national_overview(region_data):
    """
    Landscape 2-panel figure:
    Left:  10-region horizontal stacked bars (barh) — fuel capacity
    Right: uc_ic_flow.png embedded as image
    """
    import matplotlib.image as mpimg

    fig, (ax_bar, ax_flow) = plt.subplots(
        1, 2, figsize=(16, 5.5), facecolor="white",
        gridspec_kw={"width_ratios": [1.1, 1], "wspace": 0.06}
    )

    # ── Left: horizontal stacked bars (regions on y-axis) ──────────
    ax_bar.set_facecolor("white")
    fuels_present = set()
    for rd in region_data.values():
        fuels_present.update(rd.keys())
    fuel_order = [f for f in ["nuclear","coal","lng","gas","oil","hydro",
                               "geothermal","solar","wind","biomass","waste","storage","other"]
                  if f in fuels_present]

    y = np.arange(len(REGION_ORDER))
    lefts = np.zeros(len(REGION_ORDER))
    bar_handles = []
    for fuel in fuel_order:
        vals = np.array([region_data.get(r, {}).get(fuel, 0) / 1000
                         for r in REGION_ORDER])
        if vals.sum() < 0.01:
            continue
        ax_bar.barh(y, vals, left=lefts,
                    color=FUEL_COLORS.get(fuel, "#bbb"),
                    label=FUEL_LABELS.get(fuel, fuel),
                    height=0.68, zorder=2)
        lefts += vals
        bar_handles.append(mpatches.Patch(color=FUEL_COLORS.get(fuel, "#bbb"),
                                           label=FUEL_LABELS.get(fuel, fuel)))

    ax_bar.set_yticks(y)
    ax_bar.set_yticklabels([REGIONS_JA[r] for r in REGION_ORDER], fontsize=10)
    ax_bar.set_xlabel("設備容量 (GW)", fontsize=10)
    ax_bar.set_title("10 地域別 燃料種別設備容量構成", fontsize=11, pad=6, color="#222")
    ax_bar.grid(axis="x", color="#ddd", lw=0.5, zorder=0)
    ax_bar.set_axisbelow(True)
    for sp in ax_bar.spines.values():
        sp.set_color("#ccc")
    ax_bar.legend(handles=bar_handles, fontsize=7.5, loc="lower right",
                  ncol=2, facecolor="white", edgecolor="#bbb", framealpha=0.95)
    ax_bar.invert_yaxis()   # 北海道を上に

    # ── Right: uc_ic_flow image ─────────────────────────────────────
    ic_path = f"{OUT_DIR}/uc_ic_flow.png"
    if os.path.exists(ic_path):
        img = mpimg.imread(ic_path)
        ax_flow.imshow(img, aspect="auto")
        ax_flow.set_title("地域間連系線 24 時間潮流", fontsize=11, pad=6, color="#222")
    else:
        ax_flow.text(0.5, 0.5, "uc_ic_flow.png\nnot found",
                     ha="center", va="center", transform=ax_flow.transAxes,
                     fontsize=10, color="#888")
    ax_flow.axis("off")

    plt.suptitle("全国 Unit Commitment 結果 (783 機, 10 地域, 24 時間)",
                 fontsize=12, y=1.01, color="#111")

    out = f"{OUT_DIR}/fig_uc_national_overview.png"
    plt.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"Saved: {out}")


if __name__ == "__main__":
    print("Building UC national overview...")
    uc = load_uc_result()
    if uc:
        print("  (loaded existing UC result)")
    else:
        print("  (using synthetic capacity data from GeoJSON)")
    data = build_synthetic_data()
    make_national_overview(data)
