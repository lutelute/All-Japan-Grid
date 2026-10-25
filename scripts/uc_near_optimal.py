"""Near the cost optimum, how much N-1 shortfall can a little more cost buy away?

Solves the national UC for cost (the reference), then, for each slack eps, solves the same
model again with cost <= (1 + eps) * reference cost and the N-1 shortfall of src/uc/risk.py
as the objective (eps-constraint method). The reference plan satisfies every cap, so it is
handed over as the MIP start: each run starts in the band and moves within it. Each plan is checked by the validator and scored
after the fact with the same definition; congestion hours and start-ups are reported too.
The plans themselves (on/off and output per generator, tie-line flows) are written for the map.

    python -m scripts.uc_near_optimal --scenario fy2023r2 --eps 0 0.001 0.005 0.01 --out near.json
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import time

from src.uc.risk import congested_hours, n1_shortfall, near_optimal_hook
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc


def case(scenario, time_limit, gap):
    params = build_national_scenario(scenario=scenario).to_uc_parameters()
    params.solver_name, params.solver_time_limit_s, params.mip_gap = "HiGHS", time_limit, gap
    params.solver_options = {"threads": 1}
    return params


def score(params, result, trip_cap):
    if not result.schedules:
        return {"status": result.status, "verified": False, "cost": None, "gap": result.gap,
                "solve_s": result.solve_time_s, "n1_shortfall_mwh": None, "warnings": result.warnings[-3:]}
    n1 = n1_shortfall(params, result, trip_cap_mw=trip_cap)
    starts = sum(1 for s in result.schedules for t in range(len(s.commitment))
                 if s.commitment[t] and not (s.commitment[t - 1] if t else 0))
    return {"status": result.status, "verified": result.feasibility_verified, "cost": result.total_cost,
            "solver_objective": result.solver_objective, "secondary_objective": result.secondary_objective,
            "gap": result.gap, "solve_s": result.solve_time_s, "n1_shortfall_mwh": n1["total_mwh"],
            "n1_short_hours": n1["short_hours"],
            "n1_by_region_mwh": {r: round(sum(v), 1) for r, v in n1["shortfall_mw"].items()},
            "congested_hours": congested_hours(params, result), "startups": starts,
            "plan": {"on": {s.generator_id: sum(1 << t for t, c in enumerate(s.commitment) if c > 0.5) for s in result.schedules},
                     "mw": {s.generator_id: [round(x, 1) for x in s.power_output_mw] for s in result.schedules},
                     "flows": {f.interconnection_id: [round(x, 1) for x in f.flow_mw] for f in result.interconnection_flows},
                     "shortfall_mw": {r: [round(x, 1) for x in v] for r, v in n1["shortfall_mw"].items()}}}


def run_eps(job):
    scenario, eps, cap, trip_cap, time_limit, start = job
    params = case(scenario, time_limit, 1e-4)
    params.warm_start_schedules = start
    params.model_hook = near_optimal_hook(cap, trip_cap_mw=trip_cap, interconnections=params.interconnections)
    begin = time.monotonic()
    result = solve_uc(params)
    out = score(params, result, trip_cap)
    out.update(eps=eps, cost_cap=cap, wall_s=time.monotonic() - begin)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--eps", type=float, nargs="+", default=[0, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.02])
    ap.add_argument("--trip-cap", type=float, default=1000.0, help="largest single trip (MW); 0 = whole station")
    ap.add_argument("--ref-gap", type=float, default=1e-4)
    ap.add_argument("--time-limit", type=float, default=300)
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    trip_cap = args.trip_cap or None
    begin = time.monotonic()
    params = case(args.scenario, args.time_limit, args.ref_gap)
    ref = solve_uc(params)
    reference = score(params, ref, trip_cap)
    reference.update(eps=None, wall_s=time.monotonic() - begin)
    # 1e-6 of slack so that eps = 0 still admits the reference plan within the solver's tolerances
    jobs = [(args.scenario, eps, ref.solver_objective * (1 + eps + 1e-6), trip_cap, args.time_limit, ref.schedules)
            for eps in args.eps]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        runs = list(pool.map(run_eps, jobs))
    out = {"schema_version": 1, "kind": "near_optimal_n1", "scenario": args.scenario,
           "provenance": f"scenario_{args.scenario}_assumed_day", "trip_cap_mw": trip_cap,
           "definition": "src/uc/risk.py (region-level N-1: largest committed unit vs spinning headroom + tie-line import)",
           "reference": reference, "runs": runs, "wall_s": time.monotonic() - begin}
    args.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"ref_cost": ref.total_cost, "ref_n1": reference["n1_shortfall_mwh"], "ref_gap": ref.gap}))
    for r in runs:
        print(json.dumps({k: r.get(k) for k in ["eps", "status", "verified", "cost", "n1_shortfall_mwh", "n1_short_hours",
                                                "congested_hours", "startups", "gap", "solve_s"]}))


if __name__ == "__main__":
    main()
