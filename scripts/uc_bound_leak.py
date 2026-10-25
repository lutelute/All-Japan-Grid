"""Where does the LP lower bound lose cost? Compare the LP relaxation with a known schedule.

Builds the synthetic UC MILP, solves (1) its LP relaxation and (2) the same LP with the
commitment u fixed to a saved verified schedule, and splits both objectives by cost term
(fuel p, no-load u, shutdown w, startup by type y_*, spill). Run on a compute host:

    python -m scripts.uc_bound_leak --hours 48 --solution run.solution.json.gz --out leak.json
"""

import argparse
from collections import defaultdict
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time

import highspy
import numpy as np

import src.uc.solver as uc_solver
from src.uc.benchmark_cases import synthetic_case
from src.uc.models import STRENGTHEN_OPTIONS

TERMS = {"p": "fuel", "u": "no_load", "w": "shutdown", "v": "startup_single",
         "y_hot": "startup_hot", "y_warm": "startup_warm", "y_cold": "startup_cold"}
NAME = re.compile(r"^(?P<kind>[a-z_]+?)_\('(?P<gen>.+?)',_(?P<t>\d+)\)$")


class _Exported(Exception):
    pass


def export_mps(params, path):
    """Write the MILP with the production builder; stop before any solver is chosen."""
    def stop(_params):
        raise _Exported
    original = uc_solver._select_solver
    uc_solver._select_solver = stop
    params.model_export_path = str(path)
    try:
        uc_solver.solve_uc(params)
    except _Exported:
        pass
    finally:
        uc_solver._select_solver = original


def solve_lp(path, fixed_u=None):
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("threads", 1)
    h.readModel(str(path))
    lp = h.getLp()
    n = lp.num_col_
    names = list(lp.col_names_)
    h.changeColsIntegrality(n, np.arange(n, dtype=np.int32), np.zeros(n, dtype=np.uint8))
    if fixed_u is not None:
        idx, val = [], []
        for j, name in enumerate(names):
            m = NAME.match(name)
            if m and m["kind"] == "u":
                idx.append(j)
                val.append(float(fixed_u[m["gen"]][int(m["t"])]))
        idx = np.asarray(idx, dtype=np.int32)
        val = np.asarray(val, dtype=np.float64)
        h.changeColsBounds(len(idx), idx, val, val)
    highspy.Highs.resetGlobalScheduler(True)
    begin = time.monotonic()
    h.run()
    seconds = time.monotonic() - begin
    status = h.modelStatusToString(h.getModelStatus())
    x = np.asarray(h.getSolution().col_value)
    cost = np.asarray(lp.col_cost_)
    return {"status": status, "seconds": seconds, "objective": h.getInfo().objective_function_value,
            "offset": lp.offset_}, names, x, cost


def breakdown(names, x, cost, fuel_of):
    terms = defaultdict(float)
    committed = defaultdict(float)
    fractional = defaultdict(int)
    for name, value, c in zip(names, x, cost):
        m = NAME.match(name)
        kind = m["kind"] if m else name.split("_")[0]
        terms[TERMS.get(kind, "other:" + kind)] += c * value
        if m and kind == "u" and m["gen"] in fuel_of:
            fuel = fuel_of[m["gen"]]
            committed[fuel] += value
            if 0.01 < value < 0.99:
                fractional[fuel] += 1
    return {"cost_by_term": dict(terms), "unit_hours_on_by_fuel": dict(committed),
            "fractional_u_by_fuel": dict(fractional)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--units", type=int, default=800)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--solution", type=Path, required=True, help="verified *.solution.json.gz of the same case")
    ap.add_argument("--strengthen", nargs="*", default=[], choices=sorted(STRENGTHEN_OPTIONS),
                    help="valid inequalities added to both LPs")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    params = synthetic_case(args.units, args.hours, args.seed)
    input_sha = hashlib.sha256(json.dumps(asdict(params), sort_keys=True, default=str).encode()).hexdigest()
    fuel_of = {g.id: g.fuel_type for g in params.generators if not g.is_storage}
    with gzip.open(args.solution, "rt") as f:
        saved = json.load(f)
    fixed_u = {s["generator_id"]: s["commitment"] for s in saved["schedules"]}
    with tempfile.TemporaryDirectory() as tmp:
        mps = Path(tmp) / "model.mps"
        params.strengthen = tuple(args.strengthen)  # after hashing: the input data is the same case
        export_mps(params, mps)
        relaxed, names, x, cost = solve_lp(mps)
        relaxed.update(breakdown(names, x, cost, fuel_of))
        fixed, names, x, cost = solve_lp(mps, fixed_u)
        fixed.update(breakdown(names, x, cost, fuel_of))
    report = {"schema_version": 1, "provenance": "synthetic_not_observed", "kind": "bound_leak",
              "case_id": f"synthetic-uc-v1-n{args.units}-t{args.hours}-seed{args.seed}",
              "input_sha256": input_sha, "strengthen": list(args.strengthen), "solution_file": args.solution.name,
              "solution_total_cost": saved.get("total_cost"), "solver": f"HiGHS {highspy.Highs().version()}",
              "lp_relaxation": relaxed, "commitment_fixed_lp": fixed}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: (v["objective"], v["status"], round(v["seconds"], 1))
                      for k, v in report.items() if isinstance(v, dict) and "objective" in v}))


if __name__ == "__main__":
    main()
