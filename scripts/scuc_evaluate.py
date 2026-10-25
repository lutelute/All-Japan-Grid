"""Run a UC plan through the real grid, hour by hour: base-case and N-1 loading of 154 kV+ lines.

SCUC stage 1 (docs/research/uc800-open-solver/SCUC_PLAN.md). The plan comes from the zonal UC
(10 regions + tie lines). Each island is built with the same steps as the production power flow
and the N-1 screening (scripts/sensitivity/benchmark_sensitivity.production_net), keeping its
largest connected component and one reference bus. Then, for every hour:

- each UC generator is put on the bus its plant is attached to (net.gen.src_feature is the UC id
  `{region}_g{index}`; when the two picked different copies of a duplicated plant, by OSM id);
- each region's solar, wind and run-of-river hydro go to that region's solar / wind / hydro
  plants in proportion to capacity (the UC only knows them as regional totals);
- each region's gross demand is spread over its loads in the production proportions;
- DC links inject the UC flow at the 154 kV+ bus nearest to their converter station;
- what is left over (generators outside the main component, rounding) is spread over all loads
  of the island in proportion (a distributed slack), and reported;
- flows are PTDF x injections; the N-1 screen (src/powerflow/contingency.screen) runs on them.

Only branches that exist (OSM / disclosure lines, nameplate transformers) at 154 kV and above
are watched, as in scripts/sensitivity/n1_screening.py. Heavy: run on a lab server, not a laptop.

    python -m scripts.scuc_evaluate --plan near.json --plan-key reference --out scuc_eval.json
"""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import time

import numpy as np
import pandapower as pp
from pandapower.pypower.idx_brch import BR_STATUS, F_BUS, T_BUS
from pandapower.pypower.makePTDF import makePTDF

from scripts.sensitivity.benchmark_sensitivity import main_component_subnet
from scripts.sensitivity.n1_screening import PHYSICAL_CLASSES, classify, edge_lookup
from scripts.run_full_powerflow_from_db import load_demand_config
from src.powerflow import contingency as cg
from src.powerflow.full_from_built import (GEN_ZONE_BY_OPERATOR, ISLAND_FREQ, add_per_component_slacks,
                                          allocate_loads, attach_default_for, attach_generators,
                                          balance_by_zone, build_island_net)
from src.uc.scenario import build_national_scenario

BUILT = Path("docs/data/built/all.json")
ISLAND_OF_REGION = {"hokkaido": "hokkaido", "tohoku": "east", "tokyo": "east", "chubu": "west", "hokuriku": "west",
                    "kansai": "west", "chugoku": "west", "shikoku": "west", "kyushu": "west", "okinawa": "okinawa"}
# Converter stations (lat, lon) of the DC links in the UC, one site per end
DC_TERMINALS = {
    ("hokkaido", "tohoku"): ((41.80, 140.75), (40.75, 141.22)),    # 函館 / 上北（北本連系）
    ("tokyo", "chubu"): ((36.11, 137.88), (36.11, 137.88)),        # 新信濃 FC（両側とも同じ敷地）
    ("kansai", "shikoku"): ((34.29, 135.57), (33.86, 134.66)),     # 紀北 / 阿南
    ("chubu", "hokuriku"): ((36.53, 136.87), (36.53, 136.87)),     # 南福光 BTB
}
RE_FUELS = {"solar": ("solar",), "wind": ("wind",), "hydro_ror": ("hydro", "water")}


def haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def island_model(island, nodes, edges, cfg, pref_gwh, cap_calib):
    net, bus_of, _ = build_island_net(island, nodes, edges, ISLAND_FREQ[island], {}, cap_calib=cap_calib)
    attach_generators(net, bus_of, nodes, island, attach_mode=attach_default_for(island))
    allocate_loads(net, cfg, pref_gwh=pref_gwh)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    add_per_component_slacks(net)
    balance_by_zone(net, cfg, use_zone_src=GEN_ZONE_BY_OPERATOR)
    sub, _ = main_component_subnet(net)
    pp.rundcpp(sub)
    ppc = sub._ppc
    lk_bus = sub._pd2ppc_lookups["bus"]
    ref = int(lk_bus[int(sub.ext_grid.bus.iloc[0])])
    ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"], slack=ref)
    nl = ptdf.shape[0]
    elems = cg.branch_elements(sub)
    lk = edge_lookup(edges)
    cls = np.array([classify(sub, t, e, lk) if t else "unknown" for t, e in elems])
    kv = cg.branch_kv(ppc)
    status = ppc["branch"][:, BR_STATUS].real.astype(float) > 0
    min_kv = 154.0 if ((kv >= 153.5) & status).any() else float(np.max(kv[status]))
    monitor = (kv >= min_kv - 0.5) & status & np.isin(cls, PHYSICAL_CLASSES)
    node_of_bus = {b: i for i, b in bus_of.items()}
    xy = {}
    for b in sub.bus.index:
        n = nodes[node_of_bus[int(b)]] if int(b) in node_of_bus else {}
        xy[int(b)] = (n.get("lat"), n.get("lon"))
    return {"island": island, "sub": sub, "ppc": ppc, "ptdf": ptdf, "ref": ref, "nl": nl, "kv": kv,
            "cap": cg.branch_capacity_mw(sub, nl, 1.0), "par": cg.branch_parallel(sub, nl), "elems": elems,
            "cls": cls, "monitor": monitor, "min_kv": min_kv, "bus_ppc": lambda b: int(lk_bus[int(b)]), "xy": xy}


def plant_osm_ids():
    out = {}
    for path in Path("data").glob("*_plants.geojson"):
        region = path.name.split("_plants")[0]
        for i, f in enumerate(json.loads(path.read_text())["features"]):
            oid = (f.get("properties") or {}).get("osm_id")
            if oid is not None:
                out[f"{region}_g{i}"] = oid
    return out


def nearest_bus(m, latlon, zone):
    sub, best = m["sub"], None
    for b in sub.bus.index:
        if sub.bus.at[b, "zone"] != zone or float(sub.bus.at[b, "vn_kv"]) < 153.5:
            continue
        p = m["xy"][int(b)]
        if p[0] is None:
            continue
        d = haversine(latlon, p)
        if best is None or d < best[0]:
            best = (d, int(b))
    return best


def mapping(m, params, osm):
    """Where every part of the zonal plan goes on this island's buses (ppc indices)."""
    sub = m["sub"]
    island = m["island"]
    regions = [r for r, isl in ISLAND_OF_REGION.items() if isl == island]
    # UC generator -> bus
    by_src = {s: int(sub.gen.at[g, "bus"]) for g, s in sub.gen["src_feature"].items() if isinstance(s, str)}
    by_osm = {osm[s]: b for s, b in by_src.items() if s in osm}
    gen_bus, unmapped = {}, []
    for g in params.generators:
        if ISLAND_OF_REGION.get(g.region) != island:
            continue
        b = by_src.get(g.id)
        if b is None and g.id in osm:
            b = by_osm.get(osm[g.id])
        if b is None:
            unmapped.append(g.id)
        else:
            gen_bus[g.id] = m["bus_ppc"](b)
    # regional renewables -> that region's plants of the fuel, by capacity
    re_share = {}
    for kind, fuels in RE_FUELS.items():
        for r in regions:
            rows = [(m["bus_ppc"](sub.gen.at[g, "bus"]), float(sub.gen.at[g, "max_p_mw"])) for g in sub.gen.index
                    if str(sub.gen.at[g, "type"]).lower() in fuels and sub.bus.at[int(sub.gen.at[g, "bus"]), "zone"] == r]
            tot = sum(c for _, c in rows)
            re_share[(kind, r)] = [(b, c / tot) for b, c in rows] if tot > 0 else []
    # demand -> loads, production proportions per region
    load_rows = defaultdict(list)
    for _, row in sub.load.iterrows():
        z = sub.bus.at[int(row["bus"]), "zone"]
        load_rows[z].append((m["bus_ppc"](row["bus"]), float(row["p_mw"])))
    load_share = {z: [(b, p / sum(q for _, q in rows)) for b, p in rows] for z, rows in load_rows.items()
                  if sum(q for _, q in rows) > 0}
    # DC terminals
    dc = []
    for ic in params.interconnections:
        key = (ic.from_region, ic.to_region)
        if key not in DC_TERMINALS:
            continue
        for end, latlon in zip((ic.from_region, ic.to_region), DC_TERMINALS[key]):
            if ISLAND_OF_REGION.get(end) == island:
                nbus = nearest_bus(m, latlon, end)
                if nbus:
                    dc.append((ic.id, end == ic.from_region, m["bus_ppc"](nbus[1]), round(nbus[0], 1)))
    all_load = [(b, sh) for z in load_share for b, sh in load_share[z]]
    return {"regions": regions, "gen_bus": gen_bus, "unmapped": unmapped, "re_share": re_share,
            "load_share": load_share, "all_load": all_load, "dc": dc}


def injection(m, mp, scn, params, plan, t):
    """Bus injections (MW, ppc order) of hour t; the left-over is spread over all loads."""
    inj = np.zeros(m["ppc"]["bus"].shape[0])
    unmapped_mw = 0.0
    for g in params.generators:
        if ISLAND_OF_REGION.get(g.region) != m["island"]:
            continue
        p = plan["mw"][g.id][t]
        if g.id in mp["gen_bus"]:
            inj[mp["gen_bus"][g.id]] += p
        else:
            unmapped_mw += p
    for kind, series in (("solar", scn.solar_gen_r), ("wind", scn.wind_gen_r), ("hydro_ror", scn.hydro_ror_gen_r)):
        for r in mp["regions"]:
            v = float(series[r][t]) if r in series else 0.0
            for b, sh in mp["re_share"][(kind, r)]:
                inj[b] += v * sh
    demand = 0.0
    for r in mp["regions"]:
        d = float(scn.gross_demand_r[r][t])
        demand += d
        for b, sh in mp["load_share"].get(r, []):
            inj[b] -= d * sh
    for ic_id, is_from, b, _ in mp["dc"]:
        f = plan["flows"][ic_id][t]
        inj[b] += -f if is_from else f
    mismatch = float(inj.sum())
    tot_share = sum(sh for _, sh in mp["all_load"])
    for b, sh in mp["all_load"]:
        inj[b] -= mismatch * sh / tot_share
    return inj, {"demand_mw": round(demand, 1), "unmapped_mw": round(unmapped_mw, 1), "mismatch_mw": round(mismatch, 1)}


def evaluate(m, scn, params, plan, hours, osm):
    sub, ppc, ptdf = m["sub"], m["ppc"], m["ptdf"]
    nb = ppc["bus"].shape[0]
    island = m["island"]
    mp = mapping(m, params, osm)
    res = {"island": island, "n_bus": nb, "n_branch": m["nl"], "n_monitored": int(m["monitor"].sum()),
           "unmapped_generators": len(mp["unmapped"]), "dc_terminals": [(i, frm, d) for i, frm, _, d in mp["dc"]], "hours": []}
    over_count = defaultdict(int)
    max_base = defaultdict(float)
    for t in hours:
        inj, info = injection(m, mp, scn, params, plan, t)
        flow = ptdf @ inj
        res_n1 = cg.screen(ptdf, ppc["branch"], flow, m["cap"], m["par"], monitor=m["monitor"])
        base = res_n1.base_loading
        mon = m["monitor"]
        base_over = np.where(mon & (base > 100))[0]
        new_over = int((res_n1.post_n_new_over > 0).sum())
        for k in base_over:
            over_count[int(k)] += 1
        for k in np.where(mon)[0]:
            max_base[int(k)] = max(max_base[int(k)], float(np.nan_to_num(base[k])))
        res["hours"].append({"t": t, **info, "base_over": int(len(base_over)),
                             "base_max_loading": round(float(np.nanmax(np.where(mon, base, np.nan))), 1),
                             "n1_outages_with_new_over": new_over,
                             "n1_max_new_loading": round(float(np.nanmax(res_n1.post_max_new)) if np.isfinite(res_n1.post_max_new).any() else 0.0, 1)})
    lines = []
    inv = {m["bus_ppc"](b): int(b) for b in sub.bus.index}
    for k, n in sorted(over_count.items(), key=lambda kv_: -kv_[1])[:200]:
        tbl, eid = m["elems"][k]
        fb = int(ppc["branch"][k, F_BUS].real)
        tb = int(ppc["branch"][k, T_BUS].real)
        a, b = m["xy"].get(inv.get(fb)), m["xy"].get(inv.get(tb))
        lines.append({"k": k, "kv": float(m["kv"][k]), "class": str(m["cls"][k]), "hours_over": n,
                      "max_loading": round(max_base[k], 1), "a": a, "b": b,
                      "name": str(getattr(sub, tbl).at[eid, "name"]) if tbl else ""})
    res["overloaded_lines"] = lines
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--plan", type=Path, required=True, help="uc_near_optimal output")
    ap.add_argument("--plan-key", default="reference", help="'reference' or an eps value of a run, e.g. 0.01")
    ap.add_argument("--islands", nargs="*", default=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--cap-calib", action=argparse.BooleanOptionalAction, default=True,
                    help="line capacities calibrated to operating capacity (intervention #45)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    begin = time.monotonic()
    data = json.loads(args.plan.read_text())
    if args.plan_key == "reference":
        plan = data["reference"]["plan"]
    else:
        plan = next(r["plan"] for r in data["runs"] if abs(r["eps"] - float(args.plan_key)) < 1e-12)
    scn = build_national_scenario(scenario=args.scenario)
    params = scn.to_uc_parameters()
    built = json.loads(BUILT.read_text())
    nodes, edges = built["nodes"], built["edges"]
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)
    osm = plant_osm_ids()
    out = {"schema_version": 1, "kind": "scuc_evaluation", "scenario": args.scenario, "plan": str(args.plan),
           "plan_key": args.plan_key, "cap_calib": args.cap_calib, "islands": []}
    for island in args.islands:
        t0 = time.monotonic()
        m = island_model(island, nodes, edges, cfg, pref_gwh, args.cap_calib)
        r = evaluate(m, scn, params, plan, range(params.time_horizon.num_periods), osm)
        r["seconds"] = round(time.monotonic() - t0, 1)
        out["islands"].append(r)
        hs = r["hours"]
        print(json.dumps({"island": island, "bus": r["n_bus"], "monitored": r["n_monitored"],
                          "unmapped_gen": r["unmapped_generators"],
                          "max_unmapped_mw": max(h["unmapped_mw"] for h in hs),
                          "max_abs_mismatch_mw": max(abs(h["mismatch_mw"]) for h in hs),
                          "base_over_max": max(h["base_over"] for h in hs),
                          "base_max_loading": max(h["base_max_loading"] for h in hs),
                          "n1_bad_outages_max": max(h["n1_outages_with_new_over"] for h in hs),
                          "lines_ever_over": len(r["overloaded_lines"]), "s": r["seconds"]}, ensure_ascii=False))
    out["wall_s"] = time.monotonic() - begin
    args.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
