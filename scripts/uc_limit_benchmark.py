"""Measure the UC solvability frontier under explicit resource budgets.

Run with --execute to launch a sequential sweep. Without it, write a plan only.
Each cell is a fresh one-thread process, with solver and whole-process timeouts.
Memory limits are sampled process-tree RSS, not an OS hard allocation limit.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time

import psutil


GIB = 2 ** 30


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def stop_owned_process(proc):
    """Stop only the process group created by this controller."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    except ProcessLookupError:
        proc.wait()


def supervise(command, *, cwd, log_path, memory_bytes, wall_seconds,
              min_available_bytes, poll_seconds=0.25):
    """Return controller evidence even when a child cannot produce a report."""
    start = time.monotonic()
    peak = 0
    cpu = 0.0
    reason = None
    low_available = psutil.virtual_memory().available
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    with log_path.open("w") as log:
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while proc.poll() is None:
                elapsed = time.monotonic() - start
                try:
                    parent = psutil.Process(proc.pid)
                    processes = [parent] + parent.children(recursive=True)
                    rss = 0
                    used_cpu = 0.0
                    for child in processes:
                        try:
                            rss += child.memory_info().rss
                            times = child.cpu_times()
                            used_cpu += times.user + times.system
                        except psutil.NoSuchProcess:
                            pass
                    peak = max(peak, rss)
                    cpu = max(cpu, used_cpu)
                except psutil.NoSuchProcess:
                    continue
                available = psutil.virtual_memory().available
                low_available = min(low_available, available)
                if rss > memory_bytes:
                    reason = "memory_budget_exceeded"
                elif available < min_available_bytes:
                    reason = "system_memory_guard"
                elif elapsed > wall_seconds:
                    reason = "wall_budget_exceeded"
                if reason:
                    stop_owned_process(proc)
                    break
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            reason = "operator_interrupted"
        except (PermissionError, psutil.AccessDenied):
            reason = "monitor_unavailable"
        finally:
            stop_owned_process(proc)
    return {"controller_stop_reason": reason, "return_code": proc.returncode,
            "observed_wall_s": time.monotonic() - start,
            "sampled_peak_tree_rss_bytes": peak, "sampled_cpu_seconds": cpu,
            "minimum_system_available_bytes": low_available, "sampling_interval_s": poll_seconds}


def classify(report, evidence, target_gap):
    if evidence["controller_stop_reason"]:
        return evidence["controller_stop_reason"]
    if report is None:
        return "process_failed_without_report"
    result = report["result"]
    if result["feasibility_verified"]:
        gap = result["gap"]
        if gap is not None and gap <= target_gap:
            return "target_reached"
        return "feasible_gap_unknown" if gap is None else "feasible_above_target"
    if result["status"] == "Infeasible":
        return "infeasible_model"
    return "invalid_solution" if result["has_incumbent"] else "no_incumbent"


def render_table(cells):
    lines = ["# UC resource-bounded frontier", "",
             "Synthetic hourly zonal UC; 4 storage units are additional to the commitment-unit count.", "",
             "| Units | Hours | Solver | Start | Outcome | Last phase | Gap (%) | Wall (s) | Peak RSS (GiB) |",
             "|---:|---:|---|---|---|---|---:|---:|---:|"]
    for c in cells:
        result = c.get("result", {})
        gap = result.get("gap")
        gap_text = "unknown" if gap is None else f"{100 * gap:.4f}"
        evidence = c.get("resource_evidence", {})
        wall = evidence.get("observed_wall_s")
        rss = evidence.get("sampled_peak_tree_rss_bytes")
        start = c.get("warm_start", "none")
        lines.append(f"| {c['units']} | {c['hours']} | {c['solver']} | {start} | {c['outcome']} | "
                     f"{c.get('last_phase', 'not_started')} | {gap_text} | "
                     f"{wall:.2f} | {rss / GIB:.3f} |" if wall is not None else
                     f"| {c['units']} | {c['hours']} | {c['solver']} | {start} | {c['outcome']} | — | — | — | — |")
    lines += ["", "A resource cutoff identifies a limit of this formulation, implementation, machine, and budget.",
              "It does not prove that a larger UC instance is mathematically unsolvable.",
              "RSS is sampled and may overshoot the requested ceiling. Skipped cells are unmeasured.", ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--units", type=int, nargs="+", default=[100, 400, 800])
    ap.add_argument("--hours", type=int, nargs="+", default=[24, 48, 168, 720, 8760])
    ap.add_argument("--solvers", nargs="+", choices=["HiGHS", "SCIP"], default=["HiGHS", "SCIP"])
    ap.add_argument("--seeds", type=int, nargs="+", default=[17])
    ap.add_argument("--time-limit", type=float, default=60)
    ap.add_argument("--wall-limit", type=float, default=180)
    ap.add_argument("--total-wall-limit", type=float, default=1800)
    ap.add_argument("--memory-limit-gib", type=float, default=4)
    ap.add_argument("--min-system-available-gib", type=float, default=2)
    ap.add_argument("--gap", type=float, default=0.001)
    ap.add_argument("--warm-starts", nargs="+", choices=["none", "rolling"], default=["none"],
                    help="rolling: solve rolling windows first and pass the schedule as a MIP start")
    ap.add_argument("--rolling-window", type=int, default=24)
    ap.add_argument("--rolling-step", type=int, default=24)
    ap.add_argument("--rolling-time-limit", type=float, default=60)
    ap.add_argument("--rolling-gap", type=float, default=0.01,
                    help="per-window gap; the start needs feasibility, not window optimality")
    ap.add_argument("--strengthen", nargs="*", default=[], choices=["startup_type", "ramp"])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args(argv)
    if min(args.units) < 4 or min(args.hours) < 1:
        ap.error("units >= 4 and hours >= 1 required")
    if min(args.time_limit, args.wall_limit, args.total_wall_limit, args.memory_limit_gib) <= 0:
        ap.error("budgets must be positive")
    if args.min_system_available_gib < 0 or not 0 <= args.gap <= 1:
        ap.error("memory reserve must be nonnegative and gap in [0, 1]")
    root = Path(__file__).resolve().parents[1]
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out / "sweep.json").exists():
        ap.error("output already has a sweep; choose a new directory to preserve evidence")
    source_files = [Path(__file__), root / "scripts/uc_open_solver_benchmark.py", root / "src/__init__.py"]
    source_files += sorted((root / "src/uc").glob("*.py"))
    source_files += sorted((root / "src/model").glob("*.py"))
    source_files += sorted((root / "src/utils").glob("*.py"))
    source_bytes = {str(p.relative_to(root)): p.read_bytes() for p in source_files}
    snapshot = args.out / "source_snapshot"
    if args.execute:
        for name, contents in source_bytes.items():
            destination = snapshot / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)
    cells = [{"units": n, "hours": h, "solver": s, "seed": seed, "warm_start": ws,
              "outcome": "planned", "binary_count_6NT_reference": 6 * n * h}
             for n in sorted(set(args.units)) for h in sorted(set(args.hours))
             for seed in sorted(set(args.seeds)) for s in dict.fromkeys(args.solvers)
             for ws in dict.fromkeys(args.warm_starts)]
    manifest = {"schema_version": 1, "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "provenance": "synthetic_not_observed", "execution": args.execute,
                "scope": "empirical_frontier_for_this_model_and_budget_not_a_universal_UC_limit",
                "settings": {k: v for k, v in vars(args).items() if k != "out"},
                "environment": {"host": platform.node(), "machine": platform.machine(), "logical_cpus": os.cpu_count(),
                                "memory_total_bytes": psutil.virtual_memory().total,
                                "memory_available_bytes_at_start": psutil.virtual_memory().available},
                "source_files": {name: hashlib.sha256(contents).hexdigest()
                                 for name, contents in source_bytes.items()}, "cells": cells}
    def checkpoint():
        write_json(args.out / "sweep.json", manifest)
        (args.out / "summary.md").write_text(render_table(cells))
    checkpoint()
    if not args.execute:
        print(f"Plan written: {args.out / 'sweep.json'}; use --execute to run")
        return 0
    sweep_start = time.monotonic()
    memory_frontiers = set()
    stop_campaign = None
    for cell in cells:
        key = (cell["units"], cell["solver"], cell["seed"], cell["warm_start"])
        remaining = args.total_wall_limit - (time.monotonic() - sweep_start)
        if stop_campaign:
            cell["outcome"] = "skipped_" + stop_campaign
        elif key in memory_frontiers:
            cell["outcome"] = "skipped_after_memory_cutoff"
        elif remaining <= 1:
            cell["outcome"] = "skipped_total_wall_budget"
        elif psutil.virtual_memory().available < args.min_system_available_gib * GIB:
            cell["outcome"] = "skipped_system_memory_guard"
        else:
            stem = f"n{cell['units']}-t{cell['hours']}-{cell['solver'].lower()}-s{cell['seed']}"
            if cell["warm_start"] != "none":
                stem += "-ws" + cell["warm_start"]
            report_path = args.out / (stem + ".json")
            cmd = [sys.executable, "-m", "scripts.uc_open_solver_benchmark",
                   "--units", str(cell["units"]), "--hours", str(cell["hours"]),
                   "--solver", cell["solver"], "--seed", str(cell["seed"]),
                   "--time-limit", str(args.time_limit), "--gap", str(args.gap),
                   "--threads", "1", "--out", str(report_path)]
            if args.strengthen:
                cmd += ["--strengthen", *args.strengthen]
            if cell["warm_start"] != "none":
                cmd += ["--warm-start", cell["warm_start"],
                        "--rolling-window", str(args.rolling_window),
                        "--rolling-step", str(args.rolling_step),
                        "--rolling-time-limit", str(args.rolling_time_limit),
                        "--rolling-gap", str(args.rolling_gap)]
            print(f"Running {stem} (one CPU; RSS ceiling {args.memory_limit_gib} GiB)", flush=True)
            cell["outcome"] = "running"
            checkpoint()
            evidence = supervise(cmd, cwd=snapshot, log_path=args.out / (stem + ".runner.log"),
                                  memory_bytes=args.memory_limit_gib * GIB,
                                  wall_seconds=min(args.wall_limit, remaining),
                                  min_available_bytes=args.min_system_available_gib * GIB)
            report = json.loads(report_path.read_text()) if report_path.exists() else None
            cell["resource_evidence"] = evidence
            cell["outcome"] = classify(report, evidence, args.gap)
            progress_path = report_path.with_suffix(".progress.json")
            if progress_path.exists():
                cell["stages"] = json.loads(progress_path.read_text())["stages"]
                cell["last_phase"] = cell["stages"][-1]["stage"]
            if report:
                cell["result"] = report["result"]
                cell["input_sha256"] = report["input_sha256"]
                cell["report"] = report_path.name
                if "warm_start" in report:
                    cell["warm_start_evidence"] = report["warm_start"]
            if cell["outcome"] in ("memory_budget_exceeded", "system_memory_guard"):
                memory_frontiers.add(key)
            if cell["outcome"] in ("operator_interrupted", "monitor_unavailable"):
                stop_campaign = cell["outcome"]
            print(json.dumps({k: cell.get(k) for k in ("units", "hours", "solver", "outcome", "last_phase")}), flush=True)
        checkpoint()
    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["wall_time_s"] = time.monotonic() - sweep_start
    checkpoint()
    print(f"Sweep recorded: {args.out / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
