"""Reproducible bounded synthetic UC solve; never labels synthetic units observed.

Run from the repository root: python -m scripts.uc_open_solver_benchmark --help
Native solver time includes presolve/search; wall time also includes build and audit.
With --warm-start rolling, a rolling-horizon schedule of the same case is solved
first, checked over the full horizon, and handed to the solver as a MIP start.
Its time is reported separately; the solver time limit covers only the full solve.
"""

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np

from src.uc.benchmark_cases import synthetic_case
from src.uc.models import GeneratorSchedule
from src.uc.models import STRENGTHEN_OPTIONS
from src.uc.rolling import RollingUCConfig, solve_rolling_uc
from src.uc.solver import solve_uc


def option_value(text):
    """'true'/'false' -> bool, then int, then float, else the string (HiGHS option types)."""
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def load_schedules(path):
    with gzip.open(path, "rt") as f:
        return [GeneratorSchedule(**s) for s in json.load(f)["schedules"]]


def apply_initial_state(params, path, hour):
    """Start from a saved verified schedule's state at the end of `hour` (on/off streaks, output, SOC).

    The saved run must start with every unit off for max(cold_start_h, 1) hours (the synthetic default).
    """
    with gzip.open(path, "rt") as f:
        saved = {s["generator_id"]: s for s in json.load(f)["schedules"]}
    commitment, history, power, gens = {}, {}, {}, []
    for g in params.generators:
        s = saved[g.id]
        u = s["commitment"][:hour + 1]
        run = 1
        while run < len(u) and u[-1 - run] == u[-1]:
            run += 1
        if run == len(u) and not u[-1]:
            run += max(g.cold_start_h, 1)      # off since before the saved horizon
        commitment[g.id] = int(u[-1])
        history[g.id] = run if u[-1] else -run
        power[g.id] = float(s["power_output_mw"][hour])
        if g.is_storage and s["soc_mwh"]:
            g = replace(g, initial_soc_fraction=min(1.0, max(0.0, s["soc_mwh"][hour] / g.storage_capacity_mwh)))
        gens.append(g)
    params.generators = gens
    params.initial_commitment, params.initial_history_h, params.initial_power_mw = commitment, history, power


def rolling_start(params, args):
    """Solve the same case by rolling windows; return (schedules or None, evidence)."""
    begin = time.monotonic()
    options = {"threads": 1, "random_seed": args.seed} if args.rolling_solver == "HiGHS" else {
        "options": [f"randomization/randomseedshift={args.seed}"]}
    config = RollingUCConfig(window_h=args.rolling_window, step_h=args.rolling_step,
        reserve_margin=params.reserve_margin, mip_gap=args.rolling_gap,
        solver_name=args.rolling_solver, retry_gaps=(),
        solver_time_limit_s=args.rolling_time_limit, solver_options=options)
    roll = solve_rolling_uc(params.generators, np.asarray(params.demand.demands),
        {r: np.asarray(v) for r, v in params.regional_demands.items()},
        params.interconnections, config, progress=False)
    evidence = {"method": "rolling", "solver": args.rolling_solver,
        "window_h": args.rolling_window, "step_h": args.rolling_step,
        "per_window_time_limit_s": args.rolling_time_limit, "per_window_gap": args.rolling_gap,
        "status": roll.status, "feasibility_verified": roll.feasibility_verified,
        "primal_bound": roll.primal_bound, "n_windows": roll.n_windows,
        "failed_window": roll.failed_window, "window_statuses": roll.window_statuses,
        "window_gaps": [w.get("gap") for w in roll.window_summaries],
        "window_times_s": roll.window_times_s, "wall_s": time.monotonic() - begin,
        "scope": "upper_bound_only_rolling_windows_prove_no_lower_bound"}
    return (list(roll.schedules.values()) if roll.is_complete else None), evidence


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--units", type=int, default=800)
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--start-hour", type=int, default=0, help="first hour of the synthetic demand profile")
    ap.add_argument("--initial-state", type=Path, help="saved *.solution.json.gz whose state starts this case")
    ap.add_argument("--initial-state-hour", type=int, help="hour of the saved schedule to start from")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--solver", choices=["HiGHS", "SCIP"], default="SCIP")
    ap.add_argument("--time-limit", type=float, default=60)
    ap.add_argument("--gap", type=float, default=0.001)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--export-mps", type=Path)
    ap.add_argument("--warm-start", choices=["none", "rolling", "file"], default="none")
    ap.add_argument("--warm-start-file", type=Path, help="saved *.solution.json.gz of the same case (with --warm-start file)")
    ap.add_argument("--highs-option", action="append", default=[], metavar="NAME=VALUE",
                    help="extra HiGHS option, e.g. presolve=off or mip_heuristic_effort=0.3 (repeatable)")
    ap.add_argument("--scip-param", action="append", default=[], metavar="NAME=VALUE",
                    help="extra SCIP parameter, e.g. presolving/maxrounds=0 (repeatable)")
    ap.add_argument("--rolling-solver", choices=["HiGHS", "SCIP"], default="HiGHS")
    ap.add_argument("--rolling-window", type=int, default=24)
    ap.add_argument("--rolling-step", type=int, default=24)
    ap.add_argument("--rolling-time-limit", type=float, default=60)
    ap.add_argument("--rolling-gap", type=float, default=0.01)
    ap.add_argument("--strengthen", nargs="*", default=[], choices=sorted(STRENGTHEN_OPTIONS),
                    help="valid inequalities for the full-horizon MILP (the rolling start is unchanged)")
    args = ap.parse_args(argv)
    if args.threads < 1 or (args.solver == "SCIP" and args.threads != 1):
        ap.error("SCIP serial uses one thread; use independent runs or UG for parallel experiments")
    if args.time_limit <= 0 or not 0 <= args.gap <= 1:
        ap.error("time limit must be positive and gap must be in [0, 1]")
    if not 0 < args.rolling_step <= args.rolling_window or args.rolling_time_limit <= 0:
        ap.error("rolling requires 0 < step <= window and a positive window time limit")
    if (args.initial_state is None) != (args.initial_state_hour is None):
        ap.error("--initial-state and --initial-state-hour go together")
    if (args.warm_start == "file") != (args.warm_start_file is not None):
        ap.error("--warm-start file needs --warm-start-file, and the reverse")
    if args.initial_state and args.warm_start == "rolling":
        ap.error("the rolling start assumes every unit starts off; do not combine it with --initial-state")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    log_path = args.out.with_suffix(".solver.log")
    begin = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    stages = []
    progress_path = args.out.with_suffix(".progress.json")
    def progress(stage, **metrics):
        stages.append({"stage": stage, "elapsed_s": time.monotonic() - begin, **metrics})
        temporary = progress_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"stages": stages}, indent=2) + "\n")
        temporary.replace(progress_path)

    progress("input")
    params = synthetic_case(args.units, args.hours, args.seed, start_hour=args.start_hour)
    if args.initial_state:
        apply_initial_state(params, args.initial_state, args.initial_state_hour)
    canonical = asdict(params)
    canonical_bytes = json.dumps(canonical, sort_keys=True, default=str).encode()
    warm_start = None
    if args.warm_start == "rolling":
        progress("warm_start")
        params.warm_start_schedules, warm_start = rolling_start(params, args)
        progress("warm_start_done", status=warm_start["status"],
                 primal_bound=warm_start["primal_bound"], wall_s=warm_start["wall_s"])
    elif args.warm_start == "file":
        params.warm_start_schedules = load_schedules(args.warm_start_file)
        warm_start = {"method": "file", "file": args.warm_start_file.name, "primal_bound": None,
                      "status": "loaded", "wall_s": 0.0}
    params.strengthen = tuple(args.strengthen)  # after hashing: same input data, stronger model
    params.solver_name = args.solver
    params.solver_time_limit_s = args.time_limit
    params.mip_gap = args.gap
    params.model_export_path = str(args.export_mps) if args.export_mps else None
    if args.solver == "HiGHS":
        params.solver_options = {"threads": args.threads, "random_seed": args.seed,
                                 "log_file": str(log_path), "log_to_console": False, "msg": True}
        for item in args.highs_option:
            name, value = item.split("=", 1)
            params.solver_options[name] = option_value(value)
    else:
        params.solver_options = {"logPath": str(log_path),
            "options": [f"randomization/randomseedshift={args.seed}"] + list(args.scip_param)}
    result = solve_uc(params, progress_callback=progress)
    elapsed = time.monotonic() - begin
    usage = resource.getrusage(resource.RUSAGE_SELF)
    versions = {}
    for package in ("pulp", "highspy", "pyscipopt"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    if versions["pyscipopt"]:
        import pyscipopt
        scip = pyscipopt.Model()
        versions["scip"] = f"{scip.getMajorVersion()}.{scip.getMinorVersion()}.{scip.getTechVersion()}"
    report = {
        "schema_version": 1, "provenance": "synthetic_not_observed",
        "started_at_utc": started_at, "stages": stages,
        "case_id": f"synthetic-uc-v1-n{args.units}-t{args.hours}-seed{args.seed}"
                   + (f"-from{args.start_hour}" if args.start_hour else "")
                   + ("-warmstate" if args.initial_state else ""),
        "input_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "commitment_units": args.units, "storage_units": 4,
        "ybus_gate": "not_applicable_synthetic_transport_model_no_grid_data_consumed",
        "model_semantics": "hourly_zonal_transport_capacity_reserve_truncated_terminal_min_times",
        "settings": {"solver": args.solver, "time_limit_s": args.time_limit,
                     "requested_gap": args.gap, "threads": args.threads, "seed": args.seed,
                     "warm_start": args.warm_start, "strengthen": list(args.strengthen),
                     "highs_options": list(args.highs_option), "scip_params": list(args.scip_param)},
        "environment": {"host": platform.node(), "machine": platform.machine(),
                        "python": platform.python_version(), "logical_cpus": os.cpu_count(),
                        "versions": versions},
        "result": result.summary, "validation": result.validation,
        "wall_time_s": elapsed, "cpu_time_s": usage.ru_utime + usage.ru_stime,
        "peak_rss_bytes": usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "warnings": result.warnings,
    }
    if warm_start is not None:
        start, final = warm_start["primal_bound"], result.primal_bound
        warm_start["used"] = params.warm_start_schedules is not None
        warm_start["final_minus_start"] = (final - start
            if warm_start["used"] and start is not None and final is not None else None)
        report["warm_start"] = warm_start
    if args.export_mps:
        report["mps_sha256"] = hashlib.sha256(args.export_mps.read_bytes()).hexdigest()
    solution_path = args.out.with_suffix(".solution.json.gz")
    with gzip.open(solution_path, "wt", encoding="utf-8") as f:
        json.dump(asdict(result), f, ensure_ascii=False, allow_nan=False)
    report["solution_file"] = solution_path.name
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"report": str(args.out), **result.summary}, ensure_ascii=False))
    return 0 if result.feasibility_verified else 2


if __name__ == "__main__":
    raise SystemExit(main())
