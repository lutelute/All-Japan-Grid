#!/usr/bin/env python3
"""Audit data quality across all GeoJSON files.

Scans all GeoJSON files and reports placeholder counts per region, layer,
and field.  Placeholders include: empty/None name, fuel_type='unknown',
empty operator, and synthetic _display_name values (plant_{id}, sub_{i},
line_{id}).

Output: JSON report to stdout and a summary table to stderr.

Usage:
    python scripts/audit_data_quality.py                  # all regions
    python scripts/audit_data_quality.py --region okinawa # single region
"""

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

REGIONS = [
    "hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
    "kansai", "chugoku", "shikoku", "kyushu", "okinawa",
]

LAYERS = ["substations", "plants", "lines"]

# Patterns for synthetic/placeholder _display_name values
SYNTHETIC_DISPLAY_NAME_RE = re.compile(
    r"^(plant_\d+|sub_\d+|line_\d+)$"
)


def _is_empty(value):
    """Check if a property value is empty or None."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _is_synthetic_display_name(value):
    """Check if a _display_name is a synthetic placeholder."""
    if not value or not isinstance(value, str):
        return False
    return bool(SYNTHETIC_DISPLAY_NAME_RE.match(value))


def audit_file(region, layer):
    """Audit a single GeoJSON file. Returns dict of placeholder counts."""
    path = os.path.join(DATA_DIR, f"{region}_{layer}.geojson")
    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8") as f:
        fc = json.load(f)

    features = fc.get("features", [])
    total = len(features)

    counts = {
        "total": total,
        "empty_name": 0,
        "synthetic_display_name": 0,
    }

    # Layer-specific checks
    if layer == "plants":
        counts["unknown_fuel_type"] = 0
        counts["empty_operator"] = 0

    if layer == "lines":
        counts["empty_operator"] = 0

    for feat in features:
        props = feat.get("properties", {})

        # Check empty name (applies to all layers)
        name = props.get("name")
        name_ja = props.get("name:ja")
        if _is_empty(name) and _is_empty(name_ja):
            counts["empty_name"] += 1

        # Check synthetic _display_name
        display_name = props.get("_display_name")
        if _is_synthetic_display_name(display_name):
            counts["synthetic_display_name"] += 1

        # Plants: check fuel_type and operator
        if layer == "plants":
            fuel = props.get("fuel_type", "")
            if fuel == "unknown":
                counts["unknown_fuel_type"] += 1
            operator = props.get("operator")
            if _is_empty(operator):
                counts["empty_operator"] += 1

        # Lines: check operator
        if layer == "lines":
            operator = props.get("operator")
            if _is_empty(operator):
                counts["empty_operator"] += 1

    return counts


def compute_totals(report):
    """Compute aggregate totals across all regions."""
    totals = {}
    for region, layers in report.items():
        for layer, counts in layers.items():
            if counts is None:
                continue
            if layer not in totals:
                totals[layer] = {}
            for field, value in counts.items():
                totals[layer][field] = totals[layer].get(field, 0) + value
    return totals


def count_all_placeholders(report):
    """Count total placeholder values across the entire report."""
    total = 0
    for region, layers in report.items():
        for layer, counts in layers.items():
            if counts is None:
                continue
            for field, value in counts.items():
                if field == "total":
                    continue
                total += value
    return total


def print_summary(report, totals, file=sys.stderr):
    """Print a human-readable summary table to stderr."""
    # Header
    file.write("\n=== Data Quality Audit ===\n\n")

    # Per-region breakdown
    file.write(f"{'Region':<12} {'Layer':<15} {'Total':>7} {'Empty Name':>12} "
               f"{'Synth Disp':>12} {'Unk Fuel':>10} {'Empty Op':>10}\n")
    file.write("-" * 83 + "\n")

    for region in REGIONS:
        if region not in report:
            continue
        for layer in LAYERS:
            counts = report[region].get(layer)
            if counts is None:
                continue
            file.write(
                f"{region:<12} {layer:<15} {counts['total']:>7} "
                f"{counts['empty_name']:>12} "
                f"{counts['synthetic_display_name']:>12} "
                f"{counts.get('unknown_fuel_type', '-'):>10} "
                f"{counts.get('empty_operator', '-'):>10}\n"
            )

    # Totals
    file.write("-" * 83 + "\n")
    for layer in LAYERS:
        if layer not in totals:
            continue
        t = totals[layer]
        file.write(
            f"{'TOTAL':<12} {layer:<15} {t['total']:>7} "
            f"{t['empty_name']:>12} "
            f"{t['synthetic_display_name']:>12} "
            f"{t.get('unknown_fuel_type', '-'):>10} "
            f"{t.get('empty_operator', '-'):>10}\n"
        )

    # Grand total placeholders
    placeholder_count = count_all_placeholders(report)
    file.write(f"\nTotal placeholders: {placeholder_count}\n")
    if placeholder_count == 0:
        file.write("Status: PASS (zero placeholders)\n")
    else:
        file.write("Status: FAIL (placeholders remain)\n")
    file.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description="Audit data quality across GeoJSON files"
    )
    parser.add_argument(
        "--region", type=str, default=None,
        help="Single region to audit (default: all)",
    )
    args = parser.parse_args()

    regions = [args.region] if args.region else REGIONS

    report = {}
    for region in regions:
        if region not in REGIONS:
            sys.stderr.write(f"  Unknown region: {region}\n")
            continue
        report[region] = {}
        for layer in LAYERS:
            counts = audit_file(region, layer)
            if counts is not None:
                report[region][layer] = counts

    totals = compute_totals(report)

    # Print summary table to stderr
    print_summary(report, totals)

    # Print JSON report to stdout
    output = {
        "regions": report,
        "totals": totals,
        "total_placeholders": count_all_placeholders(report),
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    # Exit code: 0 if zero placeholders, 1 otherwise
    if count_all_placeholders(report) > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
