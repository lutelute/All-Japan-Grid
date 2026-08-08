#!/usr/bin/env python3
"""2026-08-08 の作業結果を1枚にまとめる図。

3段階の改善（初回突合 → crosswalk地理裁定 → 座標解決バグ修正）と、
その各段で食い違いの内訳がどう動いたかを示す。数値の出典は
docs/reports/keitouzu_* と IMPROVEMENT_LOG（旧値は同日の計測記録）。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "docs" / "reports"
OUT = ROOT / "docs" / "assets" / "toporag" / "day_summary_2026-08-08.png"

plt.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]

# ── 3段階の計測値（同日の実測。段階2/3は本日の実行ログ、段階3は現行レポート） ──
STAGES = [
    {"label": "① 初回突合",           "hop1": 360, "hop24": 285, "div": 145, "rate": 0.816,
     "A": 80, "B": 37, "C": 28},
    {"label": "② crosswalk地理裁定後", "hop1": 360, "hop24": 285, "div": 127, "rate": 0.835,
     "A": 69, "B": 31, "C": 27},
    {"label": "③ 座標解決バグ修正後",   "hop1": 386, "hop24": 294, "div": 92,  "rate": 0.881,
     "A": 30, "B": 34, "C": 28},
]

cc = json.load(open(REPORTS / "keitouzu_crosscheck_2026-08-08.json"))
adj = json.load(open(REPORTS / "keitouzu_xwalk_adjudication_2026-08-08.json"))
tp = json.load(open(REPORTS / "toporag_phase0_2026-08-08.json"))

# 現行レポートと段階③が食い違っていないか確認（図が古びるのを防ぐ）
e = cc["edges"]
assert (e["hop1"], e["hop2_4"], e["divergent"]) == (STAGES[2]["hop1"], STAGES[2]["hop24"], STAGES[2]["div"]), \
    f"段階③がレポートと不一致: {e}"

fig, ax = plt.subplots(2, 2, figsize=(15.5, 9.4))
fig.suptitle("2026-08-08 の成果 — open-keitouzu 突合の精緻化と topoRAG 実証",
             fontsize=15, fontweight="bold", y=0.98)

# ── A: 整合率の推移 ────────────────────────────────────────────
a = ax[0][0]
xs = np.arange(3)
rates = [s["rate"] * 100 for s in STAGES]
bars = a.bar(xs, rates, color=["#90a4ae", "#5c6bc0", "#2e7d32"], width=0.55)
for x, r in zip(xs, rates):
    a.text(x, r + 0.6, f"{r:.1f}%", ha="center", fontsize=13, fontweight="bold")
a.set_xticks(xs)
a.set_xticklabels([s["label"] for s in STAGES], fontsize=9.5)
a.set_ylim(75, 92)
a.set_ylabel("公式系統図の接続が本モデルで再現される率")
a.set_title("A. 突合の整合率 — 2段の是正で 81.6% → 88.1%", fontsize=11.5, fontweight="bold")
a.grid(axis="y", alpha=0.3)
a.annotate("", xy=(1, 83.5), xytext=(0, 81.6),
           arrowprops=dict(arrowstyle="->", color="#5c6bc0", lw=1.6))
a.annotate("", xy=(2, 88.1), xytext=(1, 83.5),
           arrowprops=dict(arrowstyle="->", color="#2e7d32", lw=1.6))

# ── B: 食い違いの内訳変化 ───────────────────────────────────────
b = ax[0][1]
A = [s["A"] for s in STAGES]; B = [s["B"] for s in STAGES]; C = [s["C"] for s in STAGES]
b.bar(xs, A, width=0.55, label="A 完全断絶（最優先）", color="#c62828")
b.bar(xs, B, width=0.55, bottom=A, label="B 遠距離 hop7+", color="#ef9a9a")
b.bar(xs, C, width=0.55, bottom=np.array(A) + np.array(B), label="C 近距離 hop5-6", color="#ffcdd2")
for x, s in zip(xs, STAGES):
    b.text(x, s["div"] + 2.5, f"計 {s['div']}", ha="center", fontsize=11, fontweight="bold")
    b.text(x, s["A"] / 2, str(s["A"]), ha="center", va="center", fontsize=11,
           color="white", fontweight="bold")
b.set_xticks(xs); b.set_xticklabels([s["label"] for s in STAGES], fontsize=9.5)
b.set_ylabel("裁定待ちの食い違い本数")
b.set_title("B. 食い違い候補 — 断絶が 80 → 30 本に（誤検出を除去）", fontsize=11.5, fontweight="bold")
b.legend(fontsize=9, loc="upper right"); b.grid(axis="y", alpha=0.3)
b.set_ylim(0, 175)

# ── C: crosswalk 地理裁定の内訳 ────────────────────────────────
c = ax[1][0]
counts = adj["counts"]
labels = ["ok\n(整合)", "borderline\n(要確認)", "likely\n(同名異地)", "confirmed\n(沖縄跨ぎ)"]
vals = [counts.get("ok", 0), counts.get("borderline", 0),
        counts.get("likely", 0), counts.get("confirmed", 0)]
cols = ["#2e7d32", "#fbc02d", "#f57c00", "#c62828"]
bb = c.barh(range(4), vals, color=cols, height=0.6)
for i, v in enumerate(vals):
    c.text(v + 8, i, str(v), va="center", fontsize=11, fontweight="bold")
c.set_yticks(range(4)); c.set_yticklabels(labels, fontsize=9.5)
c.invert_yaxis(); c.set_xlim(0, 720)
c.set_xlabel("crosswalk 対応の件数（全 657）")
c.set_title("C. crosswalk 地理裁定 — 誤マッチ 16 件を除外し上流へ報告", fontsize=11.5, fontweight="bold")
c.grid(axis="x", alpha=0.3)
c.text(300, 2.6, "likely + confirmed + エッジ文脈有罪 = 16 件を除外\n→ open-keitouzu issue #1 として報告済",
       fontsize=9.5, bbox=dict(boxstyle="round,pad=0.5", fc="#fff3e0", ec="#f57c00"))

# ── D: topoRAG 構造照合の層別性能 ──────────────────────────────
d = ax[1][1]
st = tp["stratified_wl0"]
xs2 = np.arange(len(st))
for k, col, w, z in ((10, "#c5cae9", 0.70, 1), (5, "#5c6bc0", 0.48, 2), (1, "#1a237e", 0.26, 3)):
    d.bar(xs2, [s["recall"][str(k)] * 100 if isinstance(list(s["recall"])[0], str)
                else s["recall"][k] * 100 for s in st],
          width=w, color=col, label=f"recall@{k}", zorder=z)
d.set_xticks(xs2)
d.set_xticklabels([f"{s['bucket']}\n(n={s['n']})" for s in st], fontsize=9)
d.set_ylabel("正解が上位に入る率 (%)")
d.set_title("D. topoRAG — 名前も座標も使わない照合はハブでのみ効く", fontsize=11.5, fontweight="bold")
d.legend(fontsize=9); d.grid(axis="y", alpha=0.3)
disc = [x for x in tp["discrimination"] if x["wl"] == 0][0]
d.text(0.02, 0.97, f"判別性能 AUC = {disc['auc_vs_neg']:.3f}\n（正例 {disc['pos_median']:.2f} / "
                   f"誤マッチ {disc['neg_median']:.2f} / 無関係な変電所 {disc['random_median']:.2f}）",
       transform=d.transAxes, va="top", fontsize=9.5,
       bbox=dict(boxstyle="round,pad=0.5", fc="#e8eaf6", ec="#5c6bc0"))

fig.tight_layout(rect=(0, 0, 1, 0.96))
OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, dpi=130)
print(f"→ {OUT.relative_to(ROOT)}")
