"""N-1 shortfall of a UC plan, as an after-the-fact score and as an objective near the optimum.

The question asked of a plan, per region r and hour t: if the largest committed generator
in r trips, can the spinning headroom in r plus what the tie lines can still bring in cover
it? The part that cannot be covered is the shortfall s[r,t] (MW); summed over regions and
hours it is the plan's N-1 shortfall (MWh). Zero means every single trip is covered.

    trip[r,t]     = max over committed g in r of min(Pmax_g, trip_cap_mw)
    headroom[r,t] = sum over committed g in r of (Pmax_g - p[g,t])
    import[r,t]   = sum over tie lines l touching r of
                    min(spare capacity of l towards r, headroom of the region at the other end)
    s[r,t]        = max(0, trip - headroom - import)

Storage units count neither as a trip nor as headroom. The generators of the national
scenario are whole power stations (e.g. 5,040 MW), so the trip is capped at
``trip_cap_mw`` (default 1,000 MW, one large unit); None takes the whole station.
Ramp limits on the headroom are ignored, and a neighbour's headroom may be counted by
more than one of its neighbours.

``n1_shortfall`` scores a solved plan. ``near_optimal_hook`` returns a
``UCParameters.model_hook`` that keeps cost <= cost_cap and minimises the same shortfall,
so the after-the-fact score of the result equals the solver's secondary objective.
"""

from collections import defaultdict

import pulp


def _trip_size(g, trip_cap_mw):
    return g.capacity_mw if trip_cap_mw is None else min(g.capacity_mw, trip_cap_mw)


def _region(g):
    return g.region or "_unassigned"


def n1_shortfall(params, result, *, trip_cap_mw=1000.0):
    """Per-region hourly shortfall (MW) of a solved plan, plus totals."""
    T = params.time_horizon.num_periods
    sched = {s.generator_id: s for s in result.schedules}
    regions = sorted({_region(g) for g in params.generators})
    headroom = {r: [0.0] * T for r in regions}
    trip = {r: [0.0] * T for r in regions}
    for g in params.generators:
        if g.is_storage:
            continue
        s, r = sched[g.id], _region(g)
        for t in range(T):
            if s.commitment[t] > 0.5:
                headroom[r][t] += g.capacity_mw - s.power_output_mw[t]
                trip[r][t] = max(trip[r][t], _trip_size(g, trip_cap_mw))
    flows = {f.interconnection_id: f.flow_mw for f in result.interconnection_flows}
    imports = {r: [0.0] * T for r in regions}
    for ic in params.interconnections:
        for t in range(T):
            fl = flows[ic.id][t]
            imports[ic.to_region][t] += max(0.0, min(ic.cap_fwd - fl, headroom[ic.from_region][t]))
            imports[ic.from_region][t] += max(0.0, min(ic.cap_rev + fl, headroom[ic.to_region][t]))
    short = {r: [max(0.0, trip[r][t] - headroom[r][t] - imports[r][t]) for t in range(T)] for r in regions}
    return {"trip_cap_mw": trip_cap_mw, "shortfall_mw": short, "trip_mw": trip, "headroom_mw": headroom,
            "import_mw": imports, "total_mwh": sum(sum(v) for v in short.values()),
            "short_hours": sum(1 for v in short.values() for x in v if x > 1e-6)}


def congested_hours(params, result, *, threshold=0.995):
    """Tie-line hours used at or above ``threshold`` of their limit in the flow direction."""
    flows = {f.interconnection_id: f.flow_mw for f in result.interconnection_flows}
    count = 0
    for ic in params.interconnections:
        for fl in flows.get(ic.id, []):
            limit = ic.cap_fwd if fl >= 0 else ic.cap_rev
            count += limit > 0 and abs(fl) >= threshold * limit
    return count


def near_optimal_hook(cost_cap, *, trip_cap_mw=1000.0, interconnections=(), record=None):
    """model_hook: cost <= cost_cap, minimise the N-1 shortfall defined above."""

    def hook(model, var):
        u, p, f, gens, timesteps = var["u"], var["p"], var["f"], var["generators"], var["timesteps"]
        by_region = defaultdict(list)
        for g in gens:
            if not g.is_storage:
                by_region[_region(g)].append(g)
        regions = sorted(by_region)
        T = list(timesteps)
        head = {(r, t): pulp.lpSum(g.capacity_mw * u[(g.id, t)] - p[(g.id, t)] for g in by_region[r])
                for r in regions for t in T}
        trip = pulp.LpVariable.dicts("n1_trip", [(r, t) for r in regions for t in T], lowBound=0)
        short = pulp.LpVariable.dicts("n1_short", [(r, t) for r in regions for t in T], lowBound=0)
        imp = defaultdict(list)
        for ic in interconnections:
            for t in T:
                for end, other, spare in ((ic.to_region, ic.from_region, ic.cap_fwd - f[(ic.id, t)]),
                                          (ic.from_region, ic.to_region, ic.cap_rev + f[(ic.id, t)])):
                    if end not in by_region:
                        continue
                    x = pulp.LpVariable(f"n1_imp_{ic.id}_{end}_{t}", lowBound=0)
                    model += x <= spare, f"n1_imp_spare_{ic.id}_{end}_{t}"
                    if other in by_region:
                        model += x <= head[(other, t)], f"n1_imp_head_{ic.id}_{end}_{t}"
                    else:
                        model += x <= 0, f"n1_imp_none_{ic.id}_{end}_{t}"
                    imp[(end, t)].append(x)
        for r in regions:
            for t in T:
                for g in by_region[r]:
                    model += trip[(r, t)] >= _trip_size(g, trip_cap_mw) * u[(g.id, t)], f"n1_trip_{g.id}_{t}"
                model += short[(r, t)] >= trip[(r, t)] - head[(r, t)] - pulp.lpSum(imp[(r, t)]), f"n1_short_{r}_{t}"
        model += var["cost"] <= cost_cap, "near_optimal_cost_cap"
        model.setObjective(pulp.lpSum(short.values()))
        if record is not None:
            record.update(regions=regions, rows=model.numConstraints())

    return hook
