"""TEPCO per-line flow disclosure vs the built model: topology ground truth.

TEPCO publishes hourly flow time series for the trunk grid (275 kV+) whose
CSV **column names alone** are a topology ground truth: each column is
"<substation>(変) - <equipment>", e.g. ``京浜(変) - 東京南線1･2L`` — an
official statement that 東京南線 terminates at 京浜変電所. From the header
we extract:

- the official substation set (88 sites, 2024 file),
- the official line set (179 named trunk lines),
- the official (substation, line) attachment pairs (286) — the strongest
  per-edge connectivity truth available for the Tokyo area.

This module scores the BUILT model (not raw OSM) against those pairs,
which is why the snapped builder carries OSM line names onto its branches.
Match tiers: exact (NFKC, suffix-stripped) and loose (containment, e.g.
TEPCO 港北線 vs OSM 横浜港北線 counts as loose only).

Data drop (not redistributable — TEPCO terms; data/external/ is
gitignored)::

    curl -A "Mozilla/5.0" -o data/external/tepco/tyouryu_kikan.zip \\
      https://www.tepco.co.jp/pg/consignment/system/pdf/tyouryu_kikan.zip
    # extract jisseki_kikan.csv (zip member names are CP932)

CLI::

    python -m src.validation.external_tepco \\
        --csv data/external/tepco/jisseki_kikan.csv [--region tokyo] [--missing]

The flow VALUES in the same CSV are the next validation layer (model DC
flow vs measured MW per named line) — see docs/VALIDATION_SOURCES.md.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_COL_PAT = re.compile(r"^(.+?)\((変|開|開閉所)\)\s*-\s*(.+)$")
_CIRCUIT_SUFFIX = re.compile(r"[0-9０-９･・,，]+L$")


_CLASS_SUFFIX = re.compile(r"\s*(\d+(\.\d+)?kV|\(untyped\))$")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s))
    s = _CLASS_SUFFIX.sub("", s)   # multi-voltage builder bus-name suffixes
    for suf in ("変電所", "開閉所", "発電所"):
        s = s.replace(suf, "")
    return "".join(s.split())


def parse_tepco_header(csv_path: str) -> dict:
    """Extract (substations, lines, attachment pairs) from the column names."""
    with io.open(csv_path, encoding="cp932", newline="") as f:
        header = next(csv.reader(f))
    subs, lines, pairs = set(), set(), set()
    for col in header[1:]:
        m = _COL_PAT.match(col.strip())
        if not m:
            continue
        sub = m.group(1).strip()
        eq = m.group(3).strip()
        subs.add(sub)
        if eq.endswith("L") and "線" in eq:
            line = _CIRCUIT_SUFFIX.sub("", eq).strip()
            if line:
                lines.add(line)
                pairs.add((sub, line))
    return {"subs": subs, "lines": lines, "pairs": pairs}


def _model_inventory(region: str, data_dir: str | None = None):
    """Built-model name inventories: substations and line->endpoint-subs."""
    from src.powerflow.snapped_topology import build_network_snapped

    net = build_network_snapped(region, data_dir=data_dir)
    if net is None:
        raise FileNotFoundError(f"no data for region {region}")
    sub_name = {}    # substation id -> normalised name
    for s in net.substations:
        if "_jct_" not in s.id:
            sub_name[s.id] = _norm(s.name)
    sub_names = set(sub_name.values())

    line_ends = defaultdict(set)   # normalised line name -> {endpoint sub names}
    for ln in net.transmission_lines:
        if "_xfmr_" in ln.id or not ln.name or ln.name.startswith(f"{region}_line_"):
            continue
        key = _norm(ln.name)
        for end in (ln.from_substation_id, ln.to_substation_id):
            if end in sub_name:
                line_ends[key].add(sub_name[end])
        line_ends[key]  # ensure key exists even with junction-only endpoints
    return net, sub_names, dict(line_ends)


def match_tepco(region: str, csv_path: str, data_dir: str | None = None) -> dict:
    """Score the built model against TEPCO's substation-line attachments."""
    truth = parse_tepco_header(csv_path)
    _net, sub_names, line_ends = _model_inventory(region, data_dir=data_dir)
    line_keys = list(line_ends.keys())

    def find_line(official: str):
        key = _norm(official)
        if key in line_ends:
            return key, "exact"
        hits = [k for k in line_keys if key in k or k in key]
        if hits:
            return hits[0], "loose"
        return None, None

    sub_hit = sum(1 for s in truth["subs"] if _norm(s) in sub_names)

    line_exact = line_loose = 0
    missing_lines = []
    for ln in sorted(truth["lines"]):
        _, tier = find_line(ln)
        if tier == "exact":
            line_exact += 1
        elif tier == "loose":
            line_loose += 1
        else:
            missing_lines.append(ln)

    pair_ok = pair_half = 0
    missing_pairs = []
    for sub, ln in sorted(truth["pairs"]):
        key, tier = find_line(ln)
        if key is None:
            missing_pairs.append(f"{sub} - {ln} (line missing)")
            continue
        if _norm(sub) in line_ends.get(key, set()):
            pair_ok += 1
        else:
            # the line exists in the model but does not terminate at the
            # official substation -> a concrete, named connectivity error
            pair_half += 1
            missing_pairs.append(f"{sub} - {ln} (line present, not attached)")

    n_subs, n_lines, n_pairs = (len(truth["subs"]), len(truth["lines"]),
                                len(truth["pairs"]))
    return {
        "region": region,
        "truth": {"subs": n_subs, "lines": n_lines, "pairs": n_pairs},
        "sub_recall": round(sub_hit / n_subs, 4) if n_subs else 0.0,
        "line_recall_exact": round(line_exact / n_lines, 4) if n_lines else 0.0,
        "line_recall_loose": round((line_exact + line_loose) / n_lines, 4) if n_lines else 0.0,
        "pair_attached": pair_ok,
        "pair_line_present_not_attached": pair_half,
        "pair_recall": round(pair_ok / n_pairs, 4) if n_pairs else 0.0,
        "missing_lines": missing_lines,
        "missing_pairs": missing_pairs,
    }


def render_tepco(m: dict) -> str:
    t = m["truth"]
    return "\n".join([
        f"{m['region']} vs TEPCO trunk disclosure "
        f"({t['subs']} subs / {t['lines']} lines / {t['pairs']} attachments):",
        f"  substation recall : {100 * m['sub_recall']:.1f}%",
        f"  line recall       : {100 * m['line_recall_exact']:.1f}% exact, "
        f"{100 * m['line_recall_loose']:.1f}% incl. loose",
        f"  attachment recall : {100 * m['pair_recall']:.1f}% "
        f"({m['pair_attached']}/{t['pairs']}; "
        f"{m['pair_line_present_not_attached']} lines present but not attached)",
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Match the built model against TEPCO's per-line flow "
                    "disclosure header (topology ground truth)")
    ap.add_argument("--csv", default="data/external/tepco/jisseki_kikan.csv")
    ap.add_argument("--region", default="tokyo")
    ap.add_argument("--json", help="write the full scorecard")
    ap.add_argument("--missing", action="store_true", help="list missing items")
    args = ap.parse_args(argv)

    if not os.path.exists(args.csv):
        print(f"no CSV at {args.csv} — fetch it first (see module docstring)")
        return 2
    m = match_tepco(args.region, args.csv)
    print(render_tepco(m))
    if args.missing:
        print("\nofficial trunk lines absent from the model (work list):")
        for ln in m["missing_lines"]:
            print(f"  - {ln}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1, ensure_ascii=False)
        print(f"\nscorecard -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
