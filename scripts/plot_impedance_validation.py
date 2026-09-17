#!/usr/bin/env python3
"""公表インピーダンス X_公表 / X_モデル を 3 つの視点で見る。

  1. 解析的  — 散布図(縦 X_公表 / 横 X_モデル)。比の分布と電圧階級の効き
  2. 地形的  — 地図上に比を配色。どの地域で乖離が大きいか
  3. Ybus 的 — Ybus の非零要素のうち、公表値で答え合わせできた要素はどこか

X_モデル = 線種の典型 x[Ω/km] × **弦距離** ÷ par（スライドの定義と同じ）。
弦距離は実線長の下限なので比 > 1 が自然で、比は実質「迂回率」を測っている。

入力は系統情報公表の正規化データ（`data/external/` は .gitignore＝ライセンス上
非公開）。**図には線名を出さない**（集計・分布としてのみ示す）。

出力: docs/reports/figs/impedance_{scatter,map,ybus}.png
"""
from __future__ import annotations
import json, math, os, re, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parent.parent
NORM = Path(os.environ.get("AGJ_DISCLOSURE_NORM",
                           ROOT / "data/external/system_disclosure/normalized"))
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG = "#faf8f1"
VC = {66: "#9fb4c9", 110: "#6f9bc4", 154: "#3a6ea5", 187: "#b3812f",
      220: "#cf4f5f", 275: "#8e44ad", 500: "#1a1a17"}
JA = {"hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京", "chubu": "中部",
      "hokuriku": "北陸", "kansai": "関西", "chugoku": "中国", "shikoku": "四国",
      "kyushu": "九州", "okinawa": "沖縄"}


def load():
    f = NORM / "compare_observed_derived_impedance.csv"
    if not f.exists():
        print(f"入力が無い: {f}\n  AGJ_DISCLOSURE_NORM で正規化データの場所を指定",
              file=sys.stderr)
        raise SystemExit(1)
    d = pd.read_csv(f)
    d = d[(d.X_pct > 0) & (d.X_derived_pct > 0)].copy()
    d["ratio"] = d.X_pct / d.X_derived_pct
    return d


def fig_scatter(d):
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(12.4, 5.6), facecolor=BG,
                                  gridspec_kw={"width_ratios": [1.35, 1]})
    for a in (ax, ax2):
        a.set_facecolor("#fffdf6")
        for s in a.spines.values():
            s.set_color("#dcd8cc")
    lo = min(d.X_derived_pct.min(), d.X_pct.min()) * 0.7
    hi = max(d.X_derived_pct.max(), d.X_pct.max()) * 1.4
    ax.plot([lo, hi], [lo, hi], color="#928f84", lw=1.2, ls="--", zorder=2,
            label="y = x（比 1.0）")
    med = d.ratio.median()
    ax.plot([lo, hi], [lo * med, hi * med], color="#cf4f5f", lw=1.6, zorder=3,
            label=f"中央値の比 {med:.2f}")
    for kv, g in d.groupby("voltage_kv"):
        ax.scatter(g.X_derived_pct, g.X_pct, s=42, alpha=.8,
                   color=VC.get(int(kv), "#666"), edgecolor="white", lw=.6,
                   zorder=4, label=f"{int(kv)} kV (n={len(g)})")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_xlabel("X モデル [%]（線種の典型 x × 弦距離 ÷ par）", fontsize=10.5)
    ax.set_ylabel("X 公表 [%]（様式5・1000MVA ベース）", fontsize=10.5)
    ax.grid(alpha=.22, color="#dcd8cc", which="both")
    ax.legend(fontsize=8.5, frameon=False, ncol=2, loc="upper left")
    ax.set_title(f"① 解析的 — 公表 X とモデル X は同じ直線に乗る\n"
                 f"n={len(d)}・比の中央値 {med:.3f}（四分位 "
                 f"{d.ratio.quantile(.25):.2f}–{d.ratio.quantile(.75):.2f}）",
                 fontsize=12, loc="left", color="#1a1a17", pad=10)

    bins = np.logspace(np.log10(max(d.ratio.min(), .3)),
                       np.log10(min(d.ratio.max(), 4)), 26)
    ax2.hist(d.ratio, bins=bins, color="#3a6ea5", alpha=.8)
    ax2.axvline(1.0, color="#928f84", ls="--", lw=1.2)
    ax2.axvline(med, color="#cf4f5f", lw=1.8)
    ax2.text(med, ax2.get_ylim()[1] * .92, f" 中央値 {med:.2f}", color="#cf4f5f",
             fontsize=10)
    ax2.set_xscale("log")
    ax2.set_xlabel("X 公表 / X モデル", fontsize=10.5)
    ax2.set_ylabel("本数", fontsize=10.5)
    ax2.grid(axis="y", alpha=.22, color="#dcd8cc")
    n_gt = int((d.ratio > 1).sum())
    ax2.set_title(f"比の分布 — {n_gt}/{len(d)} 本が 1 より大きい\n"
                  "弦距離は実線長の下限なので比>1 が自然（＝迂回率）",
                  fontsize=12, loc="left", color="#1a1a17", pad=10)
    fig.tight_layout()
    out = FIGS / "impedance_scatter.png"
    fig.savefig(out, dpi=180, facecolor=BG); plt.close(fig)
    print(f"  {out.name}  n={len(d)} 中央値={med:.3f}")
    return med


def fig_map(d):
    k = math.cos(math.radians(36.0))
    fig, (ax, axb) = plt.subplots(1, 2, figsize=(12.6, 8.6), facecolor=BG,
                                  gridspec_kw={"width_ratios": [1.5, 1]})
    ax.set_facecolor("#fffdf6")
    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    for e in built["edges"]:                      # 背景に全国網
        p = e.get("path") or [e["a"], e["b"]]
        if len(p) > 6:
            p = p[::4] + [p[-1]]
        ax.plot([q[1] * k for q in p], [q[0] for q in p], color="#d8dfe6",
                lw=.3, alpha=.7, zorder=1)
    cmap = plt.get_cmap("coolwarm")
    lo, hi = 0.7, 1.8
    for _, r in d.iterrows():
        c = cmap((min(max(r.ratio, lo), hi) - lo) / (hi - lo))
        ax.plot([r.from_lon * k, r.to_lon * k], [r.from_lat, r.to_lat],
                color=c, lw=1.0 + 2.2 * min(r.L_straight_km / 80, 1), zorder=4,
                solid_capstyle="round", alpha=.95)
    ax.set_ylim(30.3, 45.8); ax.set_xlim(128.2 * k, 146.4 * k)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#dcd8cc")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(lo, hi))
    cb = fig.colorbar(sm, ax=ax, fraction=.03, pad=.02)
    cb.set_label("X 公表 / X モデル", fontsize=10)
    cb.outline.set_edgecolor("#dcd8cc")
    ax.set_title("② 地形的 — 乖離は地域でまとまる\n"
                 "（青＝公表がモデルより小さい／赤＝大きい・太さ∝弦距離）",
                 fontsize=12, loc="left", color="#1a1a17", pad=10)

    g = d.groupby("utility").ratio.agg(["size", "median"]).sort_values("median")
    axb.set_facecolor("#fffdf6")
    cols = [cmap((min(max(v, lo), hi) - lo) / (hi - lo)) for v in g["median"]]
    axb.barh([JA.get(i, i) for i in g.index], g["median"], color=cols, height=.62)
    axb.axvline(1.0, color="#928f84", ls="--", lw=1.2)
    for i, (n, v) in enumerate(zip(g["size"], g["median"])):
        axb.text(v + .02, i, f"{v:.2f} (n={n})", va="center", fontsize=9.5)
    axb.set_xlim(0, max(g["median"]) * 1.35)
    axb.set_xlabel("比の中央値", fontsize=10.5)
    axb.grid(axis="x", alpha=.22, color="#dcd8cc")
    for s in axb.spines.values():
        s.set_color("#dcd8cc")
    axb.set_title("事業者別の中央値\n東京だけ 1 を下回る（都市部・地中で迂回が小さい）",
                  fontsize=11.5, loc="left", color="#1a1a17", pad=10)
    fig.tight_layout()
    out = FIGS / "impedance_map.png"
    fig.savefig(out, dpi=175, facecolor=BG); plt.close(fig)
    print(f"  {out.name}")


def fig_ybus(d):
    """Ybus の非零のうち、公表値で答え合わせできた要素を重ねる。"""
    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    nodes = built["nodes"]
    order = sorted(range(len(nodes)), key=lambda i: (-nodes[i]["lat"], nodes[i]["lon"]))
    idx = {}
    for rank, i in enumerate(order):
        n = nodes[i]
        idx[(round(n["lat"], 5), round(n["lon"], 5))] = rank
    ii, jj = [], []
    for e in built["edges"]:
        a = idx.get((round(e["a"][0], 5), round(e["a"][1], 5)))
        b = idx.get((round(e["b"][0], 5), round(e["b"][1], 5)))
        if a is None or b is None:
            continue
        ii += [a, b]; jj += [b, a]
    # 公表線 → 最近傍ノードの (i,j)
    lat = np.array([n["lat"] for n in nodes]); lon = np.array([n["lon"] for n in nodes])
    vi, vj, vr = [], [], []
    for _, r in d.iterrows():
        for (la, lo) in ((r.from_lat, r.from_lon), (r.to_lat, r.to_lon)):
            pass
        a = int(np.argmin((lat - r.from_lat) ** 2 + (lon - r.from_lon) ** 2))
        b = int(np.argmin((lat - r.to_lat) ** 2 + (lon - r.to_lon) ** 2))
        ra = idx[(round(nodes[a]["lat"], 5), round(nodes[a]["lon"], 5))]
        rb = idx[(round(nodes[b]["lat"], 5), round(nodes[b]["lon"], 5))]
        vi += [ra, rb]; vj += [rb, ra]; vr += [r.ratio, r.ratio]

    N = len(nodes)
    fig, ax = plt.subplots(figsize=(9.6, 9.6), facecolor=BG)
    ax.set_facecolor("#fffdf6")
    ax.scatter(jj, ii, s=.25, color="#c8d3dd", alpha=.75, zorder=2, marker="s")
    cmap = plt.get_cmap("coolwarm")
    sc = ax.scatter(vj, vi, s=26, c=np.clip(vr, .7, 1.8), cmap=cmap, vmin=.7, vmax=1.8,
                    zorder=4, edgecolor="white", lw=.5)
    ax.set_xlim(0, N); ax.set_ylim(N, 0)
    ax.set_aspect("equal")
    ax.set_xlabel("バス番号（北 → 南に整列）", fontsize=10.5)
    ax.set_ylabel("バス番号（北 → 南に整列）", fontsize=10.5)
    for s in ax.spines.values():
        s.set_color("#dcd8cc")
    cb = fig.colorbar(sc, ax=ax, fraction=.035, pad=.02)
    cb.set_label("X 公表 / X モデル", fontsize=10)
    cb.outline.set_edgecolor("#dcd8cc")
    nz = len(ii)
    ax.set_title(f"③ Ybus 的 — 行列のどこが答え合わせ済みか\n"
                 f"非零 {nz:,} 要素（灰）のうち、公表 X で検算できたのは "
                 f"{len(vi):,} 要素（{len(vi)/nz*100:.2f}%・色）",
                 fontsize=12.5, loc="left", color="#1a1a17", pad=12)
    ax.text(.012, .015, "※ 対角（自己アドミタンス）は省略。北から南へ並べたので\n"
                        "　 塊は地域に対応する", transform=ax.transAxes,
            fontsize=9, color="#928f84", va="bottom")
    fig.tight_layout()
    out = FIGS / "impedance_ybus.png"
    fig.savefig(out, dpi=175, facecolor=BG); plt.close(fig)
    print(f"  {out.name}  非零{nz:,} / 検証済{len(vi):,}")


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    d = load()
    print(f"評価対象 {len(d)} 本（両端解決・並列重複除去・弦距離>0.5km・X>0）")
    fig_scatter(d); fig_map(d); fig_ybus(d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
