"""Post-build pandapower network transforms for the reconstruction pipeline.

The net-shaping steps applied after PandapowerBuilder and before solving —
voltage repair, transformer insertion, slack selection, topology fixing /
island handling, DC-infeasible pruning, thermal-rating scaling and
generation/demand balancing. Each operates on a pandapower net in place.

Promoted verbatim from ``examples/run_powerflow_all`` (Phase C pipeline
promotion) so the dependency flows src <- scripts/examples; the example
re-exports these names for back-compat. The group is self-contained: it
uses only pandapower / numpy / networkx and the two private helpers below,
with no module-level globals.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandapower as pp
import pandapower.topology as top

# Synthetic transformer parameters by (HV kV, LV kV) class, used by
# insert_transformers / _get_trafo_params.
_TRAFO_PARAMS = {
    (500, 275): {"sn_mva": 1000, "vk_percent": 12.0, "vkr_percent": 0.25, "pfe_kw": 200, "i0_percent": 0.05},
    (500, 220): {"sn_mva": 800, "vk_percent": 12.0, "vkr_percent": 0.25, "pfe_kw": 180, "i0_percent": 0.05},
    (500, 187): {"sn_mva": 700, "vk_percent": 12.0, "vkr_percent": 0.3, "pfe_kw": 160, "i0_percent": 0.06},
    (500, 154): {"sn_mva": 600, "vk_percent": 12.0, "vkr_percent": 0.3, "pfe_kw": 150, "i0_percent": 0.06},
    (275, 154): {"sn_mva": 500, "vk_percent": 10.0, "vkr_percent": 0.3, "pfe_kw": 120, "i0_percent": 0.06},
    (275, 132): {"sn_mva": 400, "vk_percent": 10.0, "vkr_percent": 0.35, "pfe_kw": 100, "i0_percent": 0.07},
    (275, 110): {"sn_mva": 350, "vk_percent": 10.0, "vkr_percent": 0.35, "pfe_kw": 90, "i0_percent": 0.07},
    (275, 66):  {"sn_mva": 300, "vk_percent": 10.0, "vkr_percent": 0.4, "pfe_kw": 80, "i0_percent": 0.08},
    (275, 77):  {"sn_mva": 300, "vk_percent": 10.0, "vkr_percent": 0.4, "pfe_kw": 80, "i0_percent": 0.08},
    (220, 110): {"sn_mva": 300, "vk_percent": 10.0, "vkr_percent": 0.35, "pfe_kw": 80, "i0_percent": 0.07},
    (220, 66):  {"sn_mva": 250, "vk_percent": 10.0, "vkr_percent": 0.4, "pfe_kw": 70, "i0_percent": 0.08},
    (187, 66):  {"sn_mva": 200, "vk_percent": 10.0, "vkr_percent": 0.4, "pfe_kw": 60, "i0_percent": 0.08},
    (154, 66):  {"sn_mva": 200, "vk_percent": 10.0, "vkr_percent": 0.4, "pfe_kw": 60, "i0_percent": 0.08},
    (154, 77):  {"sn_mva": 200, "vk_percent": 10.0, "vkr_percent": 0.4, "pfe_kw": 60, "i0_percent": 0.08},
    (132, 66):  {"sn_mva": 150, "vk_percent": 8.0, "vkr_percent": 0.5, "pfe_kw": 40, "i0_percent": 0.1},
    (110, 66):  {"sn_mva": 150, "vk_percent": 8.0, "vkr_percent": 0.5, "pfe_kw": 40, "i0_percent": 0.1},
    (77, 66):   {"sn_mva": 100, "vk_percent": 8.0, "vkr_percent": 0.5, "pfe_kw": 30, "i0_percent": 0.1},
}


def fix_zero_voltages(net):
    """Fix buses with vn_kv=0 using connected line voltages or defaults."""
    zero_mask = net.bus["vn_kv"] <= 0
    n_zero = int(zero_mask.sum())
    if n_zero == 0:
        return 0

    # Infer from connected lines
    for idx in net.bus.index[zero_mask]:
        connected_lines = net.line[(net.line["from_bus"] == idx) | (net.line["to_bus"] == idx)]
        if connected_lines.empty:
            continue
        # Get voltage from the other end of connected lines
        voltages = []
        for _, line_row in connected_lines.iterrows():
            other_bus = line_row["to_bus"] if line_row["from_bus"] == idx else line_row["from_bus"]
            v = net.bus.at[other_bus, "vn_kv"]
            if v > 0:
                voltages.append(v)
        if voltages:
            net.bus.at[idx, "vn_kv"] = max(voltages)

    # Remaining zero-voltage buses: use median or 66 kV default
    still_zero = net.bus["vn_kv"] <= 0
    if still_zero.any():
        nonzero = net.bus.loc[~still_zero, "vn_kv"]
        fallback = float(nonzero.median()) if len(nonzero) > 0 else 66.0
        net.bus.loc[still_zero, "vn_kv"] = fallback

    fixed = n_zero - int((net.bus["vn_kv"] <= 0).sum())
    return fixed


def _snap_voltage(vn_kv):
    """Snap a voltage to the nearest standard Japanese voltage class."""
    classes = [500, 275, 220, 187, 154, 132, 110, 77, 66]
    if vn_kv <= 0:
        return 66
    return min(classes, key=lambda c: abs(c - vn_kv))


def _get_trafo_params(hv_kv, lv_kv):
    """Get transformer parameters for a voltage pair, with fallback."""
    hv = _snap_voltage(max(hv_kv, lv_kv))
    lv = _snap_voltage(min(hv_kv, lv_kv))
    if hv == lv:
        return None

    key = (hv, lv)
    if key in _TRAFO_PARAMS:
        return _TRAFO_PARAMS[key]

    # Find closest match
    best_key = None
    best_dist = float("inf")
    for k in _TRAFO_PARAMS:
        d = abs(k[0] - hv) + abs(k[1] - lv)
        if d < best_dist:
            best_dist = d
            best_key = k
    if best_key:
        return _TRAFO_PARAMS[best_key]

    # Generic fallback
    return {"sn_mva": 200, "vk_percent": 10.0, "vkr_percent": 0.5, "pfe_kw": 50, "i0_percent": 0.1}


def insert_transformers(net):
    """Replace lines connecting buses at different voltages with transformers."""
    lines_to_remove = []
    trafos_created = 0

    for idx in net.line.index:
        from_bus = net.line.at[idx, "from_bus"]
        to_bus = net.line.at[idx, "to_bus"]
        vn_from = net.bus.at[from_bus, "vn_kv"]
        vn_to = net.bus.at[to_bus, "vn_kv"]

        # Check if voltage ratio > 1.2 (same class lines may have small differences)
        ratio = max(vn_from, vn_to) / max(min(vn_from, vn_to), 0.1)
        if ratio < 1.2:
            continue

        hv_kv = max(vn_from, vn_to)
        lv_kv = min(vn_from, vn_to)
        hv_bus = from_bus if vn_from >= vn_to else to_bus
        lv_bus = to_bus if vn_from >= vn_to else from_bus

        params = _get_trafo_params(hv_kv, lv_kv)
        if params is None:
            continue

        # Carry the line's parallel count onto the transformer: parallel
        # circuits between two voltages imply parallel transformer banks.
        n_par = int(net.line.at[idx, "parallel"]) if "parallel" in net.line.columns else 1
        pp.create_transformer_from_parameters(
            net,
            hv_bus=hv_bus,
            lv_bus=lv_bus,
            sn_mva=params["sn_mva"],
            vn_hv_kv=hv_kv,
            vn_lv_kv=lv_kv,
            vk_percent=params["vk_percent"],
            vkr_percent=params["vkr_percent"],
            pfe_kw=params["pfe_kw"],
            i0_percent=params["i0_percent"],
            name=f"trafo_{hv_kv:.0f}/{lv_kv:.0f}kV",
            parallel=max(n_par, 1),
        )
        lines_to_remove.append(idx)
        trafos_created += 1

    # Remove replaced lines
    if lines_to_remove:
        net.line = net.line.drop(lines_to_remove)

    return trafos_created


def apply_voltage_setpoints(net):
    """Schedule generator / slack voltage setpoints by bus voltage class.

    Real JP operation holds EHV buses slightly above nominal (AVR
    schedules); a flat 1.00 pu everywhere leaves long radials sagging
    further than reality. Conservative class schedule:
    >=400 kV: 1.03, >=200: 1.02, >=100: 1.01, below: 1.00.
    """
    def _sched(vn):
        if vn >= 400:
            return 1.03
        if vn >= 200:
            return 1.02
        if vn >= 100:
            return 1.01
        return 1.00

    n = 0
    if len(net.gen) > 0:
        vn = net.bus.loc[net.gen["bus"], "vn_kv"].to_numpy()
        net.gen["vm_pu"] = [_sched(v) for v in vn]
        n += len(net.gen)
    if len(net.ext_grid) > 0:
        vn = net.bus.loc[net.ext_grid["bus"], "vn_kv"].to_numpy()
        net.ext_grid["vm_pu"] = [_sched(v) for v in vn]
        n += len(net.ext_grid)
    return n


def select_slack_bus(net):
    """Select optimal slack bus: well-connected high-voltage bus with generation."""
    active_buses = net.bus[net.bus["in_service"]]
    if active_buses.empty:
        return None

    # Count connections per bus (lines + trafos)
    connectivity = {}
    for idx in active_buses.index:
        n_conn = 0
        if len(net.line) > 0:
            n_conn += ((net.line["from_bus"] == idx) | (net.line["to_bus"] == idx)).sum()
        if len(net.trafo) > 0:
            n_conn += ((net.trafo["hv_bus"] == idx) | (net.trafo["lv_bus"] == idx)).sum()
        connectivity[idx] = n_conn

    # Aggregate generation per bus
    gen_at_bus = {}
    if len(net.gen) > 0:
        active_gens = net.gen[net.gen["in_service"]]
        for gen_idx in active_gens.index:
            bus = active_gens.at[gen_idx, "bus"]
            if bus in active_buses.index:
                gen_at_bus[bus] = gen_at_bus.get(bus, 0) + active_gens.at[gen_idx, "p_mw"]

    # Score: heavily weight voltage level and connectivity, plus generation
    best_bus = None
    best_score = -1
    for bus_idx in active_buses.index:
        vn_kv = active_buses.at[bus_idx, "vn_kv"]
        conn = connectivity.get(bus_idx, 0)
        gen_mw = gen_at_bus.get(bus_idx, 0)
        # Voltage dominates (500kV >> 66kV), connectivity matters, gen is bonus
        score = vn_kv * 10 + conn * 50 + gen_mw * 0.1
        if score > best_score:
            best_score = score
            best_bus = bus_idx

    if best_bus is not None and len(net.ext_grid) > 0:
        net.ext_grid.at[net.ext_grid.index[0], "bus"] = best_bus

    return best_bus


def fix_topology(net, multi_slack=False):
    """Fix isolated components and return diagnostics.

    multi_slack=True: instead of disabling every non-largest component, give
    each viable component (>=2 buses) its own slack so it is solved in place.
    This keeps genuinely separate grids (islands, real gaps) visible and
    solved WITHOUT fabricating cross-water synthetic lines, and without
    dropping their real OSM lines. Single-bus stragglers are still disabled.
    """
    mg = top.create_nxgraph(net, respect_switches=False)
    components = list(nx.connected_components(mg))
    diag = {
        "n_components": len(components),
        "n_isolated_buses": 0,
        "n_active_buses": int(net.bus["in_service"].sum()),
    }

    if multi_slack and len(components) > 1:
        def _has_inservice_slack(comp):
            if net.ext_grid.empty:
                return False
            for i in net.ext_grid.index:
                if net.ext_grid.at[i, "in_service"] and net.ext_grid.at[i, "bus"] in comp:
                    return True
            return False

        n_iso = 0
        for comp in components:
            if len(comp) < 2:
                # lone bus with no line: disable (nothing to solve)
                for b in comp:
                    if b in net.bus.index:
                        net.bus.at[b, "in_service"] = False
                        n_iso += 1
                continue
            if _has_inservice_slack(comp):
                continue
            # prefer a bus carrying the largest generator, else any bus
            slack_bus = None
            if not net.gen.empty:
                gens = net.gen[net.gen["bus"].isin(comp)]
                if not gens.empty:
                    slack_bus = int(gens.sort_values("max_p_mw", ascending=False).iloc[0]["bus"])
            if slack_bus is None:
                slack_bus = int(next(iter(comp)))
            pp.create_ext_grid(net, bus=slack_bus, vm_pu=1.0, name="comp_slack")
        diag["n_isolated_buses"] = n_iso
        diag["n_active_buses"] = int(net.bus["in_service"].sum())
        return diag

    if len(components) > 1:
        largest = max(components, key=len)
        isolated = set()
        for comp in components:
            if comp != largest:
                isolated.update(comp)
        diag["n_isolated_buses"] = len(isolated)

        for bus_idx in isolated:
            if bus_idx in net.bus.index:
                net.bus.at[bus_idx, "in_service"] = False
        for tbl in ("load", "gen", "sgen", "line", "trafo"):
            table = getattr(net, tbl, None)
            if table is None or table.empty:
                continue
            if tbl in ("line", "trafo"):
                from_col = "hv_bus" if tbl == "trafo" else "from_bus"
                to_col = "lv_bus" if tbl == "trafo" else "to_bus"
                mask = table[from_col].isin(isolated) | table[to_col].isin(isolated)
            else:
                mask = table["bus"].isin(isolated)
            table.loc[mask, "in_service"] = False
        if not net.ext_grid.empty:
            mask = net.ext_grid["bus"].isin(isolated)
            net.ext_grid.loc[mask, "in_service"] = False
            if net.ext_grid["in_service"].sum() == 0:
                for i, row in net.ext_grid.iterrows():
                    if row["bus"] in largest:
                        net.ext_grid.at[i, "in_service"] = True
                        break
                else:
                    bus_idx = next(iter(largest))
                    pp.create_ext_grid(net, bus=bus_idx, vm_pu=1.0, name="slack_recovery")

        diag["n_active_buses"] = int(net.bus["in_service"].sum())

    return diag


def reduce_to_backbone(net, min_kv=154.0, min_keep_buses=20):
    """Aggregate the sub-transmission layer onto the >= ``min_kv`` backbone.

    The OSM sub-transmission layer (66-132 kV) is the *proven* root cause
    of AC non-convergence (docs/WEST_AC_ANALYSIS.md: kansai converges with
    no-trafo or hv>=154 — 539 ill-conditioned transformers with voltage
    ratios up to 20 make the Jacobian singular). Rather than fighting that
    layer with numerical workarounds, this transform produces the honest
    backbone model:

    - buses with vn_kv >= min_kv are kept;
    - generators on dropped buses are re-attached to the kept bus their
      sub-network actually hangs from (multi-source BFS from the boundary
      buses through the dropped subgraph), so generation capacity is
      aggregated, not lost;
    - dropped buses / lines / trafos are removed BEFORE load allocation,
      so the regional demand is distributed across the backbone buses —
      the sub-network's demand arrives aggregated at the backbone instead
      of vanishing.

    If the cut would leave fewer than ``min_keep_buses`` (okinawa's highest
    class is 132 kV), the threshold steps down one voltage class at a time;
    the effective threshold is reported so callers can disclose it.

    Returns a summary dict (effective_min_kv, kept/dropped counts, gens
    moved / unreachable).
    """
    classes = sorted({float(v) for v in net.bus["vn_kv"] if v > 0}, reverse=True)
    if not classes:
        return {"effective_min_kv": 0.0, "n_dropped_buses": 0,
                "n_gens_moved": 0, "n_gens_lost": 0, "reduced": False}

    eff_kv = float(min_kv)
    while True:
        kept = set(net.bus.index[net.bus["vn_kv"] >= eff_kv])
        if len(kept) >= min_keep_buses or eff_kv <= classes[-1]:
            break
        lower = [c for c in classes if c < eff_kv]
        eff_kv = lower[0] if lower else classes[-1]

    dropped = set(net.bus.index) - kept
    if not dropped:
        return {"effective_min_kv": eff_kv, "n_dropped_buses": 0,
                "n_gens_moved": 0, "n_gens_lost": 0, "reduced": False}

    # Adjacency over lines + trafos (the boundary trafos are exactly how the
    # sub-network hangs from the backbone — BFS through them finds the
    # electrically correct aggregation bus).
    adj = {}
    def _link(a, b):
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    for _, row in net.line.iterrows():
        _link(int(row["from_bus"]), int(row["to_bus"]))
    for _, row in net.trafo.iterrows():
        _link(int(row["hv_bus"]), int(row["lv_bus"]))

    # Multi-source BFS: every dropped bus gets the nearest kept boundary bus.
    anchor = {}
    frontier = []
    for k in kept:
        for nb in adj.get(int(k), ()):
            if nb in dropped and nb not in anchor:
                anchor[nb] = int(k)
                frontier.append(nb)
    while frontier:
        nxt = []
        for b in frontier:
            for nb in adj.get(b, ()):
                if nb in dropped and nb not in anchor:
                    anchor[nb] = anchor[b]
                    nxt.append(nb)
        frontier = nxt

    n_moved = n_lost = 0
    if len(net.gen) > 0:
        for gi in net.gen.index:
            b = int(net.gen.at[gi, "bus"])
            if b in dropped:
                if b in anchor:
                    net.gen.at[gi, "bus"] = anchor[b]
                    n_moved += 1
                else:
                    # sub-network component with no path to the backbone —
                    # dropping is the honest outcome (counted, not hidden)
                    net.gen.at[gi, "in_service"] = False
                    n_lost += 1

    pp.drop_buses(net, list(dropped))

    return {"effective_min_kv": eff_kv,
            "n_dropped_buses": len(dropped),
            "n_kept_buses": len(kept),
            "n_gens_moved": n_moved,
            "n_gens_lost": n_lost,
            "reduced": True}


def prune_dc_infeasible(net, angle_threshold=45.0):
    """After DC power flow, remove lines/trafos with extreme angle differences.

    Lines with large angle differences across them represent bottlenecks
    that will prevent AC convergence. Iteratively prune and re-run DC
    until the network is clean.
    """
    total_removed = 0
    for _iteration in range(5):  # max 5 rounds
        try:
            pp.rundcpp(net)  # in-place: rundcpp writes only res_*; inputs intact
        except Exception:
            break

        removed_this_round = 0
        va = net.res_bus["va_degree"]

        # Check lines (vectorized: replaces per-line .at loop + per-round deepcopy)
        li = net.line[net.line["in_service"]]
        if len(li) > 0:
            d = np.abs(va.reindex(li["from_bus"].to_numpy()).to_numpy()
                       - va.reindex(li["to_bus"].to_numpy()).to_numpy())
            bad = li.index[np.nan_to_num(d, nan=0.0) > angle_threshold]
            if len(bad) > 0:
                net.line.loc[bad, "in_service"] = False
                removed_this_round += int(len(bad))

        # Check trafos (vectorized)
        tr = net.trafo[net.trafo["in_service"]]
        if len(tr) > 0:
            d = np.abs(va.reindex(tr["hv_bus"].to_numpy()).to_numpy()
                       - va.reindex(tr["lv_bus"].to_numpy()).to_numpy())
            bad = tr.index[np.nan_to_num(d, nan=0.0) > angle_threshold]
            if len(bad) > 0:
                net.trafo.loc[bad, "in_service"] = False
                removed_this_round += int(len(bad))

        total_removed += removed_this_round
        if removed_this_round == 0:
            break

    return total_removed


def scale_line_ratings(net):
    """Scale line and transformer ratings to prevent unrealistic overloading.

    The synthetic network has limited topology, so a few lines carry
    disproportionate power.  Scale max_i_ka and trafo sn_mva so that
    the network is physically feasible.
    """
    # Quick in-place DC to estimate flows (rundcpp writes only res_*; inputs intact)
    try:
        pp.rundcpp(net)
    except Exception:
        return

    # Scale lines (vectorized)
    if len(net.res_line) > 0 and "loading_percent" in net.res_line.columns:
        load = net.res_line["loading_percent"].reindex(net.line.index)
        bad = net.line.index[(load > 100).fillna(False).to_numpy()]
        if len(bad) > 0:
            f = load.loc[bad].to_numpy() / 80.0
            net.line.loc[bad, "max_i_ka"] = net.line.loc[bad, "max_i_ka"].to_numpy() * f

    # Scale transformers (vectorized)
    if len(net.res_trafo) > 0 and "loading_percent" in net.res_trafo.columns:
        load = net.res_trafo["loading_percent"].reindex(net.trafo.index)
        bad = net.trafo.index[(load > 100).fillna(False).to_numpy()]
        if len(bad) > 0:
            f = load.loc[bad].to_numpy() / 80.0
            net.trafo.loc[bad, "sn_mva"] = net.trafo.loc[bad, "sn_mva"].to_numpy() * f


# Typical JP annual capacity factors by fuel — the merit-order weighting
# for synthetic dispatch. Uniform scaling ran every plant at the same
# fraction, which compressed near-baseload LNG/coal trunk plants to ~35%
# while phantom default-capacity rooftop solar ran at the same rate —
# flattening the corridor flow pattern (measured against TEPCO actuals:
# 新袖ヶ浦線 model 1,929 MW vs measured p95 4,690 MW).
_DISPATCH_CF = {
    "nuclear": 0.8, "coal": 0.7, "gas": 0.55, "lng": 0.55, "oil": 0.1,
    "hydro": 0.45, "solar": 0.15, "wind": 0.25, "biomass": 0.6,
    "geothermal": 0.6, "waste": 0.6,
}
_DEFAULT_CF = 0.3


def _dispatch_cf(fuel) -> float:
    """Capacity factor for a fuel tag; multi-fuel uses the FIRST token.

    "oil;gas" plants are typically legacy oil stations with partial gas
    repowering (鹿島: nameplate 5.7 GW, largely retired) — taking the
    best fuel's factor over-dispatched them and flooded their corridors
    (香取線 model 5,727 MW vs measured p95 1,321 MW), so the first tag
    wins and stale-nameplate damping is left to authoritative capacity
    data (Pillar 3).
    """
    tokens = [t.strip().lower() for t in str(fuel or "").split(";") if t.strip()]
    return _DISPATCH_CF.get(tokens[0], _DEFAULT_CF) if tokens else _DEFAULT_CF


def balance_power(net, demand_config):
    """Match generation to load with merit-order (capacity-factor) dispatch.

    Each generator's available output is max_p_mw x its fuel's typical
    capacity factor; the fleet is scaled to the demand target on that
    basis (clipped at nameplate). Falls back to uniform scaling when the
    builder did not provide fuel types (``type`` column).
    """
    if len(net.load) == 0:
        return

    # Only count active loads and gens
    active_load = net.load[net.load["in_service"]]["p_mw"].sum()
    if active_load <= 0:
        return

    reserve_margin = demand_config.get("reserve_margin", 0.05)
    target_gen = active_load * (1 + reserve_margin)

    if len(net.gen) > 0:
        # Disable generators on out-of-service buses
        inactive_buses = set(net.bus.index[~net.bus["in_service"]])
        gen_inactive_mask = net.gen["bus"].isin(inactive_buses)
        net.gen.loc[gen_inactive_mask, "in_service"] = False

        active = net.gen["in_service"]
        cap = (net.gen.loc[active, "max_p_mw"]
               if "max_p_mw" in net.gen.columns else net.gen.loc[active, "p_mw"])
        if "type" in net.gen.columns and net.gen.loc[active, "type"].notna().any():
            avail = cap * net.gen.loc[active, "type"].map(_dispatch_cf)
        else:
            avail = cap.astype(float)
        total_avail = float(avail.sum())
        if total_avail > 0:
            p = avail * (target_gen / total_avail)
            net.gen.loc[active, "p_mw"] = p.clip(upper=cap)
