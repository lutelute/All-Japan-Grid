"""Summarise a difficulty sweep (units x hours x formulation) for the difficulty map.

Reads cells/<name>.json and cells/<name>.solver.log written by uc_open_solver_benchmark,
classifies each cell (proven / feasible with a gap / no solution / cut off before a report)
and keeps the gap-over-time trace from the HiGHS log. Never launches a solve.

    python -m scripts.uc_frontier_summary --cells DIR --out frontier.json
"""

import argparse
import json
from pathlib import Path
import re

from scripts.uc_explorer_report import read_log

NAME = re.compile(r"^n(?P<n>\d+)-t(?P<h>\d+)-(?P<form>\w+)$")


def gap_trace(trace):
    out = []
    for p in trace:
        if p["ub"] is not None and p["lb"] is not None and p["ub"] > 0:
            out.append([round(p["t"], 1), max(0.0, (p["ub"] - p["lb"]) / p["ub"])])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cells", type=Path, required=True)
    ap.add_argument("--target-gap", type=float, default=0.001)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    done = {}
    for line in (args.cells / "done.txt").read_text().splitlines():
        parts = line.split()
        if parts and NAME.match(parts[0]):
            done[parts[0]] = {k: v for k, v in (p.split("=") for p in parts[1:])}
    cells = []
    for name, meta in sorted(done.items()):
        m = NAME.match(name)
        cell = {"units": int(m["n"]), "hours": int(m["h"]), "form": m["form"], "exit": int(meta["exit"]),
                "wall_s": int(meta["wall"])}
        report = args.cells / f"{name}.json"
        log = read_log(args.cells / f"{name}.solver.log", "HiGHS")
        cell["binary"] = log["dimensions"].get("binary")
        cell["rows"] = log["dimensions"].get("rows")
        trace = gap_trace(log["trace"])
        cell["trace"] = trace
        if not report.exists():
            cell["outcome"] = "cut"                     # killed by the 900 s process limit (build/transfer too slow)
        else:
            r = json.loads(report.read_text())["result"]
            cell.update(primal=r.get("primal_bound"), dual=r.get("dual_bound"), gap=r.get("gap"),
                        nodes=r.get("node_count"), solve_s=r.get("solve_time_s"), build_s=r.get("build_time_s"))
            if not r.get("feasibility_verified"):
                cell["outcome"] = "none"
            elif r.get("gap") is not None and r["gap"] <= args.target_gap:
                cell["outcome"] = "proven"
            else:
                cell["outcome"] = "feasible"
            hit = next((t for t, g in trace if g <= args.target_gap), None)
            first = next((t for t, g in trace), None)
            cell["proven_at_s"], cell["first_solution_s"] = hit, first
        cells.append(cell)
    out = {"schema_version": 1, "provenance": "synthetic_not_observed", "kind": "difficulty_map",
           "target_gap": args.target_gap, "solver": "HiGHS, 1 thread, 300 s", "cells": cells}
    args.out.write_text(json.dumps(out, ensure_ascii=False) + "\n")
    for c in cells:
        print(c["units"], c["hours"], c["form"], c["outcome"], c.get("gap"), c.get("proven_at_s"), c["wall_s"])


if __name__ == "__main__":
    main()
