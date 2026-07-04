#!/usr/bin/env python3
"""UC 24h → built正典(v4銘板)全規模潮流 — 時間別ディスパッチの通年断面検証.

UC→潮流連携の第3経路(モデル別の役割分担):
  - scripts/uc_to_pf.py          : 単一地域 backbone(154kV縮約)。6月実績=24h全時刻AC収束
  - scripts/uc_to_pf_national.py : snapped島 before/after比較(merit vs UC注入)
  - 本スクリプト                  : **built正典・全規模・v4銘板入り**
    (run_full_powerflow_from_db と同一の build_island_net — Ybus v4 と同一モデル)
    で24時間のUCディスパッチを注入して解く。

解法(確定事項に従う):
  east(6,205バス)=AC — 全規模ACの収束実績 2026-07-04(v4銘板・vm 0.83-1.02pu)
  west(10,193バス)=DC — AC「収束」はfragmentationの見せかけと確定済み
                        (docs/WEST_AC_ANALYSIS.md)
  hokkaido/okinawa=AC

契約(docs/UC_HANDOFF.md): ybus_gate PASS の島にのみ注入する。

使い方:
    PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py --islands east --hours 0 11 19
    PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py \
        --islands hokkaido east west okinawa --all-hours

出力: docs/reports/uc_pf_built_<islands>_<hours>_<date>.json
"""
import argparse
import copy
import datetime as _dt
import json
import os
import subprocess
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandapower as pp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from scripts.run_full_powerflow_from_db import (  # noqa: E402
    BUILT,
    ISLAND_OF,
    add_per_component_slacks,
    allocate_loads,
    attach_generators,
    build_island_net,
)
from src.powerflow.load_estimator import load_demand_config  # noqa: E402
from src.powerflow.ybus_gate import ybus_gate  # noqa: E402
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402

ISLAND_FREQ = {"hokkaido": 50.0, "east": 50.0, "west": 60.0, "okinawa": 60.0}
ISLAND_MODE = {"hokkaido": "ac", "east": "ac", "west": "dc", "okinawa": "ac"}


def _git_head():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def tie_flows_by_pair(net):
    """zone跨ぎ線の潮流を地域対で集計(MW, from側)。"""
    zone = net.bus["zone"]
    out = {}
    if "p_from_mw" not in getattr(net, "res_line", {}):
        return out
    for li in net.line.index:
        if not net.line.at[li, "in_service"] or li not in net.res_line.index:
            continue
        za = zone.get(int(net.line.at[li, "from_bus"]))
        zb = zone.get(int(net.line.at[li, "to_bus"]))
        if not za or not zb or za == zb:
            continue
        key = "->".join(sorted((str(za), str(zb))))
        p = float(net.res_line.at[li, "p_from_mw"])
        if str(za) > str(zb):          # 集計方向を辞書順に正規化
            p = -p
        out[key] = out.get(key, 0.0) + p
    return {k: round(v, 1) for k, v in sorted(out.items())}


def solve_hour(base, mode):
    """1時刻断面を解く — 正典実行(run_full_powerflow_from_db)と同一の
    solve_island(prune ladder付きAC / DC)を共用する。AC不成立は正直に
    dc_fallback と記録する。"""
    from scripts.run_full_powerflow_from_db import solve_island
    net = copy.deepcopy(base)
    if mode == "ac":
        net_dc, dc, net_ac, ac = solve_island(net, max_ac_buses=10**9)
        if ac.get("converged"):
            return net_ac, "ac"
        return net_dc, "dc_fallback"
    net_dc, _dc, _na, _ac = solve_island(net, max_ac_buses=0)
    return net_dc, "dc"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--islands", nargs="+", default=["east"])
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--all-hours", action="store_true")
    ap.add_argument("--hours", nargs="*", type=int, default=None,
                    help="解く時刻(0-23)。省略時=島純需要ピーク時刻のみ")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    print(f"UC求解中... ({args.scenario})")
    scn = build_national_scenario(scenario=args.scenario)
    uc = solve_uc(scn.to_uc_parameters())
    print(f"  {uc.status}")
    if not uc.is_optimal:
        print("UCがOptimalでないため中止")
        return 1

    built = json.load(open(BUILT))
    cfg = load_demand_config()

    report = {"meta": {"date": _dt.date.today().isoformat(),
                       "git_head": _git_head(), "scenario": args.scenario,
                       "model": "built_full_v4_nameplate",
                       "builder": "run_full_powerflow_from_db.build_island_net"},
              "islands": {}}
    rc = 0
    for island in args.islands:
        regions = sorted(r for r, (isl, _f) in ISLAND_OF.items() if isl == island)
        mode = ISLAND_MODE[island]
        net_dem = sum(np.asarray(scn.net_demand_r[r]) for r in regions)
        if args.all_hours:
            hours = list(range(24))
        elif args.hours:
            hours = args.hours
        else:
            hours = [int(np.argmax(net_dem))]

        print(f"\n== {island} ({'+'.join(regions)}) mode={mode} "
              f"hours={hours[0]}..{hours[-1]} ({len(hours)}断面) ==")
        t0 = time.monotonic()
        geom = {}
        base, bus_of, bstats = build_island_net(
            island, built["nodes"], built["edges"], ISLAND_FREQ[island], geom)
        attach_generators(base, bus_of, built["nodes"], island)
        allocate_loads(base, cfg)
        add_per_component_slacks(base)
        print(f"  built: {bstats['n_bus']}バス trafo={bstats['n_trafo']} "
              f"(銘板{bstats['n_trafo_nameplate']}) {time.monotonic()-t0:.0f}s")

        gate = ybus_gate(base)
        isl_rep = {"mode": mode, "regions": regions,
                   "n_bus": bstats["n_bus"],
                   "n_trafo_nameplate": bstats["n_trafo_nameplate"],
                   "gate": {"pass": bool(gate["pass"]),
                            "cond_max": gate["cond_max"]},
                   "hours": {}}
        report["islands"][island] = isl_rep
        if not gate["pass"]:
            print(f"  × ybus_gate FAIL (cond={gate['cond_max']:.2e}) — "
                  f"契約により注入しない")
            rc = 1
            continue

        n_ok = 0
        for t in hours:
            th = time.monotonic()
            net_t = copy.deepcopy(base)
            fuel_by_zone = {r: uc_snapshot(uc, scn.generators, t, region=r)
                            for r in regions}
            demand = {r: float(scn.net_demand_r[r][t]) for r in regions}
            inj = inject_dispatch_by_zone(net_t, fuel_by_zone, demand)
            net_s, used = solve_hour(net_t, mode)
            conv = bool(net_s.converged)
            n_ok += int(conv)
            slack = (float(net_s.res_ext_grid.p_mw.sum())
                     if conv and len(net_s.res_ext_grid) else None)
            hrep = {"solver": used, "converged": conv,
                    "net_demand_mw": round(float(net_dem[t]), 1),
                    "load_scale": {r: inj[r]["load_scale"] for r in regions},
                    "slack_abs_mw": round(slack, 1) if slack is not None else None,
                    "solve_s": round(time.monotonic() - th, 1)}
            if conv and used == "ac":
                vm = net_s.res_bus.vm_pu
                hrep["vm_min"] = round(float(vm.min()), 4)
                hrep["vm_max"] = round(float(vm.max()), 4)
                hrep["loss_mw"] = round(
                    float(net_s.res_line.pl_mw.sum()
                          + net_s.res_trafo.pl_mw.sum()), 1)
            if conv:
                hrep["tie_mw"] = tie_flows_by_pair(net_s)
            isl_rep["hours"][str(t)] = hrep
            print(f"  t={t:2d} {used:12s} conv={conv} "
                  f"demand={float(net_dem[t]):8,.0f}MW "
                  f"slack={hrep['slack_abs_mw']} {hrep['solve_s']}s", flush=True)

        isl_rep["n_hours"] = len(hours)
        isl_rep["n_converged"] = n_ok
        isl_rep["all_converged"] = (n_ok == len(hours))
        if not isl_rep["all_converged"]:
            rc = 1

    hours_tag = "allhours" if args.all_hours else "sel"
    out = args.out or (f"docs/reports/uc_pf_built_{'_'.join(args.islands)}_"
                       f"{hours_tag}_{_dt.date.today().isoformat()}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\n-> {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
