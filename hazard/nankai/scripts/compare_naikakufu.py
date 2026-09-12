#!/usr/bin/env python3
"""内閣府想定(2013/2025 基本ケース・東海ケース)と本解析の五地域停電軒数を比較する(west+east 合算)。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/compare_naikakufu.py hazard/nankai/output/run_v0_jshis
出力: <run>/naikakufu_compare.png, naikakufu_compare.md, naikakufu_compare.json
"""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd, yaml
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from nankai.grid import GridCase
from nankai.aggregate import bus_prefecture, naikakufu_region_of, customers_per_mw
from nankai import maps  # フォント設定

NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REG = ["tokai", "kinki", "sanyo", "shikoku", "kyushu"]; LAB = {"tokai": "東海", "kinki": "近畿", "sanyo": "山陽", "shikoku": "四国", "kyushu": "九州(大分宮崎)"}
TS = [0, 1, 4, 7]


def main(run_dir: str):
    tg = yaml.safe_load(open(os.path.join(NANKAI, "config", "calibration_targets.yaml"), encoding="utf-8"))
    t13 = tg["naikakufu_2013"]["outage_households"]["①東海_基本"]; t25 = tg["naikakufu_2025"]["outage_households"]["①東海_基本"]
    t13l = tg["naikakufu_2013"]["outage_households"]["①東海_陸側"]; t25l = tg["naikakufu_2025"]["outage_households"]["①東海_陸側"]
    ours_p = {(r, t): 0.0 for r in REG for t in TS}; ours_t = dict(ours_p); cust_reg = {r: 0.0 for r in REG}
    for isl in ("west", "east"):
        bp = os.path.join(run_dir, isl, "bus_results.parquet")
        if not os.path.exists(bp):
            continue
        bus = pd.read_parquet(bp); case = GridCase.load(isl)
        reg = naikakufu_region_of(bus_prefecture(case))
        cpm = customers_per_mw(bus.groupby("zone").pd_mw.sum().to_dict()); cust = bus.pd_mw.to_numpy() * bus.zone.map(cpm).fillna(0).to_numpy()
        for r in REG:
            m = reg == r; cust_reg[r] += float(cust[m].sum())
            for t in TS:
                ours_p[(r, t)] += float(((1 - bus[f"phys_t{t}"].to_numpy()[m]) * cust[m]).sum())
                ours_t[(r, t)] += float(((1 - bus[f"served_t{t}"].to_numpy()[m]) * cust[m]).sum())
    # 図
    fig, axes = plt.subplots(1, 4, figsize=(14, 3.8), dpi=120, sharey=True); w = 0.16
    for ai, t in enumerate(TS):
        ax = axes[ai]; xi = np.arange(len(REG))
        series = [("内閣府2013 基本", [t13[r][ai] for r in REG], "#bbb"), ("内閣府2025 基本", [t25[r][ai] for r in REG], "#777"),
                  ("内閣府2025 陸側", [t25l[r][ai] for r in REG], "#333"),
                  ("本解析 物理停電", [ours_p[(r, t)] for r in REG], "#d62728"), ("本解析 供給力不足込み", [ours_t[(r, t)] for r in REG], "#ff9896")]
        for si, (nm, vals, c) in enumerate(series):
            ax.bar(xi + (si - 2) * w, np.array(vals) / 1e4, w, color=c, label=nm)
        ax.set_xticks(xi); ax.set_xticklabels([LAB[r] for r in REG], fontsize=8, rotation=20)
        ax.set_title("直後" if t == 0 else f"{t}日後", fontsize=10); ax.grid(axis="y", alpha=0.3); ax.set_yscale("symlog", linthresh=10)
    axes[0].set_ylabel("停電軒数 [万軒]"); axes[0].legend(fontsize=7, loc="upper right")
    fig.suptitle("内閣府想定(東海ケース)との比較 — 五地域の停電軒数(本解析: west+east 合算・需要家数換算)", fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(run_dir, "naikakufu_compare.png")); plt.close(fig)
    # 表
    lines = ["| 地域 | 時点 | 内閣府2013基本 | 内閣府2025基本 | 内閣府2025陸側 | 本解析 物理 | 本解析 不足込み | 本解析の需要家数 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    js = {}
    for r in REG + ["five"]:
        for ai, t in enumerate(TS):
            if r == "five":
                v13 = sum(t13[x][ai] for x in REG); v25 = sum(t25[x][ai] for x in REG); v25l = sum(t25l[x][ai] for x in REG)
                op = sum(ours_p[(x, t)] for x in REG); ot = sum(ours_t[(x, t)] for x in REG); cr = sum(cust_reg.values()); nm = "五地域計"
            else:
                v13, v25, v25l, op, ot, cr, nm = t13[r][ai], t25[r][ai], t25l[r][ai], ours_p[(r, t)], ours_t[(r, t)], cust_reg[r], LAB[r]
            lines.append(f"| {nm} | {'直後' if t == 0 else str(t)+'日後'} | {v13/1e4:,.0f}万 | {v25/1e4:,.0f}万 | {v25l/1e4:,.0f}万 | {op/1e4:,.0f}万 | {ot/1e4:,.0f}万 | {cr/1e4:,.0f}万 |")
            js[f"{r}_t{t}"] = {"n2013_basic": v13, "n2025_basic": v25, "n2025_landward": v25l, "ours_phys": round(op), "ours_total": round(ot), "customers": round(cr)}
    open(os.path.join(run_dir, "naikakufu_compare.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    json.dump(js, open(os.path.join(run_dir, "naikakufu_compare.json"), "w"), ensure_ascii=False, indent=1)
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1])
