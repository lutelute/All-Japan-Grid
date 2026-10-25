"""Merge the day files of uc_year_grid (possibly from several machines) into a year summary.

Checks that every machine numbered the branches the same way (catalog_<island>_<host>.json),
then sums per line over the year: hours overloaded before redispatch, hours still overloaded
after it (cannot be cleared by moving committed thermal units: data or commitment), and the
value of one more MW summed over the hours where the line was binding but clearable
(yen per MW per year; a fuel saving only for day files of the lexicographic redispatch, which
also count the binding hours: "method" in the summary). Also writes the daily series. Light: no solve, no network build.

    python -m scripts.uc_year_grid_merge --dirs year_a year_b year_c --out year_summary.json
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dirs", type=Path, nargs="+", required=True)
    ap.add_argument("--top", type=int, default=400)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    catalogs, digests = {}, defaultdict(dict)
    for d in args.dirs:
        for c in d.glob("catalog_*_*.json"):
            isl, host = c.stem.split("_", 2)[1:]
            text = c.read_text()
            digests[isl][host] = hashlib.sha256(text.encode()).hexdigest()[:12]
            catalogs.setdefault(isl, json.loads(text))
    same = {isl: len(set(h.values())) == 1 for isl, h in digests.items()}
    if not all(same.values()):
        raise SystemExit(f"branch numbering differs between machines: {dict(digests)}")
    days = {}
    for d in args.dirs:
        for f in d.glob("20*.json"):
            days.setdefault(f.stem, json.loads(f.read_text()))
    # h_before, h_after, max_after, value, days_over, days_residual, h_binding, h_stuck
    lines = {isl: defaultdict(lambda: [0, 0, 0.0, 0.0, 0, 0, 0, 0]) for isl in catalogs}
    lexicographic = set()
    daily = []
    month_hours = {isl: defaultdict(lambda: [0] * 12) for isl in catalogs}
    for date in sorted(days):
        day = days[date]
        row = {k: day.get(k) for k in ("date", "status", "verified", "cost", "gap", "peak_mw", "gross_demand_mwh",
                                       "n1_shortfall_mwh", "tie_hours_at_limit", "solve_s", "wall_s")}
        month = int(date[5:7]) - 1
        for isl, v in (day.get("islands") or {}).items():
            row[isl] = {k: v[k] for k in ("redispatch_yen", "over_before_mw", "over_after_mw", "n_over_before", "n_over_after")}
            row[isl]["lp_failed"] = v.get("lp_failed", 0)
            row[isl]["probe_failed"] = v.get("probe_failed", 0)
            lexicographic.add(all(len(x) == 6 for x in v["lines"].values()))
            for k, (hb, ha, mx, val, *more) in v["lines"].items():
                acc = lines[isl][k]
                acc[0] += hb
                acc[1] += ha
                acc[2] = max(acc[2], mx)
                acc[3] += val
                acc[4] += hb > 0
                acc[5] += ha > 0
                if more:
                    acc[6] += more[0]
                    acc[7] += more[1]
                month_hours[isl][k][month] += hb
        daily.append(row)
    if len(lexicographic) > 1:
        raise SystemExit("day files from the penalty and the lexicographic redispatch are mixed")
    method = "lexicographic" if lexicographic == {True} else "penalty"
    out = {"schema_version": 1, "kind": "year_grid_summary", "method": method, "days": len(daily),
           "dirs": [str(d) for d in args.dirs],
           "catalog_digests": digests, "daily": daily, "islands": {}}
    for isl, acc in lines.items():
        cat = catalogs[isl]
        rows = []
        for k, (hb, ha, mx, val, dov, dres, hbind, hstuck) in acc.items():
            c = cat[int(k)]
            rows.append({"k": int(k), "name": c["name"], "kv": c["kv"], "class": c["class"], "a": c["a"], "b": c["b"],
                         "hours_over": hb, "hours_residual": ha, "max_residual_mw": round(mx, 1),
                         "value_yen_per_mw_year": round(val, 0), "hours_binding": hbind, "hours_stuck": hstuck,
                         "days_over": dov,
                         "days_residual": dres,
                         "month_hours": month_hours[isl][k]})
        out["islands"][isl] = {
            "monitored": sum(1 for c in cat if c["monitored"]),
            "lines_ever_over": sum(1 for r in rows if r["hours_over"] > 0),
            "lines_residual": sum(1 for r in rows if r["hours_residual"] > 0),
            # over before redispatch and still over after it, in the same hour: the data suspects
            "lines_stuck": sum(1 for r in rows if r["hours_stuck"] > 0),
            "residual": sorted([r for r in rows if r["hours_residual"] > 0], key=lambda r: -r["hours_residual"])[:args.top],
            "stuck": sorted([r for r in rows if r["hours_stuck"] > 0], key=lambda r: -r["hours_stuck"])[:args.top],
            "congestion": sorted([r for r in rows if r["value_yen_per_mw_year"] > 0], key=lambda r: -r["value_yen_per_mw_year"])[:args.top]}
        print(isl, "monitored", out["islands"][isl]["monitored"], "ever over", out["islands"][isl]["lines_ever_over"],
              "residual", out["islands"][isl]["lines_residual"], "stuck", out["islands"][isl]["lines_stuck"])
    failed = sum(r[isl]["lp_failed"] for r in daily for isl in catalogs if isl in r)
    probes = sum(r[isl]["probe_failed"] for r in daily for isl in catalogs if isl in r)
    out["lp_failed_hours"], out["probe_failed"] = failed, probes
    args.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    print("days", len(daily), "method", method, "redispatch LPs failed", failed, "probes failed", probes,
          "numbering identical across machines:", same)


if __name__ == "__main__":
    main()
