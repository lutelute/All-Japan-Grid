#!/usr/bin/env python3
"""動的カスケード(run_v2_dyn)の集計: 受電率と原因の時間推移、独立系統の数の分布、静的 run_v1 との比較。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/summarize_dynamic.py hazard/nankai/output/run_v2_dyn hazard/nankai/output/run_v1_jshis \
        docs/reports/nankai_hazard_2026-09-13/dynamics
"""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd, yaml
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from nankai.grid import GridCase
from nankai.aggregate import bus_prefecture, naikakufu_region_of, customers_per_mw

plt.rcParams["font.family"] = ["Hiragino Sans"]
NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REG = ["tokai", "kinki", "sanyo", "shikoku", "kyushu"]
ISL_J = {"west": "西 60 Hz(中部・北陸・関西・中国・四国・九州)", "east": "東 50 Hz(東京・東北)"}


def five_region_customers(run_dir, cols):
    out = {c: 0.0 for c in cols}
    for isl in ("west", "east"):
        bp = os.path.join(run_dir, isl, "bus_results.parquet")
        if not os.path.exists(bp):
            continue
        bus = pd.read_parquet(bp); case = GridCase.load(isl)
        reg = naikakufu_region_of(bus_prefecture(case)); m = np.isin(reg, REG)
        cpm = customers_per_mw(bus.groupby("zone").pd_mw.sum().to_dict()); cust = bus.pd_mw.to_numpy() * bus.zone.map(cpm).fillna(0).to_numpy()
        for c in cols:
            if c in bus:
                out[c] += float(((1 - bus[c].to_numpy()) * cust)[m].sum())
    return out


def sensitivity_table(runs):
    """runs: [(ラベル, run_dir)]。島ごとに 3 分・10 分・3 時間の受電率・崩壊・独立系統の数を並べる。"""
    md = ["## 感度: 過負荷リレーの扱い", "", "| 条件 | 島 | 3 分 受電率 | 10 分 受電率 | 3 時間 受電率 | 3 時間 崩壊(平均 / 中央値) | 全域の 8 割超が崩壊したサンプル | 10 分 独立系統 平均 / 最大 | 10 分で 2 個以上に分かれた割合 |", "|---|---|---|---|---|---|---|---|---|"]
    for lab, rd in runs:
        for isl in ("west", "east"):
            f = os.path.join(rd, isl, "dyn_samples.csv")
            if not os.path.exists(f):
                continue
            ds = pd.read_csv(f); L = float(pd.read_csv(os.path.join(rd, isl, "dyn_summary.csv")).load_mw.iloc[0])
            g = lambda t, c: ds[ds.t_s == t][c]
            md.append(f"| {lab} | {'西' if isl == 'west' else '東'} | {g(180, 'energized_mw').mean()/L:.1%} | {g(600, 'energized_mw').mean()/L:.1%} | {g(10800, 'energized_mw').mean()/L:.1%} | "
                      f"{g(10800, 'collapsed_mw').mean()/1e3:.1f} / {g(10800, 'collapsed_mw').median()/1e3:.1f} GW | {float((g(10800, 'collapsed_mw') > 0.8 * L).mean()):.0%} | {g(600, 'n_islands').mean():.2f} / {int(g(600, 'n_islands').max())} | {float((g(600, 'n_islands') >= 2).mean()):.0%} |")
    return md


def main(dyn, v1, out, *extra):
    os.makedirs(out, exist_ok=True)
    md = [f"# 動的カスケードの集計({os.path.basename(os.path.normpath(dyn))})", ""]
    fig, axes = plt.subplots(2, 2, figsize=(15, 9))
    for j, isl in enumerate(("west", "east")):
        ds = pd.read_csv(os.path.join(dyn, isl, "dyn_samples.csv")); sm = pd.read_csv(os.path.join(dyn, isl, "dyn_summary.csv"))
        L = float(sm.load_mw.iloc[0]); N = ds["sample"].nunique()
        ax = axes[0, j]
        x = sm.t_s.clip(lower=0.5)
        parts = [("site_out_mw", "#ff9f40", "設備損傷"), ("isolated_mw", "#5b667c", "電源から孤立"), ("collapsed_mw", "#ff3b2f", "周波数崩壊"), ("shed_mw", "#ffd86b", "UFLS 遮断")]
        ax.stackplot(x, *[sm[c] / L * 100 for c, _, _ in parts], colors=[c for _, c, _ in parts], labels=[l for _, _, l in parts], alpha=0.9)
        ax.plot(x, (1 - sm.energized_p10 / L) * 100, color="k", lw=0.8, ls=":", label="停電率 90 パーセンタイル")
        ax.set_xscale("log"); ax.set_xlim(0.5, 10800); ax.set_ylim(0, max(40, float((1 - sm.energized_p10 / L).max() * 110)))
        ax.set_xticks([1, 10, 60, 300, 1800, 10800]); ax.set_xticklabels(["1秒", "10秒", "1分", "5分", "30分", "3時間"])
        ax.set_ylabel("需要に対する割合 [%](平均)"); ax.set_title(f"{ISL_J[isl]}  停電の原因(N={N})", fontsize=12); ax.legend(loc="upper left", fontsize=9); ax.grid(alpha=0.3)
        ax = axes[1, j]
        kmax = int(ds.n_islands.max())
        for q, (tt, c, lab) in enumerate(((60, "#9bbcff", "1 分後"), (180, "#3b6fd6", "3 分後"), (600, "#1a3a8a", "10 分後"), (10800, "#111", "3 時間後"))):
            v = ds[ds.t_s == tt].n_islands.value_counts().reindex(range(0, kmax + 1), fill_value=0)
            ax.bar(np.arange(kmax + 1) + (q - 1.5) * 0.2, v.values / N * 100, width=0.2, color=c, label=lab)
        ax.set_xticks(range(0, kmax + 1))
        ax.set_xlabel("受電を続ける独立系統の数(平常時の幹線から分かれた島・負荷 10 MW 以上)"); ax.set_ylabel("サンプルの割合 [%]"); ax.grid(alpha=0.3); ax.legend(fontsize=9)
        ax.set_title("独立系統の数の分布", fontsize=12)
        # 表
        md += [f"## {ISL_J[isl]}(N={N}・需要 {L/1e3:,.1f} GW)", "", "| 時刻 | 受電率(平均) | 受電率 10% 点 | UFLS | 周波数崩壊 | 孤立 | 設備損傷 | 独立系統の数 平均 / 90% 点 / 最大 | 100 MW 以上 平均 / 最大 | 1 GW 超の崩壊が起きた割合 | 最低周波数の 10% 点 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in sm.iterrows():
            if r.t_s in (10, 30, 60, 90, 120, 180, 300, 600, 1800, 3600, 7200, 10800):
                lab = f"{int(r.t_s)} 秒" if r.t_s < 60 else (f"{r.t_s/60:g} 分" if r.t_s < 3600 else f"{r.t_s/3600:g} 時間")
                md.append(f"| {lab} | {r.energized_mw/L:.1%} | {r.energized_p10/L:.1%} | {r.shed_mw/1e3:.2f} GW | {r.collapsed_mw/1e3:.2f} GW | {r.isolated_mw/1e3:.2f} GW | {r.site_out_mw/1e3:.2f} GW | {r.n_islands_mean:.2f} / {r.n_islands_p90:.0f} / {r.n_islands_max:.0f} | {r.n_100mw_mean:.2f} / {r.n_100mw_max:.0f} | {r.p_collapse_any:.0%} | {r.f_min_p10:.2f} Hz |")
        v = ds[ds.t_s == 600]
        md += ["", f"- 10 分後に独立系統が 2 個以上: {float((v.n_islands >= 2).mean()):.0%}、3 個以上: {float((v.n_islands >= 3).mean()):.0%}、100 MW 以上の島が 2 個以上: {float((v.n_islands_100mw >= 2).mean()):.0%}", ""]
    fig.tight_layout(); fig.savefig(os.path.join(out, "dynamic_summary.png"), dpi=130)
    # 五地域の停電軒数: 静的 run_v1 と動的 run_v2 の比較
    tg = yaml.safe_load(open(os.path.join(NANKAI, "config", "calibration_targets.yaml"), encoding="utf-8"))["naikakufu_2025"]["outage_households"]["①東海_基本"]
    nk = {t: sum(tg[r][i] for r in REG) for i, t in enumerate((0, 1, 4, 7))}
    cols = [f"phys_t{t:g}" for t in (0, 1, 4, 7)]
    a = five_region_customers(v1, cols); b = five_region_customers(dyn, cols)
    dyn_cols = ["dyn_energized_t60s", "dyn_energized_t600s", "dyn_energized_t3600s", "dyn_energized_t10800s"]
    c = five_region_customers(dyn, dyn_cols)
    md += ["## 五地域の停電軒数(物理停電)", "", f"| 時点 | 静的 {os.path.basename(os.path.normpath(v1))} | 動的 {os.path.basename(os.path.normpath(dyn))} | 内閣府 2025 基本 |", "|---|---|---|---|"]
    for t, col in zip((0, 1, 4, 7), cols):
        md.append(f"| {t} 日後 | {a[col]/1e4:,.0f} 万軒 | {b[col]/1e4:,.0f} 万軒 | {nk[t]/1e4:,.0f} 万軒 |")
    md += ["", "動的カスケードの直後の推移(五地域・受電していない需要家。t=0 の `phys_t0` は損傷と津波をすべて一度に入れた値なので、秒・分単位の値とは定義が違う)", "",
           "| 地震から | 停電軒数 |", "|---|---|"]
    for col, lab in zip(dyn_cols, ("1 分", "10 分", "1 時間", "3 時間")):
        md.append(f"| {lab} | {c[col]/1e4:,.0f} 万軒 |")
    runs = [("既定(縮約網・主幹系統で過負荷リレー)", dyn)] + [tuple(x.split("=", 1)) for x in extra]
    if len(runs) > 1:
        md += [""] + sensitivity_table(runs)
    open(os.path.join(out, "dynamic_summary.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    json.dump({"five_region_phys_v1": a, "five_region_phys_v2": b, "five_region_dyn": c, "naikakufu_2025": nk}, open(os.path.join(out, "dynamic_summary.json"), "w"), ensure_ascii=False, indent=1)
    print("\n".join(md))


if __name__ == "__main__":
    main(*sys.argv[1:])
