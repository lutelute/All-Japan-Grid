#!/usr/bin/env python3
"""UC → 潮流 → AGC の運用チェーンを1コマンドで通す（論文実証・2026-08-29）.

3段:
  ① UC     — 全国24h MILP(fy2023r2)。オンライン機集合(→慣性)・基点(→調整余力)・
              最大オンライン機(→N-1外乱)が決まる
  ② 潮流   — 島ピーク時刻のUC断面を built正典ネットへ注入してDC断面検証
              (需給整合・slack・線ロード)。同じネットからエリア間連系の
              同期化係数 T_ab = SΣ1/x を**実抽出網から**測る
  ③ AGC    — IEEJ AGC30(GH1386)簡易版の三階層 GF/LFC/EDC 周波数応答。
              外乱2種:
                (a) 基準外乱 = 島需要の2%負荷ステップ(LFC性能の標準試験)
                (b) プラント脱落 = UC解の最大オンラインプラントのトリップ
                    (実プラント名・実MW)。UC発電機はプラント粒度のため
                    ユニットN-1の**上界**であり、小島では LFC領域を超える
                    → 簡易UFLS(典型3段)込みで評価し、その旨を帳簿に記す

②のAC正典結果は uc_to_pf_built.py(east AC実績 2026-07-04)にあり、本スクリプトの
DC断面はチェーンの需給整合チェックとして走らせる(モードは帳簿に記録)。

出力:
  docs/data/agc/agc_chain.json        — 全島の帳簿つき結果
  docs/assets/figs/fig_agc_national.png
  papers/figs/fig_agc.pdf             — ieee-openaccess 論文用

Usage:
  PYTHONPATH=. python scripts/run_agc_from_uc.py                # 4島すべて
  PYTHONPATH=. python scripts/run_agc_from_uc.py --islands east west
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
# 図は全て英語ラベル(論文用) — 日本語フォント指定はPDFバックエンドで
# グリフ名がASCII化できず落ちるため使わない
plt.rcParams["axes.unicode_minus"] = False

from scripts.run_full_powerflow_from_db import (  # noqa: E402
    BUILT, ISLAND_OF, add_per_component_slacks, allocate_loads,
    attach_generators, GEN_ATTACH_DEFAULT, build_island_net)
from src.powerflow.load_estimator import load_demand_config  # noqa: E402
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402
from src.dynamics.agc import (  # noqa: E402
    MultiAreaLFC, Disturbance, build_area_from_uc, tie_stiffness_from_net,
    largest_online_unit, remove_unit_from_area, S_BASE_MVA)

ISLAND_FREQ = {"hokkaido": 50.0, "east": 50.0, "west": 60.0, "okinawa": 60.0}
OUT_JSON = "docs/data/agc/agc_chain.json"


def run_island(island, scn, uc, built, cfg, pref_gwh, t_end):
    regions = sorted(r for r, (isl, _f) in ISLAND_OF.items() if isl == island)
    f0 = ISLAND_FREQ[island]
    net_dem = sum(np.asarray(scn.net_demand_r[r]) for r in regions)
    h = int(np.argmax(net_dem))
    print(f"\n== {island} ({'+'.join(regions)}) f0={f0}Hz ピーク時刻 t={h} "
          f"純需要 {net_dem[h]:,.0f} MW ==")
    rep = {"regions": regions, "f0_hz": f0, "peak_hour": h,
           "net_demand_mw": round(float(net_dem[h]), 1)}

    # ── ② 潮流: built正典ネットへUC断面を注入(DC断面) + T_ab 測定 ──
    t0 = time.monotonic()
    geom = {}
    base, bus_of, _ = build_island_net(island, built["nodes"], built["edges"],
                                       f0, geom)
    attach_generators(base, bus_of, built["nodes"], island,
                      attach_mode=GEN_ATTACH_DEFAULT)
    allocate_loads(base, cfg, pref_gwh=pref_gwh)
    add_per_component_slacks(base)
    tie = tie_stiffness_from_net(base, regions) if len(regions) > 1 else {}
    fuel_by_zone = {r: uc_snapshot(uc, scn.generators, h, region=r)
                    for r in regions}
    demand = {r: float(scn.net_demand_r[r][h]) for r in regions}
    import pandapower as pp
    net = copy.deepcopy(base)
    try:
        inject_dispatch_by_zone(net, fuel_by_zone, demand)
        pp.rundcpp(net)
        served = float(net.res_load.p_mw.sum())
        pre = float(net.load.loc[net.load.in_service, "p_mw"].sum())
        lmax = float(net.res_line.loading_percent.max()) \
            if len(net.res_line) else None
        rep["pf"] = {"mode": "dc", "served_mw": round(served, 1),
                     "load_mw": round(pre, 1),
                     "served_frac": round(served / max(pre, 1e-9), 4),
                     "line_loading_max_pct": round(lmax, 1) if lmax else None,
                     "note": "DC断面検証。AC正典は uc_to_pf_built.py "
                             "(east AC実績 2026-07-04) を参照"}
        print(f"  PF(dc): served {served:,.0f}/{pre:,.0f} MW "
              f"({served/max(pre,1e-9)*100:.1f}%)")
    except Exception as exc:  # noqa: BLE001
        rep["pf"] = {"mode": "dc", "error": str(exc)[:200]}
        print(f"  PF失敗(帳簿に記録): {exc}")
    rep["tie_pu_per_rad"] = {f"{a}-{b}": round(v, 1)
                             for (a, b), v in sorted(tie.items())}
    print(f"  ネット構築+PF {time.monotonic()-t0:.0f}s / "
          f"T_ab {len(tie)}ペア")

    # ── ③ AGC: 最大オンライン機トリップ ──
    areas = [build_area_from_uc(r, uc, scn.generators, h,
                                float(scn.net_demand_r[r][h]))
             for r in regions]
    big = largest_online_unit(uc, scn.generators, h, regions)
    if big is None:
        rep["agc"] = {"error": "オンライン機なし"}
        return rep
    gen, p_mw = big
    print(f"  N-1外乱: {gen.name} ({gen.region}, "
          f"{normfuel(gen)}, {p_mw:,.0f} MW online)")
    areas = [remove_unit_from_area(a, gen, p_mw) if a.name == gen.region
             else a for a in areas]
    # (a) 基準外乱: 島需要2%の負荷ステップ(外乱エリア=最大需要エリア)
    big_area = max(areas, key=lambda a: a.load_mw)
    step_mw = 0.02 * float(net_dem[h])
    areas_ref = [build_area_from_uc(r_, uc, scn.generators, h,
                                    float(scn.net_demand_r[r_][h]))
                 for r_ in regions]
    dist_ref = Disturbance(area=big_area.name, dp_mw=step_mw,
                           label="2% load step")
    out = {}
    for mode in ("off", "tbc"):
        model = MultiAreaLFC(f0, areas_ref, tie, mode=mode)
        r = model.simulate(dist_ref, t_end=t_end)
        out["ref_" + mode] = r
        print(f"  [2%step {mode:3s}] nadir {r.nadir_hz:+.3f} Hz / "
              f"restore {r.restore_s and round(r.restore_s) or '—'} s")
    # (b) プラント脱落(上界) + 簡易UFLS
    dist = Disturbance(area=gen.region, dp_mw=p_mw,
                       label=f"{gen.name} trip (plant-granularity)")
    model = MultiAreaLFC(f0, areas, tie, mode="tbc", ufls=True)
    r = model.simulate(dist, t_end=t_end)
    out["trip_tbc"] = r
    print(f"  [trip+UFLS] nadir {r.nadir_hz:+.3f} Hz / "
          f"RoCoF {r.rocof_hz_s:+.3f} Hz/s / "
          f"restore {r.restore_s and round(r.restore_s) or '—'} s")
    m_tot = sum(a.M for a in areas)
    rep["agc"] = {
        "disturbance": {"unit": gen.name, "region": gen.region,
                        "fuel": normfuel(gen), "p_mw": round(p_mw, 1)},
        "inertia_gws": round(m_tot * S_BASE_MVA / 2000.0, 1),  # ΣH·S [GW·s]
        "areas": {a.name: {"M_pu_s": round(a.M, 1),
                           "beta_pu": round(a.beta, 1),
                           "load_mw": round(a.load_mw, 1)} for a in areas},
        "ref_2pct_step": {
            "dp_mw": round(step_mw, 1), "area": big_area.name,
            "nadir_primary_hz": round(out["ref_off"].nadir_hz, 4),
            "qss_primary_hz": round(out["ref_off"].qss_hz, 4),
            "nadir_lfc_hz": round(out["ref_tbc"].nadir_hz, 4),
            "restore_s": out["ref_tbc"].restore_s
            and round(out["ref_tbc"].restore_s, 1),
        },
        "plant_trip_upper_bound": {
            "note": "UC発電機はプラント粒度 — ユニットN-1の上界。簡易UFLS込み",
            "rocof_hz_s": round(out["trip_tbc"].rocof_hz_s, 4),
            "nadir_hz": round(out["trip_tbc"].nadir_hz, 4),
            "restore_s": out["trip_tbc"].restore_s
            and round(out["trip_tbc"].restore_s, 1),
        },
        "ledger": out["trip_tbc"].ledger,
    }
    rep["_traces"] = out          # 図生成用(JSON化前に落とす)
    return rep


def normfuel(g):
    from src.uc.pf_injection import normalize_fuel
    return normalize_fuel(str(getattr(g, "fuel_type", "") or ""))


def make_figures(reports):
    """English-labelled 3-panel figure (paper) — (a) east 2% load step
    primary vs LFC+EDC, (b) largest-plant trip per island (+UFLS),
    (c) disturbed-area pickup under TBC."""
    have = {k: v for k, v in reports.items() if "_traces" in v}
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6))
    ax = axes[0]
    if "east" in have:
        tr = have["east"]["_traces"]
        for a, y in tr["ref_off"].df_hz.items():
            ax.plot(tr["ref_off"].t, y, "--", lw=1.0, alpha=0.7,
                    label=f"{a} (primary only)")
        for a, y in tr["ref_tbc"].df_hz.items():
            ax.plot(tr["ref_tbc"].t, y, lw=1.4, label=f"{a} (LFC+EDC)")
        dp = have["east"]["agc"]["ref_2pct_step"]["dp_mw"]
        ax.set_title(f"(a) east: 2% load step ({dp:,.0f} MW)", fontsize=10)
    ax.set_xlabel("time [s]"); ax.set_ylabel("Δf [Hz]")
    ax.legend(fontsize=7); ax.grid(alpha=0.3)
    ax = axes[1]
    for isl in ("hokkaido", "east", "west", "okinawa"):
        if isl not in have:
            continue
        tr = have[isl]["_traces"]["trip_tbc"]
        d = have[isl]["agc"]["disturbance"]
        a = d["region"]
        ax.plot(tr.t, tr.df_hz[a],
                label=f"{isl}: −{d['p_mw']:,.0f} MW", lw=1.2)
    ax.set_title("(b) largest online plant trip (upper-bound N-1, +UFLS)",
                 fontsize=10)
    ax.set_xlabel("time [s]"); ax.set_ylabel("Δf [Hz]")
    ax.legend(fontsize=7); ax.grid(alpha=0.3)
    ax = axes[2]
    if "east" in have:
        tr = have["east"]["_traces"]["ref_tbc"]
        d = have["east"]["agc"]["ref_2pct_step"]
        a = d["area"]
        ax.plot(tr.t, tr.agc_mw[a], lw=1.4, color="C2",
                label=f"{a}: LFC+EDC command [MW]")
        ax.plot(tr.t, tr.ptie_mw[a], lw=1.1, color="C3",
                label=f"{a}: tie deviation [MW]")
        ax.axhline(d["dp_mw"], color="k", ls=":", lw=0.8,
                   label=f"step {d['dp_mw']:,.0f} MW")
        ax.set_title("(c) TBC assigns correction to disturbed area",
                     fontsize=10)
    ax.set_xlabel("time [s]"); ax.set_ylabel("[MW]")
    ax.legend(fontsize=7); ax.grid(alpha=0.3)
    fig.tight_layout()
    os.makedirs("docs/assets/figs", exist_ok=True)
    fig.savefig("docs/assets/figs/fig_agc_national.png", dpi=160)
    os.makedirs("papers/figs", exist_ok=True)
    fig.savefig("papers/figs/fig_agc.pdf")
    print("\n図: docs/assets/figs/fig_agc_national.png / papers/figs/fig_agc.pdf")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--islands", nargs="+",
                    default=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--t-end", type=float, default=900.0)
    args = ap.parse_args()

    print(f"① UC求解中... ({args.scenario})")
    t0 = time.monotonic()
    scn = build_national_scenario(scenario=args.scenario)
    uc = solve_uc(scn.to_uc_parameters())
    print(f"  {uc.status} ({time.monotonic()-t0:.0f}s, "
          f"{uc.num_generators}機)")
    if not uc.is_optimal:
        print("UC非最適 — 中止"); return 1

    built = json.load(open(BUILT))
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(built["nodes"])

    reports = {}
    for island in args.islands:
        reports[island] = run_island(island, scn, uc, built, cfg,
                                     pref_gwh, args.t_end)
    make_figures(reports)

    doc = {"note": ("UC→潮流→AGC 運用チェーン。AGC層は IEEJ AGC30(GH1386) の"
                    "簡易実装(GF/LFC/EDC三階層) — パラメータ出所と簡約は "
                    "src/dynamics/agc.py 冒頭に記載。構造実証であり運用予測"
                    "ではない"),
           "scenario": args.scenario,
           "islands": {k: {kk: vv for kk, vv in v.items()
                           if kk != "_traces"} for k, v in reports.items()}}
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(doc, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
    print(f"-> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
