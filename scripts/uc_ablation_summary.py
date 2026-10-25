"""Summarise a technique ablation (one case x many solver settings) against seed-to-seed spread.

Reads runs/<case>-<technique>.json written by uc_open_solver_benchmark and, per case, puts each
technique's gap and bounds next to the range the default settings give with different random
seeds (default, seed1, seed2). With three seeds that range is itself rough, so a technique only
counts as better or worse when it lands outside it by more than --margin. Never launches a solve.

    python -m scripts.uc_ablation_summary --runs DIR --out ablation.json
"""

import argparse
import json
from pathlib import Path
import re

NAME = re.compile(r"^(?P<case>n\d+-t\d+)-(?P<tech>[\w.-]+)$")
SEEDS = ("default", "seed1", "seed2")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--margin", type=float, default=0.0005, help="gap difference beyond the seed range (0.0005 = 0.05 pt)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    cases = {}
    for path in sorted(args.runs.glob("*.json")):
        m = NAME.match(path.stem)
        report = json.loads(path.read_text())
        if not m or not isinstance(report, dict) or "result" not in report:
            continue
        r = report["result"]
        ws = report.get("warm_start") or {}
        cases.setdefault(m["case"], {})[m["tech"]] = {
            "solver": report.get("settings", {}).get("solver") or ("SCIP" if "scip" in m["tech"] else "HiGHS"),
            "ub": r.get("primal_bound"), "lb": r.get("dual_bound"), "gap": r.get("gap"), "nodes": r.get("node_count"),
            "verified": r.get("feasibility_verified"), "solve_s": r.get("solve_time_s"),
            "start_ub": ws.get("primal_bound") if isinstance(ws, dict) else None}
    out = {"schema_version": 1, "provenance": "synthetic_not_observed", "kind": "technique_ablation",
           "margin": args.margin, "cases": {}}
    for case, techs in cases.items():
        seeds = [techs[s]["gap"] for s in SEEDS if s in techs and techs[s]["gap"] is not None]
        lo, hi = (min(seeds), max(seeds)) if seeds else (None, None)
        for name, t in techs.items():
            g = t["gap"]
            t["verdict"] = ("seed" if name in SEEDS else "none" if g is None or lo is None else
                            "better" if g < lo - args.margin else "worse" if g > hi + args.margin else "within_seed_range")
        out["cases"][case] = {"seed_gap_range": [lo, hi], "techniques": techs}
        for name, t in sorted(techs.items(), key=lambda kv: kv[1]["gap"] if kv[1]["gap"] is not None else 9):
            print(case, f"{name:22s}", f"{t['gap'] * 100:.3f}%" if t["gap"] is not None else "-", t["verdict"])
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
