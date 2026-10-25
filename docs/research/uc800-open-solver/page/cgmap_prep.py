"""Difficulty map: the UC-specific solver (sweep/*.json) against HiGHS strong 300 s (frontier.json). usage: cgmap_prep.py sweepdir frontier.json out.json"""
import glob, json, os, sys
fr = json.load(open(sys.argv[2]))
cells = []
for f in sorted(glob.glob(os.path.join(sys.argv[1], "n*_t*.json"))):
    d = json.load(open(f))
    h = next((c for c in fr["cells"] if c["units"] == d["units"] and c["hours"] == d["hours"] and c["form"] == "strong"), None)
    hg = (h["primal"] - h["dual"]) / h["primal"] if h and h["primal"] and h["dual"] else None
    cells.append({"units": d["units"], "hours": d["hours"],
                  "ours": {"gap": d["gap_ub_lb"], "s": d["seconds"], "cg_s": d["cg_seconds"], "it": d["cg_iterations"],
                           "lb": round(d["lower_bound"] / 1e8, 4), "ub": round(d["upper_bound"] / 1e8, 4) if d["upper_bound"] else None,
                           "floating_units": d["floating_units"], "converged": d["trace"][-1]["gap"] < 1e-6},
                  "highs": {"gap": hg, "outcome": h["outcome"] if h else None, "s": h["solve_s"] if h else None,
                            "ub": round(h["primal"] / 1e8, 4) if h and h["primal"] else None, "lb": round(h["dual"] / 1e8, 4) if h and h["dual"] else None}})
    o, g = cells[-1]["ours"], cells[-1]["highs"]
    # consistency: each lower bound below the other's plan
    if g["ub"] and o["lb"] > g["ub"] * (1 + 1e-9): raise SystemExit(f"bound above HiGHS plan {cells[-1]}")
    if g["lb"] and o["ub"] and g["lb"] > o["ub"] * (1 + 1e-9): raise SystemExit(f"HiGHS bound above our plan {cells[-1]}")
json.dump({"cells": cells, "highs_budget_s": 300}, open(sys.argv[3], "w"), separators=(",", ":"))
for c in cells: print(c["units"], c["hours"], round(100 * c["ours"]["gap"], 3), c["ours"]["s"], c["ours"]["converged"], c["highs"]["gap"] and round(100 * c["highs"]["gap"], 3))
