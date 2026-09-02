#!/usr/bin/env python3
"""感度行列で「どこに何MW繋げられるか」を全地点まとめて出す。

系統に電源を繋ぐとき効くのは、繋いだ地点そのものより**どの送電線が先に埋まるか**。
PTDF はまさにその関係なので、ある地点に P MW 注入したときの枝 j の潮流変化は
PTDF[j,b]·P。よって枝 j が限界に達するまでの注入量は 空き容量_j / |PTDF[j,b]| で、
その最小値が**その地点の接続可能量**になる。

要点は、これが行列の列ごとの割り算だけで済むこと。全バスぶんを一度に計算できる。
同じ答えを潮流の解き直しで得ようとすると、地点数 × 断面数だけ反復解法を回すことになり、
西日本（7,087バス・AC 1断面 42秒）では単純計算で数日かかる。

usage: python3 scripts/sensitivity/hosting_capacity.py [--islands west ...]
出力: docs/reports/hosting_capacity_<date>.{md,json} と地図
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandapower as pp
from pandapower.pypower.idx_brch import PF
from pandapower.pypower.makePTDF import makePTDF

from benchmark_sensitivity import main_component_subnet, production_net
from scripts.run_full_powerflow_from_db import ISLAND_FREQ, load_demand_config

REPORTS = ROOT / "docs" / "reports"
FIGS = ROOT / "docs" / "assets" / "sensitivity"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"

plt.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]
SENS_FLOOR = 1e-3      # これ未満の感度は「その枝には効かない」として制約から外す


def branch_capacity_mw(sub, n_branch: int) -> np.ndarray:
    """ppc 枝順の熱容量 [MW]。線路は √3·V·I、変圧器は銘板容量。"""
    cap = np.full(n_branch, np.inf)
    lk = sub._pd2ppc_lookups["branch"]
    if "line" in lk:
        s, _ = lk["line"]
        kv = sub.bus.loc[sub.line["from_bus"].to_numpy(), "vn_kv"].to_numpy()
        mva = np.sqrt(3.0) * kv * sub.line["max_i_ka"].to_numpy() * sub.line["parallel"].to_numpy()
        cap[s: s + len(sub.line)] = mva
    if "trafo" in lk and len(sub.trafo):
        s, _ = lk["trafo"]
        cap[s: s + len(sub.trafo)] = sub.trafo["sn_mva"].to_numpy() * sub.trafo["parallel"].to_numpy()
    return cap


def run(island: str, nodes, edges, cfg, pref_gwh, min_kv: float = 154.0,
        cap_factor: float = 1.0) -> dict:
    # 座標が要るので bus_of（built ノード索引 → バス）を自前で受け取る
    from src.powerflow.pipeline import add_reactive_compensation
    from scripts.run_full_powerflow_from_db import (
        GEN_ATTACH_DEFAULT, attach_default_for, GEN_ZONE_BY_OPERATOR, add_per_component_slacks, allocate_loads,
        attach_generators, balance_by_zone,
        build_island_net)
    net, bus_of, _ = build_island_net(island, nodes, edges, ISLAND_FREQ[island], {})
    attach_generators(net, bus_of, nodes, island, attach_mode=attach_default_for(island))
    allocate_loads(net, cfg, pref_gwh=pref_gwh)
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    add_per_component_slacks(net)
    balance_by_zone(net, cfg, use_zone_src=GEN_ZONE_BY_OPERATOR)
    sub, _ = main_component_subnet(net)
    pp.rundcpp(sub)
    ppc = sub._ppc
    ref = int(sub._pd2ppc_lookups["bus"][int(sub.ext_grid.bus.iloc[0])])

    t0 = time.perf_counter()
    ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"], slack=ref)
    sec_ptdf = time.perf_counter() - t0

    f0 = np.abs(ppc["branch"][:, PF].real.astype(float))
    cap = branch_capacity_mw(sub, ptdf.shape[0]) * cap_factor
    # cap_factor: 理論値(√3·V·I)を公表運用容量に寄せる較正係数。
    # 関西送配電の公表値との比較では全電圧階級で 0.47〜0.54（約 0.5）だった
    # — docs/reports/line_capacity_calibration_*.md。既定 1.0（未適用）。
    head = np.maximum(cap - f0, 0.0)                    # 各枝の空き容量 [MW]

    # 制約に取る枝を電圧で絞る。基幹系への接続を評価する以上、下位系(66kV等)は
    # 対象外にするのが筋。本モデルでも過負荷は 66kV に集中しており(east は 4,471本中
    # 520本)、そこを制約に入れると全地点が塞がって screening にならない。
    from pandapower.pypower.idx_brch import F_BUS, T_BUS
    from pandapower.pypower.idx_bus import BASE_KV
    kvb = ppc["bus"][:, BASE_KV].real.astype(float)
    kv_br = np.maximum(kvb[ppc["branch"][:, F_BUS].real.astype(int)],
                       kvb[ppc["branch"][:, T_BUS].real.astype(int)])
    in_scope = kv_br >= min_kv - 0.5
    head = np.where(in_scope, head, np.inf)             # 対象外の枝は制約にしない

    # ここが本体。全バスの接続可能量を一度に出す（列ごとの min）。
    # 行列が大きいので列をチャンクに切ってメモリを抑える（計算量は同じ）。
    t0 = time.perf_counter()
    nb = ptdf.shape[1]
    hc = np.full(nb, np.nan)
    binding = np.full(nb, -1, dtype=int)
    for c0 in range(0, nb, 512):
        c1 = min(c0 + 512, nb)
        S = np.abs(ptdf[:, c0:c1])
        R = np.where(S < SENS_FLOOR, np.inf, head[:, None] / np.maximum(S, 1e-300))
        hc[c0:c1] = R.min(axis=0)
        binding[c0:c1] = R.argmin(axis=0)
    hc[~np.isfinite(hc)] = np.nan     # どの枝にも効かない地点は算出対象外

    # 主指標: 1GW 注入したときに最も混む枝の「定格に対する増分」[%/GW]。
    # 接続可能量は基準ケースに1本でも過負荷枝があると全地点 0 になり使えないが、
    # この指標は基準の実行可能性に依らず常に計算でき、地点の優劣を比べられる。
    capf = np.where(np.isfinite(cap) & in_scope, cap, np.inf)
    stress = np.zeros(nb)
    for c0 in range(0, nb, 512):
        c1 = min(c0 + 512, nb)
        stress[c0:c1] = (np.abs(ptdf[:, c0:c1]) * 1000.0 / capf[:, None]).max(axis=0) * 100.0
    sec_hc = time.perf_counter() - t0

    # バス → 地理座標（built のノードに戻す）
    lbl2ppc = sub._pd2ppc_lookups["bus"]
    ppc2lbl = {}
    for lbl in sub.bus.index:
        ppc2lbl.setdefault(int(lbl2ppc[int(lbl)]), int(lbl))
    lat = np.full(len(hc), np.nan); lon = np.full(len(hc), np.nan)
    kv = ppc["bus"][:, 9].real.astype(float)
    bus2node = {}
    for ni, b in (bus_of.items() if isinstance(bus_of, dict) else enumerate(bus_of)):
        if b is not None and b >= 0:
            bus2node.setdefault(int(b), int(ni))
    for row, lbl in ppc2lbl.items():
        ni = bus2node.get(int(lbl))
        if ni is not None:
            lat[row] = nodes[ni]["lat"]; lon[row] = nodes[ni]["lon"]

    ok = np.isfinite(hc) & (hc > 0)
    n_over = int(((f0 > cap) & in_scope).sum())
    n_cap_known = int(np.isfinite(cap).sum())
    return {
        "island": island, "n_bus": int(len(hc)), "n_branch": int(ptdf.shape[0]),
        "sec_build_ptdf": round(sec_ptdf, 2),
        "sec_hosting_capacity_all_buses": round(sec_hc, 4),
        "n_branch_over_capacity": n_over, "n_branch_capacity_known": n_cap_known,
        "capacity_factor": cap_factor,
        "min_kv": min_kv, "n_branch_in_scope": int(in_scope.sum()),
        "n_bus_computable": int(ok.sum()),
        "equivalent_ac_solves": int(len(hc)),
        "hc": hc, "stress": stress, "lat": lat, "lon": lon, "kv": kv,
        "binding": binding, "ok": ok,
        "stress_stats": {
            "median_pct_per_gw": float(np.nanmedian(stress[stress > 0])),
            "p10_pct_per_gw": float(np.nanpercentile(stress[stress > 0], 10)),
            "p90_pct_per_gw": float(np.nanpercentile(stress[stress > 0], 90)),
        },
        "stats": {
            "median_mw": float(np.nanmedian(hc[ok])) if ok.any() else None,
            "p10_mw": float(np.nanpercentile(hc[ok], 10)) if ok.any() else None,
            "p90_mw": float(np.nanpercentile(hc[ok], 90)) if ok.any() else None,
            "n_below_100mw": int((hc[ok] < 100).sum()),
            "n_above_1gw": int((hc[ok] > 1000).sum()),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=None)
    ap.add_argument("--capacity-factor", type=float, default=1.0,
                    help="線路容量に掛ける較正係数(公表値との比較では約0.5)。既定1.0=未適用")
    ap.add_argument("--min-kv", type=float, default=154.0,
                    help="制約に取る枝の下限電圧(既定154kV。下位系は対象外)")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()
    FIGS.mkdir(parents=True, exist_ok=True)

    d = json.load(open(BUILT))
    nodes, edges = d["nodes"], d["edges"]
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    res = [run(i, nodes, edges, cfg, pref_gwh, args.min_kv, args.capacity_factor) for i in (args.islands or list(ISLAND_FREQ.keys()))]
    # 制約対象の枝が無い島（沖縄は最高 132kV なので 154kV しきい値では対象外）は図から外す
    drawable = [r for r in res if r["n_branch_in_scope"] > 0 and np.isfinite(r["stress"]).any()]

    # ── 地図 ────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, len(drawable), figsize=(6.0 * len(drawable), 6.6), squeeze=False)
    for ax, r in zip(axes[0], drawable):
        m = np.isfinite(r["lat"]) & (r["stress"] > 0)
        # 色域は島ごとの分布に合わせる（絶対値でなく地点差を見せるのが目的）
        lo, hi = np.percentile(r["stress"][m], [5, 95])
        v = np.clip(r["stress"][m], lo, hi)
        order = np.argsort(-r["stress"][m])          # 混む地点を上に描く
        sc = ax.scatter(r["lon"][m][order], r["lat"][m][order], c=v[order],
                        s=6 + r["kv"][m][order] / 25,
                        cmap="RdYlGn_r", norm=matplotlib.colors.LogNorm(lo, hi), alpha=0.9,
                        linewidths=0)
        ax.set_title(f"{r['island']} — 1GW繋いだときの最悪混雑増分\n"
                     f"（{int(m.sum()):,}地点を {r['sec_hosting_capacity_all_buses']*1000:.0f} ミリ秒で算出）",
                     fontsize=11.5, fontweight="bold")
        ax.set_xlabel("経度"); ax.set_ylabel("緯度")
        ax.set_aspect(1.2); ax.grid(alpha=0.25)
        plt.colorbar(sc, ax=ax, fraction=0.04, label="定格に対する増分 [%/GW]（緑=余裕 / 赤=すぐ混む）")
    fig.tight_layout()
    out_png = FIGS / f"hosting_capacity_{date}.png"
    fig.savefig(out_png, dpi=125)

    # ── レポート ────────────────────────────────────────────────
    payload = [{k: v for k, v in r.items()
                if k not in ("hc", "stress", "lat", "lon", "kv", "binding", "ok")} for r in res]
    json.dump({"date": date, "sens_floor": SENS_FLOOR, "islands": payload},
              open(REPORTS / f"hosting_capacity_{date}.json", "w"), ensure_ascii=False, indent=1)

    L = [
        f"# 地点別の接続可能量 — 感度行列で一度に出す（{date}）",
        "",
        "系統に電源を繋ぐとき効くのは、繋ぐ地点そのものより**どの送電線が先に埋まるか**。",
        "PTDF はその関係そのものなので、地点 b に P MW 注入したときの枝 j の潮流変化は `PTDF[j,b]·P`。",
        "枝 j が熱容量に達するまでの注入量は `空き容量_j / |PTDF[j,b]|` で、**その最小値がその地点の接続可能量**になる。",
        "",
        "重要なのは、これが**行列の列ごとの割り算**だけで済むこと。全地点を一度に計算できる。",
        "",
        "| 島 | 地点数 | PTDF構築 | 全地点の算出 | 同じ答えを潮流の解き直しで得る場合 |",
        "|---|---:|---:|---:|---|",
    ]
    for r in res:
        # 解き直しでやるなら 1 地点 1 回の AC が要る（当日実測の AC 1断面時間を使う）
        ac_ms = {"hokkaido": 89.2, "east": 63828.6, "west": 42174.3, "okinawa": 36.9}[r["island"]]
        days = r["n_bus"] * ac_ms / 1000 / 86400
        L.append(f"| {r['island']} | {r['n_bus']:,} | {r['sec_build_ptdf']:.2f} s | "
                 f"**{r['sec_hosting_capacity_all_buses']*1000:.0f} ミリ秒** | "
                 f"{r['n_bus']:,} 回の AC 求解 ≈ **{days:.1f} 日** |")
    L += [
        "",
        "## 主指標 — 1GW 注入したときの最悪混雑の増分 [%/GW]",
        "",
        "接続可能量は基準ケースに 1 本でも過負荷枝があると全地点 0 になり、答えとして使えない",
        "（本モデルは実際そうなっている）。そこで**常に計算できる相対指標**を主軸に置く。",
        "値が小さいほど「繋いでも系統を追い込まない地点」。",
        "",
        "| 島 | 中央値 | 良い側10% | 悪い側10% |",
        "|---|---:|---:|---:|",
    ] + [
        f"| {r['island']} | {r['stress_stats']['median_pct_per_gw']:.1f} %/GW | "
        f"{r['stress_stats']['p10_pct_per_gw']:.1f} %/GW | "
        f"{r['stress_stats']['p90_pct_per_gw']:.1f} %/GW |" for r in res
    ] + [
        "",
        "## 参考 — 絶対値としての接続可能量",
        "",
        "| 島 | 中央値 | 下位10% | 上位10% | 100MW未満の地点 | 1GW超の地点 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    fmt = lambda v: f"{v:,.0f} MW" if v is not None else "—"
    for r in res:
        s = r["stats"]
        L.append(f"| {r['island']} | {fmt(s['median_mw'])} | {fmt(s['p10_mw'])} | "
                 f"{fmt(s['p90_mw'])} | {s['n_below_100mw']:,} | {s['n_above_1gw']:,} |")
    L += [
        "",
        "## 算出できた地点と、できなかった理由",
        "",
        "| 島 | 算出できた地点 | 制約対象の枝 | うち既に容量超過 |",
        "|---|---:|---:|---:|",
    ]
    for r in res:
        L.append(f"| {r['island']} | {r['n_bus_computable']:,} / {r['n_bus']:,} | "
                 f"{r['n_branch_in_scope']:,} / {r['n_branch']:,} ({r['min_kv']:.0f}kV以上) | "
                 f"{r['n_branch_over_capacity']:,} |")
    L += [
        "",
        "接続可能量が 0 になる地点は、**その地点が効く枝の中に既に熱容量を超えているものがある**ことを意味する。",
        "これは系統の実態というより、モデルの潮流と想定した熱容量（√3·V·I の理論値）が噛み合っていない",
        "箇所を炙り出したもの。容量の出典付き値への差し替えが次の課題になる。",
    ]
    L += [
        "",
        f"![接続可能量の地図](../assets/sensitivity/hosting_capacity_{date}.png)",
        "",
        "## 前提と限界",
        "",
        f"- 直流近似・熱容量のみ（電圧や安定度の制約は見ていない）。感度 {SENS_FLOOR} 未満の枝は制約から外した",
        "- 対象は各島の最大連結成分。孤立断片上の地点は算出対象外",
        "- 送電線の熱容量は `√3·V·I` の理論値で、実際の運用容量（`docs/reports/` の出典付き値）とは別物",
        "- **screening であって空き容量の確定値ではない**。候補地の絞り込みに使い、確定は AC と実データで",
        "",
        "---",
        "生成: `scripts/sensitivity/hosting_capacity.py`",
        "",
    ]
    (REPORTS / f"hosting_capacity_{date}.md").write_text("\n".join(L), encoding="utf-8")

    for r in res:
        s = r["stats"]
        ss = r["stress_stats"]
        print(f"[{r['island']:9s}] {r['n_bus']:,}地点を {r['sec_hosting_capacity_all_buses']*1000:.0f}ms | "
              f"混雑増分 中央値 {ss['median_pct_per_gw']:6.1f}%/GW "
              f"(良い側10% {ss['p10_pct_per_gw']:.1f} / 悪い側10% {ss['p90_pct_per_gw']:.1f}) | "
              f"制約対象 {r['n_branch_in_scope']:,}枝・既存過負荷 {r['n_branch_over_capacity']:,}")
    print(f"→ {out_png.relative_to(ROOT)}")
    print(f"→ docs/reports/hosting_capacity_{date}.md")


if __name__ == "__main__":
    main()
