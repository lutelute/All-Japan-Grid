"""SCUC stage 2: the national UC with the real grid's line limits, added lazily.

docs/research/uc800-open-solver/SCUC_PLAN.md, stage 2. The flow on every watched line (154 kV+,
132 kV on Okinawa; capacities calibrated, intervention #45) is linear in the UC's variables:
outputs of the units mapped to buses, DC links at their terminals, renewables and demand fixed,
and the rest (unmapped units, spill) spread over the loads, exactly as scripts/scuc_evaluate
evaluates a plan. Only (line, hour) pairs that a solve violates are added, and the next solve
starts from the last plan (MIP start); the loop ends when no watched line is over.

Two passes, the same order as the redispatch LP (scripts/scuc_redispatch.py), but now the
commitment may change too:

A. line limits soft with a penalty per MW over. What is still over at the end cannot be cleared
   by any commitment and dispatch the model finds: data suspects (or the regional plan's own
   inputs). Those (line, hour) limits are then raised to the flow pass A left.
B. the same with cost alone. Pass B's cost minus the UC's without lines is what the grid's
   limits cost that day; the units whose commitment changed are what it takes.

The zonal UC keeps its regional balances and tie-line variables; a tie's OCCTO limit stays a
limit on the zonal transfer, not on the physical flow across the boundary (SCUC_PLAN: flowgates,
later). Lower bounds: every solve's MILP bound holds for the problem with all line limits only
when nothing is over at the end; pass B's gap is reported with that caveat.

With --exclude-from (that date's file of scripts/uc_year_grid), lines that were over before the
redispatch LP and still over after it in some hour of the day are not watched: on the summer
peak of 2025 they are 570 of 593 overloaded lines, the data suspects of
docs/reports/scuc_data_suspects_2026-10-25.md. Watching them, pass A spends 9 % more on fuel
chasing them and the total overload still grows (2025-08-06, 400 cuts, first iteration).

    python -m scripts.scuc_stage2 --date 2025-08-06 --exclude-from year/2025-08-06.json --out s2.json
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import time

import numpy as np
import pulp

from scripts.scuc_evaluate import BUILT, injection, island_model, mapping, plant_osm_ids
from src.uc.scenario import build_national_scenario, load_scenario_config
from src.uc.solver import solve_uc

PENALTY = 1.0e5          # pass A: yen per MW over a line limit for one hour (LNG is ~1.1e4 yen/MWh)
COEF_MIN = 1e-5          # sensitivities below this are left out of a line's row


def flow_model(m, mp, scn, params):
    """Watched lines of island m: F[:, t] = G @ p[:, t] + D @ dc[:, t] + C[:, t] (MW)."""
    mon = np.where(m["monitor"] & np.isfinite(m["cap"]) & (m["cap"] > 0))[0]
    ptdf = m["ptdf"][mon]
    nb = ptdf.shape[1]
    share = np.zeros(nb)
    for b, sh in mp["all_load"]:
        share[b] += sh
    share /= share.sum()
    spread = ptdf @ share                                  # flow of 1 MW taken from all loads
    units = [g.id for g in params.generators if g.id in mp["gen_bus"]]
    G = ptdf[:, [mp["gen_bus"][u] for u in units]] - spread[:, None]
    dc = [(ic_id, -1.0 if is_from else 1.0, b) for ic_id, is_from, b, _ in mp["dc"]]
    D = (np.stack([s * (ptdf[:, b] - spread) for _, s, b in dc], axis=1) if dc else np.zeros((len(mon), 0)))
    T = params.time_horizon.num_periods
    C = np.zeros((len(mon), T))
    for t in range(T):
        inj = np.zeros(nb)
        for kind, series in (("solar", scn.solar_gen_r), ("wind", scn.wind_gen_r), ("hydro_ror", scn.hydro_ror_gen_r)):
            for r in mp["regions"]:
                v = float(series[r][t]) if r in series else 0.0
                for b, sh in mp["re_share"][(kind, r)]:
                    inj[b] += v * sh
        for r in mp["regions"]:
            d = float(scn.gross_demand_r[r][t])
            for b, sh in mp["load_share"].get(r, []):
                inj[b] -= d * sh
        C[:, t] = ptdf @ inj - spread * inj.sum()
    return {"mon": mon, "cap": m["cap"][mon], "units": units, "G": G, "dc": dc, "D": D, "C": C}


def drop_lines(fm, keep):
    """The flow model restricted to the watched lines where keep is true."""
    return {**fm, "mon": fm["mon"][keep], "cap": fm["cap"][keep], "G": fm["G"][keep], "D": fm["D"][keep], "C": fm["C"][keep]}


def line_flows(fm, result):
    """Flows (watched lines x hours) of a solved plan."""
    sched = {s.generator_id: s.power_output_mw for s in result.schedules}
    P = np.array([sched[u] for u in fm["units"]], dtype=float)
    F = fm["G"] @ P + fm["C"]
    if fm["dc"]:
        flows = {fl.interconnection_id: fl.flow_mw for fl in result.interconnection_flows}
        F += fm["D"] @ np.array([flows[i] for i, _, _ in fm["dc"]], dtype=float)
    return F


def line_hook(fms, cuts, penalty):
    """model_hook: -limit <= F[line, t] <= limit for every cut, soft if penalty."""

    def hook(model, var):
        p, f, slack = var["p"], var["f"], []
        for (isl, i, t), limit in cuts.items():
            fm = fms[isl]
            g, d = fm["G"][i], fm["D"][i]
            expr = pulp.lpSum(float(g[j]) * p[(fm["units"][j], t)] for j in np.nonzero(np.abs(g) > COEF_MIN)[0])
            expr += pulp.lpSum(float(d[j]) * f[(fm["dc"][j][0], t)] for j in range(len(fm["dc"])) if abs(d[j]) > COEF_MIN)
            expr += float(fm["C"][i, t])
            name = f"line_{isl}_{int(fm['mon'][i])}_{t}"
            if penalty:
                s = pulp.LpVariable(f"over_{isl}_{int(fm['mon'][i])}_{t}", lowBound=0)
                slack.append(s)
                model += expr <= limit + s, name + "_hi"
                model += -expr <= limit + s, name + "_lo"
            else:
                model += expr <= limit, name + "_hi"
                model += -expr <= limit, name + "_lo"
        if slack:
            model.setObjective(var["cost"] + penalty * pulp.lpSum(slack))

    return hook


def violations(fms, result, cuts):
    """Watched (line, hour) over their limit (a cut's limit where there is one), largest first."""
    out = []
    for isl, fm in fms.items():
        F = line_flows(fm, result)
        for i, t in zip(*np.nonzero(np.abs(F) > fm["cap"][:, None])):
            limit = cuts.get((isl, int(i), int(t)), fm["cap"][i])
            over = abs(F[i, t]) - limit
            if over > max(1.0, 2e-3 * limit):
                out.append(((isl, int(i), int(t)), float(over), float(abs(F[i, t]))))
    return sorted(out, key=lambda v: -v[1])


def solve_pass(params, fms, cuts, penalty, start, args, log, tag):
    r = None
    for it in range(args.max_iter):
        params.model_hook = line_hook(fms, cuts, penalty)
        params.warm_start_schedules = start
        t0 = time.monotonic()
        r = solve_uc(params)
        if not r.schedules:
            log.append({"pass": tag, "iter": it, "status": r.status})
            return r
        viol = violations(fms, r, cuts)
        new = [v for v in viol if v[0] not in cuts][:args.add_per_iter]
        over_cut = [v for v in viol if v[0] in cuts]
        log.append({"pass": tag, "iter": it, "status": r.status, "cost": r.total_cost, "objective": r.solver_objective,
                    "gap": r.gap, "verified": r.feasibility_verified, "cuts": len(cuts), "new": len(new),
                    "over_on_cuts": len(over_cut), "over_mw_sum": round(sum(v[1] for v in viol), 1),
                    "s": round(time.monotonic() - t0, 1)})
        print(json.dumps(log[-1]), flush=True)
        start = r.schedules
        if not new:
            return r
        for key, _, _ in new:
            isl, i, _ = key
            cuts[key] = float(fms[isl]["cap"][i])
    return r


def summary(fms, result):
    over = defaultdict(lambda: [0, 0.0])
    for isl, fm in fms.items():
        F = line_flows(fm, result)
        ex = np.abs(F) - fm["cap"][:, None]
        for i, t in zip(*np.nonzero(ex > 1.0)):
            acc = over[(isl, int(fm["mon"][i]))]
            acc[0] += 1
            acc[1] = max(acc[1], float(ex[i, t]))
    return [{"island": isl, "k": k, "hours": h, "max_over_mw": round(mx, 1)} for (isl, k), (h, mx) in over.items()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="fy2025r1")
    ap.add_argument("--date", required=True)
    ap.add_argument("--islands", nargs="*", default=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--time-limit", type=float, default=300)
    ap.add_argument("--gap", type=float, default=1e-3)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--seed", type=int, default=None, help="HiGHS random_seed: rerun with others to tell grid-driven changes from ties")
    ap.add_argument("--max-iter", type=int, default=12)
    ap.add_argument("--add-per-iter", type=int, default=400)
    ap.add_argument("--penalty", type=float, default=PENALTY)
    ap.add_argument("--cap-calib", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--exclude-from", type=Path, help="day file of uc_year_grid: do not watch its stuck lines")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    from scripts.run_full_powerflow_from_db import load_demand_config
    from src.powerflow.pref_demand import pref_zone_gwh

    t_all = time.monotonic()
    cfg = load_scenario_config(args.scenario)
    cfg.demand_profile_ref = dict(cfg.demand_profile_ref, representative_day=args.date)
    scn = build_national_scenario(cfg)
    params = scn.to_uc_parameters()
    params.solver_name, params.solver_time_limit_s, params.mip_gap = "HiGHS", args.time_limit, args.gap
    params.solver_options = {"threads": args.threads} | ({"random_seed": args.seed} if args.seed is not None else {})
    built = json.loads(BUILT.read_text())
    nodes, edges = built["nodes"], built["edges"]
    dcfg = load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)
    osm = plant_osm_ids()
    fms, nets = {}, {}
    for isl in args.islands:
        m = island_model(isl, nodes, edges, dcfg, pref_gwh, args.cap_calib)
        nets[isl] = (m, mapping(m, params, osm))
        fms[isl] = flow_model(m, nets[isl][1], scn, params)
        print(isl, "watched", len(fms[isl]["mon"]), "units", len(fms[isl]["units"]), flush=True)
    t_net = time.monotonic() - t_all

    log = []
    base = solve_uc(params)                                    # the UC without lines
    base_over = violations(fms, base, {})
    log.append({"pass": "uc", "status": base.status, "cost": base.total_cost, "gap": base.gap,
                "verified": base.feasibility_verified, "over_pairs": len(base_over),
                "over_mw_sum": round(sum(v[1] for v in base_over), 1)})
    print(json.dumps(log[-1]), flush=True)
    # the linear flows must be the evaluation's flows (scripts/scuc_evaluate.injection)
    plan = {"mw": {s.generator_id: list(s.power_output_mw) for s in base.schedules},
            "flows": {f.interconnection_id: list(f.flow_mw) for f in base.interconnection_flows}}
    check = {}
    for isl, (m, mp) in nets.items():
        F = line_flows(fms[isl], base)
        check[isl] = max(float(np.max(np.abs(m["ptdf"][fms[isl]["mon"]] @ injection(m, mp, scn, params, plan, t)[0] - F[:, t])))
                         for t in (0, 12, params.time_horizon.num_periods - 1))
    print("flow check max |diff| MW", check, flush=True)
    if max(check.values()) > 1e-3:
        raise SystemExit(f"linear flows differ from the evaluation: {check}")
    excluded = {}
    if args.exclude_from:
        day = json.loads(args.exclude_from.read_text())
        if day["date"] != args.date or day["scenario"] != args.scenario:
            raise SystemExit(f"{args.exclude_from} is for {day['scenario']} {day['date']}")
        for isl, fm in fms.items():
            stuck = {int(k) for k, v in day["islands"][isl]["lines"].items() if len(v) == 6 and v[5] > 0}
            keep = np.array([int(k) not in stuck for k in fm["mon"]])
            excluded[isl] = sorted(int(k) for k in fm["mon"][~keep])
            fms[isl] = drop_lines(fm, keep)
        base_over = violations(fms, base, {})
        log.append({"pass": "uc_watched", "excluded_lines": {k: len(v) for k, v in excluded.items()},
                    "over_pairs": len(base_over), "over_mw_sum": round(sum(v[1] for v in base_over), 1)})
        print(json.dumps(log[-1]), flush=True)
    cuts = {}
    a = solve_pass(params, fms, cuts, args.penalty, base.schedules, args, log, "A")
    stuck = violations(fms, a, cuts)                            # still over after pass A
    held = {}
    for key, over, flow in stuck:
        cuts[key] = flow + 1.0
        held[key] = round(flow, 1)
    b = solve_pass(params, fms, cuts, args.penalty, a.schedules, args, log, "B")

    def on_hours(r):
        return {s.generator_id: int(sum(c > 0.5 for c in s.commitment)) for s in r.schedules}

    hb, hbase = on_hours(b), on_hours(base)
    gens = {g.id: g for g in params.generators}
    changed = sorted(({"id": g, "name": gens[g].name, "fuel": gens[g].fuel_type, "cap_mw": gens[g].capacity_mw,
                       "on_hours_uc": hbase.get(g, 0), "on_hours_scuc": hb.get(g, 0)}
                      for g in set(hb) | set(hbase) if hb.get(g, 0) != hbase.get(g, 0)),
                     key=lambda x: -abs(x["on_hours_scuc"] - x["on_hours_uc"]) * x["cap_mw"])
    out = {"schema_version": 1, "kind": "scuc_stage2", "scenario": args.scenario, "date": args.date,
           "islands": args.islands, "cap_calib": args.cap_calib, "penalty_pass_a": args.penalty, "seed": args.seed,
           "network_build_s": round(t_net, 1), "flow_check_max_diff_mw": check,
           "exclude_from": str(args.exclude_from) if args.exclude_from else None, "excluded_lines": excluded, "wall_s": round(time.monotonic() - t_all, 1), "log": log,
           "cost_uc": base.total_cost, "cost_scuc": b.total_cost if b else None,
           "grid_price_yen": (b.total_cost - base.total_cost) if b and b.total_cost is not None else None,
           "gap_scuc": b.gap if b else None, "verified_scuc": b.feasibility_verified if b else None,
           "cuts": len(cuts), "held_after_a": [{"island": k[0], "k": int(fms[k[0]]["mon"][k[1]]), "t": k[2], "flow_mw": v}
                                               for k, v in held.items()],
           "over_uc": summary(fms, base), "over_scuc": summary(fms, b) if b and b.schedules else None,
           "commitment_changed": changed, "on_hours_uc": hbase, "on_hours_scuc": hb}
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("cost_uc", "cost_scuc", "grid_price_yen", "gap_scuc", "cuts", "wall_s")}),
          "held", len(held), "changed", len(changed), flush=True)


if __name__ == "__main__":
    main()
