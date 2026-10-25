"""Solve the national 24h UC of a scenario and write what a Japan map needs.

Per generator: region, fuel, capacity, lat/lon, hourly output and on/off. Per interconnection:
ends, capacity and hourly flow. Per region: gross demand, solar, wind and run-of-river hydro
(the UC serves gross demand minus those three). The UC is the one in
src/uc (plant-level records from data/{region}_plants.geojson), solved with HiGHS.

    python -m scripts.uc_geo_export --scenario fy2023r2 --out geo_fy2023r2.json
"""

import argparse
import json
from pathlib import Path
import re
import time

from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--time-limit", type=float, default=300)
    ap.add_argument("--gap", type=float, default=0.001)
    ap.add_argument("--strengthen", nargs="*", default=[])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    begin = time.monotonic()
    scn = build_national_scenario(scenario=args.scenario)
    params = scn.to_uc_parameters()
    params.solver_name, params.solver_time_limit_s, params.mip_gap = "HiGHS", args.time_limit, args.gap
    params.solver_options = {"threads": 1}
    params.strengthen = tuple(args.strengthen)
    result = solve_uc(params)
    sched = {s.generator_id: s for s in result.schedules}
    # UC ids are "{source region}_g{feature index}" into data/{region}_plants.geojson; the loader
    # does not copy the point onto Generator.latitude/longitude, so look it up here.
    features = {}
    def coords(g):
        if g.latitude or g.longitude:
            return g.latitude, g.longitude
        m = re.match(r"^(\w+?)_g(\d+)$", g.id)
        if not m:
            return None, None
        r, i = m[1], int(m[2])
        if r not in features:
            path = Path("data") / f"{r}_plants.geojson"
            features[r] = json.loads(path.read_text())["features"] if path.exists() else []
        if i >= len(features[r]) or (features[r][i].get("geometry") or {}).get("type") != "Point":
            return None, None
        lon, lat = features[r][i]["geometry"]["coordinates"][:2]
        return lat, lon
    gens = []
    for g in params.generators:
        s = sched.get(g.id)
        if s is None:
            continue
        lat, lon = coords(g)
        gens.append({"id": g.id, "name": g.name, "region": g.region, "fuel": g.fuel_type, "cap": round(g.capacity_mw, 1),
                     "lat": lat and round(lat, 4), "lon": lon and round(lon, 4),
                     "mw": [round(x, 1) for x in s.power_output_mw], "on": [int(round(x)) for x in s.commitment]})
    flows = {f.interconnection_id: f.flow_mw for f in result.interconnection_flows}
    links = [{"id": ic.id, "from": ic.from_region, "to": ic.to_region, "cap": ic.capacity_mw,
              "name": getattr(ic, "name_ja", None) or ic.name_en, "flow": [round(x, 1) for x in flows.get(ic.id, [])]}
             for ic in params.interconnections]
    out = {"schema_version": 1, "kind": "uc_geo", "scenario": args.scenario, "status": result.status,
           "termination": result.termination_reason, "total_cost": result.total_cost, "gap": result.gap,
           "verified": result.feasibility_verified, "solve_s": result.solve_time_s, "wall_s": time.monotonic() - begin,
           "validation_errors": result.validation.get("errors", [])[:10],
           "hours": params.time_horizon.num_periods, "generators": gens, "links": links,
           "demand": {r: [round(x, 1) for x in v] for r, v in scn.gross_demand_r.items()},
           "solar": {r: [round(x, 1) for x in v] for r, v in scn.solar_gen_r.items()},
           "wind": {r: [round(x, 1) for x in v] for r, v in scn.wind_gen_r.items()},
           "hydro_ror": {r: [round(x, 1) for x in v] for r, v in scn.hydro_ror_gen_r.items()},
           "objective_overstatement": result.validation.get("objective_overstatement")}
    args.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"status": result.status, "verified": result.feasibility_verified, "gap": result.gap,
                      "generators": len(gens), "with_coords": sum(1 for g in gens if g["lat"]), "links": len(links),
                      "validation_errors": out["validation_errors"][:3],
                      "wall_s": round(out["wall_s"], 1)}))


if __name__ == "__main__":
    main()
