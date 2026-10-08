#!/usr/bin/env python3
"""線名照合と変電所名照合が食い違った線（fixable）を並べて描く（#47）。

赤い破線 = いまの対応付け（変電所名で解決した from→to の直線）
青い実線 = 線名照合が指すエッジ群（＝モデルが「その名前の線」として持っている実体）
どちらが正しいかを目で判断するための図。

出力: docs/reports/figs/linename_fixable.png
"""
from __future__ import annotations
import json, math, os, re, unicodedata
from collections import defaultdict
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
NORM = Path(os.environ.get("AGJ_DISCLOSURE_NORM",
                           ROOT / "data/external/system_disclosure/normalized"))
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG, C_OSM, C_OLD, C_NEW = "#faf8f1", "#d8dfe6", "#cf4f5f", "#3a6ea5"
CIRCUIT_RX = re.compile(r"[0-9０-９]*[LＬ]$|[0-9０-９]+回線$|[0-9０-９]+号線$")


def key(s):
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"\s*\([^)]*\)", "", s)
    s = re.sub(r"\s*（[^）]*）", "", s)
    return CIRCUIT_RX.sub("", "".join(s.split()))


def main():
    chk = pd.read_csv(NORM / "crosswalk_linename_check.csv")
    fx = chk[chk.verdict == "fixable"].drop_duplicates(subset=["line_name"])
    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    grp = defaultdict(list)
    for e in built["edges"]:
        n = (e.get("name") or "").strip()
        if not n or n in ("leadin", "namebind"):
            continue
        for part in n.split(";"):
            k = key(part)
            if len(k) >= 3:
                grp[k].append(e)
    n = len(fx)
    cols = 3
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4.3*cols, 4.1*rows), facecolor=BG)
    axes = axes.ravel() if n > 1 else [axes]
    for ax, (_, r) in zip(axes, fx.iterrows()):
        k = key(r.line_name)
        es = grp.get(k) or [e for kk in grp if k and k in kk for e in grp[kk]]
        pts = [p for e in es for p in (e.get("path") or [e["a"], e["b"]])]
        allp = pts + [[r.from_lat, r.from_lon], [r.to_lat, r.to_lon]]
        lat0 = sum(p[0] for p in allp) / len(allp)
        kk = math.cos(math.radians(lat0))
        la = [min(p[0] for p in allp), max(p[0] for p in allp)]
        lo = [min(p[1] for p in allp), max(p[1] for p in allp)]
        m = max(la[1]-la[0], lo[1]-lo[0]) * .12 + .01
        for e in built["edges"]:                       # 背景
            p = e.get("path") or [e["a"], e["b"]]
            if not any(la[0]-m <= q[0] <= la[1]+m and lo[0]-m <= q[1] <= lo[1]+m for q in p):
                continue
            ax.plot([q[1]*kk for q in p], [q[0] for q in p], color=C_OSM, lw=.7,
                    alpha=.85, zorder=1)
        for e in es:                                    # 線名照合の実体
            p = e.get("path") or [e["a"], e["b"]]
            ax.plot([q[1]*kk for q in p], [q[0] for q in p], color=C_NEW, lw=2.6,
                    zorder=4, solid_capstyle="round")
        ax.plot([r.from_lon*kk, r.to_lon*kk], [r.from_lat, r.to_lat], color=C_OLD,
                lw=2.4, ls=(0, (5, 3)), zorder=5)
        ax.plot([r.from_lon*kk, r.to_lon*kk], [r.from_lat, r.to_lat], "o", color=C_OLD,
                ms=5, mec="white", mew=1.1, zorder=6)
        ax.set_xlim((lo[0]-m)*kk, (lo[1]+m)*kk); ax.set_ylim(la[0]-m, la[1]+m)
        ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
        ax.set_facecolor("#fffdf6")
        for s in ax.spines.values():
            s.set_color("#dcd8cc")
        ax.set_title(f"{r.line_name}（{r.voltage_kv:.0f}kV・{r.utility}）\n"
                     f"いまの対応付け {r.chord_km:.1f} km ／ 線名の実体 {r.span_km:.1f} km",
                     fontsize=9.5, color="#1a1a17", pad=6)
    for ax in axes[n:]:
        ax.axis("off")
    handles = [Line2D([], [], color=C_OLD, lw=2.4, ls=(0, (5, 3)),
                      label="いまの対応付け（変電所名で解決した from→to）"),
               Line2D([], [], color=C_NEW, lw=2.6, label="線名照合が指すエッジ群（モデルが持つ実体）"),
               Line2D([], [], color=C_OSM, lw=1.6, label="周辺の系統")]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=10,
               bbox_to_anchor=(.5, .006))
    fig.suptitle("線名照合と変電所名照合が食い違った線 — どちらが正しいか（#47 fixable）",
                 fontsize=13, x=.03, ha="left", y=.988, color="#1a1a17")
    fig.tight_layout(rect=[0, .04, 1, .955])
    out = FIGS / "linename_fixable.png"
    fig.savefig(out, dpi=175, facecolor=BG)
    plt.close(fig)
    print(f"  {out.name}  ({n} 件)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
