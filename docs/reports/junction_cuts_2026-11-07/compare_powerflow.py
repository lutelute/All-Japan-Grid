#!/usr/bin/env python3
"""全規模の潮流の前と後(summary.json と線の負荷率)を比べる。

    PYTHONPATH=. python3 scripts/run_full_powerflow_from_db.py --max-ac-buses 20000 --no-junction-cuts --output-dir <前>
    PYTHONPATH=. python3 docs/reports/junction_cuts_2026-11-07/compare_powerflow.py <前> docs/data/powerflow_full
→ docs/reports/junction_cuts_2026-11-07/powerflow.json
"""
import glob
import json
import os
import sys

KEYS = ("n_trafo", "n_implicit_stepdown", "n_junction_cuts", "n_components", "n_synthetic_slack", "total_load_mw",
        "ac_converged", "ac_vm_min", "ac_vm_max", "ac_max_loading_pct", "ac_total_loss_mw", "dc_converged")


def lines(d):
    out = {}
    for p in glob.glob(os.path.join(d, "*_ac_lines.geojson")):
        for f in json.load(open(p, encoding="utf-8"))["features"]:
            pr = f["properties"]
            out[(pr.get("name"), json.dumps(f["geometry"]["coordinates"][:2]))] = pr
    return out


def main():
    bdir, adir = sys.argv[1], sys.argv[2]
    b = json.load(open(os.path.join(bdir, "summary.json"), encoding="utf-8"))["islands"]
    a = json.load(open(os.path.join(adir, "summary.json"), encoding="utf-8"))["islands"]
    isl = {k: {kk: [b[k].get(kk), a[k].get(kk)] for kk in KEYS} for k in b}
    lb, la = lines(bdir), lines(adir)
    d = sorted(((la[k]["loading_pct"] - lb[k]["loading_pct"], k[0], lb[k]["loading_pct"], la[k]["loading_pct"])
                for k in lb.keys() & la.keys()
                if lb[k].get("loading_pct") is not None and la[k].get("loading_pct") is not None),
               key=lambda x: -abs(x[0]))
    out = {"islands": isl,
           "lines": {"compared": len(d), "only_before": len(lb.keys() - la.keys()), "only_after": len(la.keys() - lb.keys()),
                     "moved_gt_1pt": sum(1 for x in d if abs(x[0]) > 1),
                     "moved_gt_10pt": sum(1 for x in d if abs(x[0]) > 10),
                     "over_100_before": sum(1 for v in lb.values() if (v.get("loading_pct") or 0) > 100),
                     "over_100_after": sum(1 for v in la.values() if (v.get("loading_pct") or 0) > 100),
                     "top": [[round(x[0], 1), x[1], round(x[2], 1), round(x[3], 1)] for x in d[:15]]}}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "powerflow.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    for k, v in isl.items():
        print(k, {kk: vv for kk, vv in v.items() if vv[0] != vv[1]})
    print(out["lines"]["moved_gt_10pt"], out["lines"]["over_100_before"], "->", out["lines"]["over_100_after"])


if __name__ == "__main__":
    main()
