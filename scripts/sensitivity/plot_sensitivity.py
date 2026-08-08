#!/usr/bin/env python3
"""感度行列ベンチマークの結果を図とレポートにする。

入力: docs/reports/sensitivity_bench_<date>.json（benchmark_sensitivity.py の出力）
出力: docs/assets/sensitivity/bench_<date>.png と docs/reports/sensitivity_bench_<date>.md
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "docs" / "reports"
FIGS = ROOT / "docs" / "assets" / "sensitivity"

plt.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()

    d = json.load(open(REPORTS / f"sensitivity_bench_{date}.json"))
    isls = d["islands"]
    names = [r["island"] for r in isls]
    xs = np.arange(len(isls))
    FIGS.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(1, 3, figsize=(16.5, 4.9))
    fig.suptitle("感度行列(PTDF/LODF)による潮流の高速化と精度の代償", fontsize=14, fontweight="bold", y=1.0)

    # ── ① 1断面あたりの求解時間（対数） ────────────────────────────
    a = ax[0]
    w = 0.26
    a.bar(xs - w, [r["timing"]["ac_per_snapshot_ms"] for r in isls], w, label="AC (Newton-Raphson)", color="#c62828")
    a.bar(xs,      [r["timing"]["dc_per_snapshot_ms"] for r in isls], w, label="DC (線形解法)", color="#f9a825")
    a.bar(xs + w,  [r["timing"]["ptdf_per_snapshot_ms"] for r in isls], w, label="PTDF (行列ベクトル積)", color="#2e7d32")
    a.set_yscale("log"); a.set_xticks(xs); a.set_xticklabels(names)
    a.set_ylabel("1断面あたりの求解時間 (ms・対数)")
    a.set_title("① 速度 — PTDFは反復を持たない", fontsize=11.5, fontweight="bold")
    a.legend(fontsize=9, loc="upper left"); a.grid(axis="y", alpha=0.3); a.margins(y=0.28)
    for i, r in enumerate(isls):
        a.text(i + w, r["timing"]["ptdf_per_snapshot_ms"] * 1.6,
               f"×{r['timing']['speedup_vs_ac']:.0f}", ha="center", fontsize=9.5,
               color="#2e7d32", fontweight="bold")

    # ── ② 精度: PTDF(線形DC) vs AC の枝潮流誤差 ────────────────────
    b = ax[1]
    acc = [r.get("accuracy", {}) for r in isls]
    b.bar(xs - w/2, [a_.get("p50_mw", 0) for a_ in acc], w, label="中央値", color="#90caf9")
    b.bar(xs + w/2, [a_.get("p95_mw", 0) for a_ in acc], w, label="95パーセンタイル", color="#1565c0")
    b.set_xticks(xs)
    b.set_xticklabels([f"{n}\n(平均潮流 {a_.get('mean_ac_flow_mw',0):.0f}MW)" for n, a_ in zip(names, acc)],
                      fontsize=9)
    b.set_ylabel("AC解との枝潮流の差 (MW)")
    b.set_title("② 精度の代償 — 中央値は小さく裾が重い", fontsize=11.5, fontweight="bold")
    b.legend(fontsize=9); b.grid(axis="y", alpha=0.3)
    b.margins(y=0.18)

    # ── ③ N-1: LODF一発 vs 解き直し ────────────────────────────────
    c = ax[2]
    n1 = [r.get("n1") for r in isls]
    ok = [i for i, x in enumerate(n1) if x]
    if ok:
        c.bar([i - w/2 for i in ok], [n1[i]["resolve_total_s"] * 1e3 / n1[i]["n_sampled"] for i in ok],
              w, label="枝を落として解き直し", color="#c62828")
        c.bar([i + w/2 for i in ok], [n1[i]["lodf_total_ms"] / n1[i]["n_sampled"] for i in ok],
              w, label="LODF 1列の積", color="#2e7d32")
        for i in ok:
            c.text(i, (n1[i]["resolve_total_s"] * 1e3 / n1[i]["n_sampled"]) * 2.2,
                   f"×{n1[i]['speedup']:.0f}", ha="center", fontsize=10,
                   color="#2e7d32", fontweight="bold")
    c.set_yscale("log"); c.set_xticks(xs); c.set_xticklabels(names)
    c.set_ylabel("1停止あたりの評価時間 (ms・対数)")
    c.set_title("③ N-1 — LODFは厳密（全島で不一致 0 MW）", fontsize=11.5, fontweight="bold")
    c.legend(fontsize=9, loc="lower left"); c.grid(axis="y", alpha=0.3); c.margins(y=0.35)

    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out_png = FIGS / f"bench_{date}.png"
    fig.savefig(out_png, dpi=130)

    # ── レポート ────────────────────────────────────────────────
    L = [
        f"# 感度行列による潮流の高速化と精度比較 — {date}",
        "",
        "PTDF（バス注入 → 枝潮流の線形感度）を一度作れば、潮流は**行列ベクトル積 1 回**で得られる。",
        "LODF（枝停止 → 他枝潮流の感度）を使えば N-1 も解き直しなしで評価できる。",
        "その速度と、線形化で失う精度を実測した。",
        "",
        "対象は最大連結成分（PTDF は連結・単一 slack が前提。この成分が需要の約 90% を保持することは",
        "`pf_frontier_2026-08-08.md` で確認済み）。負荷は 24 時間の代表的な日負荷曲線でスケールした。",
        "",
        "## 1. 実装の正しさ",
        "",
        "PTDF·P が DC 解の枝潮流を再現するかを機械精度で確認した。",
        "",
        "| 島 | 主成分バス | 枝 | PTDF構築 | PTDF大きさ | DC解との最大差 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in isls:
        L.append(f"| {r['island']} | {r['n_bus']} | {r['n_branch']} | {r['sec_build_ptdf']:.2f} s | "
                 f"{r['ptdf_mb']:.0f} MB | {r['validation']['max_abs_mw']:.2e} MW |")
    L += [
        "",
        "## 2. 速度",
        "",
        "| 島 | AC 1断面 | DC 1断面 | PTDF 1断面 | AC比 | DC比 | 構築コストの回収点 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in isls:
        t = r["timing"]
        L.append(f"| {r['island']} | {t['ac_per_snapshot_ms']:.1f} ms | {t['dc_per_snapshot_ms']:.1f} ms | "
                 f"**{t['ptdf_per_snapshot_ms']:.4f} ms** | ×{t['speedup_vs_ac']:.0f} | ×{t['speedup_vs_dc']:.0f} | "
                 f"{t['breakeven_snapshots']:.1f} 断面 |")
    L += [
        "",
        "「回収点」は PTDF の構築時間が AC 何断面分に相当するか。これを超える断面数を解くなら",
        "感度行列を作った方が速い。年間 8760 断面や大量のシナリオ評価では圧倒的に有利になる。",
        "",
        "## 3. 精度の代償",
        "",
        "PTDF は直流近似（電圧一定・無損失・小角度）なので、AC 解との差が線形化の代償になる。",
        "",
        "| 島 | 平均潮流 | 誤差 中央値 | 誤差 p95 | 誤差 最大 | 相対誤差 p95 | 大潮流枝のみ p95 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in isls:
        a_ = r.get("accuracy")
        if not a_:
            L.append(f"| {r['island']} | — | — | — | — | — | — |")
            continue
        L.append(f"| {r['island']} | {a_['mean_ac_flow_mw']:.0f} MW | {a_['p50_mw']:.2f} MW | "
                 f"{a_['p95_mw']:.1f} MW | {a_['max_mw']:.0f} MW | {a_['p95_rel']:.1%} | "
                 f"**{a_['p95_rel_top10pct']:.1%}** |")
    L += [
        "",
        "**中央値は小さく裾が重い**という形をしている。多くの枝では誤差は 1 MW 未満で、",
        "潮流の大きい上位 10% の枝に絞った相対誤差 p95 が実務的な指標になる。",
        "screening（過負荷になりうる枝の洗い出し）には十分だが、確定値としては AC で解き直す必要がある。",
        "",
        "## 4. N-1 — LODF は近似ではなく厳密",
        "",
        "| 島 | 評価した停止 | 解き直し | LODF | 速度比 | 最大不一致 | 橋（LODF不定） |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in isls:
        n = r.get("n1")
        if not n:
            L.append(f"| {r['island']} | — | — | — | — | — | {r.get('n_bridge_branches','—')} |")
            continue
        L.append(f"| {r['island']} | {n['n_sampled']} 本 | {n['resolve_total_s']:.2f} s | "
                 f"{n['lodf_total_ms']:.3f} ms | **×{n['speedup']:.0f}** | {n['max_abs_mw']:.2g} MW | "
                 f"{r['n_bridge_branches']} ({r.get('bridge_share',0):.1%}) |")
    L += [
        "",
        "**DC の枠内では LODF は近似ではなく厳密**で、解き直しと機械精度で一致する。",
        "ただし**橋**（落とすと網が割れる枝）では LODF が定義できない。本モデルは橋の比率が高く、",
        "そこは個別に解く必要がある。橋の多さ自体が網の弱さの指標でもある。",
        "",
        f"![ベンチマーク](../assets/sensitivity/bench_{date}.png)",
        "",
        "---",
        "生成: `scripts/sensitivity/benchmark_sensitivity.py` → `plot_sensitivity.py`",
        "",
    ]
    (REPORTS / f"sensitivity_bench_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ {out_png.relative_to(ROOT)}")
    print(f"→ docs/reports/sensitivity_bench_{date}.md")


if __name__ == "__main__":
    main()
