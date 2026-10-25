"""Zonal congestion of a UC plan: regional prices, and what each tie line's limit costs.

Solves the national UC, fixes the commitment and re-solves the LP for duals (extract_duals):
the dual of each region's balance is that region's price per MWh in each hour. For a tie line
from a to b carrying f (positive a -> b), the congestion rent is (price_b - price_a) * f and
|price_b - price_a| is what one more MW of that line would save in that hour (zero unless the
line is at its limit). Summed over the day this ranks the tie lines by what their limit costs.

    python -m scripts.uc_zonal_congestion --scenario fy2023r2 --out zonal_congestion.json
"""

import argparse
import json
from pathlib import Path

from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--gap", type=float, default=1e-4)
    ap.add_argument("--time-limit", type=float, default=300)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    params = build_national_scenario(scenario=args.scenario).to_uc_parameters(extract_duals=True)
    params.solver_name, params.solver_time_limit_s, params.mip_gap = "HiGHS", args.time_limit, args.gap
    params.solver_options = {"threads": 1}
    r = solve_uc(params)
    lmp = r.regional_lmp
    flows = {f.interconnection_id: f.flow_mw for f in r.interconnection_flows}
    links = []
    for ic in params.interconnections:
        f = flows[ic.id]
        diff = [lmp[ic.to_region][t] - lmp[ic.from_region][t] for t in range(len(f))]
        at_limit = [abs(x) >= 0.995 * (ic.cap_fwd if x >= 0 else ic.cap_rev) for x in f]
        links.append({"id": ic.id, "from": ic.from_region, "to": ic.to_region, "cap_fwd": ic.cap_fwd, "cap_rev": ic.cap_rev,
                      "flow": [round(x, 1) for x in f], "price_diff": [round(x, 2) for x in diff], "at_limit": at_limit,
                      "rent_yen": round(sum(d * x for d, x in zip(diff, f)), 0),
                      "value_of_1mw_yen_per_day": round(sum(abs(d) for d, a in zip(diff, at_limit) if a), 1)})
    links.sort(key=lambda l: -l["rent_yen"])
    out = {"schema_version": 1, "kind": "zonal_congestion", "scenario": args.scenario,
           "provenance": f"scenario_{args.scenario}_assumed_day", "status": r.status, "verified": r.feasibility_verified,
           "gap": r.gap, "total_cost": r.total_cost, "warnings": r.warnings[-5:],
           "regional_lmp": {k: [round(x, 2) for x in v] for k, v in lmp.items()}, "links": links}
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"status": r.status, "verified": r.feasibility_verified, "gap": r.gap,
                      "price_range": {k: [min(v), max(v)] for k, v in lmp.items()} if lmp else None}, ensure_ascii=False))
    for l in links:
        print(l["id"], l["from"], "->", l["to"], "rent", l["rent_yen"], "limit_hours", sum(l["at_limit"]),
              "value_of_1MW/day", l["value_of_1mw_yen_per_day"])


if __name__ == "__main__":
    main()
