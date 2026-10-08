#!/usr/bin/env python3
"""距離上限を破った leadin / namebind を全国地図に出す（#46 の可視化）。

`snapped_topology.py` の上限は leadin 1.5 km / namebind 5.0 km。
ところが正典では namebind の 25%・leadin の 29% がそれを超えている。
「どこで・どれだけ破っているか」を見ないと直しようがないので地図にする。

出力: docs/reports/figs/leadin_overrun_map.png
"""
from __future__ import annotations
import json, math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG = "#faf8f1"
LIMIT = {"leadin": 1.5, "namebind": 5.0}


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    return 6371*2*math.asin(math.sqrt(math.sin((la2-la1)/2)**2 +
        math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2))


def main():
    b = json.loads((ROOT/"docs/data/built/all.json").read_text())
    k = math.cos(math.radians(36.0))
    fig, ax = plt.subplots(figsize=(10.6, 10.2), facecolor=BG)
    ax.set_facecolor("#fffdf6")
    for e in b["edges"]:
        if (e.get("name") or "") in LIMIT:
            continue
        p = e.get("path") or [e["a"], e["b"]]
        if len(p) > 6:
            p = p[::4] + [p[-1]]
        ax.plot([q[1]*k for q in p], [q[0] for q in p], color="#d8dfe6",
                lw=.3, alpha=.7, zorder=1)
    stats = {}
    for nm, col_ok, col_ng in (("leadin", "#9fd9cc", "#1f9e8a"),
                               ("namebind", "#e8a8b0", "#cf4f5f")):
        g = [e for e in b["edges"] if (e.get("name") or "") == nm]
        lim = LIMIT[nm]
        ok = [e for e in g if hav(e["a"], e["b"]) <= lim*1.01]
        ng = sorted((e for e in g if hav(e["a"], e["b"]) > lim*1.01),
                    key=lambda e: hav(e["a"], e["b"]))
        stats[nm] = (len(g), len(ng), max((hav(e["a"], e["b"]) for e in g), default=0))
        for e in ok:
            ax.plot([e["a"][1]*k, e["b"][1]*k], [e["a"][0], e["b"][0]],
                    color=col_ok, lw=.9, alpha=.8, zorder=3)
        for e in ng:
            L = hav(e["a"], e["b"])
            ax.plot([e["a"][1]*k, e["b"][1]*k], [e["a"][0], e["b"][0]],
                    color=col_ng, lw=1.0 + min(3.2, L/6), alpha=.95, zorder=5,
                    solid_capstyle="round")
        for e in ng[-4:]:
            L = hav(e["a"], e["b"])
            mid = ((e["a"][0]+e["b"][0])/2, (e["a"][1]+e["b"][1])/2)
            ax.annotate(f"{nm} {L:.0f}km", (mid[1]*k, mid[0]), fontsize=7.5,
                        color="#8a2f3c", zorder=9, xytext=(8, 4),
                        textcoords="offset points",
                        bbox=dict(boxstyle="round,pad=.2", fc="white",
                                  ec=col_ng, alpha=.85, lw=.6))
    ax.set_ylim(30.3, 45.8); ax.set_xlim(128.2*k, 146.4*k)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#dcd8cc")
    nb, lo = stats["namebind"], stats["leadin"]
    ax.set_title(
        "距離上限を破った合成エッジはどこにあるか（#46）\n"
        f"namebind 上限 5.0km → {nb[1]}/{nb[0]} 本が超過（最長 {nb[2]:.0f}km）　"
        f"leadin 上限 1.5km → {lo[1]}/{lo[0]} 本が超過（最長 {lo[2]:.0f}km）",
        fontsize=12.5, loc="left", color="#1a1a17", pad=12)
    handles = [
        Line2D([], [], color="#cf4f5f", lw=2.6, label="namebind（上限超え）"),
        Line2D([], [], color="#e8a8b0", lw=1.4, label="namebind（上限内）"),
        Line2D([], [], color="#1f9e8a", lw=2.6, label="leadin（上限超え）"),
        Line2D([], [], color="#9fd9cc", lw=1.4, label="leadin（上限内）"),
        Line2D([], [], color="#d8dfe6", lw=1.4, label="OSM 実線形"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=9.5, frameon=True,
              facecolor="white", edgecolor="#dcd8cc")
    fig.tight_layout()
    out = FIGS/"leadin_overrun_map.png"
    fig.savefig(out, dpi=180, facecolor=BG); plt.close(fig)
    print(f"  {out.name}  namebind超過 {nb[1]}/{nb[0]} / leadin超過 {lo[1]}/{lo[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
