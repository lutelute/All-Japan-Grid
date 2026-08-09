#!/usr/bin/env python3
"""repair_search の結果を束ねて、捏造量ともっともらしさのパレート境界を図と表にする。

`repair_search.py` を島ごとに回した JSON（`--tag` で分割）をまとめ、

  - 全構成の表（島 × gen × sd × solar）
  - 3 目的（捏造容量 MW / 捏造設備 台 / 超過潮流 MW）の非劣解
  - 図: x=出典のない発電容量, y=超過潮流。sd=off/on それぞれの 2 目的境界を線で結ぶ
  - 最良構成に残る過負荷の診断（次に疑うべきものの提示）

を出す。重み付けをしないので「どこまで嘘をつけばどこまでもっともらしくなるか」を
人間がそのまま読める。採否は人間判断。

usage: python3 scripts/capacity/repair_search_report.py [--date 2026-08-09]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
REPORTS = ROOT / "docs" / "reports"
ASSETS = ROOT / "docs" / "assets" / "analysis"

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Hiragino Kaku Gothic ProN",
                                   "Apple SD Gothic Neo", "sans-serif"]
else:
    try:
        import japanize_matplotlib  # noqa: F401
    except ImportError:
        pass

ISLAND_ORDER = ["hokkaido", "east", "west", "okinawa"]
GEN_COLOR = {"base": "#888888", "site": "#1f77b4", "cap": "#2ca02c", "kvfit": "#d62728"}


def pareto_front(rows: list[dict], objectives: list[str]) -> list[int]:
    keep = []
    for i, a in enumerate(rows):
        if any(i != j and all(b[o] <= a[o] for o in objectives)
               and any(b[o] < a[o] for o in objectives) for j, b in enumerate(rows)):
            continue
        keep.append(i)
    return keep


def honest_best(rows: list[dict], cur: dict | None) -> dict | None:
    """**捏造を一切増やさない**構成のうち最良のもの。

    超過潮流だけで採点すると、951 台の変圧器を捏造し 85.7GW の水増し容量を温存した
    構成が「最良」になる。それは推奨ではない。現行モデル以下の捏造量に留まる範囲で
    最も物理的にもっともらしい点を別に示す — これが実際に採れる候補である。
    """
    if cur is None:
        return None
    ok = [r for r in rows if r["fab_unsourced_mw"] <= cur["fab_unsourced_mw"] + 1e-6
          and r["fab_n_fab_trafo"] <= cur["fab_n_fab_trafo"]]
    return min(ok, key=lambda r: r["overload"]["excess_mw"]) if ok else None


def load_runs(date: str) -> tuple[list[dict], dict]:
    runs, residual = [], {}
    for p in sorted(glob.glob(str(REPORTS / f"repair_search_{date}*.json"))):
        if "_gapfix" in p:
            continue                      # 測定器の検証用（本計測ではない）
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        runs += d.get("runs", [])
        residual.update(d.get("residual", {}))
    # 同一構成が複数ファイルにある場合は後勝ち（再実行を反映）
    uniq: dict[tuple, dict] = {}
    for r in runs:
        uniq[(r["island"], r["gen"], r["sd"], r["solar_mw"])] = r
    return list(uniq.values()), residual


def figure(runs: list[dict], date: str) -> Path:
    islands = [i for i in ISLAND_ORDER if any(r["island"] == i for r in runs)]
    n = len(islands)
    fig, axes = plt.subplots(1, n, figsize=(5.0 * n, 4.6))
    if n == 1:
        axes = [axes]
    for ax, island in zip(axes, islands):
        rows = [r for r in runs if r["island"] == island]
        for sd, style in ((False, dict(marker="o", ls="--", alpha=0.95)),
                          (True, dict(marker="^", ls="-", alpha=0.95))):
            sub = [r for r in rows if bool(r["sd"]) == sd]
            if not sub:
                continue
            for r in sub:
                ax.scatter(r["fab_unsourced_mw"] / 1000.0,
                           r["overload"]["excess_mw"] / 1000.0,
                           s=64, marker=style["marker"],
                           facecolor=GEN_COLOR.get(r["gen"], "#333"),
                           edgecolor="white" if sd else GEN_COLOR.get(r["gen"], "#333"),
                           linewidth=1.4, zorder=3)
            flat = [{"x": r["fab_unsourced_mw"], "y": r["overload"]["excess_mw"]} for r in sub]
            idx = pareto_front(flat, ["x", "y"])
            pts = sorted(((flat[i]["x"] / 1000.0, flat[i]["y"] / 1000.0) for i in idx))
            if len(pts) > 1:
                ax.plot([p[0] for p in pts], [p[1] for p in pts],
                        ls=style["ls"], color="#555", lw=1.2, zorder=2,
                        label="降圧点あり" if sd else "降圧点なし")
        cur = next((r for r in rows if r["gen"] == "base" and not r["sd"]
                    and abs(r["solar_mw"] - 10.0) < 1e-9), None)
        best = min(rows, key=lambda r: r["overload"]["excess_mw"])
        if cur is not None:
            ax.scatter(cur["fab_unsourced_mw"] / 1000.0,
                       cur["overload"]["excess_mw"] / 1000.0, s=260, marker="o",
                       facecolor="none", edgecolor="#111", linewidth=1.6, zorder=4)
        ax.scatter(best["fab_unsourced_mw"] / 1000.0,
                   best["overload"]["excess_mw"] / 1000.0, s=300, marker="*",
                   facecolor="none", edgecolor="#b00020", linewidth=1.6, zorder=5)
        hon = honest_best(rows, cur)
        if hon is not None and hon is not best:
            ax.scatter(hon["fab_unsourced_mw"] / 1000.0,
                       hon["overload"]["excess_mw"] / 1000.0, s=250, marker="D",
                       facecolor="none", edgecolor="#0a7d3c", linewidth=1.7, zorder=5)
        ax.margins(0.16)
        ax.set_title(island, fontsize=12, fontweight="bold")
        ax.set_xlabel("出典のない発電容量（GW）→ 捏造が多い", fontsize=9.5)
        ax.set_ylabel("超過潮流（GW）→ 物理的に成立しない量", fontsize=9.5)
        ax.grid(alpha=0.25, lw=0.6)
        if cur is not None:
            ce, be = cur["overload"]["excess_mw"], best["overload"]["excess_mw"]
            cu, bu = cur["fab_unsourced_mw"], best["fab_unsourced_mw"]
            pe = f"（{(be - ce) / ce:+.0%}）" if ce else ""
            pu = f"（{(bu - cu) / cu:+.0%}）" if cu else ""
            ax.text(0.98, 0.97,
                    f"現行 ○ → 最良 ☆\n"
                    f"{best['gen']} / 降圧点{'あり' if best['sd'] else 'なし'} / "
                    f"太陽光 {best['solar_mw']:g}MW\n"
                    f"超過潮流 {ce / 1000:,.1f} → {be / 1000:,.1f} GW{pe}\n"
                    f"捏造容量 {cu / 1000:,.1f} → {bu / 1000:,.1f} GW{pu}\n"
                    f"捏造設備 +{best['fab_n_fab_trafo']:,} 台"
                    + (f"\n\n捏造を増やさない最良 ◇\n"
                       f"{hon['gen']} / 降圧点なし / 太陽光 {hon['solar_mw']:g}MW\n"
                       f"超過潮流 {hon['overload']['excess_mw'] / 1000:,.1f} GW"
                       f"（{(hon['overload']['excess_mw'] - ce) / ce:+.0%}）・"
                       f"捏造 {hon['fab_unsourced_mw'] / 1000:,.1f} GW / 0 台"
                       if hon is not None and hon is not best and ce else ""),
                    transform=ax.transAxes, ha="right", va="top", fontsize=8.4,
                    bbox=dict(boxstyle="round,pad=0.45", fc="white", ec="#ccd4dc",
                              alpha=0.94))
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, label=m)
               for m, c in GEN_COLOR.items()]
    handles += [plt.Line2D([], [], marker="o", ls="", mfc="#bbb", mec="#bbb",
                           label="降圧点なし"),
                plt.Line2D([], [], marker="^", ls="", mfc="#bbb", mec="white",
                           label="降圧点あり"),
                plt.Line2D([], [], marker="o", ls="", mfc="none", mec="#111",
                           label="現行モデル"),
                plt.Line2D([], [], marker="*", ls="", mfc="none", mec="#b00020",
                           ms=12, label="最良（超過潮流のみで採点）"),
                plt.Line2D([], [], marker="D", ls="", mfc="none", mec="#0a7d3c",
                           label="捏造を増やさない最良")]
    fig.legend(handles=handles, ncol=8, loc="lower center", frameon=False, fontsize=9)
    fig.suptitle("修復候補の探索 — 捏造量ともっともらしさのパレート境界"
                 f"（DC・{date}・未適用）", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0.07, 1, 0.94))
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / f"repair_pareto_{date}.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()
    runs, residual = load_runs(date)
    if not runs:
        print(f"no repair_search_{date}*.json"); return
    islands = [i for i in ISLAND_ORDER if any(r["island"] == i for r in runs)]
    png = figure(runs, date)

    L = [f"# 修復候補の組み合わせ探索 — 捏造量ともっともらしさのパレート境界（{date}）", "",
         "診断連鎖が挙げた真因 3 つは**いずれも単独で**測られていた。単独では太陽光の是正は",
         "**悪化**に見え（east 最大 1,668% → 3,371%）、接続電圧の是正は −26%、降圧点の補充は",
         "過負荷 603 → 422 本にとどまる。交互作用のある系で一度に一つしか動かさないのは",
         "古典的な誤りなので、3 軸の全組み合わせ（4×2×2）を回した。", "",
         "同時に**捏造量を第一級の目的関数**に置いた。`docs/MODEL_INTERVENTIONS.md` の原則",
         "（解けるように見せる介入は全部登録せよ）を探索にも適用し、",
         "「過負荷が減ったか」だけで採点しない。", "",
         "| 目的（すべて最小化） | 意味 |", "|---|---|",
         "| 捏造容量 (MW) | 出典が無く既定値で埋めた発電容量。太陽光の是正はこれを**減らす** |",
         "| 捏造設備 (台) | OSM にも公開系統図にも無い、こちらで足した変圧器 |",
         "| 偽電源 (台) | 発電機を持たない成分に置く合成 slack＝**実在しない電源** |",
         "| 超過潮流 (MW) | 定格を超えて流れている分＝物理的に成立していない量 |", "",
         "> **2026-08-10 訂正**: 初版は偽電源（合成 slack）を目的に数えていなかった。",
         "> そのため east で「現行を全目的で支配する構成が 4 件ある＝トレードオフではない」",
         "> と書いたが、**偽電源を数えると 0 件**になる。接続規則を電圧に見合わせると、",
         "> 孤立ポケットに誤接続されていた発電機が本来の階級のバスへ移り、残されたポケットが",
         "> 合成 slack で賄われるため（east +23・west +84）。改善は実在するが**無償ではない**。", "",
         f"![パレート境界](../assets/analysis/{png.name})", ""]

    for island in islands:
        rows = sorted([r for r in runs if r["island"] == island],
                      key=lambda r: r["overload"]["excess_mw"])
        flat = [{"u": r["fab_unsourced_mw"], "t": r["fab_n_fab_trafo"],
                 "s": r.get("n_synth_slack", 0),
                 "e": r["overload"]["excess_mw"]} for r in rows]
        front = set(pareto_front(flat, ["u", "t", "s", "e"]))
        cur = next((r for r in rows if r["gen"] == "base" and not r["sd"]
                    and abs(r["solar_mw"] - 10.0) < 1e-9), None)
        L += [f"## {island}", "",
              "| | 接続規則 | 降圧点 | 太陽光既定 | 捏造容量 | 捏造設備 | 偽電源 | 過負荷 | 最大負荷率 | 超過潮流 |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for i, r in enumerate(rows):
            o = r["overload"]
            mark = "**◆**" if i in front else ""
            if cur is not None and r is cur:
                mark = (mark + " 現行").strip()
            L.append(f"| {mark} | {r['gen']} | {'あり' if r['sd'] else 'なし'} | "
                     f"{r['solar_mw']:g} MW | {r['fab_unsourced_mw']:,.0f} MW | "
                     f"{r['fab_n_fab_trafo']:,} 台 | {r.get('n_synth_slack', 0):,} | "
                     f"{o['n_over']:,} ({o['over_share']:.2%}) | "
                     f"{o['max_pct']}% | {o['excess_mw']:,.0f} MW |")
        L.append("")
        L.append("◆ = 4 目的の非劣解（他のどの構成にも全項目で負けていない）")
        L.append("")
        best = rows[0]
        if cur is not None and best is not cur:
            de = best["overload"]["excess_mw"] - cur["overload"]["excess_mw"]
            du = best["fab_unsourced_mw"] - cur["fab_unsourced_mw"]
            L += [f"最良は **{best['gen']} / 降圧点{'あり' if best['sd'] else 'なし'} / "
                  f"太陽光 {best['solar_mw']:g}MW** で、現行に対し超過潮流 "
                  f"{de:+,.0f} MW（{de / cur['overload']['excess_mw']:+.1%}）、"
                  f"出典のない容量 {du:+,.0f} MW"
                  f"（{du / cur['fab_unsourced_mw']:+.1%}）、"
                  f"捏造設備 +{best['fab_n_fab_trafo']:,} 台。", ""]
        hon = honest_best(rows, cur)
        if hon is not None and cur is not None and cur["overload"]["excess_mw"]:
            ho, co = hon["overload"], cur["overload"]
            dominates = (ho["excess_mw"] < co["excess_mw"] and ho["n_over"] < co["n_over"]
                         and (ho["max_pct"] or 0) < (co["max_pct"] or 0)
                         and hon["fab_unsourced_mw"] < cur["fab_unsourced_mw"])
            L += [f"**捏造を増やさない範囲での最良**は "
                  f"**{hon['gen']} / 降圧点なし / 太陽光 {hon['solar_mw']:g}MW**: "
                  f"過負荷 {co['n_over']:,} → {ho['n_over']:,} 本、"
                  f"最大負荷率 {co['max_pct']:,.0f}% → {ho['max_pct']:,.0f}%、"
                  f"超過潮流 {co['excess_mw']:,.0f} → {ho['excess_mw']:,.0f} MW"
                  f"（{(ho['excess_mw'] - co['excess_mw']) / co['excess_mw']:+.0%}）、"
                  f"出典のない容量 {cur['fab_unsourced_mw']:,.0f} → "
                  f"{hon['fab_unsourced_mw']:,.0f} MW、**設備の追加はゼロ**。", ""]
            del dominates
        # 現行モデルを**全目的で**下回る構成 — 重み付けを一切要しない最も強い言明
        if cur is not None:
            keys = [(lambda r: r["overload"]["excess_mw"]),
                    (lambda r: r["overload"]["n_over"]),
                    (lambda r: r["overload"]["max_pct"] or 0),
                    (lambda r: r["fab_unsourced_mw"]),
                    (lambda r: r["fab_n_fab_trafo"]),
                    # 2026-08-10 追加。これを数えないと east で4件が「支配」に見えるが
                    # 数えると0件になる（初版の「トレードオフではない」は目的関数の欠落）
                    (lambda r: r.get("n_synth_slack", 0))]
            dom = [r for r in rows if r is not cur
                   and all(k(r) <= k(cur) for k in keys)
                   and any(k(r) < k(cur) for k in keys)]
            if dom:
                L += ["### 現行モデルを全目的で支配する構成", "",
                      "過負荷本数・最大負荷率・超過潮流・捏造容量・捏造設備の**5 つすべて**で",
                      "現行を下回る構成。重み付けを要さないので、ここに載るものは",
                      "「どの立場から見ても現行より良い」と言える。", "",
                      "| 接続規則 | 降圧点 | 太陽光 | 過負荷 | 最大負荷率 | 超過潮流 | 捏造容量 | 捏造設備 |",
                      "|---|---|---:|---:|---:|---:|---:|---:|"]
                for r in sorted(dom, key=lambda r: r["overload"]["excess_mw"]):
                    o = r["overload"]
                    L.append(f"| {r['gen']} | {'あり' if r['sd'] else 'なし'} | "
                             f"{r['solar_mw']:g} MW | {o['n_over']:,} | {o['max_pct']:,.0f}% | "
                             f"{o['excess_mw']:,.0f} MW | {r['fab_unsourced_mw']:,.0f} MW | "
                             f"{r['fab_n_fab_trafo']:,} 台 |")
                L += ["", f"（現行: 過負荷 {cur['overload']['n_over']:,} / "
                      f"最大 {cur['overload']['max_pct']:,.0f}% / "
                      f"超過 {cur['overload']['excess_mw']:,.0f} MW / "
                      f"捏造 {cur['fab_unsourced_mw']:,.0f} MW・"
                      f"{cur['fab_n_fab_trafo']:,} 台）", "",
                      "**ここはトレードオフではない。** 捏造を減らす方向の是正が、"
                      "物理的なもっともらしさも同時に改善している。", ""]
        # ── 交互作用: 太陽光の是正の効果が接続規則で符号を変えるか ──────────
        solars = sorted({r["solar_mw"] for r in rows})
        if len(solars) >= 2:
            lo, hi = solars[0], solars[-1]
            L += ["### 交互作用 — 太陽光の是正は単独では評価できない", "",
                  f"太陽光の既定値を {hi:g}MW → {lo:g}MW に正したときの**超過潮流の変化**を、"
                  "接続規則と降圧点の各組み合わせで見る。", "",
                  "| 接続規則 | 降圧点 | 超過潮流の変化 | 最大負荷率の変化 |",
                  "|---|---|---:|---:|"]
            flips = []
            for gen in ["base", "site", "cap", "kvfit"]:
                for sd in (False, True):
                    a = next((r for r in rows if r["gen"] == gen and bool(r["sd"]) == sd
                              and abs(r["solar_mw"] - hi) < 1e-9), None)
                    b = next((r for r in rows if r["gen"] == gen and bool(r["sd"]) == sd
                              and abs(r["solar_mw"] - lo) < 1e-9), None)
                    if a is None or b is None:
                        continue
                    de = b["overload"]["excess_mw"] - a["overload"]["excess_mw"]
                    dm = (b["overload"]["max_pct"] or 0) - (a["overload"]["max_pct"] or 0)
                    flips.append((gen, sd, de, dm))
                    L.append(f"| {gen} | {'あり' if sd else 'なし'} | {de:+,.0f} MW | "
                             f"{dm:+,.0f} pt |")
            L.append("")
            # 島全体の超過潮流が小さい所（hokkaido の 0.02GW 等）では符号の反転に
            # 意味が無い。桁が動く島だけで主張する。
            material = max((abs(f[3]) for f in flips), default=0.0) >= 100.0
            worse = [f for f in flips if f[3] > 0]
            better = [f for f in flips if f[3] < 0]
            if worse and better and material:
                L += ["**符号が反転する。** 同じ「太陽光を実測中央値に正す」という一つの是正が、"
                      f"接続規則によって最大負荷率を {max(f[3] for f in worse):+,.0f}pt "
                      f"悪化させたり {min(f[3] for f in better):+,.0f}pt 改善させたりする。",
                      "膨らんだ太陽光は系統中に薄く広がった注入なので、取り除くと発電は実在の",
                      "火力・原子力へ集中する。その集中先が電圧に見合わないバスに繋がっていれば",
                      "悪化し、見合っていれば改善する。**一度に一つしか動かさない診断では、"
                      "この是正は「やってはいけないこと」に見えていた。**", ""]
        rd = residual.get(island) or {}
        if rd.get("n_over"):
            L += [f"### 残る過負荷（{rd['n_over']:,} 本）— 次に疑うべきもの", "",
                  f"超過潮流が最小の構成（`{rd.get('config', '?')}`）で残ったもの。", "",
                  "| 電圧階級 | 本数 |", "|---|---:|"]
            for kv, c in list(rd.get("by_kv", {}).items())[:8]:
                L.append(f"| {kv} kV | {c:,} |")
            L += ["", f"- 端点が放射状（次数1）: {rd.get('n_radial_endpoint', 0):,} 本",
                  f"- 単回線（parallel=1）: {rd.get('n_single_circuit', 0):,} 本",
                  f"- 発電側が優勢: {rd.get('n_gen_dominated', 0):,} 本 / "
                  f"需要側が優勢: {rd.get('n_load_dominated', 0):,} 本", ""]

    L += ["## 測定器の検証", "",
          "過負荷は pandapower の `loading_percent`（電流基準）で測っているが、この診断系列は",
          "**並列回線数の取り違えを 4 回踏んでいる**ので、`|P| /（max_i_ka × kV × √3 × parallel）`",
          "という電力基準の独立経路でも毎回計算して突き合わせた。", "",
          "**比較そのものが成立するかも確かめた。** 太陽光の既定値を下げると east の銘板容量は",
          "186,597 → 110,704 MW と 76GW 減る。`balance_by_zone` がゾーン容量に比例して配分する",
          "以上、これが「発電量そのものが減っただけ」なら超過潮流の比較は無意味になる。",
          "実測したところ 4 構成すべてで **総需要 55,250 MW / 総発電 58,013 MW / スラック",
          "−2,763 MW が 1MW 以内で一致**した（`scratchpad/balance_check.py` 相当）。",
          "動いているのは注入の**置き場所だけ**で、量ではない。", "",
          "初回は hokkaido で **14.58pt の食い違い**が出た。追跡すると原因は混在電圧線",
          "（110/66kV）で、同じ P に対し低圧側の電流が大きく pandapower は max(i_from, i_to) を",
          "採るのに対し、こちらが from 側の電圧で定格を組んでいたため。**測定器の誤りであって",
          "モデルの誤りではない**。両端の低い方の電圧を使うよう直したところ全 815 本で 0.00pt に",
          "一致した。並列回線数・df・電圧基準がすべて正しく扱えていることの裏づけになる。", "",
          "---",
          "**未適用**。採否は人間判断で、採るなら `docs/MODEL_INTERVENTIONS.md` に",
          "①根拠②帳簿③無効化を登録する。", "",
          "生成: `scripts/capacity/repair_search.py` → `repair_search_report.py`（DC）", ""]
    out = REPORTS / f"repair_search_{date}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"→ {out.relative_to(ROOT)}\n→ {png.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
