"""UC→全国ゾーナル潮流 — UC断面を同期島ネットへ地域別注入して検証する。

scripts/uc_to_pf.py（単一地域）の全国版。run_national_powerflow.py の島構築
チェーンを踏みつつ、merit-orderの balance_power_by_zone の代わりに
**UC断面のzone別ディスパッチ**（inject_dispatch_by_zone）を注入する —
UCが決めた地域間取引が、実網のtie線潮流として流れるかの検証。

島と解法（確定事項に従う）:
  - east (tohoku+tokyo, 50Hz): AC（prune_dc_infeasibleリトライ付き）
  - west (60Hz 6地域): **DC**（AC非収束の真因=下位網変圧器は確定済み、
    docs/WEST_AC_ANALYSIS.md — --try-ac で再試行は可能だが既定はDC）
  - hokkaido/okinawa: 単一地域なので scripts/uc_to_pf.py の管轄

検証ポイント:
  1. ybus_gate — FAILの島には注入しない（UC_HANDOFF契約）
  2. zone別注入（load=UC純需要スケール、gen=燃料別容量比例）
  3. tie線潮流（zone跨ぎline）を地域対で集計し、UCの連系線フローと比較

使い方:
    python scripts/uc_to_pf_national.py --islands east          # ローカル可
    python scripts/uc_to_pf_national.py --islands west          # サーバー推奨(~12kバス)
    python scripts/uc_to_pf_national.py --islands east west --hour 11

出力: docs/reports/uc_pf_national_<islands>_<date>.json
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.converter.pandapower_builder import PandapowerBuilder  # noqa: E402
from src.powerflow.batch_solve import run_powerflow  # noqa: E402
from src.powerflow.load_estimator import (  # noqa: E402
    estimate_loads,
    load_demand_config,
)
from src.powerflow.national import (  # noqa: E402
    ISLANDS,
    build_island_networks,
    load_interconnections,
)
from src.powerflow.transforms import (  # noqa: E402
    apply_voltage_setpoints,
    fix_topology,
    fix_zero_voltages,
    insert_transformers,
    prune_dc_infeasible,
    scale_line_ratings,
    select_slack_bus,
)
from src.powerflow.ybus_gate import ybus_gate  # noqa: E402
from src.reconstruction.config import ReconstructionConfig  # noqa: E402
from src.reconstruction.isolator import Isolator  # noqa: E402
from src.reconstruction.reconnector import Reconnector  # noqa: E402
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402
from scripts.run_national_powerflow import add_reactive_compensation  # noqa: E402


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def build_injected_island(isl, regions, scn, uc, t, demand_cfg, reactive):
    """島ネット構築+UC断面zone別注入（solve_islandのUC版、ソルブ前まで）。"""
    net = PandapowerBuilder().build(isl["net"]).net
    fix_zero_voltages(net)
    insert_transformers(net)
    iso = Isolator().detect(net)
    Reconnector().reconnect(net, iso, ReconstructionConfig(
        mode="reconnect", max_reconnection_distance_km=5.0))
    fix_topology(net, multi_slack=True)
    select_slack_bus(net)
    estimate_loads(net, region="national", demand_config=demand_cfg)
    inactive = set(net.bus.index[~net.bus["in_service"]])
    if len(net.load) > 0:
        net.load.loc[net.load["bus"].isin(inactive), "in_service"] = False

    # ── UC断面のzone別注入（merit-order balance_power_by_zone の代替） ──
    fuel_by_zone = {r: uc_snapshot(uc, scn.generators, t, region=r)
                    for r in regions}
    demand_by_zone = {r: float(scn.net_demand_r[r][t]) for r in regions}
    inj = inject_dispatch_by_zone(net, fuel_by_zone, demand_by_zone)

    scale_line_ratings(net)
    n_shunt = add_reactive_compensation(net, reactive)
    net.bus["vm_pu"] = 1.0
    apply_voltage_setpoints(net)
    return net, inj, n_shunt


def tie_flows_by_pair(net) -> dict:
    """zone跨ぎ稼働lineの潮流を「from_zone->to_zone」地域対で合算する。"""
    zone = net.bus["zone"]
    out: dict = {}
    if "p_from_mw" not in getattr(net, "res_line", {}):
        return out
    li = net.line[net.line["in_service"]]
    for idx in li.index:
        zf = zone.get(li.at[idx, "from_bus"])
        zt = zone.get(li.at[idx, "to_bus"])
        if not isinstance(zf, str) or not isinstance(zt, str) or zf == zt:
            continue
        if idx not in net.res_line.index:
            continue
        p = float(net.res_line.at[idx, "p_from_mw"])
        if not np.isfinite(p):
            continue
        # 方向を辞書順の対に正規化（A->B 正、B->A は符号反転して合算）
        key = f"{zf}->{zt}" if zf < zt else f"{zt}->{zf}"
        out[key] = out.get(key, 0.0) + (p if zf < zt else -p)
    return {k: round(v, 1) for k, v in out.items()}


def uc_flows_by_pair(uc, t) -> dict:
    """UC連系線フロー[t]を同じ「地域対（辞書順）」キーへ合算する。"""
    ac_ties, _ = load_interconnections()
    meta = {ic["id"]: ic for ic in ac_ties}
    out: dict = {}
    for icf in uc.interconnection_flows:
        ic = meta.get(icf.interconnection_id)
        if ic is None:  # async (HVDC/FC) は島内tieに現れない
            continue
        if t >= len(icf.flow_mw):
            continue
        p = float(icf.flow_mw[t])
        a, b = ic["from_region"], ic["to_region"]
        key = f"{a}->{b}" if a < b else f"{b}->{a}"
        out[key] = out.get(key, 0.0) + (p if a < b else -p)
    return {k: round(v, 1) for k, v in out.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--islands", nargs="*", default=["east"],
                    help="対象島 (east west)。hokkaido/okinawaはuc_to_pf.pyで")
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--hour", type=int, default=None,
                    help="注入時刻 (0-23)。省略時=島内純需要合計ピーク")
    ap.add_argument("--reactive", type=float, default=0.6)
    ap.add_argument("--try-ac", action="store_true",
                    help="westでもACを試す（既定はDC=確定事項）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    # ── 1. UC ──
    print(f"UC求解中... ({args.scenario})")
    scn = build_national_scenario(scenario=args.scenario)
    uc = solve_uc(scn.to_uc_parameters())
    print(f"  {uc.status}")
    if not uc.is_optimal:
        print("UCがOptimalでないため中止")
        return 1

    # ── 2. 島構築 ──
    print("島ネット構築中...")
    t0 = time.monotonic()
    islands, _async = build_island_networks()
    print(f"  built in {time.monotonic() - t0:.0f}s")
    demand_cfg = load_demand_config()

    report = {
        "meta": {
            "date": _dt.date.today().isoformat(),
            "git_head": _git_head(),
            "scenario": args.scenario,
            "reactive": args.reactive,
        },
        "islands": {},
    }
    overall_ok = True

    for iid in args.islands:
        if iid not in islands:
            print(f"× 未知の島: {iid}")
            continue
        isl = islands[iid]
        regions = isl["regions"]
        net_dem = sum(np.asarray(scn.net_demand_r[r]) for r in regions)
        t = args.hour if args.hour is not None else int(np.argmax(net_dem))
        print(f"\n== {iid} ({'+'.join(regions)}) t={t} "
              f"純需要 {float(net_dem[t]):,.0f} MW ==")

        net, inj, n_shunt = build_injected_island(
            isl, regions, scn, uc, t, demand_cfg, args.reactive)
        tot_inj = sum(x["injection"]["injected_mw"] for x in inj.values())
        print(f"  {len(net.bus)} buses, 注入 {tot_inj:,.0f} MW, "
              f"shunt {n_shunt}")
        for r, x in sorted(inj.items()):
            rep = x["injection"]
            print(f"    {r:9s} inj {rep['injected_mw']:8,.0f} MW "
                  f"(req {rep['requested_mw']:,.0f}, load×{x['load_scale']})")

        # ── 3. gate（契約: 流す前に必ず） ──
        gate = ybus_gate(net)
        print(f"  ybus_gate: {'PASS' if gate['pass'] else 'FAIL'} "
              f"(cond_max={gate['cond_max']:.2e})")
        isl_rep = {
            "regions": regions, "hour": t,
            "net_demand_mw": round(float(net_dem[t]), 1),
            "n_buses": int(len(net.bus)),
            "injection": inj,
            "gate": {"pass": gate["pass"], "cond_max": gate["cond_max"]},
        }
        if not gate["pass"]:
            isl_rep["skipped"] = "ybus_gate FAIL — 契約により注入断面を解かない"
            report["islands"][iid] = isl_rep
            overall_ok = False
            continue

        # ── 4. ソルブ（east=AC / west=DC既定） ──
        mode = "ac" if (iid != "west" or args.try_ac) else "dc"
        if mode == "ac":
            ac = {"converged": False}
            net_s = None
            for thr in (45.0, 30.0, 20.0):
                net_s = copy.deepcopy(net)
                if prune_dc_infeasible(net_s, angle_threshold=thr) > 0:
                    fix_topology(net_s, multi_slack=True)
                    select_slack_bus(net_s)
                    scale_line_ratings(net_s)
                ac = run_powerflow(net_s, "ac")
                if ac["converged"]:
                    isl_rep["prune_threshold"] = thr
                    break
            res = ac
        else:
            net_s = copy.deepcopy(net)
            res = run_powerflow(net_s, "dc")
        isl_rep["mode"] = mode
        isl_rep["converged"] = bool(res["converged"])

        if res["converged"]:
            if mode == "ac":
                zone = net_s.bus["zone"]
                vm_by_zone = {}
                for r in regions:
                    bidx = [i for i in net_s.res_bus.index
                            if zone.get(i) == r
                            and net_s.bus.at[i, "in_service"]]
                    if bidx:
                        vms = net_s.res_bus.loc[bidx, "vm_pu"]
                        vm_by_zone[r] = [round(float(vms.min()), 3),
                                         round(float(vms.max()), 3)]
                isl_rep["vm_by_zone"] = vm_by_zone
                print(f"  AC: converged, vm zone別 {vm_by_zone}")
            else:
                ld = net_s.res_line["loading_percent"]
                isl_rep["line_loading_p95"] = round(
                    float(np.nanpercentile(ld, 95)), 1)
                print(f"  DC: converged, loading p95 "
                      f"{isl_rep['line_loading_p95']}%")
            # ── 5. tie線潮流 vs UC連系線フロー（地域対） ──
            pf_ties = tie_flows_by_pair(net_s)
            uc_ties = {k: v for k, v in uc_flows_by_pair(uc, t).items()
                       if k in pf_ties
                       or all(r in regions for r in k.split("->"))}
            isl_rep["tie_flow_mw"] = {"pf": pf_ties, "uc": uc_ties}
            print("  tie潮流 (PF / UC):")
            for k in sorted(set(pf_ties) | set(uc_ties)):
                print(f"    {k:22s} {pf_ties.get(k, float('nan')):9,.1f} / "
                      f"{uc_ties.get(k, float('nan')):9,.1f} MW")
        else:
            isl_rep["error"] = str(res.get("error", ""))[:120]
            print(f"  {mode.upper()}: FAILED ({isl_rep['error'][:60]})")
            overall_ok = False
        report["islands"][iid] = isl_rep

    out = args.out or (
        f"docs/reports/uc_pf_national_{'_'.join(args.islands)}_"
        f"{report['meta']['date']}.json")
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out}")

    # uc_runs 索引へベストエフォート記録（正本は上のJSON）
    from src.uc.run_recorder import record_run
    record_run(
        out, kind="pf_national", run_date=report["meta"]["date"],
        git_head=report["meta"]["git_head"], scenario_id=args.scenario,
        status="converged" if overall_ok else "failed",
        summary_json=json.dumps(
            {iid: {"mode": isl.get("mode"),
                   "converged": isl.get("converged"),
                   "n_buses": isl.get("n_buses")}
             for iid, isl in report["islands"].items()},
            ensure_ascii=False),
    )
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
