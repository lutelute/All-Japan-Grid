"""AC evidence checks and reversible, explicit model trials.

Convergence, Q-limit compliance, voltage/thermal feasibility and source accuracy
are separate results. No pruning, synthetic infeed or implicit solver fallback.
"""
from __future__ import annotations

import copy
import json
import time
import warnings

import numpy as np
import pandapower as pp


def strict_ac(net, *, enforce_q_lims=True, init="dc"):
    """Solve a copy and independently inspect results, including all live buses."""
    n = copy.deepcopy(net)
    options = dict(algorithm="nr", init=init, max_iteration=50,
                   tolerance_mva=1e-4, enforce_q_lims=enforce_q_lims,
                   check_connectivity=True, numba=True)
    start = time.monotonic()
    record = dict(options=options, converged=False,
                  requested_load_mw=float((n.load.loc[n.load.in_service, "p_mw"] *
                                           n.load.loc[n.load.in_service, "scaling"]).sum()),
                  live_buses=int(n.bus.in_service.sum()))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pp.runpp(n, **options)
        live = n.bus.index[n.bus.in_service]
        vm = n.res_bus.loc[live, "vm_pu"]
        gen = n.gen[n.gen.in_service]
        q = n.res_gen.loc[gen.index, "q_mvar"]
        excess = np.maximum(q - gen.max_q_mvar, gen.min_q_mvar - q).clip(lower=0)
        d = n._ppc["internal"]
        # Sbus is the final constrained subproblem, not the pre-limit injection.
        mis = d["V"] * np.conj(d["Ybus"] @ d["V"]) - d["Sbus"]
        ids = np.r_[d["pv"], d["pq"]]
        residual = np.r_[mis[ids].real, mis[d["pq"]].imag] * n.sn_mva
        record.update(converged=bool(n.converged),
                      finite_buses=int(np.isfinite(vm).sum()),
                      served_mw=float(n.res_load.p_mw.sum()),
                      vm_min=float(vm.min()), vm_max=float(vm.max()),
                      buses_outside_09_11=int(((vm < .9) | (vm > 1.1)).sum()),
                      max_q_violation_mvar=float(excess.max()) if len(excess) else 0.,
                      q_violations=int((excess > 1e-4).sum()),
                      mismatch_max_mva=float(abs(residual).max()) if len(residual) else 0.,
                      max_line_loading_pct=float(n.res_line.loading_percent.max()),
                      max_trafo_loading_pct=float(n.res_trafo.loading_percent.max()),
                      overloaded_lines=int((n.res_line.loading_percent > 100).sum()),
                      overloaded_trafos=int((n.res_trafo.loading_percent > 100).sum()),
                      loss_mw=float(n.res_line.pl_mw.sum() + n.res_trafo.pl_mw.sum()),
                      slack_p_mw=float(n.res_ext_grid.p_mw.sum()),
                      slack_q_mvar=float(n.res_ext_grid.q_mvar.sum()),
                      slacks=len(n.ext_grid),
                      iterations=n._ppc.get("iterations"))
        record["ac_equations_and_q_pass"] = bool(
            record["converged"] and record["finite_buses"] == record["live_buses"]
            and abs(record["served_mw"] - record["requested_load_mw"]) < 1e-5
            and record["mismatch_max_mva"] <= 1e-4 and record["q_violations"] == 0)
        record["voltage_thermal_screen_pass"] = bool(
            record["ac_equations_and_q_pass"] and not record["buses_outside_09_11"]
            and not record["overloaded_lines"] and not record["overloaded_trafos"])
    except pp.LoadflowNotConverged as exc:
        record.update(error=str(exc), ac_equations_and_q_pass=False,
                      voltage_thermal_screen_pass=False)
    record["seconds"] = round(time.monotonic() - start, 3)
    return n, record


def condition_estimate(matrix):
    """Sparse 1-norm estimate; not a proof of existence of an AC solution."""
    from scipy.sparse.linalg import LinearOperator, onenormest, splu
    a = matrix.tocsc()
    if not a.shape[0]:
        return dict(size=0, nnz=0, condition_1norm_estimate=None)
    try:
        lu = splu(a)
        inv = LinearOperator(a.shape, matvec=lu.solve, matmat=lu.solve,
                             rmatvec=lambda x: lu.solve(x, "H"), dtype=a.dtype)
        # Estimator uses random probes; restore caller RNG state.
        state = np.random.get_state()
        try:
            np.random.seed(0)
            value = float(onenormest(a) * onenormest(inv))
        finally:
            np.random.set_state(state)
        return dict(size=a.shape[0], nnz=a.nnz, condition_1norm_estimate=value,
                    min_abs_lu_pivot=float(abs(lu.U.diagonal()).min()))
    except RuntimeError as exc:
        return dict(size=a.shape[0], nnz=a.nnz, error=str(exc))


def ybus_diagnosis(net):
    from scipy.sparse import bmat, diags
    from pandapower.pypower.dSbus_dV import dSbus_dV
    n = copy.deepcopy(net)
    try:
        pp.runpp(n, init="flat", max_iteration=0, enforce_q_lims=False, numba=True)
    except pp.LoadflowNotConverged:
        pass
    d = n._ppc["internal"]
    y = d["Ybus"].tocsr()
    diag = abs(y.diagonal())
    nonref = np.setdiff1d(np.arange(y.shape[0]), d["ref"])
    a = y[nonref, :][:, nonref]
    scale = np.zeros(a.shape[0])
    np.divide(1., np.sqrt(abs(a.diagonal())), out=scale,
              where=abs(a.diagonal()) > 0)
    ds_v, ds_a = dSbus_dV(y, np.ones(y.shape[0], dtype=complex))
    pq = d["pq"]
    ids = np.r_[d["pv"], pq]
    j = bmat([[ds_a[ids, :][:, ids].real, ds_v[ids, :][:, pq].real],
              [ds_a[pq, :][:, ids].imag, ds_v[pq, :][:, pq].imag]], format="csc")
    nz = diag[diag > 0]
    lookup = n._pd2ppc_lookups["bus"]
    reverse = {int(lookup[b]): int(b) for b in n.bus.index if lookup[b] >= 0}
    mismatches = []
    for i, r in n.line[n.line.in_service].iterrows():
        kv = n.bus.loc[[r.from_bus, r.to_bus], "vn_kv"].to_numpy()
        if abs(kv[0] - kv[1]) > 1e-6:
            mismatches.append(dict(line=int(i), name=str(r["name"]), kv=kv.tolist()))
    return dict(shape=list(y.shape), nnz=y.nnz, reference_buses=len(d["ref"]),
                zero_diagonal_buses=[reverse[int(i)] for i in np.where(diag == 0)[0]],
                nonzero_diagonal_spread=float(nz.max()/nz.min()) if len(nz) else None,
                grounded_ybus=condition_estimate(a),
                equilibrated_grounded_ybus=condition_estimate(diags(scale) @ a @ diags(scale)),
                flat_jacobian=condition_estimate(j), voltage_mismatch_lines=mismatches,
                interpretation="One reference per island removed. Estimates are numerical "
                "sensitivity diagnostics, not proof of AC solvability or physical accuracy.")


def trace_q_switching(net):
    """Locate a failed Q-limit transition with a bounded injection homotopy.

    Single-process diagnostic for pandapower 3.4.0. Temporarily wraps its inner
    Newton call and always restores it. Intermediate alpha is NOT a load factor,
    capacity margin, or feasible solution of the original operating point.
    """
    import pandapower.pf.run_newton_raphson_pf as nr
    from pandapower.pypower.dSbus_dV import dSbus_dV
    from scipy.sparse import bmat
    from scipy.sparse.linalg import spsolve
    if pp.__version__ != "3.4.0":
        raise ValueError("Internal Q-transition tracing is pinned to pandapower 3.4.0")
    if net.load.filter(regex="const_[zi]").to_numpy().any():
        raise ValueError("Q-transition trace requires constant-power loads")
    original = nr.newtonpf
    trace, checkpoints = [], []

    def wrapped(y, s, v0, ref, pv, pq, pc, options, makeYbus=None):
        solved = original(y, s, v0, ref, pv, pq, pc, options, makeYbus)
        row = dict(call=len(trace), pv=len(pv), pq=len(pq),
                   direct_converged=bool(solved[1]), steps=[])
        trace.append(row)
        if solved[1]:
            return solved
        v = v0.copy()
        s0 = v * np.conj(y @ v)
        alpha, step, iterations = 0., .1, 0
        settings = dict(options, voltage_depend_loads=False)
        last = None
        for _ in range(80):
            target = min(1., alpha + step)
            trial = original(y, (1-target)*s0 + target*s, v, ref, pv, pq,
                             pc, settings, makeYbus)
            iterations += trial[2]
            row["steps"].append(dict(constraint_transition_fraction=target,
                                     converged=bool(trial[1]), iterations=int(trial[2]),
                                     vm_min=float(abs(trial[0]).min())))
            if trial[1]:
                v = trial[0].copy()
                alpha = target
                last = (y.copy(), v.copy(), s-s0, pv.copy(), pq.copy(), alpha)
                if alpha == 1:
                    row["recovered"] = True
                    return trial[0], trial[1], iterations, *trial[3:]
                step = min(.2, step*1.4)
            else:
                step *= .5
                if step < 1e-5:
                    break
        row.update(recovered=False, last_constraint_transition_fraction=alpha)
        if last is not None:
            checkpoints.append(last)
        # Do not clamp more generators using a failed inner Newton iterate.
        raise pp.LoadflowNotConverged(f"Q transition stopped at fraction {alpha}")

    nr.newtonpf = wrapped
    try:
        solved, result = strict_ac(net)
    finally:
        nr.newtonpf = original
    weak = []
    if checkpoints:
        y, v, ds, pv, pq, alpha = checkpoints[-1]
        ids = np.r_[pv, pq]
        dv, da = dSbus_dV(y, v)
        j = bmat([[da[ids, :][:, ids].real, dv[ids, :][:, pq].real],
                  [da[pq, :][:, ids].imag, dv[pq, :][:, pq].imag]], format="csc")
        dx = spsolve(j, np.r_[ds[ids].real, ds[pq].imag])[len(ids):]
        lookup = solved._pd2ppc_lookups["bus"]
        reverse = {int(lookup[b]): int(b) for b in solved.bus.index if lookup[b] >= 0}
        for i in np.argsort(abs(dx))[::-1][:20]:
            b = reverse[int(pq[i])]
            weak.append(dict(bus=b, name=solved.bus.at[b, "name"],
                             kv=float(solved.bus.at[b, "vn_kv"]),
                             vm_pu=float(abs(v[pq[i]])), dvm_dalpha=float(dx[i]),
                             constraint_transition_fraction=alpha))
    return dict(result=result, transitions=trace, weak_buses=weak,
                interpretation="Local Jacobian sensitivity at the last converged artificial "
                "injection point. This is not an AC feasibility certificate or loadability limit.")


def identity_load_trial(net, groups):
    """Count same-source/same-voltage synthetic demand weights once per zone.

    Preserve every bus/branch/generator and zone P/Q totals. This changes the
    demand PRIOR, not a measured demand. Never apply to observed/pinned loads.
    Groups must be source-validated by the caller and pinned to the input hash.
    """
    n = copy.deepcopy(net)
    factor = {}
    for g in groups:
        buses = g["buses"]
        if not g.get("osm_identity") or len(set(buses)) != len(buses) or len(buses) < 2:
            raise ValueError("Explicit duplicate source identity and distinct buses required")
        for b in buses:
            if b in factor or b not in n.bus.index:
                raise ValueError("Overlapping groups or unknown bus")
            if n.bus.at[b, "zone"] != g["zone"] or abs(n.bus.at[b, "vn_kv"] - g["kv"]) > 1e-6:
                raise ValueError("Voltage and region must agree")
            factor[b] = 1 / len(buses)
    # A redistribution affects all eligible loads in a zone; require all to be
    # the synthetic allocator's rows, with no hidden scaling or ZIP dependence.
    if any(str(r["name"]) != f"load_{int(r.bus)}" for _, r in n.load.iterrows()):
        raise ValueError("Only unpinned synthetic allocator loads are supported")
    if not n.load.in_service.all() or not (n.load.scaling == 1).all():
        raise ValueError("Inactive/scaled loads require a different allocation ledger")
    zones = n.load.bus.map(n.bus.zone)
    before = n.load.groupby(zones)[["p_mw", "q_mvar"]].sum()
    old_by_bus = n.load.groupby("bus").p_mw.sum()
    f = n.load.bus.map(lambda b: factor.get(b, 1.))
    n.load["p_mw"] *= f
    n.load["q_mvar"] *= f
    adjusted = n.load.groupby(zones).p_mw.sum()
    multiplier = zones.map(before.p_mw / adjusted)
    n.load["p_mw"] *= multiplier
    n.load["q_mvar"] *= multiplier
    # This trial accepts only the baseline's estimated load compensation.
    qbus = net.load.groupby("bus").q_mvar.sum()
    if not net.shunt.empty:
        expected = net.shunt.bus.map(qbus) * -.8
        if not np.allclose(net.shunt.q_mvar, expected) or not (net.shunt.p_mw == 0).all():
            raise ValueError("Shunts are not exclusively the declared 80% estimated compensation")
    bf = n.load.groupby("bus").p_mw.sum() / old_by_bus
    n.shunt["q_mvar"] *= n.shunt.bus.map(bf).fillna(1.)
    after = n.load.groupby(zones)[["p_mw", "q_mvar"]].sum()
    if not np.allclose(before, after, atol=1e-8, rtol=1e-12):
        raise ValueError("Zone totals changed; mixed power factors need separate allocation")
    return n, dict(groups=groups, before_by_zone=before.to_dict("index"),
                   after_by_zone=after.to_dict("index"),
                   zone_multiplier=(before.p_mw/adjusted).to_dict(),
                   load_bus_multiplier=bf.to_dict(),
                   interpretation="Synthetic prior correction; actual site MW remains unvalidated.")


def restore_source_branch(net, plan, *, add_branch=True):
    """Split an existing surveyed route, then attach explicit source feeders.

    This is a copied electrical trial, not a mutation of the built GIS. Series
    R/X and total charging C of the parent route are retained. Splitting its pi
    representation can change AC results; callers must run a split-only control.
    """
    n = copy.deepcopy(net)
    li = plan["parent_circuit_line"]
    old = n.line.loc[li].copy()
    if [int(old.from_bus), int(old.to_bus)] != plan["parent_buses"]:
        raise ValueError("Parent endpoints changed")
    lengths = plan["split_lengths_km"]
    if min(lengths) <= 0 or abs(sum(lengths) - old.length_km) > 1e-8:
        raise ValueError("Parent path length must be conserved")
    station = plan["station_bus"]
    if any(abs(n.bus.at[b, "vn_kv"]-500) > 1e-6 for b in [old.from_bus, old.to_bus, station]):
        raise ValueError("This source plan is exclusively 500 kV")
    tap = plan["tap_source"]
    b = pp.create_bus(n, vn_kv=500, type="n", name="宮城中央支線 分岐点 / source trial",
                      zone=n.bus.at[station, "zone"], geodata=(tap[1], tap[0]))
    n.line.at[li, "to_bus"] = b
    n.line.at[li, "length_km"] = lengths[0]
    second = int(n.line.index.max()+1)
    n.line.loc[second] = old
    n.line.at[second, "from_bus"] = b
    n.line.at[second, "length_km"] = lengths[1]
    for row, coordinates in zip([li, second], plan["split_coordinates"]):
        n.line.at[row, "geo"] = json.dumps(dict(type="LineString", coordinates=coordinates))
    added = []
    if add_branch:
        for branch in plan["branches"]:
            i = int(n.line.index.max()+1)
            n.line.loc[i] = old
            for col, value in dict(from_bus=b, to_bus=station,
                                   length_km=branch["length_km"], parallel=branch["circuits"],
                                   name="宮城中央支線 / source trial").items():
                n.line.at[i, col] = value
            n.line.at[i, "geo"] = json.dumps(dict(type="LineString", coordinates=branch["coordinates"]))
            added.append(i)
    return n, dict(tap_bus=b, split_line=second, added_lines=added,
                   original_parent_length_km=float(old.length_km), plan=plan)
