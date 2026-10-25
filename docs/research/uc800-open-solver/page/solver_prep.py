"""Compact the UC-specific solver run for the page: usage solver_prep.py viz.json highs.solver.log out.json"""
import json, re, sys
sys.path.insert(0, "/Users/shigenoburyuto/dev/github/project_Hayashi/All-Japan-Grid/.claude/worktrees/uc800")
from src.uc.benchmark_cases import synthetic_case

d = json.load(open(sys.argv[1]))
p = synthetic_case(d["units"], d["hours"], d["seed"])
gens = [g for g in p.generators if not g.is_storage]
assert d["unit_ids"] == [g.id for g in gens]
regions = list(p.regional_demands)
FU = ["coal", "lng", "oil"]
order = sorted(range(len(gens)), key=lambda i: (regions.index(gens[i].region), FU.index(gens[i].fuel_type), gens[i].fuel_cost_per_mwh))
row = {u: r for r, u in enumerate(order)}
units = [[FU.index(gens[i].fuel_type), regions.index(gens[i].region), round(gens[i].capacity_mw)] for i in order]
iters = []
for t in d["trace"]:
    pats = sorted([row[u], format(int(s, 2), "012x")] for u, s in zip(t["new_units"], t["new_u"]))
    iters.append({"it": t["it"], "s": t["s"], "lb": round(t["best_lb"] / 1e8, 4), "m": round(t["master"] / 1e8, 4),
                  "gap": t["gap"], "n": t["new"], "cols": t["cols"], "pi": [[round(v) for v in r] for r in t["pi"]], "a": pats})
ubar = d["ubar"]
grid, floating = [], []
for r, i in enumerate(order):
    line = ""
    for h, x in enumerate(ubar[i]):
        if x <= 1e-6:
            line += "0"
        elif x >= 1 - 1e-6:
            line += "1"
        else:
            line += "f"; floating.append([r, h, round(x, 3)])
    grid.append(line)
highs = []
for ln in open(sys.argv[2]):
    m = re.match(r"^\s*\S?\s+\d+\s+\d+\s+\d+\s+[\d.]+%\s+(\S+)\s+(\S+)\s+\S+\s.*\s([\d.]+)s\s*$", ln)
    if m:
        lb, ub, t = m.groups()
        highs.append([float(t), float(lb) / 1e8 if lb not in ("0", "-inf") else None, float(ub) / 1e8 if ub != "inf" else None])
out = {"units": d["units"], "hours": d["hours"], "regions": regions, "unit_meta": units, "iters": iters, "grid": grid,
       "floating": floating, "lb": round(d["lower_bound"] / 1e8, 4), "ub": round(d["upper_bound"] / 1e8, 4),
       "cg_s": d["cg_seconds"], "band_s": d["band"]["seconds"], "total_s": d["seconds"], "columns": d["columns"],
       "highs": highs, "highs_final": {"lb": 739.6119, "ub": 743.8546, "s": 900}}
json.dump(out, open(sys.argv[3], "w"), separators=(",", ":"))
print(len(json.dumps(out, separators=(",", ":"))) // 1024, "KB", len(iters), "iters", len(floating), "floating", highs[:3], highs[-1])
