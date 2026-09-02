#!/usr/bin/env python3
"""感度行列による潮流の高速化と、その精度の代償を実測する。

  Q1 実装は正しいか  — PTDF·P が DC 解の枝潮流を機械精度で再現するか
  Q2 どれだけ速いか  — 24時間分の断面を AC / DC / PTDF で解いて実時間を比較
  Q3 精度の代償は    — PTDF(線形DC)の枝潮流を AC 解と突き合わせ、誤差を定量化
  Q4 N-1 はどうか    — LODF 一発評価 vs 枝を落として解き直す方式の一致度と速度

**基準は本番と同じ AC 解**にする。PTDF は連結・単一 slack を要するので行列自体は
最大連結成分から作るが、その成分を slack 1 枚で解こうとすると east/west は
どの解法でも発散する（本番は成分ごとの合成 slack で解いている）。そこで

  ・時間の基準  = 本番と同じ全島ネットを解く実時間
  ・精度の基準  = その AC 解のバス注入と枝潮流

とし、PTDF には AC 解の注入を与えて枝潮流を予測させ、AC 解と突き合わせる。
これで「線形化でどれだけずれるか」だけを取り出せる。

usage: python3 scripts/sensitivity/benchmark_sensitivity.py [--islands hokkaido ...]
出力: docs/reports/sensitivity_bench_<date>.json
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
os.chdir(ROOT)   # config/*.yaml は repo ルート相対で読まれる

import networkx as nx
import numpy as np
import pandapower as pp
from src.utils.pandapower_compat import select_subnet as pp_select_subnet
import pandapower.topology as top
from pandapower.pypower.idx_brch import F_BUS, PF, T_BUS

from scripts.run_full_powerflow_from_db import (
    GEN_ATTACH_DEFAULT, attach_default_for, GEN_ZONE_BY_OPERATOR, ISLAND_FREQ, add_per_component_slacks, allocate_loads,
    attach_generators,
    balance_by_zone, build_island_net, load_demand_config, solve_island,
)

REPORTS = ROOT / "docs" / "reports"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"

# 24時間の代表的な日負荷曲線（断面ごとに全負荷を一様スケール）
LOAD_PROFILE = np.array([
    0.78, 0.74, 0.72, 0.71, 0.72, 0.76, 0.83, 0.90, 0.95, 0.98, 1.00, 0.99,
    0.94, 0.97, 1.00, 0.99, 0.96, 0.94, 0.95, 0.97, 0.95, 0.90, 0.85, 0.81,
])


def production_net(island: str, nodes, edges, cfg, pref_gwh):
    """本番（run_full_powerflow_from_db）と同一手順で島ネットを組む。"""
    net, bus_of, _ = build_island_net(island, nodes, edges, ISLAND_FREQ[island], {})
    attach_generators(net, bus_of, nodes, island, attach_mode=attach_default_for(island))
    allocate_loads(net, cfg, pref_gwh=pref_gwh)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    add_per_component_slacks(net)
    balance_by_zone(net, cfg, use_zone_src=GEN_ZONE_BY_OPERATOR)
    return net


def main_component_subnet(net):
    """最大連結成分を切り出し、PTDF の参照バスとして slack を 1 枚だけ残す。"""
    g = top.create_nxgraph(net, respect_switches=False)
    main = sorted(max(nx.connected_components(g), key=len))
    sub = pp_select_subnet(net, main, keep_everything_else=True)
    if len(sub.ext_grid) > 1:
        sub.ext_grid = sub.ext_grid.iloc[:1]
    elif len(sub.ext_grid) == 0:
        pp.create_ext_grid(sub, bus=int(sub.bus.index[0]), vm_pu=1.0, name="ptdf_ref")
    if len(sub.gen):
        sub.gen["slack"] = False
    return sub, main


def run(island: str, nodes, edges, cfg, pref_gwh, n_outage: int, n_snap: int = 24) -> dict:
    from pandapower.pypower.makePTDF import makePTDF
    from pandapower.pypower.makeLODF import makeLODF

    net = production_net(island, nodes, edges, cfg, pref_gwh)
    sub, main_buses = main_component_subnet(net)
    r = {"island": island, "n_bus_full": int(len(net.bus)), "n_bus": int(len(sub.bus)),
         "main_bus_share": round(len(sub.bus) / len(net.bus), 4)}

    # ── 感度行列を主成分から構築（1回だけ払う前処理コスト） ──────────
    pp.rundcpp(sub)
    ppc = sub._ppc
    ref = int(sub._pd2ppc_lookups["bus"][int(sub.ext_grid.bus.iloc[0])])
    t0 = time.perf_counter()
    ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"], slack=ref)
    r["sec_build_ptdf"] = round(time.perf_counter() - t0, 2)
    r["n_branch"] = int(ptdf.shape[0])
    r["ptdf_mb"] = round(ptdf.nbytes / 1e6, 1)

    # Q1 実装検証: PTDF·P が主成分の DC 解を再現するか
    from pandapower.pypower.idx_bus import PD
    from pandapower.pypower.idx_gen import GEN_BUS, PG
    pinj = -ppc["bus"][:, PD].astype(float).copy()
    for gg in ppc["gen"]:
        pinj[int(gg[GEN_BUS].real)] += float(gg[PG].real)
    e = np.abs(ptdf @ pinj - ppc["branch"][:, PF].real.astype(float))
    r["validation"] = {"max_abs_mw": float(e.max()), "mean_abs_mw": float(e.mean())}

    # ── 対応表: 主成分 ppc の バス行/枝行 ↔ 全島ネットの要素ラベル ──
    bus_ppc_of_label = sub._pd2ppc_lookups["bus"]
    ppc_row_to_label = {}
    for lbl in sub.bus.index:
        ppc_row_to_label.setdefault(int(bus_ppc_of_label[int(lbl)]), int(lbl))
    lookups = sub._pd2ppc_lookups["branch"]
    branch_elem = []                      # ppc枝行 -> (テーブル名, 要素ラベル)
    for k in range(r["n_branch"]):
        hit = (None, None)
        for tbl, (s, en) in lookups.items():
            if s <= k < en:
                hit = (tbl, int(getattr(sub, tbl).index[k - s]))
                break
        branch_elem.append(hit)

    # ── Q2/Q3 24断面 ────────────────────────────────────────────
    base_p = net.load["p_mw"].to_numpy().copy()
    base_q = net.load["q_mvar"].to_numpy().copy()
    t_ac = t_dc = t_pt = 0.0
    n_ok = 0
    errs, rels, acflows = [], [], []

    # 大きい島は本番ACのはしごが1断面あたり数十秒かかるため断面を間引ける
    profile = LOAD_PROFILE[:: max(1, len(LOAD_PROFILE) // max(1, n_snap))][:n_snap]
    for s in profile:
        net.load["p_mw"] = base_p * s
        net.load["q_mvar"] = base_q * s

        t0 = time.perf_counter()
        pp.rundcpp(net)
        t_dc += time.perf_counter() - t0

        # AC は本番と同じ solve_island（角度しきい値の prune はしご＋給電率ガード）を通す。
        # 素の runpp では east/west が収束しない = 本番の収束はこの手順込みで成立している。
        t0 = time.perf_counter()
        _, _, net_ac, ac = solve_island(net, max_ac_buses=10**9)
        t_ac += time.perf_counter() - t0
        if not ac.get("converged"):
            continue
        n_ok += 1
        r.setdefault("ac_served_frac", []).append(ac.get("served_frac"))

        # AC 解の注入を主成分の ppc 順に並べ、PTDF に食わせる
        inj = np.zeros(len(ppc["bus"]))
        resb = net_ac.res_bus["p_mw"]
        for row, lbl in ppc_row_to_label.items():
            if lbl in resb.index:
                v = resb.at[lbl]
                inj[row] = -float(v) if np.isfinite(v) else 0.0
        t0 = time.perf_counter()
        f_p = ptdf @ inj                            # ← 反復なし
        t_pt += time.perf_counter() - t0

        # AC の枝潮流を同じ ppc 枝順に並べる（prune で落ちた枝は NaN=比較から除外）
        f_a = np.full(r["n_branch"], np.nan)
        for k, (tbl, eid) in enumerate(branch_elem):
            res = net_ac.res_line if tbl == "line" else (net_ac.res_trafo if tbl == "trafo" else None)
            col = "p_from_mw" if tbl == "line" else "p_hv_mw"
            if res is not None and eid in res.index:
                f_a[k] = float(res.at[eid, col])
        m = np.isfinite(f_a)
        r["n_branch_compared"] = int(m.sum())
        d = np.abs(f_p[m] - f_a[m])
        errs.append(d)
        rels.append(d / np.maximum(np.abs(f_a[m]), 1.0))
        acflows.append(np.abs(f_a[m]))

    net.load["p_mw"] = base_p
    net.load["q_mvar"] = base_q

    n = len(profile)
    r["timing"] = {
        "n_snapshots": n, "n_ac_converged": n_ok,
        "ac_per_snapshot_ms": round(t_ac / n * 1e3, 1),
        "dc_per_snapshot_ms": round(t_dc / n * 1e3, 1),
        "ptdf_per_snapshot_ms": round(t_pt / n * 1e3, 4) if t_pt else None,
        "speedup_vs_ac": round(t_ac / t_pt, 1) if t_pt else None,
        "speedup_vs_dc": round(t_dc / t_pt, 1) if t_pt else None,
        "breakeven_snapshots": round(r["sec_build_ptdf"] / (t_ac / n), 1) if t_ac else None,
    }
    if r.get("ac_served_frac"):
        sf = [x for x in r["ac_served_frac"] if x is not None]
        r["ac_served_frac"] = round(float(np.mean(sf)), 4) if sf else None
    if errs:
        E, R, A = np.concatenate(errs), np.concatenate(rels), np.concatenate(acflows)
        big = A >= np.percentile(A, 90)
        r["accuracy"] = {
            "mae_mw": round(float(E.mean()), 3), "p50_mw": round(float(np.percentile(E, 50)), 3),
            "p95_mw": round(float(np.percentile(E, 95)), 2), "max_mw": round(float(E.max()), 1),
            "p95_rel": round(float(np.percentile(R, 95)), 4),
            "mean_ac_flow_mw": round(float(A.mean()), 1),
            "p95_rel_top10pct": round(float(np.percentile(
                E[big] / np.maximum(A[big], 1.0), 95)), 4),
        }

    # ── Q4 N-1（DC の枠内で LODF が厳密かを確認） ───────────────────
    t0 = time.perf_counter()
    lodf = makeLODF(ppc["branch"], ptdf)
    r["sec_build_lodf"] = round(time.perf_counter() - t0, 2)

    # 橋では LODF が定義できない。判定は LODF の分母そのもの（自己感度が 1）。
    # makeLODF は inf を返さず対角を均すので isfinite では検出できない。
    fb = ppc["branch"][:, F_BUS].real.astype(int)
    tb = ppc["branch"][:, T_BUS].real.astype(int)
    self_sens = ptdf[np.arange(len(fb)), fb] - ptdf[np.arange(len(tb)), tb]
    bridge = np.abs(1.0 - self_sens) < 1e-9
    r["n_bridge_branches"] = int(bridge.sum())
    r["bridge_share"] = round(float(bridge.mean()), 4)

    pp.rundcpp(sub)
    f0 = sub._ppc["branch"][:, PF].real.astype(float)
    cand = np.where(~bridge & (np.abs(f0) > 1.0))[0]
    rng = np.random.default_rng(0)
    sample = rng.choice(cand, size=min(n_outage, len(cand)), replace=False) if len(cand) else []

    t_lodf = t_re = 0.0
    diffs = []
    n_used = 0
    for k in sample:
        tbl, eid = branch_elem[int(k)]
        if tbl is None:
            continue
        t0 = time.perf_counter()
        f_l = f0 + lodf[:, k] * f0[k]
        t_lodf += time.perf_counter() - t0

        tab = getattr(sub, tbl)
        t0 = time.perf_counter()
        tab.loc[eid, "in_service"] = False
        try:
            pp.rundcpp(sub)
            f_re = sub._ppc["branch"][:, PF].real.astype(float)
        finally:
            tab.loc[eid, "in_service"] = True
        t_re += time.perf_counter() - t0

        msk = np.ones(len(f0), bool); msk[k] = False
        diffs.append(np.abs(f_l[msk] - f_re[msk]))
        n_used += 1

    if diffs:
        D = np.concatenate(diffs)
        r["n1"] = {"n_sampled": n_used, "lodf_total_ms": round(t_lodf * 1e3, 3),
                   "resolve_total_s": round(t_re, 2),
                   "speedup": round(t_re / t_lodf, 1) if t_lodf else None,
                   "max_abs_mw": round(float(D.max()), 6)}
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=None)
    ap.add_argument("--n-outage", type=int, default=40)
    ap.add_argument("--snapshots", type=int, default=24, help="評価する断面数(24時間から間引く)")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()

    d = json.load(open(BUILT))
    nodes, edges = d["nodes"], d["edges"]
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    out = []
    for isl in (args.islands or list(ISLAND_FREQ.keys())):
        r = run(isl, nodes, edges, cfg, pref_gwh, args.n_outage, args.snapshots)
        out.append(r)
        t, a = r["timing"], r.get("accuracy", {})
        print(f"[{isl:9s}] 主成分 {r['n_bus']:5d}バス {r['n_branch']:5d}枝 | 構築 {r['sec_build_ptdf']:5.2f}s | "
              f"AC {t['ac_per_snapshot_ms']:7.1f}ms → PTDF {t['ptdf_per_snapshot_ms'] or float('nan'):7.4f}ms (×{t['speedup_vs_ac']}) "
              f"| AC収束 {t['n_ac_converged']}/{t['n_snapshots']} | 誤差 中央{a.get('p50_mw','—')} p95 {a.get('p95_mw','—')}MW")
        if r.get("n1"):
            n1 = r["n1"]
            print(f"{'':11s} N-1 {n1['n_sampled']}本: LODF {n1['lodf_total_ms']}ms vs 解き直し {n1['resolve_total_s']}s "
                  f"(×{n1['speedup']}) 最大不一致 {n1['max_abs_mw']}MW | 橋 {r['n_bridge_branches']}({r['bridge_share']:.0%})")

    json.dump({"date": date, "profile": LOAD_PROFILE.tolist(), "islands": out},
              open(REPORTS / f"sensitivity_bench_{date}.json", "w"), ensure_ascii=False, indent=1)
    print(f"→ docs/reports/sensitivity_bench_{date}.json")


if __name__ == "__main__":
    main()
