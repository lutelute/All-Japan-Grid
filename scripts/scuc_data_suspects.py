"""Which lines that stay overloaded after redispatch point at the network data, and why.

Input: the year summary of scripts/uc_year_grid_merge: lines overloaded before the redispatch LP
and still overloaded after it in the same hour ("stuck"; summaries of the first, penalty version
only have lines still overloaded after it, of which those also overloaded before are taken).
Every such line gets one reason, checked in order:

1. named_unbuilt: its name says 廃線 / 建設中 / 計画 (the 21 branches of
   docs/reports/unbuilt_retired_lines_2026-10-21.md are matched by name);
2. disclosure_backbone: the branch is not an OSM line but one inferred from the utilities'
   disclosures (the class of scripts/sensitivity/n1_screening), standing in for a missing backbone;
3. plant_connection: an end lies within --km of the bus where a UC unit of at least --big-mw is
   attached in the network model; the unit, its capacity and the attachment voltage are listed;
4. other.

The reasons are screening, not findings: whether a line or a connection is wrong is decided on
primary sources and goes through docs/MODEL_INTERVENTIONS.md. The island networks are built the
same way as in the year run (scripts/scuc_evaluate), so this runs where that runs.

    python -m scripts.scuc_data_suspects --summary year_summary.json --out suspects.json
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

from scripts.scuc_evaluate import BUILT, haversine, island_model, mapping, plant_osm_ids

UNBUILT = re.compile(r"廃線|建設中|計画")
LEDGER = Path("docs/reports/unbuilt_retired_lines_2026-10-21/edges.json")


def plant_attachments(scenario, cap_calib):
    """Every UC unit on the island networks: capacity, attachment voltage and position."""
    from scripts.run_full_powerflow_from_db import load_demand_config
    from src.powerflow.pref_demand import pref_zone_gwh
    from src.uc.scenario import build_national_scenario
    built = json.loads(BUILT.read_text())
    nodes, edges = built["nodes"], built["edges"]
    cfg = load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)
    params = build_national_scenario(scenario=scenario).to_uc_parameters()
    osm = plant_osm_ids()
    out = defaultdict(list)
    for isl in ("hokkaido", "east", "west", "okinawa"):
        m = island_model(isl, nodes, edges, cfg, pref_gwh, cap_calib)
        mp = mapping(m, params, osm)
        inv = {m["bus_ppc"](b): int(b) for b in m["sub"].bus.index}
        for g in params.generators:
            if g.id not in mp["gen_bus"]:
                continue
            bus = inv[mp["gen_bus"][g.id]]
            out[isl].append({"id": g.id, "name": g.name, "fuel": g.fuel_type, "cap_mw": round(g.capacity_mw, 1),
                             "attach_kv": float(m["sub"].bus.at[bus, "vn_kv"]), "at": m["xy"].get(bus)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--scenario", default="fy2025r1")
    ap.add_argument("--km", type=float, default=15.0)
    ap.add_argument("--big-mw", type=float, default=500.0)
    ap.add_argument("--cap-calib", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    summary = json.loads(args.summary.read_text())
    ledger = {e["name"] for e in json.loads(LEDGER.read_text())}
    plants = plant_attachments(args.scenario, args.cap_calib)
    result = {"summary": str(args.summary), "method": summary.get("method", "penalty"), "days": summary["days"],
              "km": args.km, "big_mw": args.big_mw, "islands": {}}
    for isl, v in summary["islands"].items():
        big = [p for p in plants[isl] if p["cap_mw"] >= args.big_mw and p["at"]]
        rows = []
        stuck = v.get("stuck")
        if stuck is None:
            stuck = [dict(r, hours_stuck=None) for r in v["residual"] if r["hours_over"] > 0 and r["hours_residual"] > 0]
        for r in stuck:
            row = {k: r[k] for k in ("k", "name", "kv", "class", "a", "b", "hours_over", "hours_residual", "hours_stuck",
                                     "days_residual", "max_residual_mw")}
            near = []
            if r["a"] and r["b"] and r["a"][0] is not None and r["b"][0] is not None:
                for p in big:
                    d = min(haversine(p["at"], r["a"]), haversine(p["at"], r["b"]))
                    if d <= args.km:
                        near.append({**{k: p[k] for k in ("id", "name", "fuel", "cap_mw", "attach_kv")}, "km": round(d, 1)})
            near.sort(key=lambda p: (-p["cap_mw"], p["km"]))
            if UNBUILT.search(r["name"]):
                reason = "named_unbuilt"
                row["in_ledger_2026_10_21"] = r["name"] in ledger
            elif r["class"].startswith("disclosure"):
                reason = "disclosure_backbone"
            elif near:
                reason = "plant_connection"
            else:
                reason = "other"
            rows.append({**row, "reason": reason, "plants_near": near[:4]})
        by_plant = defaultdict(lambda: {"lines": 0, "hours": 0, "max_mw": 0.0})
        for row in rows:
            if row["reason"] == "plant_connection":
                p = row["plants_near"][0]
                acc = by_plant[(p["id"], p["name"], p["fuel"], p["cap_mw"], p["attach_kv"])]
                acc["lines"] += 1
                acc["hours"] += row["hours_stuck"] if row["hours_stuck"] is not None else row["hours_residual"]
                acc["max_mw"] = max(acc["max_mw"], row["max_residual_mw"])
        counts = defaultdict(int)
        for row in rows:
            counts[row["reason"]] += 1
        result["islands"][isl] = {
            "lines_residual": v["lines_residual"], "lines_stuck": v.get("lines_stuck"), "listed": len(rows),
            "by_reason": dict(counts),
            "plants": sorted([{"id": k[0], "name": k[1], "fuel": k[2], "cap_mw": k[3], "attach_kv": k[4], **a}
                              for k, a in by_plant.items()], key=lambda p: -p["hours"]),
            "lines": rows}
        print(isl, "residual", v["lines_residual"], "listed", len(rows), dict(counts))
        for p in result["islands"][isl]["plants"][:6]:
            print(f"   {p['name'][:24]} {p['cap_mw']:.0f} MW at {p['attach_kv']:.0f} kV: {p['lines']} lines, {p['hours']} h")
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
