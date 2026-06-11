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

    # ── 4. 注入 ──
    ratio = scale_loads_to(net, float(net_dem[t]))
    inj = inject_dispatch(net, snapshot)
    print(f"  load×{ratio:.3f}, 注入 {inj['injected_mw']:,.0f} MW "
          f"(clip {sum(inj['clipped'].values()):,.0f} / "
          f"unmatched {sum(inj['unmatched'].values()):,.0f})")

    # ── 5. AC再ソルブ ──
    from src.powerflow.batch_solve import run_powerflow
    ac = run_powerflow(net, "ac")
    slack_mw = None
    if ac["converged"]:
        parts = []
        if len(net.ext_grid):
            parts.append(float(net.res_ext_grid["p_mw"].sum()))
        if "slack" in net.gen.columns:
            sm = net.gen["slack"].fillna(False).astype(bool)
            if sm.any():
                parts.append(float(net.res_gen.loc[sm, "p_mw"].sum()))
        slack_mw = round(sum(parts), 1) if parts else None
        vm = net.res_bus["vm_pu"]
        print(f"  AC(UC注入): converged, vm [{vm.min():.3f}, {vm.max():.3f}], "
              f"slack {slack_mw if slack_mw is not None else float('nan'):,.0f} MW")
    else:
        print(f"  AC(UC注入): FAILED ({str(ac.get('error', ''))[:80]})")

    report = {
        "meta": {
            "date": _dt.date.today().isoformat(),
            "git_head": _git_head(),
            "region": region,
            "scenario": args.scenario,
            "hour": t,
            "model": "full" if args.full else "backbone154",
        },
        "uc": {
            "status": uc.status,
            "region_dispatch_mw": round(uc_region_mw, 1),
            "region_net_demand_mw": round(float(net_dem[t]), 1),
            "fuel_mw": {k: round(v, 1) for k, v in snapshot.items()},
        },
        "gate": {"pass": gate["pass"], "cond_max": gate["cond_max"]},
        "injection": inj,
        "pf": {
            "baseline_ac_converged": bool(ac0["converged"]),
            "uc_ac_converged": bool(ac["converged"]),
            "vm_min": (round(float(net.res_bus['vm_pu'].min()), 4)
                       if ac["converged"] else None),
            "vm_max": (round(float(net.res_bus['vm_pu'].max()), 4)
                       if ac["converged"] else None),
            "slack_mw": (round(slack_mw, 1)
                         if slack_mw is not None else None),
            "load_scale_ratio": round(ratio, 4),
        },
    }
    out = args.out or (
        f"docs/reports/uc_pf_link_{region}_{report['meta']['date']}.json")
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out}")
    return 0 if ac["converged"] else 1


if __name__ == "__main__":
    sys.exit(main())
