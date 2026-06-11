"""年間 rolling UC — fy2023シナリオ × 合成8760h時系列（ROADMAP P5）。

使い方:
    python scripts/uc_annual.py --days 7 --label smoke      # ローカル検証
    python scripts/uc_annual.py --label fy2023_full         # 365日（サーバー推奨）
    python scripts/uc_annual.py --days 365 --window 48 --step 24

出力: docs/reports/uc_annual_<label>_<date>.json
（年間燃料シェア・コスト・窓統計。24hベンチ (uc_benchmark) と同じシェア定義）
"""

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.uc.rolling import RollingUCConfig, solve_rolling_uc  # noqa: E402
from src.uc.scenario import (  # noqa: E402
    build_annual_profiles,
    build_national_scenario,
)


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario", default="fy2023")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--window", type=int, default=48, help="窓長 (h)")
    ap.add_argument("--step", type=int, default=24, help="前進幅 (h)")
    ap.add_argument("--mip-gap", type=float, default=0.01)
    ap.add_argument("--reserve-margin", type=float, default=0.05)
    ap.add_argument("--no-warm-start", action="store_true")
    ap.add_argument("--label", default="annual")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    print(f"シナリオ構築中... ({args.scenario}, {args.days}日)")
    scn = build_national_scenario(scenario=args.scenario)
    profiles = build_annual_profiles(scn.config, days=args.days)
    hours = profiles.hours
    net_r = profiles.net_demand_r
    net_nat = profiles.net_demand_national
    print(f"  発電機 {len(scn.generators)}機 / {hours}h "
          f"/ ピーク純需要 {net_nat.max() / 1000:.1f} GW "
          f"/ 最小 {net_nat.min() / 1000:.1f} GW")

    cfg = RollingUCConfig(
        window_h=args.window,
        step_h=args.step,
        reserve_margin=args.reserve_margin,
        mip_gap=args.mip_gap,
        warm_start=not args.no_warm_start,
    )
    print(f"rolling UC 実行中... (window={cfg.window_h}h step={cfg.step_h}h)")
    res = solve_rolling_uc(
        scn.generators, net_nat, net_r, scn.interconnections, cfg,
    )
    print(f"  {res.status}, {res.n_windows}窓, {res.solve_time_s}s, "
          f"再計算コスト ¥{res.total_cost / 1e8:.1f}億")

    # ── 年間燃料シェア（uc_benchmark と同じエネルギーベース定義） ──
    gen_map = {g.id: g for g in scn.generators}
    fuel_energy: dict = {}
    for gid, sched in res.schedules.items():
        g = gen_map.get(gid)
        if g is None:
            continue
        e = float(np.asarray(sched.power_output_mw).clip(min=0).sum())
        fuel_energy[g.fuel_type] = fuel_energy.get(g.fuel_type, 0.0) + e
    n_solved_h = (
        len(next(iter(res.schedules.values())).power_output_mw)
        if res.schedules else 0
    )
    fuel_energy["solar"] = float(
        sum(s[:n_solved_h].sum() for s in profiles.solar_gen_r.values())
    )
    fuel_energy["wind"] = float(
        sum(w[:n_solved_h].sum() for w in profiles.wind_gen_r.values())
    )
    total = sum(fuel_energy.values())
    share = {
        k: round(v / total * 100, 2)
        for k, v in sorted(fuel_energy.items(), key=lambda kv: -kv[1])
        if v > 0
    } if total else {}

    report = {
        "meta": {
            "date": _dt.date.today().isoformat(),
            "git_head": _git_head(),
            "scenario": args.scenario,
            "days": args.days,
            "window_h": cfg.window_h,
            "step_h": cfg.step_h,
            "warm_start": cfg.warm_start,
        },
        "result": {
            "status": res.status,
            "hours": res.hours,
            "n_windows": res.n_windows,
            "n_retried": res.n_retried,
            "failed_window": res.failed_window,
            "solve_time_s": res.solve_time_s,
            "mean_window_time_s": (
                round(float(np.mean(res.window_times_s)), 2)
                if res.window_times_s else None
            ),
            "max_window_time_s": (
                max(res.window_times_s) if res.window_times_s else None
            ),
            "total_cost_oku": round(res.total_cost / 1e8, 1),
            "total_energy_twh": round(total / 1e6, 2),
        },
        "fuel_share_pct": share,
    }
    out = args.out or (
        f"docs/reports/uc_annual_{args.label}_{report['meta']['date']}.json"
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out}")
    print("\n── 年間燃料シェア ──")
    for fuel, pct in share.items():
        print(f"  {fuel:12s} {pct:6.2f}%")
    return 0 if res.is_optimal else 1


if __name__ == "__main__":
    sys.exit(main())
