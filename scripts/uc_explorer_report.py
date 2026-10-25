"""Build an offline UC evidence explorer. Reads evidence; never launches a solve.

Run: .venv/bin/python -m scripts.uc_explorer_report
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from src.uc.benchmark_cases import synthetic_case


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs/research/uc800-open-solver"


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except ValueError:
        return None


def read_log(path, solver):
    text = path.read_text() if path.exists() else ""
    dimensions = {}
    match = re.search(r"MIP has (\d+) rows; (\d+) cols; (\d+) nonzeros; (\d+) integer", text)
    if match:
        dimensions = dict(zip(("rows", "columns", "nonzeros", "binary"), map(int, match.groups())))
    trace = []
    start = None
    in_start = False
    for line in text.splitlines():
        if line.startswith("Attempting to find feasible solution"):
            in_start = True
            continue
        if solver == "HiGHS":
            match = re.match(r"\s*(?:[A-Za-z]\s+)?\d+\s+\d+\s+\d+\s+[\d.]+%\s+(\S+)\s+(\S+)\s+.*?([\d.]+)s\s*$", line)
            if in_start:
                # HiGHS completes a MIP start in a sub-MIP with the start's integers
                # fixed: its incumbent is feasible here, its BestBound is not a bound here.
                if line.startswith("Solving report"):
                    in_start = False
                elif match and number(match.group(2)) is not None:
                    start = {"t": float(match.group(3)), "ub": number(match.group(2))}
                continue
            if match:
                lb, ub, seconds = match.groups()
                trace.append({"t": float(seconds), "lb": number(lb), "ub": number(ub)})
        elif "|" in line and re.match(r"\s*[a-z]?[\d.]+s\|", line):
            parts = line.split("|")
            if len(parts) >= 16:
                seconds = re.search(r"([\d.]+)s", parts[0]).group(1)
                trace.append({"t": float(seconds), "lb": number(parts[14].strip()), "ub": number(parts[15].strip())})
    # The last report is the full model; an earlier one may be the MIP-start sub-MIP.
    presolved = re.findall(r"(\d+) cols \((\d+) binary", text)
    if presolved:
        dimensions["presolved_binary"] = int(presolved[-1][1])
    if solver == "SCIP":
        match = re.search(r"feasible solution found by completesol heuristic after ([\d.]+) seconds, objective value (\S+)", text)
        if match:
            start = {"t": float(match.group(1)), "ub": number(match.group(2))}
    return {"dimensions": dimensions, "trace": trace, "start": start, "present": path.exists(),
            "presolve_timeout": "Presolve: Time limit reached" in text,
            "large_cost_warning": "excessively large costs" in text}


def collect(results):
    reports = []
    for path in sorted(results.rglob("*.json")):
        data = json.loads(path.read_text())
        # Other evidence (e.g. LP probes) may sit beside the solver reports.
        if not isinstance(data, dict) or data.get("provenance") != "synthetic_not_observed" or "case_id" not in data or "result" not in data:
            continue
        data["hours"] = int(re.search(r"-t(\d+)-", data["case_id"]).group(1))
        data["evidence_file"] = path.relative_to(RESEARCH).as_posix()
        log = path.with_suffix(".solver.log")
        data["log_file"] = log.relative_to(RESEARCH).as_posix() if log.exists() else None
        data["log"] = read_log(log, data["settings"]["solver"])
        solution = path.parent / data.get("solution_file", "missing.solution")
        data["solution_available"] = solution.is_file()
        data["evidence_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        data["record_kind"] = "solver_report"
        reports.append(data)
    for path in sorted(results.rglob("sweep.json")):
        sweep = json.loads(path.read_text())
        for cell in sweep.get("cells", []):
            report = next((r for r in reports if Path(r["evidence_file"]).parent == path.relative_to(RESEARCH).parent
                           and r["hours"] == cell["hours"] and r["settings"]["solver"] == cell["solver"]
                           and r["settings"]["seed"] == cell["seed"] and r["commitment_units"] == cell["units"]
                           and r["settings"].get("warm_start", "none") == cell.get("warm_start", "none")), None)
            if report:
                report["controller_outcome"] = cell["outcome"]
                report["resource_evidence"] = cell.get("resource_evidence", {})
            elif cell.get("resource_evidence"):
                evidence = cell["resource_evidence"]
                peer = next((r for r in reports if Path(r["evidence_file"]).parent == path.relative_to(RESEARCH).parent), None)
                host = peer["environment"]["host"] if peer else sweep["environment"].get("host", "unknown")
                reports.append({"record_kind": "controller_report", "hours": cell["hours"],
                    "case_id": f"synthetic-uc-v1-n{cell['units']}-t{cell['hours']}-seed{cell['seed']}",
                    "commitment_units": cell["units"], "storage_units": 4,
                    "environment": {**sweep["environment"], "host": host},
                    "settings": {"solver": cell["solver"], "seed": cell["seed"], "threads": 1,
                                 "warm_start": cell.get("warm_start", "none"),
                                 "time_limit_s": sweep["settings"]["time_limit"], "requested_gap": sweep["settings"]["gap"]},
                    "controller_outcome": cell["outcome"], "result": {}, "validation": {},
                    "wall_time_s": evidence["observed_wall_s"],
                    "peak_rss_bytes": evidence["sampled_peak_tree_rss_bytes"],
                    "resource_evidence": evidence, "stages": cell.get("stages", []),
                    "evidence_file": path.relative_to(RESEARCH).as_posix(),
                    "solution_available": False, "log": {"trace": [], "dimensions": {}},
                    "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for r in reports:
        r["settings"].setdefault("warm_start", "none")
    return sorted(reports, key=lambda r: (r["environment"]["host"], r["hours"], r["settings"]["solver"],
                                          r["settings"]["warm_start"]))


def build_payload():
    reports = collect(RESEARCH / "results")
    params = synthetic_case(800, 24, 17)
    canonical = json.dumps(asdict(params), sort_keys=True, default=str).encode()
    input_hash = hashlib.sha256(canonical).hexdigest()
    matched = [r["evidence_file"] for r in reports if r.get("input_sha256") == input_hash]
    if not matched:
        raise ValueError("Regenerated inputs do not match any saved run; do not label the diagram as its input.")
    units = [{k: getattr(g, k) for k in ("id", "region", "fuel_type", "capacity_mw", "p_min_mw",
              "min_up_time_h", "min_down_time_h", "ramp_up_mw_per_h", "fuel_cost_per_mwh")}
             for g in params.generators if not g.is_storage]
    zones = []
    for region, demand in params.regional_demands.items():
        generators = [g for g in params.generators if g.region == region]
        storage = next(g for g in generators if g.is_storage)
        zones.append({"id": region, "units": sum(not g.is_storage for g in generators),
                      "capacity": sum(g.capacity_mw for g in generators if not g.is_storage),
                      "demand": demand, "storage_mw": storage.capacity_mw,
                      "storage_mwh": storage.storage_capacity_mwh})
    sources = ["src/uc/benchmark_cases.py", "src/uc/solver.py", "src/uc/constraints.py", "src/uc/validation.py"]
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "runs": reports,
            "input_sha256": input_hash, "input_matches": matched, "units": units, "zones": zones,
            "links": [{"id": ic.id, "from": ic.from_region, "to": ic.to_region,
                       "capacity": ic.capacity_mw} for ic in params.interconnections],
            "source_sha256": {s: hashlib.sha256((ROOT / s).read_bytes()).hexdigest() for s in sources}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=RESEARCH / "explorer.html")
    args = parser.parse_args()
    payload = build_payload()
    template = Path(__file__).with_name("templates") / "uc_explorer.html"
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    assert template.read_text().count("__UC_EXPLORER_DATA__") == 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(template.read_text().replace("__UC_EXPLORER_DATA__", serialized))
    print(f"{args.out}: {len(payload['runs'])} evidence records; input hash verified; no solve launched")


if __name__ == "__main__":
    main()
