#!/usr/bin/env python3
"""Generate the project hero banner (docs/assets/banner.png).

A wide, dark, power-grid-aesthetic banner: the national transmission network
drawn as voltage-coloured glowing lines on the right, the title / tagline /
key figures on the left. Pure matplotlib over the committed line GeoJSON.

    PYTHONPATH=. python3 scripts/gen_banner.py
"""
from __future__ import annotations

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
           "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
VOLT_ORDER = [66, 110, 154, 275, 500]
VOLT_COLORS = {500: "#ff453a", 275: "#ff9f0a", 154: "#ffd60a",
               110: "#30d158", 66: "#0a84ff"}
VOLT_LW = {500: 1.15, 275: 0.8, 154: 0.55, 110: 0.42, 66: 0.3}
VOLT_LABEL = {500: "500 kV", 275: "275 kV", 154: "154 kV", 110: "110 kV", 66: "66 kV"}
BG = "#0a1622"

for fam in (["Hiragino Sans", "Apple SD Gothic Neo"], ["DejaVu Sans"]):
    try:
        plt.rcParams["font.family"] = fam
        break
    except Exception:  # noqa: BLE001
        continue


def _snap_v(raw):
    if not raw:
        return None
    try:
        v = max(int(x) for x in str(raw).replace(";", ",").split(",") if x.strip())
    except ValueError:
        return None
    return min(VOLT_ORDER, key=lambda c: abs(c - v / 1000.0)) if v > 1000 \
        else min(VOLT_ORDER, key=lambda c: abs(c - v))


def load_lines():
    lines = {v: [] for v in VOLT_ORDER}
    for r in REGIONS:
        p = f"data/{r}_lines.geojson"
        if not os.path.exists(p):
            continue
        with open(p) as f:
            feats = json.load(f)["features"]
        for feat in feats:
            v = _snap_v(feat["properties"].get("voltage")) or 66
            g = feat.get("geometry") or {}
            t = g.get("type")
            segs = ([g["coordinates"]] if t == "LineString"
                    else g["coordinates"] if t == "MultiLineString" else [])
            for seg in segs:
                if len(seg) < 2:
                    continue
                xs = [c[0] for c in seg]
                ys = [c[1] for c in seg]
                lines[v].append((xs, ys))
    return lines


def main() -> int:
    lines = load_lines()
    n_lines = sum(len(v) for v in lines.values())
    print(f"  loaded {n_lines:,} line segments")

    fig = plt.figure(figsize=(12.8, 4.6), facecolor=BG)
    ax = fig.add_axes([0.32, 0.02, 0.67, 0.96])  # map fills the right side
    ax.set_facecolor(BG)
    # faint glow underlay then the crisp line on top
    for v in VOLT_ORDER:
        for xs, ys in lines[v]:
            ax.plot(xs, ys, color=VOLT_COLORS[v], lw=VOLT_LW[v] * 3.2,
                    alpha=0.07, solid_capstyle="round")
    for v in VOLT_ORDER:
        for xs, ys in lines[v]:
            ax.plot(xs, ys, color=VOLT_COLORS[v], lw=VOLT_LW[v],
                    alpha=0.92, solid_capstyle="round")
    ax.set_xlim(126.6, 146.6)
    ax.set_ylim(25.6, 46.2)  # include Okinawa (all 10 regions)
    ax.set_aspect(1.24)
    ax.axis("off")

    # ── left text panel ──
    fig.text(0.035, 0.74, "All-Japan-Grid", fontsize=43, color="white",
             weight="bold", ha="left", va="center")
    fig.text(0.037, 0.55,
             "Open, standards-based reference model\nof Japan's power transmission grid",
             fontsize=14.5, color="#aeb9c6", ha="left", va="center", linespacing=1.4)
    fig.text(0.037, 0.345,
             "40,000+ lines   ·   7,000+ substations   ·   19,000+ plants",
             fontsize=13, color="#eaf0f7", ha="left", va="center", weight="bold")
    fig.text(0.037, 0.245,
             "OSM-derived  ·  CGMES 2.4.15  ·  pandapower power flow  ·  10 regions",
             fontsize=11, color="#7e8b9b", ha="left", va="center")

    # voltage legend (bottom-left)
    handles = [Line2D([0], [0], color=VOLT_COLORS[v], lw=2.4, label=VOLT_LABEL[v])
               for v in reversed(VOLT_ORDER)]
    leg = fig.legend(handles=handles, loc="lower left",
                     bbox_to_anchor=(0.037, 0.06), ncol=5, frameon=False,
                     handlelength=1.3, columnspacing=1.2, fontsize=9.5)
    for txt in leg.get_texts():
        txt.set_color("#9aa6b4")

    out = "docs/assets/banner.png"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=150, facecolor=BG, bbox_inches="tight", pad_inches=0.12)
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
