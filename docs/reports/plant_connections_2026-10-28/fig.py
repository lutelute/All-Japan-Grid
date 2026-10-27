"""報告の図: 台帳の機の繋ぎ先の電圧(公表 / 前 = 島の規則 / 後 = 台帳)。

    python docs/reports/plant_connections_2026-10-28/fig.py      # stats.json(measure.py の出力)から描く
"""
import json
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
plt.rcParams["font.family"] = ["Hiragino Sans", "Noto Sans CJK JP", "DejaVu Sans"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
C_BEFORE, C_AFTER = "#eb6834", "#2a78d6"
KV = [66, 77, 110, 154, 187, 220, 275, 500]
X = {kv: i for i, kv in enumerate(KV)}
JA = {"west": "西", "hokkaido": "北海道"}

S = json.loads((HERE / "stats.json").read_text(encoding="utf-8"))
rows = list(S["plants"].items())
fig, ax = plt.subplots(figsize=(9.2, 0.36 * len(rows) + 1.6))
for y, (name, r) in enumerate(rows):
    yy = len(rows) - 1 - y
    ax.axhline(yy, color=GRID, lw=0.6, zorder=0)
    b, a, p = X[round(r["capkv" if r["default"] == "capkv" else "cap"]["kv"])], X[round(r["ledger"]["kv"])], X[round(r["pub_kv"])]
    if b != a:
        ax.annotate("", xy=(a, yy), xytext=(b, yy),
                    arrowprops=dict(arrowstyle="->", color=INK2, lw=0.9, shrinkA=6, shrinkB=6), zorder=1)
    ax.scatter([p], [yy], s=190, facecolor="none", edgecolor=INK, lw=1.3, zorder=2)
    ax.scatter([b], [yy], s=46, color=C_BEFORE, edgecolor="white", lw=1.2, zorder=3)
    ax.scatter([a], [yy], s=46, color=C_AFTER, edgecolor="white", lw=1.2, zorder=4)
    label = f"{name.replace('発電所', '')}({JA[r['island']]}・{r['mw']:,} MW)"
    ax.text(-0.45, yy, label, ha="right", va="center", fontsize=8.5, color=INK)
ax.set_xticks(range(len(KV)), [f"{kv} kV" for kv in KV], fontsize=8.5, color=INK2)
ax.set_yticks([])
ax.set_xlim(-0.4, len(KV) - 0.5)
ax.set_ylim(-0.8, len(rows) - 0.2)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color(GRID)
ax.scatter([], [], s=150, facecolor="none", edgecolor=INK, lw=1.3, label="公表の電圧")
ax.scatter([], [], s=46, color=C_BEFORE, label="前: 島の規則(西 capkv・北海道 capkv)")
ax.scatter([], [], s=46, color=C_AFTER, label="後: 台帳(介入#55)")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=3, fontsize=8.5, frameon=False)
sc = S["score"]
ax.set_title(f"台帳の {sc['ledger']['of']} 機の繋ぎ先の電圧 — 公表と合う機 前 {sc['capkv']['n']}"
             f"(西・北海道の既定) → 後 {sc['ledger']['n']}", fontsize=11, color=INK, loc="left")
fig.tight_layout()
fig.savefig(HERE / "voltage_match.png", dpi=150, bbox_inches="tight")
print("→", HERE / "voltage_match.png")
