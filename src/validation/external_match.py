"""External ground-truth matching: official utility line lists vs OSM.

The first measurable answer to "how complete is the OSM input vs official
reality". Japanese TSOs publish machine-readable lists of their >=154 kV
transmission lines (line name, voltage, circuit count, operating capacity)
as part of the grid-availability disclosure (空容量マッピング). Matching
those names against the OSM ``name`` tags (100% filled on kansai lines)
yields:

- **recall**: which official backbone lines exist in OSM at all — the
  input-completeness bound no builder can exceed;
- **attribute agreement**: voltage / circuit count for the matched lines —
  direct evidence quality for the ``circuits``-tag work;
- **a missing-lines work list**: concrete, named gaps suitable for OSM
  contribution and for honest model disclaimers.

Ground-truth files are NOT redistributable (utility site terms) and live
untracked under ``data/external/`` — fetch them yourself, e.g. Kansai
Transmission & Distribution (updated ~daily, CP932 CSV)::

    curl -L -o data/external/kansai_td/154kv_more_line.csv \\
      https://www.kansai-td.co.jp/interchange/takusou/pdf/154kv_more_line.csv

CLI::

    python -m src.validation.external_match kansai \\
        --csv data/external/kansai_td/154kv_more_line.csv
    # or: ajgrid validate --topology ... (KPIs) / this (ground truth)

See docs/VALIDATION_SOURCES.md for the full source survey (TEPCO hourly
flow CSVs, OCCTO 30-min line flows, GSI vector tiles, ...).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import unicodedata
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.powerflow.snapped_topology import DATA_DIR


def _norm(name: str) -> str:
    """Normalise a Japanese line name for matching (NFKC, no spaces)."""
    s = unicodedata.normalize("NFKC", str(name))
    return "".join(s.split())


def load_official_lines(csv_path: str) -> list[dict]:
    """Parse a TSO grid-availability line CSV (Kansai-TD column layout).

    Header row is auto-detected by the 送電線名 column, so the leading
    "updated YYYY-MM-DD" row and layout drift are tolerated.
    """
    with open(csv_path, encoding="cp932", newline="") as f:
        rows = list(csv.reader(f))
    header_i = next(i for i, r in enumerate(rows)
                    if any("送電線名" in c for c in r))
    header = rows[header_i]
    col = {key: next(i for i, c in enumerate(header) if key in c)
           for key in ("送電線名", "電圧", "回線数")}
    cap_i = next((i for i, c in enumerate(header) if "運用容量値" in c), None)

    out = []
    for r in rows[header_i + 1:]:
        if len(r) <= col["回線数"] or not r[col["送電線名"]].strip():
            continue
        try:
            kv = float(r[col["電圧"]])
        except ValueError:
            continue
        try:
            circuits = int(r[col["回線数"]])
        except ValueError:
            circuits = None
        cap = None
        if cap_i is not None and len(r) > cap_i:
            try:
                cap = float(r[cap_i])
            except ValueError:
                cap = None
        out.append({"name": r[col["送電線名"]].strip(), "kv": kv,
                    "circuits": circuits, "capacity_mw": cap})
    return out


def load_osm_names(region: str, data_dir: str | None = None) -> dict[str, dict]:
    """name -> {kv_max, circuits_max} over the region's OSM line features."""
    path = os.path.join(data_dir or DATA_DIR, f"{region}_lines.geojson")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    from src.utils.voltage import parse_voltage_kv

    info = defaultdict(lambda: {"kv": 0.0, "circuits": 0})
    for ft in data.get("features", []):
        p = ft.get("properties", {})
        name = p.get("name")
        if not name:
            continue
        key = _norm(name)
        kv = parse_voltage_kv(p.get("voltage")) or 0.0
        info[key]["kv"] = max(info[key]["kv"], kv / 1.0)
        try:
            c = int(str(p.get("circuits", "")).split(";")[0])
        except ValueError:
            c = 0
        info[key]["circuits"] = max(info[key]["circuits"], c)
    return dict(info)


def match_official(region: str, csv_path: str,
                   data_dir: str | None = None) -> dict:
    """Match official lines against OSM names; return the scorecard."""
    official = load_official_lines(csv_path)
    osm = load_osm_names(region, data_dir=data_dir)
    osm_keys = list(osm.keys())

    matched, loose, missing = [], [], []
    for o in official:
        key = _norm(o["name"])
        if key in osm:
            matched.append((o, key))
            continue
        # loose: official name contained in an OSM name (e.g. OSM uses
        # "...変電所~...変電所線" long forms or branch suffixes)
        hits = [k for k in osm_keys if key in k]
        if hits:
            loose.append((o, hits[0]))
        else:
            missing.append(o)

    def _agree(pairs, field):
        ok = tot = 0
        for o, k in pairs:
            if o.get(field) and osm[k].get(field if field != "kv" else "kv"):
                tot += 1
                if field == "kv":
                    if abs(osm[k]["kv"] - o["kv"]) <= max(0.1 * o["kv"], 1.0):
                        ok += 1
                elif osm[k]["circuits"] == o["circuits"]:
                    ok += 1
        return ok, tot

    kv_ok, kv_tot = _agree(matched, "kv")
    c_ok, c_tot = _agree(matched, "circuits")

    n = len(official)
    by_kv = Counter(int(o["kv"]) for o in official)
    missing_by_kv = Counter(int(o["kv"]) for o in missing)
    return {
        "region": region,
        "n_official": n,
        "official_by_kv": {str(k): v for k, v in sorted(by_kv.items(), reverse=True)},
        "n_matched_exact": len(matched),
        "n_matched_loose": len(loose),
        "n_missing": len(missing),
        "recall_exact": round(len(matched) / n, 4) if n else 0.0,
        "recall_with_loose": round((len(matched) + len(loose)) / n, 4) if n else 0.0,
        "missing_by_kv": {str(k): v for k, v in sorted(missing_by_kv.items(), reverse=True)},
        "voltage_agree": f"{kv_ok}/{kv_tot}",
        "circuits_agree": f"{c_ok}/{c_tot}",
        "missing_names": [f"{o['name']} ({o['kv']:.0f}kV)" for o in missing],
    }


def render_match(m: dict) -> str:
    lines = [
        f"{m['region']}: official >=154kV lines = {m['n_official']} "
        f"(by kV: {m['official_by_kv']})",
        f"  exact name match : {m['n_matched_exact']:4d}  (recall {100*m['recall_exact']:.1f}%)",
        f"  + loose contain  : {m['n_matched_loose']:4d}  (recall {100*m['recall_with_loose']:.1f}%)",
        f"  missing from OSM : {m['n_missing']:4d}  (by kV: {m['missing_by_kv']})",
        f"  matched-line agreement — voltage {m['voltage_agree']}, circuits {m['circuits_agree']}",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Match official TSO line lists against OSM (ground truth)")
    ap.add_argument("region")
    ap.add_argument("--csv", required=True,
                    help="TSO grid-availability line CSV (untracked, see docstring)")
    ap.add_argument("--json", help="write the full scorecard (incl. missing names)")
    ap.add_argument("--missing", action="store_true", help="list missing line names")
    args = ap.parse_args(argv)

    if not os.path.exists(args.csv):
        print(f"no CSV at {args.csv} — fetch it first (see module docstring)")
        return 2
    m = match_official(args.region, args.csv)
    print(render_match(m))
    if args.missing:
        print("\nmissing official lines (OSM contribution work list):")
        for name in m["missing_names"]:
            print(f"  - {name}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1, ensure_ascii=False)
        print(f"\nscorecard -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
