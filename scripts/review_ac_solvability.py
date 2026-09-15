#!/usr/bin/env python3
"""Replay the frozen east AC/Ybus review without altering the production model."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ajg-ac-review-mpl")
REPORT = ROOT / "docs/reports/codex_ac_diagnosis_2026-09-15"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_inputs(report):
    import pandapower as pp
    manifest = json.loads((report / "input_metadata.json").read_text())
    path = report / "input_network.json.gz"
    if digest(path) != manifest["baseline_network_sha256"]:
        raise ValueError("Frozen circuit SHA256 mismatch")
    net = pp.from_json_string(gzip.decompress(path.read_bytes()).decode())
    if pp.__version__ != manifest["pandapower"]:
        raise ValueError(f"Replay requires pandapower {manifest['pandapower']}; got {pp.__version__}")
    branch = json.loads((report / "branch_plan.json").read_text())
    identities = json.loads((report / "load_identity_plan.json").read_text())
    for filename in ("branch_plan.json", "load_identity_plan.json"):
        if digest(report / filename) != manifest["plan_sha256"][filename]:
            raise ValueError(f"Plan SHA256 mismatch: {filename}")
    return net, branch, identities


def replay(report, output):
    import networkx as nx
    import numpy as np
    import pandapower as pp
    from pandapower.topology import create_nxgraph
    from scripts.solve_same_site_trial import safe
    from src.powerflow.ac_validation import (
        strict_ac, ybus_diagnosis, restore_source_branch, identity_load_trial, trace_q_switching)
    base, plan, identities = read_inputs(report)
    split, _ = restore_source_branch(base, plan, add_branch=False)
    restored, branch_ledger = restore_source_branch(base, plan)
    corrected, load_ledger = identity_load_trial(restored, identities["groups"])
    variants = dict(before=base, split_only=split, branch_restored=restored,
                    branch_and_identity_load=corrected)
    result = dict(pandapower=pp.__version__, complete=False, variants={},
                  branch_ledger=branch_ledger, load_ledger=load_ledger,
                  definition="All original buses, loads, generators and branches retained. "
                  "Identity weighting changes synthetic load location and estimated local "
                  "shunts, while preserving each zone's P/Q. Slacks remain synthetic assumptions.")
    output.mkdir(parents=True, exist_ok=True)

    def save():
        (output / "results.json").write_text(json.dumps(safe(result), ensure_ascii=False,
                                                       indent=2, allow_nan=False) + "\n")
    for name, net in variants.items():
        print(f"Checking {name}", flush=True)
        row = dict(buses=len(net.bus), lines=len(net.line), trafos=len(net.trafo),
                   components=nx.number_connected_components(create_nxgraph(net)),
                   generator_mw=float(net.gen.p_mw.sum()))
        for table in ("gen", "ext_grid", "trafo"):
            assert net[table].equals(base[table]), f"Unexpected mutation: {table}"
        assert net.bus.in_service.all() and net.line.in_service.all()
        for constrained in (True, False):
            solved, metrics = strict_ac(net, enforce_q_lims=constrained)
            key = "strict_q" if constrained else "unbounded_q_diagnostic"
            if metrics["converged"]:
                metrics["osato_line_1129"] = solved.res_line.loc[1129].to_dict()
                metrics["osato_trafo_126"] = solved.res_trafo.loc[126].to_dict()
                metrics["lowest_voltage_buses"] = [
                    dict(bus=int(b), name=solved.bus.at[b, "name"], vm_pu=float(v))
                    for b, v in solved.res_bus.vm_pu.nsmallest(15).items()]
            row[key] = metrics
        if name in ("before", "branch_and_identity_load"):
            row["ybus"] = ybus_diagnosis(net)
            row["q_transition_trace"] = trace_q_switching(net)
        result["variants"][name] = row
        save()
    # Splitting is DC-series equivalent, but pi charging is relocated in AC.
    a, b = copy.deepcopy(base), copy.deepcopy(split)
    pp.rundcpp(a)
    pp.rundcpp(b)
    ids = base.line.index
    result["split_only_control"] = dict(
        dc_max_original_line_delta_mw=float(abs(a.res_line.loc[ids, "p_from_mw"]-
                                                  b.res_line.loc[ids, "p_from_mw"]).max()),
        ac_note="Series length, R/X and total charging C preserved; pi segmentation "
                "changes charging location. AC control reported separately.")
    # A continuation is an operating-point sensitivity, NOT target-load success.
    result["strict_operating_point_ramp"] = []
    previous = None
    for alpha in (.05, .2, .4, .6, .8, .9, 1.):
        n = copy.deepcopy(corrected)
        for table, cols in (("load", ["p_mw", "q_mvar"]), ("gen", ["p_mw"]),
                            ("shunt", ["q_mvar"])):
            n[table][cols] *= alpha
        if previous is not None:
            n.res_bus = previous.res_bus.copy()
        solved, metrics = strict_ac(n, init="results" if previous is not None else "dc")
        metrics["operating_point_fraction"] = alpha
        result["strict_operating_point_ramp"].append(metrics)
        previous = solved if metrics["converged"] else None
        save()
        if not metrics["converged"]:
            break
    result["complete"] = True
    save()
    print(output / "results.json")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["summary", "verify", "replay"])
    p.add_argument("--report", type=Path, default=REPORT)
    p.add_argument("--out", type=Path, default=Path("/tmp/ajg-ac-replay"))
    args = p.parse_args()
    if args.command == "replay":
        if args.out.resolve() == args.report.resolve():
            p.error("Replay output must differ from the published evidence directory")
        replay(args.report, args.out)
    elif args.command == "verify":
        manifest = json.loads((args.report / "manifest.json").read_text())
        bad = [name for name, sha in manifest.items()
               if not (args.report/name).is_file() or digest(args.report/name) != sha]
        if bad:
            raise SystemExit("Evidence mismatch: " + ", ".join(bad))
        print(f"Verified {len(manifest)} evidence files")
    else:
        r = json.loads((args.report / "results.json").read_text())
        for name, v in r["variants"].items():
            print(name, "strict AC:", v["strict_q"]["converged"],
                  "Q-unbounded AC:", v["unbounded_q_diagnostic"]["converged"])
        print("Unbounded-Q convergence or a reduced operating point is not target feasibility.")


if __name__ == "__main__":
    main()
