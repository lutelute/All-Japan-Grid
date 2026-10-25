"""Summarise the synthetic fleet, its demand and a saved schedule for plotting.

Reads a verified *.solution.json.gz of the same synthetic case and writes small
JSON: units by fuel, the cost function per unit, regional demand, and hourly
output / units online / start-ups by type. Never launches a solve.

    python -m scripts.uc_profile_summary --hours 48 --solution run.solution.json.gz --out profile48.json
"""

import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import statistics

from src.uc.benchmark_cases import synthetic_case

FUELS = ["coal", "lng", "oil"]


def startup_kind(off_hours, g):
    """Same thresholds as the model: hot below warm_start_h, warm below cold_start_h."""
    if off_hours < g.warm_start_h:
        return "hot"
    return "warm" if off_hours < g.cold_start_h else "cold"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--units", type=int, default=800)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--solution", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    params = synthetic_case(args.units, args.hours, args.seed)
    gens = {g.id: g for g in params.generators}
    thermal = [g for g in params.generators if not g.is_storage]
    with gzip.open(args.solution, "rt") as f:
        sol = json.load(f)
    T = args.hours

    fleet = {}
    for fuel in FUELS:
        gs = [g for g in thermal if g.fuel_type == fuel]
        caps = [g.capacity_mw for g in gs]
        fleet[fuel] = {
            "units": len(gs), "capacity_mw": sum(caps), "capacity_range_mw": [min(caps), max(caps)],
            "pmin_fraction": gs[0].p_min_mw / gs[0].capacity_mw,
            "min_up_h": gs[0].min_up_time_h, "min_down_h": gs[0].min_down_time_h,
            "ramp_fraction_per_h": gs[0].ramp_up_mw_per_h / gs[0].capacity_mw,
            "marginal_cost_range": [min(g.fuel_cost_per_mwh for g in gs), max(g.fuel_cost_per_mwh for g in gs)],
            "no_load_per_mw_h_range": [min(g.no_load_cost / g.capacity_mw for g in gs),
                                       max(g.no_load_cost / g.capacity_mw for g in gs)],
            "cold_start_per_mw_range": [min(g.cold_start_cost / g.capacity_mw for g in gs),
                                        max(g.cold_start_cost / g.capacity_mw for g in gs)],
        }
        med = sorted(gs, key=lambda g: g.capacity_mw)[len(gs) // 2]
        fleet[fuel]["example"] = {"id": med.id, "pmin": med.p_min_mw, "pmax": med.capacity_mw,
                                  "no_load": med.no_load_cost, "marginal": med.fuel_cost_per_mwh,
                                  "hot": med.hot_start_cost, "warm": med.warm_start_cost, "cold": med.cold_start_cost}
    # Merit order by full-output average cost (fuel + no-load), one point per unit
    merit = sorted(({"fuel": g.fuel_type, "cap": round(g.capacity_mw, 1),
                     "cost": round(g.fuel_cost_per_mwh + g.no_load_cost / g.capacity_mw, 1)} for g in thermal),
                   key=lambda m: m["cost"])
    storage = [{"id": g.id, "region": g.region, "mw": g.capacity_mw, "mwh": g.storage_capacity_mwh}
                for g in params.generators if g.is_storage]

    out_by_fuel = {k: [0.0] * T for k in FUELS + ["storage"]}
    on_by_fuel = {k: [0] * T for k in FUELS}
    starts = {k: [0] * T for k in ("hot", "warm", "cold")}
    stops = [0] * T
    # Lengths of complete on/off runs (opened and closed inside the horizon), against the minimum times
    runs = {fuel: {"on": [], "off": []} for fuel in FUELS}
    for s in sol["schedules"]:
        g = gens[s["generator_id"]]
        u, p = s["commitment"], s["power_output_mw"]
        if g.is_storage:
            for t in range(T):
                out_by_fuel["storage"][t] += p[t]
            continue
        off = max(g.cold_start_h, 1)          # the synthetic case starts with every unit off and cold
        prev = 0
        changes = [t for t in range(1, T) if u[t] != u[t - 1]]
        for a, b in zip(changes, changes[1:]):
            runs[g.fuel_type]["on" if u[a] else "off"].append(b - a)
        for t in range(T):
            out_by_fuel[g.fuel_type][t] += p[t]
            on_by_fuel[g.fuel_type][t] += u[t]
            if u[t] and not prev:
                starts[startup_kind(off, g)][t] += 1
            if prev and not u[t]:
                stops[t] += 1
            off = 0 if u[t] else off + 1
            prev = u[t]
    report = {
        "schema_version": 1, "provenance": "synthetic_not_observed", "kind": "profile",
        "case_id": f"synthetic-uc-v1-n{args.units}-t{args.hours}-seed{args.seed}",
        "solution_file": args.solution.name, "solution_total_cost": sol.get("total_cost"),
        "solution_primal_bound": sol.get("primal_bound"),
        "cost_function": "per unit and hour: no_load*u + marginal*p (linear in p), plus start-up cost by type",
        "fleet": fleet, "storage": storage, "merit": merit,
        "demand": {r: [round(x, 1) for x in v] for r, v in params.regional_demands.items()},
        "demand_total": [round(x, 1) for x in params.demand.demands],
        "output_mw": {k: [round(x, 1) for x in v] for k, v in out_by_fuel.items()},
        "units_on": on_by_fuel, "startups": starts, "shutdowns": stops,
        "startups_total": {k: sum(v) for k, v in starts.items()},
        "run_lengths": runs,
        "flows_mw": {f["interconnection_id"]: [round(x, 1) for x in f["flow_mw"]] for f in sol.get("interconnection_flows", [])},
        "median_marginal": {fuel: statistics.median(g.fuel_cost_per_mwh for g in thermal if g.fuel_type == fuel) for fuel in FUELS},
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False) + "\n")
    print(json.dumps({"startups_total": report["startups_total"], "units_on_peak": {k: max(v) for k, v in on_by_fuel.items()},
                      "output_peak_mw": round(max(sum(out_by_fuel[k][t] for k in FUELS) for t in range(T)))}))


if __name__ == "__main__":
    main()
