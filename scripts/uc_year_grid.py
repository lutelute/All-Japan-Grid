"""A year of national UC days, each run through the real grid (SCUC stage 1 at scale).

For every date: the national UC of the scenario with that day's observed OCCTO area demand
(fy2025r1: profile_ref.representative_day), solved with HiGHS; the region-level N-1 shortfall
(src/uc/risk.py); tie lines at their limit; then, island by island and hour by hour, the
redispatch LP of scripts/scuc_redispatch.py on the 154 kV+ lines (overloads before and after
redispatch, redispatch cost, value of one more MW of each binding line).

Each worker process builds the four island networks and their PTDFs once and then works
through its dates, writing one JSON per date into --out-dir (dates already done are skipped,
so a run can be restarted or split across machines with --shard i/n). The UC plan of each date
goes next to it as <date>.plan.json.gz; with --plans-dir pointing at those, a rerun redoes only
the grid stage.

    python -m scripts.uc_year_grid --from 2025-04-01 --to 2026-03-31 --shard 0/3 --workers 12 --out-dir year
"""

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import datetime as dt
import gzip
import json
import os
from pathlib import Path
import time

_STATE = {}


def _init(cap_calib):
    """Per worker: the island networks, built once."""
    from scripts.run_full_powerflow_from_db import load_demand_config
    from scripts.scuc_evaluate import BUILT, island_model, plant_osm_ids
    from src.powerflow.pref_demand import pref_zone_gwh
    built = json.loads(BUILT.read_text())
    nodes, edges = built["nodes"], built["edges"]
    cfg = load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)
    _STATE["models"] = {isl: island_model(isl, nodes, edges, cfg, pref_gwh, cap_calib)
                        for isl in ("hokkaido", "east", "west", "okinawa")}
    _STATE["osm"] = plant_osm_ids()
    # Line keys in the day files are ppc branch indices: write what they are, once per machine,
    # so that results from different machines can be checked to use the same numbering.
    out_dir = Path(os.environ["UC_YEAR_OUT"])
    host = os.uname().nodename
    for isl, m in _STATE["models"].items():
        path = out_dir / f"catalog_{isl}_{host}.json"
        if path.exists():
            continue
        sub, ppc = m["sub"], m["ppc"]
        inv = {m["bus_ppc"](b): int(b) for b in sub.bus.index}
        rows = []
        for k in range(m["nl"]):
            tbl, eid = m["elems"][k]
            fb, tb = int(ppc["branch"][k, 0].real), int(ppc["branch"][k, 1].real)
            rows.append({"k": k, "name": str(getattr(sub, tbl).at[eid, "name"]) if tbl else "", "kv": float(m["kv"][k]),
                         "class": str(m["cls"][k]), "monitored": bool(m["monitor"][k]),
                         "a": m["xy"].get(inv.get(fb)), "b": m["xy"].get(inv.get(tb))})
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
        tmp.rename(path)


def solve_day_plan(date, scenario, time_limit, gap):
    """The national UC of one date: the day file's header fields and the plan (None if unsolved)."""
    from src.uc.risk import congested_hours, n1_shortfall
    from src.uc.scenario import build_national_scenario, load_scenario_config
    from src.uc.solver import solve_uc
    cfg = load_scenario_config(scenario)
    cfg.demand_profile_ref = dict(cfg.demand_profile_ref, representative_day=date)
    scn = build_national_scenario(cfg)
    params = scn.to_uc_parameters()
    params.solver_name, params.solver_time_limit_s, params.mip_gap = "HiGHS", time_limit, gap
    params.solver_options = {"threads": 1}
    r = solve_uc(params)
    out = {"date": date, "scenario": scenario, "demand_sha": scn.demand_profile_sha, "status": r.status,
           "verified": r.feasibility_verified, "cost": r.total_cost, "gap": r.gap, "solve_s": r.solve_time_s,
           "gross_demand_mwh": float(sum(v.sum() for v in scn.gross_demand_r.values())),
           "peak_mw": float(sum(scn.gross_demand_r.values()).max())}
    plan = None
    if r.schedules:
        n1 = n1_shortfall(params, r)
        out.update(n1_shortfall_mwh=n1["total_mwh"], n1_by_region_mwh={k: round(sum(v), 1) for k, v in n1["shortfall_mw"].items()},
                   tie_hours_at_limit=congested_hours(params, r))
        plan = {"mw": {s.generator_id: list(s.power_output_mw) for s in r.schedules},
                "on": {s.generator_id: sum(1 << t for t, c in enumerate(s.commitment) if c > 0.5) for s in r.schedules},
                "flows": {f.interconnection_id: list(f.flow_mw) for f in r.interconnection_flows}}
    return scn, params, out, plan


def run_day(job):
    date, scenario, out_dir, time_limit, gap, plans_dir = job
    path = Path(out_dir) / f"{date}.json"
    if path.exists():
        return date, "skipped"
    from scripts.scuc_evaluate import mapping
    from scripts.scuc_redispatch import MOVABLE, solve_hour
    from src.uc.scenario import build_national_scenario, load_scenario_config
    begin = time.monotonic()
    # The UC plan of a date is kept next to the day file, so that the grid stage can be rerun
    # (another redispatch, corrected network data) without solving the UC again.
    plan_path = Path(plans_dir or out_dir) / f"{date}.plan.json.gz"
    if plan_path.exists():
        saved = json.loads(gzip.decompress(plan_path.read_bytes()))
        out, plan = saved["uc"], saved["plan"]
        cfg = load_scenario_config(scenario)
        cfg.demand_profile_ref = dict(cfg.demand_profile_ref, representative_day=date)
        scn = build_national_scenario(cfg)
        params = scn.to_uc_parameters()
        if scn.demand_profile_sha != out["demand_sha"] or out["scenario"] != scenario:
            raise SystemExit(f"{plan_path}: saved plan is for another scenario or demand")
        out["plan_reused"] = str(plan_path)
    else:
        scn, params, out, plan = solve_day_plan(date, scenario, time_limit, gap)
        tmp = Path(out_dir) / f"{date}.plan.tmp"
        tmp.write_bytes(gzip.compress(json.dumps({"uc": out, "plan": plan}, separators=(",", ":")).encode()))
        tmp.rename(Path(out_dir) / f"{date}.plan.json.gz")
    if plan:
        islands = {}
        for isl, m in _STATE["models"].items():
            mp = mapping(m, params, _STATE["osm"])
            gens = [g for g in params.generators if g.id in mp["gen_bus"] and g.fuel_type in MOVABLE]
            # h_before, h_after, max_after_mw, value_yen, h_binding, h_stuck (over before and still over after)
            lines = defaultdict(lambda: [0, 0, 0.0, 0.0, 0, 0])
            agg = defaultdict(float)
            for t in range(params.time_horizon.num_periods):
                hr = solve_hour(m, mp, scn, params, plan, t, gens)
                agg["lp_failed"] += hr["status"] != "optimal"
                for key in ("redispatch_yen", "over_before_mw", "over_after_mw", "n_over_before", "n_over_after", "probe_failed"):
                    agg[key] += hr.get(key, 0) or 0
                for k, v in hr.get("lines", {}).items():
                    row = lines[k]
                    row[0] += v["before"] > 0
                    row[1] += v["after"] > 0
                    row[2] = max(row[2], v["after"])
                    row[3] += v["value"] or 0.0
                    row[4] += (v["value"] or 0.0) > 1e-6
                    row[5] += v["before"] > 0 and v["after"] > 0
            islands[isl] = {**{k: round(v, 1) for k, v in agg.items()},
                            "lines": {str(k): [a, b, round(c, 1), round(d, 1), e, f] for k, (a, b, c, d, e, f) in lines.items()}}
        out["islands"] = islands
    out["wall_s"] = round(time.monotonic() - begin, 1)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.rename(path)
    return date, out["status"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="fy2025r1")
    ap.add_argument("--from", dest="date_from", default="2025-04-01")
    ap.add_argument("--to", dest="date_to", default="2026-03-31")
    ap.add_argument("--shard", default="0/1", help="i/n: this machine takes every n-th date starting at i")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--time-limit", type=float, default=180)
    ap.add_argument("--gap", type=float, default=1e-3)
    ap.add_argument("--cap-calib", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--plans-dir", type=Path, help="reuse <date>.plan.json.gz from here (default: --out-dir)")
    args = ap.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    d0, d1 = dt.date.fromisoformat(args.date_from), dt.date.fromisoformat(args.date_to)
    dates = [(d0 + dt.timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]
    i, n = map(int, args.shard.split("/"))
    mine = [d for k, d in enumerate(dates) if k % n == i and not (args.out_dir / f"{d}.json").exists()]
    (args.out_dir / "meta.json").write_text(json.dumps({"scenario": args.scenario, "from": args.date_from, "to": args.date_to,
                                                        "time_limit": args.time_limit, "gap": args.gap,
                                                        "cap_calib": args.cap_calib}, indent=1) + "\n")
    print(f"{len(mine)} dates for shard {args.shard}, {args.workers} workers", flush=True)
    jobs = [(d, args.scenario, str(args.out_dir), args.time_limit, args.gap, args.plans_dir and str(args.plans_dir))
            for d in mine]
    os.environ["UC_YEAR_OUT"] = str(args.out_dir)
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init, initargs=(args.cap_calib,)) as pool:
        for date, status in pool.map(run_day, jobs):
            print(date, status, flush=True)


if __name__ == "__main__":
    main()
