"""Can redispatch clear the overloads? Line-level congestion of a UC plan on the real grid.

SCUC stage 1b (docs/research/uc800-open-solver/SCUC_PLAN.md). For each island and hour the
commitment stays as in the UC plan. Thermal units that are on (coal, LNG, oil, biomass) may move
between their minimum and maximum output; everything else (nuclear, hydro, geothermal, storage,
renewables, demand, DC links) stays as planned, and so does the island's total generation.
DC flows go through the PTDF (scripts/scuc_evaluate builds the island the same way). The linear
program is solved lexicographically, three times on the same model with a warm start:

1. least total overload (MW above the watched lines' capacities) that any redispatch leaves;
2. least fuel cost with the total overload held at that minimum;
3. the same, with each line's overload held at its value from 2, so that the dual of every
   line limit is a fuel saving (yen per MW for that hour) and not a penalty traded between lines;
4. for every line whose limit binds there: the same with that limit 1 MW wider. The saving is
   the value of one more MW of the line for that hour. The dual alone overstates it when the
   only units that relieve the line barely affect it (PTDF ~1e-4): it is fuel difference over
   sensitivity, valid for a shift far smaller than 1 MW of the line needs.

- Overloads that survive cannot be cleared by any redispatch of the committed units. Under this
  network model they point at the data (a plant attached to too low a voltage, a missing line)
  or at the commitment itself, not at congestion that operation could handle.
- Overloads that vanish are congestion candidates. The redispatch cost is what clearing them
  costs, and step 4 gives what one more MW of each binding line would save.
  A single LP with a penalty on overloads (the first version of this script) gave duals that
  mixed fuel with the penalty: up to 2.4e9 yen per MW and year on lines next to unclearable ones.

    python -m scripts.scuc_redispatch --plan near.json --plan-key reference --out redispatch.json
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import time

import highspy
import numpy as np

from scripts.run_full_powerflow_from_db import load_demand_config
from scripts.scuc_evaluate import BUILT, ISLAND_OF_REGION, injection, island_model, mapping, plant_osm_ids
from src.uc.scenario import build_national_scenario

MOVABLE = {"coal", "lng", "oil", "biomass"}
CLEAR_MW = 0.05          # an overload below this after redispatch counts as cleared (outputs are rounded to 0.1)


def _run(h):
    """Solve; on anything but optimal, again from scratch, then with the interior point method.

    Warm starts after a change of costs or bounds end in status 'unknown' now and then on the
    island LPs (east, fy2023r2, hour 0: step 3, and 3 of 4 probes of step 4).
    """
    ok = highspy.HighsModelStatus.kOptimal
    highspy.Highs.resetGlobalScheduler(True)    # one thread pool per process: a run with other threads leaves it unusable
    h.run()
    if h.getModelStatus() == ok:
        return True
    h.clearSolver()
    h.run()
    if h.getModelStatus() == ok:
        return True
    h.setOptionValue("solver", "ipm")
    h.clearSolver()
    h.run()
    h.setOptionValue("solver", "choose")
    return h.getModelStatus() == ok


def redispatch_lp(a, c, cap, p0, lo, hi, cost, weight=None, probe_mw=1.0):
    """Lexicographic redispatch of one hour (module docstring, steps 1-3).

    a: (lines x units) PTDF of the movable units, c: flow on each line from everything that does
    not move, cap: line capacities, p0/lo/hi/cost: the units' planned output, bounds and fuel cost.
    The units' total stays at p0's. weight (per line, default 1) weighs the overload in step 1.
    Returns None if the LP fails, otherwise output p, overload after redispatch per line, the
    line duals of step 3 (yen per MW, sign dropped), the saving of step 4 for a line probe_mw
    wider (yen; 0 where the limit does not bind or the line stays over, NaN where that LP failed)
    and the minimum weighted overload of step 1.
    """
    k, n = a.shape
    w = np.ones(k) if weight is None else np.asarray(weight, dtype=float)
    w2 = np.concatenate([w, w])
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("threads", 1)
    slack = np.arange(n, n + 2 * k, dtype=np.int32)
    h.addVars(n + 2 * k, np.concatenate([lo, np.zeros(2 * k)]), np.concatenate([hi, np.full(2 * k, highspy.kHighsInf)]))
    h.changeColsCost(2 * k, slack, w2)
    if n:
        h.addRow(float(p0.sum()), float(p0.sum()), n, np.arange(n, dtype=np.int32), np.ones(n))
    first_line = h.getNumRow()
    for i in range(k):
        nz = np.nonzero(np.abs(a[i]) > 1e-4)[0]
        idx = np.concatenate([nz, [n + i, n + k + i]]).astype(np.int32)
        val = np.concatenate([a[i, nz], [-1.0, 1.0]])
        h.addRow(float(-cap[i] - c[i]), float(cap[i] - c[i]), len(idx), idx, val)
    if not _run(h):                                               # 1. least overload
        return None
    least = float(h.getInfo().objective_function_value)
    budget = h.getNumRow()
    # Any slack in the overload budget is spent on fuel (moving load onto a cheap unit through an
    # overloaded line), so it is only as wide as the solver's tolerance, and widened if needed.
    h.addRow(-highspy.kHighsInf, least + 1e-7 * max(1.0, least), 2 * k, slack, w2)
    h.changeColsCost(n + 2 * k, np.arange(n + 2 * k, dtype=np.int32), np.concatenate([cost, np.zeros(2 * k)]))
    if not _run(h):                                               # 2. least fuel at that overload
        h.changeRowBounds(budget, -highspy.kHighsInf, least + 1e-4 * max(1.0, least))
        if not _run(h):
            return None
    s = np.array(h.getSolution().col_value)[n:]
    h.changeColsBounds(2 * k, slack, np.zeros(2 * k), np.maximum(s, 0.0))
    h.changeRowBounds(budget, -highspy.kHighsInf, highspy.kHighsInf)
    if not _run(h):                                               # 3. per-line overload held: fuel duals
        return None
    sol = h.getSolution()
    x = np.array(sol.col_value)
    over_after = x[n:n + k] + x[n + k:]
    duals = np.abs(np.array(sol.row_dual)[first_line:first_line + k])
    base = float(h.getInfo().objective_function_value)
    gain = np.zeros(k)
    for i in np.nonzero((duals > 1e-6) & (over_after < CLEAR_MW))[0] if probe_mw else []:
        row, lo_i, hi_i = first_line + int(i), float(-cap[i] - c[i]), float(cap[i] - c[i])
        h.changeRowBounds(row, lo_i - probe_mw, hi_i + probe_mw)
        gain[i] = (max(base - float(h.getInfo().objective_function_value), 0.0) if _run(h)   # 4. a line wider
                   else np.nan)
        h.changeRowBounds(row, lo_i, hi_i)
    return {"p": x[:n], "over_after": over_after, "least_over": least, "duals": duals, "gain": gain}


def solve_hour(m, mp, scn, params, plan, t, gens):
    inj, info = injection(m, mp, scn, params, plan, t)
    mon = np.where(m["monitor"] & np.isfinite(m["cap"]) & (m["cap"] > 0))[0]
    ptdf = m["ptdf"][mon]
    cap = m["cap"][mon]
    f0 = ptdf @ inj
    on = [g for g in gens if (plan["on"][g.id] >> t) & 1]
    p0 = np.array([plan["mw"][g.id][t] for g in on])
    cols = np.array([mp["gen_bus"][g.id] for g in on], dtype=int)
    a = ptdf[:, cols] if len(on) else np.zeros((len(mon), 0))
    c = f0 - (a @ p0 if len(on) else 0.0)                    # flow from everything that does not move
    fuel = np.array([g.fuel_cost_per_mwh for g in on])
    over_before = np.maximum(np.abs(f0) - cap, 0)
    # Among redispatches with the same least overload, keep it on the lines that were already
    # over rather than pushing it onto lines that were not (which then look like data suspects).
    weight = np.where(over_before >= CLEAR_MW, 1.0, 1.001)
    r = redispatch_lp(a, c, cap, p0, np.array([min(g.p_min_mw, p) for g, p in zip(on, p0)]),
                      np.array([max(g.capacity_mw, p) for g, p in zip(on, p0)]), fuel, weight)
    if r is None:
        return {"t": t, "status": "lp_failed", **info}
    p, over_after = r["p"], r["over_after"]
    lines = {}
    for i in range(len(mon)):
        before, after = float(over_before[i]), float(over_after[i])
        after = after if after >= CLEAR_MW else 0.0
        value = float(r["gain"][i]) if after == 0 and not np.isnan(r["gain"][i]) else None
        if before >= CLEAR_MW or after > 0 or (value and value > 1e-6):
            lines[int(mon[i])] = {"before": round(before, 1), "after": round(after, 1),
                                  "value": None if value is None else round(value, 1)}
    return {"t": t, "status": "optimal", **info,
            "redispatch_yen": round(float(np.dot(fuel, p - p0)) if len(on) else 0.0, 0),
            "moved_mw": round(float(np.abs(p - p0).sum()) / 2, 1),
            "over_before_mw": round(float(over_before.sum()), 1), "over_after_mw": round(float(over_after.sum()), 1),
            "n_over_before": int((over_before >= CLEAR_MW).sum()), "n_over_after": int((over_after >= CLEAR_MW).sum()),
            "probe_failed": int(np.isnan(r["gain"]).sum()), "lines": lines}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--plan-key", default="reference")
    ap.add_argument("--islands", nargs="*", default=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--cap-calib", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    data = json.loads(args.plan.read_text())
    plan = (data["reference"]["plan"] if args.plan_key == "reference" else
            next(r["plan"] for r in data["runs"] if abs(r["eps"] - float(args.plan_key)) < 1e-12))
    scn = build_national_scenario(scenario=args.scenario)
    params = scn.to_uc_parameters()
    built = json.loads(BUILT.read_text())
    nodes, edges = built["nodes"], built["edges"]
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)
    osm = plant_osm_ids()
    out = {"schema_version": 1, "kind": "scuc_redispatch", "scenario": args.scenario, "plan": str(args.plan),
           "plan_key": args.plan_key, "cap_calib": args.cap_calib, "method": "lexicographic: overload, then fuel",
           "movable_fuels": sorted(MOVABLE), "islands": []}
    for island in args.islands:
        t0 = time.monotonic()
        m = island_model(island, nodes, edges, cfg, pref_gwh, args.cap_calib)
        mp = mapping(m, params, osm)
        gens = [g for g in params.generators if g.id in mp["gen_bus"] and g.fuel_type in MOVABLE]
        hours = [solve_hour(m, mp, scn, params, plan, t, gens) for t in range(params.time_horizon.num_periods)]
        per_line = defaultdict(lambda: {"h_before": 0, "h_after": 0, "max_after": 0.0, "value_yen": 0.0, "h_binding": 0})
        for hr in hours:
            for k, v in hr.get("lines", {}).items():
                d = per_line[k]
                d["h_before"] += v["before"] > 0
                d["h_after"] += v["after"] > 0
                d["max_after"] = max(d["max_after"], v["after"])
                if v["value"]:
                    d["value_yen"] += v["value"]
                    d["h_binding"] += 1
        sub, ppc = m["sub"], m["ppc"]
        rows = []
        for k, d in per_line.items():
            tbl, eid = m["elems"][k]
            rows.append({"k": k, "name": str(getattr(sub, tbl).at[eid, "name"]) if tbl else "", "kv": float(m["kv"][k]),
                         "class": str(m["cls"][k]), **{x: (round(y, 1) if isinstance(y, float) else y) for x, y in d.items()}})
        residual = sorted([r for r in rows if r["h_after"] > 0], key=lambda r: -r["max_after"])
        relieved = sorted([r for r in rows if r["h_before"] > 0 and r["h_after"] == 0], key=lambda r: -r["value_yen"])
        binding = sorted([r for r in rows if r["value_yen"] > 0], key=lambda r: -r["value_yen"])
        for hr in hours:
            hr.pop("lines", None)
        res = {"island": island, "hours": hours, "residual": residual[:300], "relieved": relieved[:300],
               "binding": binding[:300], "seconds": round(time.monotonic() - t0, 1),
               "redispatch_yen_day": sum(h.get("redispatch_yen", 0) for h in hours),
               "over_before_mwh": round(sum(h.get("over_before_mw", 0) for h in hours), 1),
               "over_after_mwh": round(sum(h.get("over_after_mw", 0) for h in hours), 1)}
        out["islands"].append(res)
        print(json.dumps({"island": island, "lines_over_before": sum(1 for r in rows if r["h_before"] > 0),
                          "relieved": len(relieved), "residual": len(residual), "binding_after": len(binding),
                          "over_before_mwh": res["over_before_mwh"], "over_after_mwh": res["over_after_mwh"],
                          "redispatch_yen_day": res["redispatch_yen_day"], "s": res["seconds"]}, ensure_ascii=False))
        for r in binding[:5]:
            print("   binding:", r["name"][:36], r["kv"], r["class"], r["h_binding"], "h", f"{r['value_yen']:,.0f} yen/MW/day")
        for r in residual[:3]:
            print("   residual:", r["name"][:36], r["kv"], r["class"], r["h_after"], "h", f"{r['max_after']:,.0f} MW")
    args.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
