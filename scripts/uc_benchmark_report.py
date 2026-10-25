"""Render a self-contained HTML report from measured UC runs and sweep evidence."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def collect(results):
    reports = []
    sweeps = []
    for path in sorted(results.rglob("*.json")):
        data = json.loads(path.read_text())
        # Other evidence (e.g. LP probes) may sit beside the solver reports.
        if not isinstance(data, dict) or data.get("provenance") != "synthetic_not_observed":
            continue
        if "result" in data and "case_id" in data:
            data["evidence_file"] = "results/" + str(path.relative_to(results))
            data["hours"] = int(data["case_id"].split("-t")[1].split("-")[0])
            reports.append(data)
        elif "cells" in data:
            sweeps.append((path, data))
    # Include cutoffs that could not produce an ordinary solver report.
    for path, sweep in sweeps:
        host = sweep["environment"].get("host", sweep.get("host_label", "unknown"))
        for cell in sweep["cells"]:
            if cell["outcome"] in ("planned", "running") or cell["outcome"].startswith("skipped_"):
                continue
            # Match by folder: a sweep and its solver reports are written side by side.
            folder = Path("results") / path.relative_to(results).parent
            existing = next((r for r in reports if Path(r["evidence_file"]).parent == folder
                             and r["hours"] == cell["hours"] and r["settings"]["solver"] == cell["solver"]
                             and r["settings"]["seed"] == cell["seed"]
                             and r["commitment_units"] == cell["units"]
                             and r["settings"].get("warm_start", "none") == cell.get("warm_start", "none")), None)
            if existing:
                existing["controller_outcome"] = cell["outcome"]
                existing["resource_evidence"] = cell.get("resource_evidence", {})
                continue
            if "resource_evidence" not in cell:
                continue
            resource = cell["resource_evidence"]
            reports.append({"case_id": f"synthetic-uc-v1-n{cell['units']}-t{cell['hours']}-seed{cell['seed']}",
                            "hours": cell["hours"], "commitment_units": cell["units"],
                            "environment": {**sweep["environment"], "host": host},
                            "settings": {"solver": cell["solver"], "seed": cell["seed"],
                                         "warm_start": cell.get("warm_start", "none"),
                                         "time_limit_s": sweep["settings"]["time_limit"], "threads": 1},
                            "result": {}, "validation": {}, "controller_outcome": cell["outcome"],
                            "wall_time_s": resource["observed_wall_s"],
                            "peak_rss_bytes": resource["sampled_peak_tree_rss_bytes"],
                            "resource_evidence": resource, "stages": cell.get("stages", []),
                            "evidence_file": "results/" + str(path.relative_to(results))})
    for r in reports:
        r["settings"].setdefault("warm_start", "none")
    return reports


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", type=Path, default=Path("docs/research/uc800-open-solver/results"))
    ap.add_argument("--campaign", type=Path, default=Path("docs/research/uc800-open-solver/campaign.json"))
    ap.add_argument("--out", type=Path, default=Path("docs/research/uc800-open-solver/dashboard.html"))
    args = ap.parse_args()
    payload = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
               "runs": collect(args.results), "campaign": json.loads(args.campaign.read_text())}
    serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    template = Path(__file__).with_name("templates") / "uc_benchmark_report.html"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(template.read_text().replace("__REPORT_DATA__", serialized))
    print(f"{args.out}: {len(payload['runs'])} measured runs; no solver launched")


if __name__ == "__main__":
    main()
