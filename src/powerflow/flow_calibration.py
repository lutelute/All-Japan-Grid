"""Demand state estimation from measured corridor flows (PLAN_66KV ㊽).

The ceiling-breaker the name-matching tiers could not reach: the
disclosure's ~700 measured per-line flows are themselves demand
information. On a (near-)radial sub-transmission layer, cutting one
corridor splits the network into a SOURCE side (reaches an injection —
a transformer from the >=140 kV grid) and a LOAD subtree; conservation
says the corridor's flow equals the subtree's total demand. So every
measured corridor pins the aggregate demand of every yard hanging
below it — named or nameless. Names only matter for finding the
corridor itself; the yards it feeds need none.

Nested corridors are processed inner-first: an inner corridor fixes
its subtree exactly; an outer corridor then scales only the not-yet-
fixed remainder of its own subtree. Buses pinned by measured busbar
loads (``measured_*``) are never rescaled — the synthetic residual
absorbs the correction.

Honesty: calibrating on the same corridors the validator scores would
be circular. ``exclude`` holds out a test set; the validator
(--corridor-calib) splits matched corridors deterministically and
reports the held-out rho.
"""

from __future__ import annotations

from typing import Dict, Iterable, Set

from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def corridor_subtree_calibration(net, stats: Dict[str, float],
                                 lo_kv: float = 60.0, hi_kv: float = 140.0,
                                 exclude: Iterable[str] = (),
                                 max_scale: float = 25.0) -> dict:
    """Scale subtree demands so measured corridor flows are conserved.

    Args:
        net: pandapower net AFTER load placement (modified in place).
        stats: {normalised corridor name: measured MW} — the statistic
            should match the solved snapshot's level (p95 convention).
        exclude: corridor keys to hold out (validation test set).
        max_scale: per-subtree scale clamp — a subtree whose synthetic
            demand would need more than this factor indicates a wiring
            problem, not a demand one; skipped and counted honestly.

    Returns a summary dict (n_calibrated / n_skipped_* / mw_moved).
    """
    import networkx as nx

    from src.validation.external_tepco import _model_name_keys

    vn = net.bus["vn_kv"]
    excl = set(exclude)

    # in-band corridor graph; the band test uses the HIGHER endpoint so
    # unknown-voltage junction buses (vn 0) don't sever connectivity
    G = nx.Graph()
    key_edges: Dict[str, list] = {}
    for idx in net.line.index:
        if not bool(net.line.at[idx, "in_service"]):
            continue
        fb = int(net.line.at[idx, "from_bus"])
        tb = int(net.line.at[idx, "to_bus"])
        kvln = max(float(vn.get(fb, 0)), float(vn.get(tb, 0)))
        if not (lo_kv <= kvln < hi_kv):
            continue
        G.add_edge(fb, tb)
        raw = str(net.line.at[idx, "name"] or "")
        if not raw or raw.startswith("recon_line"):
            continue
        for k in _model_name_keys(raw):
            if k in stats:
                key_edges.setdefault(k, []).append((fb, tb))

    # injection nodes: buses tied (via trafo) to the >=hi_kv grid, plus
    # in-band buses carrying generation or an ext_grid
    inj: Set[int] = set()
    for t in net.trafo.itertuples():
        if not t.in_service:
            continue
        hvb, lvb = int(t.hv_bus), int(t.lv_bus)
        if lvb in G and float(vn.get(hvb, 0)) >= hi_kv:
            inj.add(lvb)
    for g in net.gen.itertuples():
        if g.in_service and int(g.bus) in G:
            inj.add(int(g.bus))
    for e in net.ext_grid.itertuples():
        if e.in_service and int(e.bus) in G:
            inj.add(int(e.bus))

    load_by_bus: Dict[int, list] = {}
    pinned_by_bus: Dict[int, float] = {}
    for li in net.load.index:
        if not bool(net.load.at[li, "in_service"]):
            continue
        b = int(net.load.at[li, "bus"])
        if str(net.load.at[li, "name"] or "").startswith("measured_"):
            pinned_by_bus[b] = pinned_by_bus.get(b, 0.0) + float(
                net.load.at[li, "p_mw"])
        else:
            load_by_bus.setdefault(b, []).append(li)

    # resolve each corridor to ONE load subtree
    jobs = []
    skip = {"no_edge": 0, "meshed_or_isolated": 0, "no_injection_side": 0,
            "excluded": 0, "overscale": 0}
    for key, mw in stats.items():
        if key in excl:
            skip["excluded"] += 1
            continue
        edges = key_edges.get(key)
        if not edges:
            skip["no_edge"] += 1
            continue
        H = G.copy()
        for (a, b) in edges:                 # all segments cut together
            if H.has_edge(a, b):
                H.remove_edge(a, b)
        # A series corridor leaves its internal junctions as fragments
        # after the cut; classify ALL touched components instead of
        # expecting exactly two sides: components holding an injection
        # form the source side, the rest (union) is the load subtree.
        sides = []
        seen: Set[int] = set()
        for (a, b) in edges:
            for n in (a, b):
                if n in seen or n not in H:
                    continue
                comp = nx.node_connected_component(H, n)
                seen |= comp
                sides.append(comp)
        src_sides = [c for c in sides if c & inj]
        load_nodes: Set[int] = set().union(
            *[c for c in sides if not (c & inj)]) if len(src_sides) < len(sides) else set()
        if not src_sides:
            skip["no_injection_side"] += 1    # nothing feeds either side
            continue
        if not load_nodes:
            skip["meshed_or_isolated"] += 1   # every side still reaches a source -> loop
            continue
        jobs.append((len(load_nodes), key, float(mw), load_nodes))

    # inner-first; once a subtree is calibrated its buses are frozen
    fixed: Set[int] = set()
    n_cal = 0
    mw_moved = 0.0
    for _size, key, mw, subtree in sorted(jobs, key=lambda j: j[0]):
        free = [li for b in subtree if b not in fixed
                for li in load_by_bus.get(b, ())]
        fixed_mw = sum(float(net.load.at[li, "p_mw"])
                       for b in (subtree & fixed)
                       for li in load_by_bus.get(b, ()))
        fixed_mw += sum(pinned_by_bus.get(b, 0.0) for b in subtree)
        free_mw = sum(float(net.load.at[li, "p_mw"]) for li in free)
        target_free = mw - fixed_mw
        if not free or free_mw <= 0:
            continue
        if target_free <= 0:
            scale = 0.0   # measured flow already covered by pinned demand
        else:
            scale = target_free / free_mw
            if scale > max_scale:
                skip["overscale"] += 1
                continue
        for li in free:
            p0 = float(net.load.at[li, "p_mw"])
            net.load.at[li, "p_mw"] = p0 * scale
            q0 = float(net.load.at[li, "q_mvar"])
            net.load.at[li, "q_mvar"] = q0 * scale
            mw_moved += abs(p0 * scale - p0)
        fixed |= subtree
        n_cal += 1

    summary = {"n_corridors": len(stats), "n_calibrated": n_cal,
               "mw_moved": round(mw_moved, 1), **skip}
    logger.info("corridor calibration: %s", summary)
    return summary


def ptdf_demand_estimation(net, stats: Dict[str, float],
                           lo_kv: float = 60.0, hi_kv: float = 140.0,
                           lam: float = 0.1, total_w: float = 10.0,
                           max_scale: float = 25.0,
                           cell_deg: float | None = 0.15) -> dict:
    """v2 (ledger 49): fit ALL measured corridor flows simultaneously.

    Linearized DC state estimation over the adjustable (synthetic)
    loads::

        min ||S (P - P0) - r||^2 + lam ||P - P0||^2 + w (1'(P-P0))^2
        s.t. 0 <= P <= max_scale * P0

    where S holds PTDF load-sensitivities of one representative segment
    per measured corridor and r = sign(f0)*measured - f0 is the flow
    residual at the prior point. Unlike the greedy subtree pass (v1),
    loops, nested corridors and cross-subtree balance are handled by
    construction; the soft total row keeps the regional sum honest.

    Call on a BALANCED, solvable net (the pipeline rebalances after).
    """
    import numpy as np
    import pandapower as pp
    import scipy.sparse as sp
    from scipy.optimize import lsq_linear
    from scipy.sparse.linalg import splu

    from src.validation.external_tepco import _model_name_keys

    pp.rundcpp(net)
    base_mva = float(net.sn_mva or 100.0)
    vn = net.bus["vn_kv"]

    # --- branch susceptances and incidence over in-service elements ----
    rows = []   # (from_bus, to_bus, b_pu, line_idx or None)
    for idx in net.line.index:
        if not bool(net.line.at[idx, "in_service"]):
            continue
        fb, tb = int(net.line.at[idx, "from_bus"]), int(net.line.at[idx, "to_bus"])
        x_ohm = (float(net.line.at[idx, "x_ohm_per_km"])
                 * float(net.line.at[idx, "length_km"])
                 / max(int(net.line.at[idx, "parallel"] or 1), 1))
        vkv = float(vn.get(fb, 0)) or 1.0
        x_pu = x_ohm * base_mva / (vkv * vkv)
        if x_pu <= 0:
            x_pu = 1e-6
        rows.append((fb, tb, 1.0 / x_pu, idx))
    for t in net.trafo.itertuples():
        if not t.in_service:
            continue
        x_pu = max(float(t.vk_percent), 0.1) / 100.0 * base_mva / float(t.sn_mva)
        rows.append((int(t.hv_bus), int(t.lv_bus), 1.0 / x_pu, None))

    # --- main island ---------------------------------------------------
    import networkx as nx
    G = nx.Graph((a, b) for a, b, _bb, _i in rows)
    main = max(nx.connected_components(G), key=len)
    bus_col = {b: i for i, b in enumerate(sorted(main))}
    nb = len(bus_col)
    slack_bus = None
    for e in net.ext_grid.itertuples():
        if e.in_service and int(e.bus) in bus_col:
            slack_bus = int(e.bus)
            break
    if slack_bus is None:
        return {"error": "no slack in main island"}

    use = [(a, b, bb, i) for a, b, bb, i in rows if a in bus_col and b in bus_col]
    A = sp.lil_matrix((len(use), nb))
    bvec = np.zeros(len(use))
    line_row = {}
    for r, (a, b, bb, idx) in enumerate(use):
        A[r, bus_col[a]] = 1.0
        A[r, bus_col[b]] = -1.0
        bvec[r] = bb
        if idx is not None:
            line_row[idx] = r
    A = A.tocsr()
    Bf = sp.diags(bvec) @ A
    Bbus = (A.T @ Bf).tocsc()
    keep = np.array([i for b, i in sorted(bus_col.items()) if b != slack_bus])
    pos_of = {int(c): k for k, c in enumerate(keep)}
    lu = splu(Bbus[keep][:, keep].tocsc())

    # --- corridors -> representative line rows -------------------------
    key_lines: Dict[str, list] = {}
    for idx in net.line.index:
        if idx not in line_row:
            continue
        fb = int(net.line.at[idx, "from_bus"])
        tb = int(net.line.at[idx, "to_bus"])
        if not (lo_kv <= max(float(vn.get(fb, 0)), float(vn.get(tb, 0))) < hi_kv):
            continue
        raw = str(net.line.at[idx, "name"] or "")
        if not raw or raw.startswith("recon_line"):
            continue
        for k in _model_name_keys(raw):
            if k in stats:
                key_lines.setdefault(k, []).append(idx)

    f0 = net.res_line["p_from_mw"]
    targets = []   # (line_idx, residual_mw)
    for key, idxs in key_lines.items():
        rep = max(idxs, key=lambda i: abs(float(f0.get(i, 0.0))))
        f = float(f0.get(rep, 0.0))
        sign = 1.0 if f >= 0 else -1.0
        targets.append((rep, sign * float(stats[key]) - f))
    if not targets:
        return {"error": "no matched corridors"}

    # --- adjustable loads ----------------------------------------------
    var_loads = []
    for li in net.load.index:
        if not bool(net.load.at[li, "in_service"]):
            continue
        b = int(net.load.at[li, "bus"])
        if b not in bus_col or b == slack_bus:
            continue
        if str(net.load.at[li, "name"] or "").startswith("measured_"):
            continue
        if not (lo_kv <= float(vn.get(b, 0)) < hi_kv):
            continue
        p0 = float(net.load.at[li, "p_mw"])
        if p0 <= 0:
            continue
        var_loads.append((li, b, p0))
    if not var_loads:
        return {"error": "no adjustable loads"}
    nv = len(var_loads)
    P0 = np.array([p for _l, _b, p in var_loads])

    # --- sensitivity matrix S (corridor x load) -------------------------
    S = np.zeros((len(targets), nv))
    r_vec = np.zeros(len(targets))
    for ti, (rep, resid) in enumerate(targets):
        row = Bf.getrow(line_row[rep]).toarray().ravel()[keep]
        x = lu.solve(row)                       # PTDF over non-slack buses
        for vi, (_li, b, _p) in enumerate(var_loads):
            k = pos_of.get(bus_col[b])
            if k is not None:
                # dimensionless PTDF: MW of corridor flow per MW of load
                # (negative injection) — per-unit bases cancel
                S[ti, vi] = -x[k]
        r_vec[ti] = resid

    # --- spatial-cluster reparameterization (v3, ledger 49) -------------
    # On a near-tree, a corridor flow constrains only its own subtree:
    # per-load freedom fits train corridors and transfers nothing
    # (cross-fit test rho ~ baseline). Shrinking the DOF to geographic
    # cells makes train corridors constrain AREA scale factors that test
    # corridors share — the transfer mechanism. Deterministic grid cells
    # (no k-means randomness).
    if cell_deg:
        import json as _json
        geo = net.bus.get("geo")
        cell_of = []
        for (_li, b, _p) in var_loads:
            try:
                g = _json.loads(geo.at[b]) if geo is not None else None
                lon, lat = g["coordinates"][0], g["coordinates"][1]
                cell_of.append((round(lat / cell_deg), round(lon / cell_deg)))
            except (TypeError, ValueError, KeyError):
                cell_of.append(("x", "x"))
        cells = sorted(set(cell_of))
        cidx = {c: j for j, c in enumerate(cells)}
        nc = len(cells)
        Gm = np.zeros((nv, nc))
        for i, c in enumerate(cell_of):
            Gm[i, cidx[c]] = P0[i]            # dP = Gm @ s (per-cell scale)
        A_meas = S @ Gm
        cell_p0 = Gm.sum(axis=0)
        sq_lam = np.sqrt(lam)
        ones = (cell_p0 / max(cell_p0.sum(), 1.0))[None, :] * np.sqrt(total_w)
        A_st = np.vstack([A_meas, sq_lam * np.diag(cell_p0), ones])
        b_st = np.concatenate([r_vec, np.zeros(nc), [0.0]])
        res = lsq_linear(A_st, b_st,
                         bounds=(-0.95 * np.ones(nc),
                                 (max_scale - 1.0) * np.ones(nc)),
                         max_iter=300)
        dP = Gm @ res.x
        n_dof = nc
    else:
        sq_lam = np.sqrt(lam)
        ones = np.ones((1, nv)) * np.sqrt(total_w) / np.sqrt(nv)
        A_st = np.vstack([S, sq_lam * np.eye(nv), ones])
        b_st = np.concatenate([r_vec, np.zeros(nv), [0.0]])
        res = lsq_linear(A_st, b_st, bounds=(-P0, (max_scale - 1.0) * P0),
                         lsmr_tol="auto", max_iter=200)
        dP = res.x
        n_dof = nv
    for (li, _b, _p0), d in zip(var_loads, dP):
        p_new = float(net.load.at[li, "p_mw"]) + float(d)
        scale = p_new / max(float(net.load.at[li, "p_mw"]), 1e-9)
        net.load.at[li, "p_mw"] = p_new
        net.load.at[li, "q_mvar"] = float(net.load.at[li, "q_mvar"]) * scale

    resid_after = S @ dP - r_vec
    summary = {"method": "ptdf", "n_corridors_fit": len(targets),
               "n_vars": nv, "n_dof": n_dof,
               "mw_moved": round(float(np.abs(dP).sum()), 1),
               "net_mw_change": round(float(dP.sum()), 1),
               "resid_rms_before": round(float(np.sqrt((r_vec ** 2).mean())), 1),
               "resid_rms_after": round(float(np.sqrt((resid_after ** 2).mean())), 1),
               "lam": lam}
    logger.info("ptdf demand estimation: %s", summary)
    return summary
