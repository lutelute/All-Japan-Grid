#!/usr/bin/env python3
"""Read and verify saved site/terminal connection evidence; never change a model.

Python standard library only. See docs/SITE_CONNECTION_REVIEW_TOOL.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "docs/reports/codex_same_site_trial_2026-09-13"
MODEL_PATH = "docs/data/built/all.json"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def local_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Evidence path leaves its directory: {relative}")
    return path


def summary(report):
    trial = read_json(report / "trial.json")
    visual = read_json(report / "visual_review.json")
    terminals = read_json(report / "site_terminals.json")
    projection = read_json(report / "site_terminal_verification.json")
    powerflow = read_json(report / "powerflow.json")
    return {
        "report": str(report),
        "input_sha256": trial["source_sha256"],
        "screen": trial["screen"],
        "retrace_after_visual_review": visual["retrace_initial_aliases"],
        "sites": len(terminals["sites"]),
        "saved_model_branch_ends": len(terminals["terminals"]),
        "overlap_candidates": len(read_json(report / "path_overlaps.json")["rows"]),
        "recorded_projection_check": {
            "electrical_tables_equal": projection["electrical_tables_equal"],
            "display_buses_anchored": projection["changes"]["display_buses_anchored"],
            "max_line_flow_difference_mw": projection["max_line_flow_difference_mw"],
        },
        "recorded_ac_converged": {
            key: value["ac"]["converged"] for key, value in powerflow["variants"].items()
        },
        "artifacts": {
            "html": str(report / "index.html"),
            "review": str(report / "REVIEW.md"),
            "powerpoint": [str(p) for p in sorted(report.glob("*.pptx"))],
            "tool_manual": str(ROOT / "docs/SITE_CONNECTION_REVIEW_TOOL.md"),
        },
        "scope": "Saved trial evidence, not approved physical connections. No solver rerun.",
    }


def case_details(report, case_id):
    trial = read_json(report / "trial.json")
    candidate = next((c for c in trial["candidates"] if c["case_id"] == case_id), None)
    if candidate is None:
        raise ValueError(f"Unknown case: {case_id}")
    view = read_json(report / "site_terminals.json")
    memberships = view["cases"][case_id]
    return {
        "case_id": case_id,
        "candidate": {key: value for key, value in candidate.items()
                      if key not in ("local_edges", "local_nodes")},
        "full_neighborhood_source": str(report / "trial.json"),
        "visual_review": read_json(report / "visual_review.json")["cases"][case_id],
        "site_membership": memberships,
        "terminals": [t for t in view["terminals"] if t["terminal_id"] in memberships["terminal_ids"]],
        "scope": "Geometric evidence and connection hypotheses; electrical confirmation is separate.",
    }


def verify(report, current_input=None):
    """Verify recorded hashes and shared input identity, without extracting the ZIP.

    This checks retained evidence, not the truth of an electrical connection or
    current solver output. Source-code/config hashes are reviewed at their pinned
    commit separately; they are not silently compared to a moving checkout.
    """
    errors = []
    checked = 0

    def check_bytes(label, data, expected):
        nonlocal checked
        checked += 1
        if sha(data) != expected:
            errors.append(f"SHA256 mismatch: {label}")

    def check_file(relative, expected):
        try:
            check_bytes(relative, local_path(report, relative).read_bytes(), expected)
        except (OSError, ValueError) as exc:
            errors.append(f"{relative}: {exc}")

    trial = read_json(report / "trial.json")
    qa = read_json(report / "qa.json")
    visual = read_json(report / "visual_review.json")
    inputs = read_json(report / "reproduction_inputs.json")
    basemap = read_json(report / "basemap_manifest.json")
    check_file("index.html", qa["html_sha256"])
    check_file("reproduction_inputs.zip", inputs["archive_sha256"])
    with zipfile.ZipFile(report / "reproduction_inputs.zip") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(inputs["files"]):
            errors.append("Archive members differ from reproduction_inputs.json")
        for name, metadata in inputs["files"].items():
            if name not in names:
                continue
            check_bytes(f"archive:{name}", archive.read(name), metadata["sha256"])
    for group in (basemap["tiles"], basemap["date_sources"]):
        for metadata in group.values():
            if metadata.get("available", True) is not True:
                errors.append(f"Unavailable basemap: {metadata['path']}")
                continue
            check_file(metadata["path"], metadata["sha256"])
    for name, digest in visual["contact_sheets"].items():
        check_file(name, digest)
    for name in ("powerflow.json", "site_terminal_verification.json", "path_overlaps.json"):
        if read_json(report / name)["source_sha256"] != trial["source_sha256"]:
            errors.append(f"Different recorded input: {name}")
    if visual["input_source_sha256"] != trial["source_sha256"]:
        errors.append("Different recorded input: visual_review.json")
    for name in ("alias_plan.json", "site_terminals.json"):
        if read_json(report / name)["input_model_digest"] != trial["input_model_digest"]:
            errors.append(f"Different model digest: {name}")
    if inputs["files"][MODEL_PATH]["sha256"] != trial["source_sha256"]:
        errors.append("Archived model does not match the trial input")
    if current_input is not None:
        check_bytes(str(current_input), current_input.read_bytes(), trial["source_sha256"])
    return {
        "ok": not errors,
        "checked_hashes": checked,
        "current_input_checked": str(current_input) if current_input else None,
        "errors": errors,
        "scope": "Recorded HTML, archive members, basemaps, inspected contact sheets and input identity. "
                 "Does not rerun visual inspection, browser QA, or power flow; does not verify every report file.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("summary", "case", "verify"))
    parser.add_argument("case_id", nargs="?", help="SS01 etc.; required only for case")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT,
                        help="Saved report directory with the same evidence schema")
    parser.add_argument("--check-current-input", action="store_true",
                        help="verify: also require the current canonical input to match")
    args = parser.parse_args()
    if (args.command == "case") != (args.case_id is not None):
        parser.error("case requires a case ID; other commands take no case ID")
    if args.check_current_input and args.command != "verify":
        parser.error("--check-current-input is only valid for verify")
    report = args.report_dir.resolve()
    try:
        if args.command == "summary":
            result = summary(report)
        elif args.command == "case":
            result = case_details(report, args.case_id.upper())
        else:
            result = verify(report, ROOT / MODEL_PATH if args.check_current_input else None)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
