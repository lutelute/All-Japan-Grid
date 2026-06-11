"""Validation-section figures for the papers (PLAN_NEXT P2, ledger 62).

    PYTHONPATH=. python scripts/gen_paper_figs.py   # -> papers/figs/val_*.{pdf,png}

All inputs are committed scorecards under docs/reports/ — the figures
regenerate bit-stable from the repository alone (reproducibility rule).
"""

import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
plt.rcParams["font.family"] = "Hiragino Sans"
plt.rcParams["pdf.fonttype"] = 42

R = "docs/reports"
OUT = "papers/figs"


def _load(name):
    return json.load(open(os.path.join(R, name)))


def _save(fig, stem):
    os.makedirs(OUT, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(f"{OUT}/{stem}.{ext}", bbox_inches="tight", dpi=200)
    plt.close(fig)
    print(f"  -> {OUT}/{stem}.pdf/.png")


def fig_a_rho_progression():
    """3-layer rho across the campaign, instrument revisions marked."""
    steps = [  # (label, file, kind)  kind: I=instrument, M=model change
        ("基線\n(計器v1)", "external_flows_tokyo_full_2026-06-11.json", "I"),
        ("名寄せ拡張\n(計器v2)", "external_flows_tokyo_full_2026-06-11b.json", "I"),
        ("実測需要ピン", "external_flows_tokyo_full_2026-06-11c.json", "M"),
        ("XLPEケーブル", "external_flows_tokyo_full_2026-06-11f.json", "M"),
        ("eponym配置", "external_flows_tokyo_full_2026-06-11g.json", "M"),
        ("タップスナップ", "external_flows_tokyo_full_2026-06-11j.json", "M"),
    ]
    keys = [("interior_spearman_rho", "全体(内部)", "#222222", "-"),
            ("trunk_spearman_rho", "幹線 275kV+", "#cc0000", "-"),
            ("kv154_spearman_rho", "154kV", "#007733", "--"),
            ("kv66_spearman_rho", "66kV", "#334455", "--")]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    xs = range(len(steps))
    for key, lab, col, ls in keys:
        ys = [_load(f).get(key) for _l, f, _k in steps]
        ax.plot(xs, ys, marker="o", ms=4, color=col, ls=ls, lw=1.4, label=lab)
    for i, (lab, _f, kind) in enumerate(steps):
        ax.axvline(i, color="#dddddd", lw=0.6, zorder=0)
        ax.text(i, -0.13, lab, ha="center", va="top", fontsize=7.5,
                color="#444" if kind == "M" else "#1a4f8a")
    ax.set_xticks([])
    ax.set_ylabel("Spearman ρ (対 東電実測)")
    ax.set_ylim(0, 0.75)
    ax.legend(fontsize=8, ncol=4, loc="upper center")
    ax.set_title("3層流れ相関の推移 — 青字=計器改訂・黒字=モデル変更（東京フルモデル）",
                 fontsize=10)
    _save(fig, "val_rho_progression")


def fig_b_recall_tiers():
    m = _load("external_match_tokyo_tepco_banded_2026-06-11c.json")
    bands = ["trunk", "154", "66"]
    recall = [m["pair_recall_by_band"][b] * 100 for b in bands]
    totals = [m["pair_total_by_band"][b] for b in bands]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.0))
    ax1.bar([f"{b}\n(n={t})" for b, t in zip(bands, totals)], recall,
            color=["#cc0000", "#007733", "#334455"], width=0.6)
    for i, v in enumerate(recall):
        ax1.text(i, v + 1, f"{v:.1f}%", ha="center", fontsize=9)
    ax1.set_ylabel("接続再現率 [%]")
    ax1.set_ylim(0, 75)
    ax1.set_title("帯別 接続recall (真値1,057ペア)", fontsize=10)
    tiers = [("name", m["pair_attached_name"]),
             ("position\n(±1.5km)", m["pair_attached_position"]),
             ("adjacent\n(電気的隣接)", m["pair_attached_adjacent"]),
             ("homonym\nguard除外", m["pair_homonym_guarded"]),
             ("unattached", m["pair_unattached"])]
    ax2.bar([t for t, _v in tiers], [v for _t, v in tiers],
            color=["#1a4f8a", "#5588bb", "#88aacc", "#bbbbbb", "#dd8888"])
    ax2.set_title("マッチ階層の内訳", fontsize=10)
    ax2.tick_params(axis="x", labelsize=7.5)
    _save(fig, "val_recall_tiers")


def fig_c_reconcile():
    m = _load("reconcile_occto_2026-06-11.json")
    rows = m["demand"]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    regions = [r["region"] for r in rows]
    ratio = [r["snapshot_over_p95"] for r in rows]
    cols = ["#2e7d32" if r["band"] == "q50..p95" else
            "#c62828" if r["band"] == ">p95" else "#f9a825" for r in rows]
    ax.bar(regions, ratio, color=cols, width=0.62)
    ax.axhline(1.0, color="#555", lw=0.8, ls="--")
    ax.axhspan(0.66, 1.0, color="#2e7d32", alpha=0.06)
    for i, r in enumerate(rows):
        ax.text(i, ratio[i] + 0.02, f"{ratio[i]:.2f}", ha="center", fontsize=8)
    ax.set_ylabel("設定断面 / OCCTO実測p95")
    ax.set_title("地域需要設定のOCCTO実測突合（修正前: 北海道過小・四国過大を検出→56で修正）",
                 fontsize=9.5)
    ax.tick_params(axis="x", rotation=30, labelsize=8)
    _save(fig, "val_reconcile_bands")


def fig_d_west_pockets():
    pockets = json.load(open(f"{R}/west_isolated_pockets_2026-06-12.json"))
    linked = {"chubu": 95, "kansai": 91, "kyushu": 98}   # ledger 58
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.0))
    ax1.bar(list(linked), list(linked.values()), color="#1a4f8a", width=0.55)
    ax1.axhline(95, color="#c62828", ls="--", lw=0.9)
    ax1.text(2.45, 95.4, "ゲート95%", fontsize=8, color="#c62828")
    for i, v in enumerate(linked.values()):
        ax1.text(i, v + 0.3, f"{v}%", ha="center", fontsize=9)
    ax1.set_ylim(85, 100)
    ax1.set_title("66kVポケットの上位網連結率", fontsize=10)
    cats = ["ノイズ", "OSM欠落疑い", "遠隔", "中距離"]
    keymap = {"ノイズ": "ノイズ断片", "OSM欠落疑い": "上位接続欠落",
              "遠隔": "遠隔", "中距離": "中距離"}
    bottoms = [0, 0, 0]
    colors = ["#bbbbbb", "#c62828", "#88aacc", "#f9a825"]
    regs = ["chubu", "kansai", "kyushu"]
    for cat, col in zip(cats, colors):
        vals = [sum(1 for p in pockets[r]
                    if keymap[cat] in p["class"]) for r in regs]
        ax2.bar(regs, vals, bottom=bottoms, color=col, width=0.55, label=cat)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax2.legend(fontsize=7.5)
    ax2.set_title("孤立ポケット33件の分類", fontsize=10)
    _save(fig, "val_west_pockets")


def fig_e_closed_loop():
    fig, ax = plt.subplots(figsize=(7.2, 2.2))
    ax.axis("off")
    boxes = ["fetch\n(OCCTO/東電\n+メタ管理)", "calibrate\n(DB: 4卓)",
             "reconcile\n(帯判定)", "config修正\n(根拠つき)", "帯内化\n確認"]
    for i, b in enumerate(boxes):
        ax.add_patch(plt.Rectangle((i * 1.45, 0.25), 1.18, 0.55, fill=True,
                                   facecolor="#eef3fa", edgecolor="#1a4f8a"))
        ax.text(i * 1.45 + 0.59, 0.525, b, ha="center", va="center", fontsize=8.5)
        if i < len(boxes) - 1:
            ax.annotate("", xy=(i * 1.45 + 1.40, 0.525),
                        xytext=(i * 1.45 + 1.20, 0.525),
                        arrowprops=dict(arrowstyle="->", color="#1a4f8a"))
    ax.annotate("", xy=(0.59, 0.20), xytext=(5.85, 0.20),
                arrowprops=dict(arrowstyle="->", color="#888",
                                connectionstyle="arc3,rad=0.25"))
    ax.text(3.2, -0.13, "次サイクル（機械的更新）", ha="center", fontsize=8,
            color="#666")
    ax.set_xlim(-0.2, 7.5)
    ax.set_ylim(-0.25, 1.0)
    ax.set_title("計器駆動の閉ループ（実例: 北海道/四国ピーク修正・台帳56）", fontsize=10)
    _save(fig, "val_closed_loop")


if __name__ == "__main__":
    fig_a_rho_progression()
    fig_b_recall_tiers()
    fig_c_reconcile()
    fig_d_west_pockets()
    fig_e_closed_loop()
    print("done")
