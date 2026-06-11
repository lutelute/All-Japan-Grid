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
