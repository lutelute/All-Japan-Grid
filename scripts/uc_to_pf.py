"""UC→潮流 連携検証 — UCディスパッチ断面が送電網で流せるかを確認する。

フロー（docs/UC_HANDOFF.md の契約遵守）:
  1. fy2023r2 で全国24h UCを解く（ノーダル+連系線、HiGHS ~12s）
  2. 対象地域のPF網を build_and_solve で構築（backbone既定、merit-order初期解）
  3. **ybus_gate** — PASSでなければ注入せず島名を報告して終了（契約#1,2）
  4. UCの指定時刻断面（既定=地域純需要ピーク時刻）を燃料別に集計し、
     PF側 load をUC断面需要へスケール、gen へ容量比例注入（コミットメント反映）
  5. AC再ソルブ → 収束・電圧範囲・slack吸収量・注入整合をレポート

使い方:
    python scripts/uc_to_pf.py --region tokyo
    python scripts/uc_to_pf.py --region kansai --hour 19
    python scripts/uc_to_pf.py --region tokyo --full   # backbone縮約なし

出力: docs/reports/uc_pf_link_<region>_<date>.json
"""

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.uc.pf_injection import (  # noqa: E402
    inject_dispatch,
    scale_loads_to,
    uc_snapshot,
)
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="tokyo")
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--hour", type=int, default=None,
                    help="注入する時刻 (0-23)。省略時=地域純需要ピーク時刻")
    ap.add_argument("--all-hours", action="store_true",
                    help="24時刻全断面を検証（UCは解けるがPFで流せない時間帯の特定）")
    ap.add_argument("--full", action="store_true",
                    help="backbone縮約なしのフルモデルで検証")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    region = args.region

    # ── 1. UC ──
    print(f"UC求解中... ({args.scenario})")
    scn = build_national_scenario(scenario=args.scenario)
    params = scn.to_uc_parameters()
    t0 = time.monotonic()
    uc = solve_uc(params)
    print(f"  {uc.status}, {time.monotonic() - t0:.1f}s")
    if not uc.is_optimal:
        print("UCがOptimalでないため中止")
        return 1

    net_dem = scn.net_demand_r[region]
    t = args.hour if args.hour is not None else int(np.argmax(net_dem))
    snapshot = uc_snapshot(uc, scn.generators, t, region=region)
    uc_region_mw = sum(snapshot.values())
    print(f"  {region} t={t}: UCディスパッチ {uc_region_mw:,.0f} MW "
          f"(純需要 {net_dem[t]:,.0f} MW) 燃料別: "
          + ", ".join(f"{k}={v:,.0f}" for k, v in
                      sorted(snapshot.items(), key=lambda kv: -kv[1])))

    # ── 2. PF網構築（merit-order初期解つき） ──
    print(f"PF網構築中... ({region}, {'full' if args.full else 'backbone'})")
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pipeline import build_and_solve

    result = build_and_solve(
        region, load_demand_config(),
        topology="snapped", reconnect=True,
        backbone_kv=None if args.full else 154.0,
    )
    if result is None:
        print("PF網が構築できません")
        return 1
    _net_dc, dc0, net, ac0, info, _geom = result
    print(f"  {info['n_buses']} buses, baseline AC "
          f"{'converged' if ac0['converged'] else 'FAILED'}")

    # ── 3. Ybus shipping gate（契約: 解く/流す前に必ず通す） ──
    from src.powerflow.ybus_gate import ybus_gate
    gate = ybus_gate(net)
    print(f"  ybus_gate: {'PASS' if gate['pass'] else 'FAIL'} "
          f"(cond_max={gate['cond_max']:.2e})")
    if not gate["pass"]:
        print(f"  FAIL島: {gate.get('failing')} — 契約により注入せず終了")
        return 1

    # ── 4./5. 注入 + AC再ソルブ（--all-hours は24断面スイープ） ──
    import copy as _copy

    from src.powerflow.batch_solve import run_powerflow

    hours_list = list(range(24)) if args.all_hours else [t]
    rows = []
    for hh in hours_list:
        snap_h = uc_snapshot(uc, scn.generators, hh, region=region)
        # 元のnetは触らず時刻ごとに複製へ注入（単一断面なら複製不要）
        net_h = _copy.deepcopy(net) if len(hours_list) > 1 else net
        ratio = scale_loads_to(net_h, float(net_dem[hh]))
        inj = inject_dispatch(net_h, snap_h)
        ac = run_powerflow(net_h, "ac")
        row = {
            "hour": hh,
            "uc_dispatch_mw": round(sum(snap_h.values()), 1),
            "net_demand_mw": round(float(net_dem[hh]), 1),
            "load_scale": round(ratio, 3),
            "injected_mw": round(inj["injected_mw"], 1),
            "clipped_mw": round(sum(inj["clipped"].values()), 1),
            "unmatched_mw": round(sum(inj["unmatched"].values()), 1),
            "converged": bool(ac["converged"]),
        }
        if ac["converged"]:
            parts = []
            if len(net_h.ext_grid):
                parts.append(float(net_h.res_ext_grid["p_mw"].sum()))
            if "slack" in net_h.gen.columns:
                sm = net_h.gen["slack"].fillna(False).astype(bool)
                if sm.any():
                    parts.append(float(net_h.res_gen.loc[sm, "p_mw"].sum()))
            slack_mw = round(sum(parts), 1) if parts else None
            vm = net_h.res_bus["vm_pu"]
            row.update({
                "vm_min": round(float(vm.min()), 3),
                "vm_max": round(float(vm.max()), 3),
                "slack_mw": slack_mw,
            })
            print(f"  h={hh:02d}: converged vm[{row['vm_min']:.3f}, "
                  f"{row['vm_max']:.3f}] slack {slack_mw} MW "
                  f"(注入 {row['injected_mw']:,.0f} MW)")
        else:
            row["error"] = str(ac.get("error", ""))[:120]
            print(f"  h={hh:02d}: FAILED ({row['error'][:60]})")
        rows.append(row)

    n_fail = sum(1 for r in rows if not r["converged"])
    if args.all_hours:
        print(f"  全{len(rows)}断面: 収束 {len(rows) - n_fail} / 失敗 {n_fail}")

    report = {
        "meta": {
            "date": _dt.date.today().isoformat(),
            "git_head": _git_head(),
            "region": region,
            "scenario": args.scenario,
            "hour": t,
            "all_hours": bool(args.all_hours),
            "model": "full" if args.full else "backbone154",
        },
        "uc": {
            "status": uc.status,
            "region_dispatch_mw": round(uc_region_mw, 1),
            "region_net_demand_mw": round(float(net_dem[t]), 1),
            "fuel_mw": {k: round(v, 1) for k, v in snapshot.items()},
        },
        "gate": {"pass": gate["pass"], "cond_max": gate["cond_max"]},
        "pf": {
            "baseline_ac_converged": bool(ac0["converged"]),
            "all_converged": n_fail == 0,
            "n_failed_hours": n_fail,
            "hours": rows,
        },
    }
    suffix = "_allhours" if args.all_hours else ""
    out = args.out or (
        f"docs/reports/uc_pf_link_{region}{suffix}_{report['meta']['date']}.json")
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out}")

    # uc_runs 索引へベストエフォート記録（正本は上のJSON）
    from src.uc.run_recorder import record_run
    record_run(
        out, kind="pf_link", run_date=report["meta"]["date"],
        git_head=report["meta"]["git_head"], scenario_id=args.scenario,
        status="converged" if n_fail == 0 else f"{n_fail}/{len(rows)} failed",
        summary_json=json.dumps(
            {"region": region, "hours": len(rows), "n_failed": n_fail,
             "vm_min": min((r["vm_min"] for r in rows if "vm_min" in r),
                           default=None),
             "vm_max": max((r["vm_max"] for r in rows if "vm_max" in r),
                           default=None)},
            ensure_ascii=False),
    )
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
