#!/usr/bin/env python3
"""Full-scale national power flow from the canonical built DB (docs/data/built).

Owner directive (2026-06-18, PLAN_NEXT "DB:" DB1-3): solve the power flow at
**full scale** — every node in ``all.json`` is a bus, every edge a branch — with
NO voltage-class reduction (reduction is deferred as DB5). The built physical
connectivity is treated as ground truth ("OSM で繋がっているものは極力繋がっている
ように計算"), so we solve **per connected component within each frequency island**.

Key modelling choices (stated, not fabricated):
  * Bus     = built node (lat/lon/kv/sub/region preserved; id is unique).
  * Branch  = built edge. R/X/C and ampacity come from the committed per-class
              reference table (config/line_types.yaml via line_parameters), at
              the island frequency (50 Hz east / 60 Hz west). ``par`` sets the
              number of parallel circuits. edge kv==0 inherits the max kv of its
              endpoints. Branch length = haversine over the stored polyline.
  * Transformer = a SITE that hosts >1 distinct voltage (co-located nodes of
              different kv). We connect the voltage levels with an ideal-ish
              pandapower 2-winding transformer instead of a zero-length line or
              a coord self-loop (the coarse-key trap the owner warned about).
              Rating = sum of the lower-side lines' thermal capacity (min 100 MVA).
  * Load    = allocated ONLY to substation buses (sub==1), per region, by the
              committed regional peak demand x load_factor, voltage-class
              weighted (config/regional_demand.yaml). Junction buses carry none
              (they are tap points on a line, not delivery points). This realises
              "負荷bus は変電所に接続".
  * Gen     = OSM plants (data/{region}_plants.geojson) attached to the nearest
              substation bus (<=20 km), capacity from OSM or class default.
  * Slack   = the largest-capacity generator bus in each solved component; a
              component with no generator gets an ext_grid at its highest-kv,
              highest-degree substation (so every component is solvable; flagged).

Each frequency island is assembled as ONE pandapower net (so the cross-region
AC ties inside an island transfer power), then solved per connected component:
AC (Newton, q-lims, with a DC-prune fallback ladder) first, DC as the honest
fallback when AC will not converge. Non-convergence is recorded, never faked.
Outputs go to a NEW dir (docs/data/powerflow_full) so the live powerflow tab
(docs/data/powerflow) is untouched. allow_nan=False on every dump.

Usage (heavy -> pws-160core):
  PYTHONPATH=. .venv/bin/python scripts/run_full_powerflow_from_db.py \
      --output-dir docs/data/powerflow_full
  ... --islands east            # subset
  ... --max-ac-buses 6000       # skip AC attempt for components bigger than this
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time
import warnings
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import networkx as nx
import pandapower as pp

from src.converter.line_parameters import get_line_parameters_safe
from src.powerflow.load_estimator import load_demand_config
from src.powerflow.batch_solve import run_powerflow

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILT = os.path.join(ROOT, "docs", "data", "built", "all.json")
OUT_DEFAULT = os.path.join(ROOT, "docs", "data", "powerflow_full")

# Synchronous AC islands (region -> island, freq). Mirrors src.powerflow.national
# ISLANDS exactly (east 50 Hz, west 60 Hz, hokkaido 50 Hz alone, okinawa 60 Hz).
ISLAND_OF = {
    "hokkaido": ("hokkaido", 50),
    "tohoku": ("east", 50), "tokyo": ("east", 50),
    "chubu": ("west", 60), "hokuriku": ("west", 60), "kansai": ("west", 60),
    "chugoku": ("west", 60), "shikoku": ("west", 60), "kyushu": ("west", 60),
    "okinawa": ("okinawa", 60),
}
ISLAND_FREQ = {"hokkaido": 50, "east": 50, "west": 60, "okinawa": 60}

VALID_KV = [66, 77, 110, 132, 154, 187, 220, 275, 500]
_DEFAULT_CAP = {"nuclear": 1000.0, "coal": 600.0, "gas": 400.0, "oil": 300.0,
                "hydro": 50.0, "solar": 10.0, "wind": 10.0, "biomass": 20.0}
_CAP_FALLBACK = 30.0


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _path_len_km(path):
    if not path or len(path) < 2:
        return 0.0
    return sum(_haversine_km(path[i][0], path[i][1], path[i + 1][0], path[i + 1][1])
               for i in range(len(path) - 1))


def _k5(la, lo):
    return (round(la, 5), round(lo, 5))


def _nearest_kv(kv):
    if kv and kv > 0:
        return min(VALID_KV, key=lambda k: abs(k - kv))
    return 0.0


# ──────────────────────────────────────────────────────────────────────────
#  Build one frequency island as a pandapower net straight from built nodes/edges
# ──────────────────────────────────────────────────────────────────────────
def build_island_net(island, nodes, edges, freq, geom_out):
    """Return (net, bus_of_nodeidx, stats). One bus per node, one line per edge,
    transformers between co-located voltage levels. No reduction."""
    net = pp.create_empty_network(name=f"full_{island}", f_hz=freq)

    # candidate buses = nodes whose region maps to this island
    isl_nodes = [(i, n) for i, n in enumerate(nodes)
                 if ISLAND_OF.get(n.get("region"), (None, None))[0] == island]
    bus_of = {}
    for i, n in isl_nodes:
        vn = float(n.get("kv") or 0.0)
        if vn <= 0:
            vn = 66.0  # unknown -> lowest transmission class (kept solvable)
        b = pp.create_bus(net, vn_kv=vn, name=str(n.get("name") or n["id"]),
                          type="b" if n.get("sub") == 1 else "n",
                          geodata=(n["lon"], n["lat"]))
        net.bus.at[b, "zone"] = n.get("region")
        bus_of[i] = b

    # coord -> node indices in this island (for edge endpoint resolution + trafos)
    coord_nodes = defaultdict(list)
    for i, n in isl_nodes:
        coord_nodes[_k5(n["lat"], n["lon"])].append(i)

    # ---- lines from edges (skip a leg if its two endpoints differ in kv at the
    #      SAME coordinate — that is a transformer, handled below) ----
    n_line = 0
    n_edge_skipped = 0
    for e in edges:
        ka, kb = _k5(*e["a"]), _k5(*e["b"])
        ca, cb = coord_nodes.get(ka), coord_nodes.get(kb)
        if not ca or not cb:
            continue  # edge not in this island
        ekv = float(e.get("kv") or 0.0)
        # endpoint node: prefer the one whose kv matches the edge kv, else first
        def pick(cands):
            if ekv > 0:
                for j in cands:
                    if abs(float(nodes[j].get("kv") or 0) - ekv) < 0.5:
                        return j
            return cands[0]
        ja, jb = pick(ca), pick(cb)
        if ja == jb:
            n_edge_skipped += 1
            continue
        fa, ta = bus_of[ja], bus_of[jb]
        kv = ekv or max(float(nodes[ja].get("kv") or 0),
                        float(nodes[jb].get("kv") or 0)) or 66.0
        params = get_line_parameters_safe(_nearest_kv(kv) or kv, freq)
        if params is None:
            n_edge_skipped += 1
            continue
        length = _path_len_km(e.get("path") or [e["a"], e["b"]])
        if length <= 0:
            length = max(_haversine_km(*e["a"], *e["b"]), 0.05)
        x = params["x_ohm_per_km"] or 0.001
        li = pp.create_line_from_parameters(
            net, from_bus=fa, to_bus=ta, length_km=length,
            r_ohm_per_km=params["r_ohm_per_km"], x_ohm_per_km=x,
            c_nf_per_km=params["c_nf_per_km"], max_i_ka=params["max_i_ka"],
            name=str(e.get("name") or f"line_{n_line}"),
            parallel=max(int(e.get("par") or 1), 1))
        n_line += 1
        # geometry for export (key by endpoint bus coords, both directions)
        a5 = (_k5(nodes[ja]["lat"], nodes[ja]["lon"]))
        b5 = (_k5(nodes[jb]["lat"], nodes[jb]["lon"]))
        path = e.get("path") or [e["a"], e["b"]]
        coords = [[p[1], p[0]] for p in path]
        geom_out[(a5, b5)] = coords
        geom_out[(b5, a5)] = list(reversed(coords))

    # ---- transformers between co-located voltage levels (a real substation
    #      that steps voltage). For each site, chain adjacent distinct-kv buses
    #      (high->low) with a 2-winding transformer sized to the lower side. ----
    n_trafo = 0
    for coord, idxs in coord_nodes.items():
        if len(idxs) < 2:
            continue
        # distinct voltage levels at this site -> representative bus each
        by_kv = {}
        for j in idxs:
            vn = float(net.bus.at[bus_of[j], "vn_kv"])
            by_kv.setdefault(round(vn, 1), bus_of[j])
        kvs = sorted(by_kv.keys(), reverse=True)
        for hv_kv, lv_kv in zip(kvs, kvs[1:]):
            hb, lb = by_kv[hv_kv], by_kv[lv_kv]
            if hv_kv <= lv_kv:
                continue
            # rating: cover the lower side's typical line capacity, >=100 MVA
            sn = max(100.0, math.sqrt(3) * lv_kv
                     * (get_line_parameters_safe(_nearest_kv(lv_kv) or lv_kv, freq) or
                        {"max_i_ka": 1.0})["max_i_ka"])
            try:
                pp.create_transformer_from_parameters(
                    net, hv_bus=hb, lv_bus=lb, sn_mva=sn,
                    vn_hv_kv=hv_kv, vn_lv_kv=lv_kv,
                    vkr_percent=0.5, vk_percent=12.0,   # typical large power trafo
                    pfe_kw=0.0, i0_percent=0.0,
                    name=f"trafo_{hv_kv:.0f}/{lv_kv:.0f}kV")
                n_trafo += 1
            except (ValueError, TypeError):
                pass

    return net, bus_of, {"n_bus": len(bus_of), "n_line": n_line,
                         "n_trafo": n_trafo, "n_edge_skipped": n_edge_skipped}


# ──────────────────────────────────────────────────────────────────────────
#  Generators from OSM plants (nearest substation bus)
# ──────────────────────────────────────────────────────────────────────────
def attach_generators(net, bus_of, nodes, island):
    """Attach OSM plants to the nearest in-island substation bus (<=20 km)."""
    import glob
    # substation bus coords for nearest search
    sub_bus = [(i, bus_of[i], nodes[i]["lat"], nodes[i]["lon"])
               for i in bus_of if nodes[i].get("sub") == 1]
    if not sub_bus:
        return 0
    regions = [r for r, (isl, _f) in ISLAND_OF.items() if isl == island]
    n_gen = 0
    for region in regions:
        path = os.path.join(ROOT, "data", f"{region}_plants.geojson")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for k, feat in enumerate(data.get("features", [])):
            g = feat.get("geometry") or {}
            if g.get("type") != "Point":
                continue
            lon, lat = g["coordinates"][0], g["coordinates"][1]
            props = feat.get("properties", {})
            try:
                cap = float(props.get("capacity_mw"))
            except (TypeError, ValueError):
                cap = None
            fuel = props.get("fuel_type") or props.get("plant:source") or "unknown"
            if not isinstance(fuel, str) or fuel.startswith("http"):
                fuel = "unknown"
            if cap is None or cap <= 0:
                cap = _DEFAULT_CAP.get(fuel, _CAP_FALLBACK)
            # nearest substation bus
            best = min(sub_bus, key=lambda s: _haversine_km(lat, lon, s[2], s[3]))
            if _haversine_km(lat, lon, best[2], best[3]) > 20.0:
                continue
            try:
                pp.create_gen(net, bus=best[1], p_mw=cap, vm_pu=1.0,
                              name=str(props.get("name") or f"{region}_gen_{k}"),
                              type=fuel, max_p_mw=cap, min_p_mw=0.0,
                              max_q_mvar=0.5 * cap, min_q_mvar=-0.3 * cap)
                n_gen += 1
            except (ValueError, TypeError):
                pass
    return n_gen


# ──────────────────────────────────────────────────────────────────────────
#  Load allocation: substation buses only, per region, voltage-class weighted
# ──────────────────────────────────────────────────────────────────────────
def allocate_loads(net, cfg):
    peak = cfg["regional_peak_demand_mw"]
    lf = cfg.get("load_factor", 0.85)
    pf = cfg.get("power_factor", 0.95)
    vw = cfg.get("voltage_weights", {})
    tan_phi = math.tan(math.acos(pf))
    total = 0.0
    is_sub = net.bus["type"] != "n"
    for zone, grp in net.bus.groupby("zone"):
        target = peak.get(zone, 0) * lf
        if target <= 0:
            continue
        idxs = [b for b in grp.index if is_sub.get(b, False)]
        if not idxs:
            idxs = list(grp.index)
        weights = []
        for b in idxs:
            vn = float(net.bus.at[b, "vn_kv"])
            key = int(round(vn))
            w = vw.get(key) or vw.get(min(
                [k for k in vw if isinstance(k, (int, float)) and k > 0] or [0],
                key=lambda k: abs(k - vn)), 0.5)
            weights.append(w)
        tw = sum(weights) or len(idxs)
        for b, w in zip(idxs, weights):
            p = target * (w / tw)
            pp.create_load(net, bus=b, p_mw=p, q_mvar=p * tan_phi,
                           name=f"load_{b}")
            total += p
    return total


# ──────────────────────────────────────────────────────────────────────────
#  Per-component slack + balance, then solve
# ──────────────────────────────────────────────────────────────────────────
def add_per_component_slacks(net):
    """Every connected component (over in-service lines+trafos) needs a slack.
    Prefer the bus carrying the largest generator; else the highest-kv,
    highest-degree substation. Returns (n_components, n_slack, n_synth_slack)."""
    g = nx.Graph()
    g.add_nodes_from(net.bus.index)
    for _, r in net.line.iterrows():
        if r["in_service"]:
            g.add_edge(int(r["from_bus"]), int(r["to_bus"]))
    for _, r in net.trafo.iterrows():
        if r["in_service"]:
            g.add_edge(int(r["hv_bus"]), int(r["lv_bus"]))
    gen_bus = set(net.gen["bus"].tolist())
    gen_cap = net.gen.groupby("bus")["max_p_mw"].sum().to_dict()
    deg = dict(g.degree())
    n_slack = n_synth = 0
    comps = list(nx.connected_components(g))
    for comp in comps:
        gens_here = [b for b in comp if b in gen_bus]
        if gens_here:
            slack = max(gens_here, key=lambda b: gen_cap.get(b, 0))
        else:
            # synthetic slack: a real substation, highest kv then highest degree
            subs = [b for b in comp if net.bus.at[b, "type"] != "n"] or list(comp)
            slack = max(subs, key=lambda b: (float(net.bus.at[b, "vn_kv"]),
                                             deg.get(b, 0)))
            n_synth += 1
        pp.create_ext_grid(net, bus=int(slack), vm_pu=1.0,
                           name=f"slack_{slack}")
        n_slack += 1
    return len(comps), n_slack, n_synth


def balance_by_zone(net, cfg):
    """Scale each zone's generation toward its load so the slacks don't carry
    the whole region (keeps the AC solution physical). ext_grid absorbs residual."""
    load_by_zone = defaultdict(float)
    for _, r in net.load.iterrows():
        z = net.bus.at[int(r["bus"]), "zone"]
        load_by_zone[z] += float(r["p_mw"])
    gens_by_zone = defaultdict(list)
    for gi, r in net.gen.iterrows():
        z = net.bus.at[int(r["bus"]), "zone"]
        gens_by_zone[z].append(gi)
    reserve = 1.0 + cfg.get("reserve_margin", 0.05)
    for z, gis in gens_by_zone.items():
        cap = sum(float(net.gen.at[gi, "max_p_mw"]) for gi in gis)
        if cap <= 0:
            continue
        target = load_by_zone.get(z, 0.0) * reserve
        scale = min(target / cap, 1.0)
        for gi in gis:
            net.gen.at[gi, "p_mw"] = float(net.gen.at[gi, "max_p_mw"]) * scale


def solve_island(net, max_ac_buses):
    """DC always; AC with a prune ladder unless the island exceeds max_ac_buses."""
    net.bus["vm_pu"] = 1.0
    net_dc = copy.deepcopy(net)
    dc = run_powerflow(net_dc, "dc")
    ac = {"mode": "ac", "converged": False}
    net_ac = None
    if len(net.bus) <= max_ac_buses:
        for thr in (None, 45.0, 30.0, 20.0):
            net_ac = copy.deepcopy(net)
            if thr is not None:
                from src.powerflow.transforms import prune_dc_infeasible
                try:
                    prune_dc_infeasible(net_ac, angle_threshold=thr)
                except Exception:
                    pass
            ac = run_powerflow(net_ac, "ac")
            if ac["converged"]:
                break
    else:
        ac["error"] = f"island too large for AC ({len(net.bus)} > {max_ac_buses}); DC only"
    return net_dc, dc, net_ac, ac


# ──────────────────────────────────────────────────────────────────────────
#  Export per-region GeoJSON slices + summary
# ──────────────────────────────────────────────────────────────────────────
def _bus_lonlat(net, b):
    """(lon, lat) from pandapower 3.x GeoJSON 'geo' column; (None, None) if absent."""
    g = net.bus.at[b, "geo"] if "geo" in net.bus.columns else None
    if not g:
        return None, None
    try:
        coords = json.loads(g)["coordinates"]
        return float(coords[0]), float(coords[1])
    except (ValueError, KeyError, IndexError, TypeError):
        return None, None


def export_region(net, region, geom, mode, out_dir):
    buses = []
    region_bus = set()
    for b in net.bus.index:
        if not net.bus.at[b, "in_service"] or net.bus.at[b, "zone"] != region:
            continue
        x, y = _bus_lonlat(net, b)
        if x is None or (x == 0 and y == 0):
            continue
        region_bus.add(b)
        vm = float(net.res_bus.at[b, "vm_pu"]) if b in net.res_bus.index else float("nan")
        va = float(net.res_bus.at[b, "va_degree"]) if b in net.res_bus.index else float("nan")
        if not (math.isfinite(vm) and math.isfinite(va)):
            continue
        buses.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [x, y]},
                      "properties": {"name": str(net.bus.at[b, "name"]),
                                     "vn_kv": round(float(net.bus.at[b, "vn_kv"]), 1),
                                     "vm_pu": round(vm, 4), "va_deg": round(va, 2)}})
    lines = []
    for li in net.line.index:
        if not net.line.at[li, "in_service"]:
            continue
        fb, tb = int(net.line.at[li, "from_bus"]), int(net.line.at[li, "to_bus"])
        zf, zt = net.bus.at[fb, "zone"], net.bus.at[tb, "zone"]
        if region not in (zf, zt):
            continue
        fx, fy = _bus_lonlat(net, fb); tx, ty = _bus_lonlat(net, tb)
        if fx is None or tx is None:
            continue
        load = float(net.res_line.at[li, "loading_percent"]) if li in net.res_line.index and "loading_percent" in net.res_line.columns else 0.0
        p = float(net.res_line.at[li, "p_from_mw"]) if li in net.res_line.index and "p_from_mw" in net.res_line.columns else 0.0
        load = load if math.isfinite(load) else 0.0
        p = p if math.isfinite(p) else 0.0
        coords = geom.get((_k5(fy, fx), _k5(ty, tx))) or [[fx, fy], [tx, ty]]
        coords = [[fx, fy]] + list(coords)[1:-1] + [[tx, ty]] if len(coords) > 2 else [[fx, fy], [tx, ty]]
        lines.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": {"name": str(net.line.at[li, "name"]),
                                     "loading_pct": round(min(load, 200), 1),
                                     "p_mw": round(p, 1),
                                     "tie": zf != zt}})
    # transformers as short links (so stepped sites don't look 'floating')
    for ti in net.trafo.index:
        if not net.trafo.at[ti, "in_service"]:
            continue
        hb, lb = int(net.trafo.at[ti, "hv_bus"]), int(net.trafo.at[ti, "lv_bus"])
        if region not in (net.bus.at[hb, "zone"], net.bus.at[lb, "zone"]):
            continue
        hx, hy = _bus_lonlat(net, hb); lx, ly = _bus_lonlat(net, lb)
        if hx is None or lx is None or (abs(hx - lx) < 1e-6 and abs(hy - ly) < 1e-6):
            continue
        ld = float(net.res_trafo.at[ti, "loading_percent"]) if ti in net.res_trafo.index and "loading_percent" in net.res_trafo.columns else 0.0
        ld = ld if math.isfinite(ld) else 0.0
        lines.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": [[hx, hy], [lx, ly]]},
                      "properties": {"name": str(net.trafo.at[ti, "name"]),
                                     "loading_pct": round(min(ld, 200), 1),
                                     "p_mw": 0.0, "tie": False, "trafo": True}})
    tag = mode
    json.dump({"type": "FeatureCollection", "features": buses},
              open(f"{out_dir}/{region}_{tag}_buses.geojson", "w"),
              separators=(",", ":"), allow_nan=False)
    json.dump({"type": "FeatureCollection", "features": lines},
              open(f"{out_dir}/{region}_{tag}_lines.geojson", "w"),
              separators=(",", ":"), allow_nan=False)
    return len(buses), len(lines)


def region_vm(net, region):
    idx = [b for b in net.bus.index if net.bus.at[b, "in_service"]
           and net.bus.at[b, "zone"] == region and b in net.res_bus.index]
    vm = [float(net.res_bus.at[b, "vm_pu"]) for b in idx
          if math.isfinite(float(net.res_bus.at[b, "vm_pu"]))]
    if not vm:
        return {}
    return {"vm_min": round(min(vm), 4), "vm_max": round(max(vm), 4), "n": len(vm)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=None)
    ap.add_argument("--output-dir", default=OUT_DEFAULT)
    ap.add_argument("--max-ac-buses", type=int, default=6000,
                    help="skip AC attempt for islands larger than this (DC only)")
    args = ap.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    with open(BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = load_demand_config()

    targets = args.islands or ["hokkaido", "east", "west", "okinawa"]
    summary = {"_meta": {"source": "docs/data/built/all.json",
                         "n_nodes": len(nodes), "n_edges": len(edges),
                         "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "scale": "full (no voltage-class reduction)"},
               "islands": {}, "regions": {}}

    for island in targets:
        t0 = time.time()
        freq = ISLAND_FREQ[island]
        geom = {}
        net, bus_of, bstats = build_island_net(island, nodes, edges, freq, geom)
        n_gen = attach_generators(net, bus_of, nodes, island)
        total_load = allocate_loads(net, cfg)
        n_comp, n_slack, n_synth = add_per_component_slacks(net)
        balance_by_zone(net, cfg)
        net_dc, dc, net_ac, ac = solve_island(net, args.max_ac_buses)
        net_used = net_ac if ac.get("converged") else net_dc
        mode = "ac" if ac.get("converged") else "dc"

        regions = sorted({r for r, (isl, _f) in ISLAND_OF.items() if isl == island})
        for region in regions:
            nb, nl = export_region(net_used, region, geom, mode, args.output_dir)
            vm = region_vm(net_used, region)
            summary["regions"][region] = {
                "island": island, "solved_mode": mode,
                "ac_converged": bool(ac.get("converged")),
                "dc_converged": bool(dc.get("converged")),
                "vm_min": vm.get("vm_min"), "vm_max": vm.get("vm_max"),
                "n_buses": vm.get("n"), "n_buses_exported": nb, "n_lines_exported": nl,
            }
        summary["islands"][island] = {
            "frequency_hz": freq, **bstats, "n_gen": n_gen,
            "total_load_mw": round(total_load, 1),
            "n_components": n_comp, "n_slack": n_slack, "n_synthetic_slack": n_synth,
            "ac_converged": bool(ac.get("converged")),
            "ac_solver": ac.get("solver"), "ac_error": ac.get("error"),
            "dc_converged": bool(dc.get("converged")),
            "ac_vm_min": ac.get("vm_pu_min"), "ac_vm_max": ac.get("vm_pu_max"),
            "ac_max_loading_pct": ac.get("max_loading_pct"),
            "dc_max_loading_pct": dc.get("max_loading_pct"),
            "ac_total_loss_mw": ac.get("total_loss_mw"),
            "solve_seconds": round(time.time() - t0, 1),
        }
        print(f"[{island:9s}] f={freq} buses={bstats['n_bus']} lines={bstats['n_line']} "
              f"trafo={bstats['n_trafo']} gen={n_gen} comps={n_comp} "
              f"AC={'OK' if ac.get('converged') else 'FAIL'} DC={'OK' if dc.get('converged') else 'FAIL'} "
              f"vm=[{ac.get('vm_pu_min')},{ac.get('vm_pu_max')}] "
              f"maxload={ac.get('max_loading_pct')} {time.time()-t0:.0f}s", flush=True)

    with open(f"{args.output_dir}/summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"done -> {args.output_dir}")


if __name__ == "__main__":
    main()
