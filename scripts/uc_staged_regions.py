"""Solve the synthetic UC in stages: national LP for the tie-line flows, then each region alone.

Stage 1 solves the LP relaxation of the full model and keeps its interconnection flows
(or, with --flows-from rolling, takes them from a rolling-horizon schedule: faster, no bound).
Stage 2 fixes those flows and solves one MILP per region (in parallel processes), each
covering its own demand minus net imports and holding its own reserve margin, so the
system-wide reserve is met too. The joined schedule is checked against the full model;
if it passes, its cost is an upper bound. The stage-1 LP value is a lower bound.

    python -m scripts.uc_staged_regions --hours 48 --region-time-limit 300 --out staged48.json

With --scenario NAME the case is the national 10-area UC of config/uc_scenarios/NAME.yaml
(24 h) instead of the synthetic one; --log-dir keeps each region's HiGHS log, and every
region records when it started and finished, for the parallel timeline.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from src.uc.benchmark_cases import synthetic_case
from src.uc.models import (STRENGTHEN_OPTIONS, DemandProfile, GeneratorSchedule, InterconnectionFlow,
                           TimeHorizon, UCParameters, UCResult)
from src.uc.rolling import RollingUCConfig, solve_rolling_uc
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc
from src.uc.validation import validate_uc_solution


def net_imports(params, flows):
    T = params.time_horizon.num_periods
    imports = {r: [0.0] * T for r in params.regional_demands}
    for ic in params.interconnections:
        for t, f in enumerate(flows[ic.id]):
            imports[ic.to_region][t] += f
            imports[ic.from_region][t] -= f
    return imports


def solve_region(job):
    region, gens, demand, args, start, requirement = job
    options = {"threads": 1, "random_seed": args["seed"]}
    if args.get("log"):
        options.update(log_file=args["log"], log_to_console=False, msg=True)
    sub = UCParameters(generators=gens, demand=DemandProfile(demands=demand),
                       time_horizon=TimeHorizon(num_periods=len(demand)), reserve_margin=args["reserve"],
                       solver_name="HiGHS", solver_time_limit_s=args["time_limit"], mip_gap=args["gap"],
                       solver_options=options, strengthen=args["strengthen"],
                       warm_start_schedules=start, reserve_requirement_mw=requirement)
    begin, wall = time.monotonic(), time.time()
    r = solve_uc(sub)
    return region, time.monotonic() - begin, r.summary, [asdict(s) for s in r.schedules], wall


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--units", type=int, default=800)
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--scenario", help="national scenario name (24 h) instead of the synthetic case")
    ap.add_argument("--log-dir", type=Path, help="write each region's HiGHS log here")
    ap.add_argument("--strengthen", nargs="*", default=["startup_type"], choices=sorted(STRENGTHEN_OPTIONS))
    ap.add_argument("--flows-from", choices=["lp", "rolling"], default="lp")
    ap.add_argument("--lp-time-limit", type=float, default=1800)
    ap.add_argument("--rolling-time-limit", type=float, default=300)
    ap.add_argument("--reserve-split", choices=["own", "stage1"], default="own",
                    help="own: each region holds the margin on its own net demand; stage1: the system "
                         "reserve is split in proportion to the headroom each region had in the stage-1 schedule")
    ap.add_argument("--warm-start-regions", action="store_true",
                    help="with --flows-from rolling, start each region's MILP from its part of the rolling schedule")
    ap.add_argument("--region-time-limit", type=float, default=300)
    ap.add_argument("--gap", type=float, default=0.001)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    begin = time.monotonic()

    def case():
        if args.scenario:
            return build_national_scenario(scenario=args.scenario).to_uc_parameters()
        return synthetic_case(args.units, args.hours, args.seed)
    params = case()
    input_sha = hashlib.sha256(json.dumps(asdict(params), sort_keys=True, default=str).encode()).hexdigest()
    params.strengthen = tuple(args.strengthen)

    # Stage 1: tie-line flows from the national LP relaxation (also a lower bound) or a rolling schedule
    t0 = time.monotonic()
    rolling_schedules = {}
    if args.flows_from == "lp":
        lp = case()
        lp.strengthen = tuple(args.strengthen)
        lp.solver_name, lp.solver_time_limit_s = "HiGHS", args.lp_time_limit
        lp.solver_options = {"mip": False, "threads": 1}
        lp_result = solve_uc(lp)
        flows = {f.interconnection_id: list(f.flow_mw) for f in lp_result.interconnection_flows}
        stage1 = {"source": "lp", "objective": lp_result.dual_bound, "status": lp_result.status,
                  "termination": lp_result.termination_reason}
    else:
        import numpy as np
        roll = solve_rolling_uc(params.generators, np.asarray(params.demand.demands),
            {r: np.asarray(v) for r, v in params.regional_demands.items()}, params.interconnections,
            RollingUCConfig(window_h=24, step_h=24, reserve_margin=params.reserve_margin, mip_gap=0.02,
                            solver_name="HiGHS", retry_gaps=(), solver_time_limit_s=args.rolling_time_limit,
                            solver_options={"threads": 1, "random_seed": args.seed}), progress=False)
        if not roll.is_complete:
            raise SystemExit(f"stage 1 rolling failed: {roll.status}")
        flows = {k: list(v) for k, v in roll.interconnection_flows.items()}
        rolling_schedules = roll.schedules
        stage1 = {"source": "rolling", "objective": None, "rolling_upper_bound": roll.primal_bound, "status": roll.status}
    lp_seconds = time.monotonic() - t0
    stage1["seconds"] = lp_seconds
    if set(flows) != {ic.id for ic in params.interconnections}:
        raise SystemExit(f"stage 1 gave no flows: {lp_result.summary}")
    imports = net_imports(params, flows)

    # Reserve split: each region's committed capacity requirement per hour
    T = params.time_horizon.num_periods
    nets = {r: [d - imp for d, imp in zip(dem, imports[r])] for r, dem in params.regional_demands.items()}
    requirements = {r: None for r in params.regional_demands}
    if args.reserve_split == "stage1":
        if not rolling_schedules:
            raise SystemExit("--reserve-split stage1 needs --flows-from rolling")
        cap = {g.id: g.capacity_mw for g in params.generators}
        region_of = {g.id: g.region for g in params.generators}
        for t in range(T):
            committed = {r: 0.0 for r in nets}
            for gid, sched in rolling_schedules.items():
                committed[region_of[gid]] += cap[gid] * sched.commitment[t]
            headroom = {r: max(committed[r] - nets[r][t], 0.0) for r in nets}
            total = sum(headroom.values())
            need = params.reserve_margin * params.demand.demands[t]
            for r in nets:
                if requirements[r] is None:
                    requirements[r] = [0.0] * T
                share = headroom[r] / total if total > 0 else 1.0 / len(nets)
                requirements[r][t] = nets[r][t] + need * share

    # Stage 2: one MILP per region with the flows fixed
    jobs = []
    for region, demand in params.regional_demands.items():
        gens = [g for g in params.generators if g.region == region]
        net = nets[region]
        start = ([rolling_schedules[g.id] for g in gens if g.id in rolling_schedules]
                 if args.warm_start_regions and rolling_schedules else None)
        log = None
        if args.log_dir:
            args.log_dir.mkdir(parents=True, exist_ok=True)
            log = str(args.log_dir / f"{region}.solver.log")
        jobs.append((region, gens, net, {"reserve": params.reserve_margin, "time_limit": args.region_time_limit,
                                          "gap": args.gap, "seed": args.seed, "strengthen": tuple(args.strengthen),
                                          "log": log}, start, requirements[region]))
    t1, t1_wall = time.monotonic(), time.time()
    with ProcessPoolExecutor(max_workers=len(jobs)) as pool:
        regions = list(pool.map(solve_region, jobs))
    stage2_seconds = time.monotonic() - t1

    # Join and check against the full model
    schedules = [GeneratorSchedule(**s) for _, _, _, ss, _ in regions for s in ss]
    joined = UCResult(schedules=schedules,
                      interconnection_flows=[InterconnectionFlow(k, v) for k, v in flows.items()],
                      regional_spill_mw={r: [0.0] * T for r in params.regional_demands})
    validation = validate_uc_solution(params, joined, check_objective=False)
    report = {
        "schema_version": 1, "kind": "staged_regions",
        "provenance": f"scenario_{args.scenario}_assumed_day" if args.scenario else "synthetic_not_observed",
        "case_id": (f"scenario-{args.scenario}" if args.scenario else
                    f"synthetic-uc-v1-n{args.units}-t{args.hours}-seed{args.seed}"), "input_sha256": input_sha,
        "strengthen": list(args.strengthen), "warm_start_regions": args.warm_start_regions,
        "reserve_split": args.reserve_split,
        "stage1": stage1,
        "fixed_flows": {k: [round(x, 1) for x in v] for k, v in flows.items()},
        "stage2": [{"region": reg, "seconds": sec, "started_s": wall - t1_wall, "status": s["status"],
                    "termination": s.get("termination_reason"),
                    "primal_bound": s.get("primal_bound"), "dual_bound": s.get("dual_bound"), "gap": s.get("gap"),
                    "verified": s.get("feasibility_verified"), "units": sum(1 for x in ss if not x["generator_id"].startswith("storage"))}
                   for reg, sec, s, ss, wall in regions],
        "stage2_wall_seconds": stage2_seconds,
        "joined": {"passed": validation["passed"], "violations": validation["violation_count"],
                   "errors": validation["errors"][:10], "objective": validation.get("objective")},
        "wall_seconds": time.monotonic() - begin,
    }
    if validation["passed"] and stage1.get("objective"):
        report["joined"]["gap_to_stage1_lp"] = (validation["objective"] - stage1["objective"]) / validation["objective"]
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"stage1": stage1, "joined": report["joined"].get("objective"),
                      "passed": validation["passed"], "gap": report["joined"].get("gap_to_stage1_lp"),
                      "stage2_wall": round(stage2_seconds), "wall": round(report["wall_seconds"])}))


if __name__ == "__main__":
    main()
