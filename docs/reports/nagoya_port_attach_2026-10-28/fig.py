"""報告の図: 名古屋港の周りの大型機の繋ぎ先(前 = cap / 後 = capkv)。

    python docs/reports/nagoya_port_attach_2026-10-28/fig.py      # stats.json(measure.py の出力)から描く
"""
import json
import logging
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
plt.rcParams["font.family"] = ["Hiragino Sans", "Noto Sans CJK JP", "DejaVu Sans"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
C_BEFORE, C_AFTER = "#eb6834", "#2a78d6"
BOX = (136.56, 137.12, 34.79, 35.16)          # lon, lon, lat, lat(川越・西名古屋変電所まで入れる)
# 発電所の名札の位置(点からのずらし・重ならないように手で決めた)。1,000 MW 未満は名札なし
OFFSET = {"川越火力発電所": (6, -12), "碧南火力発電所": (6, -12), "新名古屋火力発電所": (-30, 9),
          "西名古屋火力発電所": (-34, 9), "知多第二火力発電所": (6, -2), "知多火力発電所": (-50, -12),
          "武豊火力発電所": (6, -12)}
# 住所から付いた名前のうち、公表の線名で同定できたもの(報告の「同定」)
ALIAS = {"大字石浜変電所 275kV": "大字石浜(=東浦開閉所)", "川口町五丁目変電所 275kV": "川口町五丁目(=碧南変電所)"}

S = json.loads((HERE / "stats.json").read_text(encoding="utf-8"))
built = json.loads((ROOT / "docs/data/built/all.json").read_text(encoding="utf-8"))


def inbox(p):
    return BOX[0] <= p[1] <= BOX[1] and BOX[2] <= p[0] <= BOX[3]


segs = {"hi": [], "lo": []}
for e in built["edges"]:
    if e["kv"] < 154 or not (inbox(e["a"]) or inbox(e["b"])):
        continue
    pts = e.get("path") or [e["a"], e["b"]]
    segs["hi" if e["kv"] >= 275 else "lo"].append([(p[1], p[0]) for p in pts])

fig, axes = plt.subplots(1, 2, figsize=(13, 6.2), sharey=True)
for ax, mode, col, title in ((axes[0], "cap", C_BEFORE, "前: cap(配布ケースに書き込まれていた)"),
                             (axes[1], "capkv", C_AFTER, "後: capkv(島別の既定・介入#41)")):
    ax.add_collection(LineCollection(segs["lo"], colors=GRID, linewidths=0.7, zorder=1))
    ax.add_collection(LineCollection(segs["hi"], colors="#b9b8b3", linewidths=1.4, zorder=1))
    load = defaultdict(float)
    where = {}
    for name, r in S["plants"].items():
        t = r[mode]
        load[t["bus"]] += r["mw"]
        where[t["bus"]] = (t["lonlat"], t["kv"])
        (x0, y0), (x1, y1) = r["lonlat"], t["lonlat"]
        ax.plot([x0, x1], [y0, y1], color=col, lw=1.4, alpha=0.85, zorder=2)
        ax.scatter([x0], [y0], s=8 + r["mw"] / 25, marker="s", facecolor="white", edgecolor=INK2, lw=0.9, zorder=3)
        if name in OFFSET:
            ax.annotate(name.replace("発電所", ""), (x0, y0), xytext=OFFSET[name],
                        textcoords="offset points", fontsize=7.5, color=INK2, zorder=5)
    for bus, mw in load.items():
        (x, y), kv = where[bus]
        ax.scatter([x], [y], s=20 + mw / 12, color=col, edgecolor="white", lw=1.5, zorder=4)
        if mw >= 3000:
            ax.annotate(f"{ALIAS.get(bus, bus.replace('変電所', '').replace(' 275kV', ''))} {kv:.0f} kV\n{mw:,.0f} MW", (x, y),
                        xytext=(8, 6), textcoords="offset points", fontsize=8.5, color=INK, zorder=6,
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))
    ax.set_xlim(BOX[0], BOX[1])
    ax.set_ylim(BOX[2], BOX[3])
    ax.set_aspect(1 / 0.82)   # 緯度 35° の経度の縮み
    ax.set_title(title, fontsize=11, color=INK, loc="left")
    ax.tick_params(labelsize=8, colors=INK2)
    for s in ax.spines.values():
        s.set_color(GRID)
axes[0].scatter([], [], s=60, marker="s", facecolor="white", edgecolor=INK2, label="発電所(面積 ∝ 出力)")
axes[0].scatter([], [], s=60, color=INK2, label="繋ぎ先のバス(面積 ∝ 載った出力)")
axes[0].plot([], [], color="#b9b8b3", lw=1.4, label="275 kV 以上の線")
axes[0].plot([], [], color=GRID, lw=0.9, label="154 kV の線")
axes[0].legend(loc="lower left", fontsize=8, frameon=False)
fig.suptitle("名古屋港の周りの 200 MW 以上の機の繋ぎ先(西の島・正典の網)", fontsize=12, color=INK, x=0.06, ha="left")
fig.tight_layout()
fig.savefig(HERE / "attach_map.png", dpi=150)
print("→", HERE / "attach_map.png")
