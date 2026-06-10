"""Tests for the backbone aggregation transform (reduce_to_backbone).

The backbone model is the project's answer to the proven AC-non-convergence
root cause (docs/WEST_AC_ANALYSIS.md: the 66-132 kV OSM sub-grid's
ill-conditioned transformers). These tests pin:

- the mechanics on a synthetic net (BFS anchoring, generator aggregation,
  unreachable-generator honesty, threshold auto-degrade), and
- the headline result on real data: **kansai converges in AC at full
  demand on the >=154 kV backbone** — previously only reachable at
  x0.3-0.4 demand scaling.
"""

import pandapower as pp
import pytest

pytest.importorskip("pandapower")

from src.powerflow.transforms import reduce_to_backbone  # noqa: E402


def _net_with_subgrid():
    """275 kV pair -- trafo -- 66 kV chain (gen at the far end) + isolated 66."""
    net = pp.create_empty_network(f_hz=60)
    b275a = pp.create_bus(net, vn_kv=275.0)
    b275b = pp.create_bus(net, vn_kv=275.0)
    b66a = pp.create_bus(net, vn_kv=66.0)
    b66b = pp.create_bus(net, vn_kv=66.0)
    b66iso = pp.create_bus(net, vn_kv=66.0)   # no path to the backbone
    pp.create_line_from_parameters(net, b275a, b275b, 30.0, 0.028, 0.325, 12.0, 2.0)
    pp.create_transformer_from_parameters(
        net, hv_bus=b275b, lv_bus=b66a, sn_mva=300, vn_hv_kv=275, vn_lv_kv=66,
        vk_percent=10.0, vkr_percent=0.3, pfe_kw=80, i0_percent=0.06)
    pp.create_line_from_parameters(net, b66a, b66b, 10.0, 0.1, 0.4, 9.0, 1.0)
    pp.create_gen(net, bus=b66b, p_mw=50.0, max_p_mw=80.0, vm_pu=1.0)
    pp.create_gen(net, bus=b66iso, p_mw=5.0, max_p_mw=10.0, vm_pu=1.0)
    pp.create_gen(net, bus=b275a, p_mw=400.0, max_p_mw=500.0, vm_pu=1.0)
    return net, b275a, b275b


def test_reduce_keeps_backbone_and_aggregates_gens():
    net, b275a, b275b = _net_with_subgrid()
    info = reduce_to_backbone(net, min_kv=154.0, min_keep_buses=1)
    assert info["reduced"] is True
    assert info["effective_min_kv"] == 154.0
    assert info["n_dropped_buses"] == 3
    # the 66 kV chain's generator lands on its boundary bus (through the trafo)
    assert info["n_gens_moved"] == 1
    moved = net.gen[net.gen["bus"] == b275b]
    assert len(moved) == 1 and float(moved.iloc[0]["p_mw"]) == 50.0
    # the unreachable 66 kV generator is dropped and counted, not silently kept
    assert info["n_gens_lost"] == 1
    assert set(net.bus.index) == {b275a, b275b}
    assert len(net.trafo) == 0


def test_reduce_threshold_degrades_when_too_thin():
    """A 66/132-only region (okinawa-like) steps the cut down, disclosed."""
    net = pp.create_empty_network(f_hz=60)
    b1 = pp.create_bus(net, vn_kv=132.0)
    b2 = pp.create_bus(net, vn_kv=132.0)
    pp.create_line_from_parameters(net, b1, b2, 5.0, 0.1, 0.4, 9.0, 1.0)
    info = reduce_to_backbone(net, min_kv=154.0, min_keep_buses=2)
    assert info["effective_min_kv"] == 132.0
    assert info["reduced"] is False          # nothing below the effective cut
    assert len(net.bus) == 2                 # untouched


def test_reduce_noop_when_all_backbone():
    net = pp.create_empty_network(f_hz=60)
    b1 = pp.create_bus(net, vn_kv=275.0)
    b2 = pp.create_bus(net, vn_kv=275.0)
    pp.create_line_from_parameters(net, b1, b2, 5.0, 0.028, 0.325, 12.0, 2.0)
    info = reduce_to_backbone(net, min_kv=154.0, min_keep_buses=1)
    assert info["reduced"] is False
    assert len(net.bus) == 2


# ── the headline: kansai AC at full demand (real data) ───────────────────────

def test_kansai_backbone_ac_converges_full_demand():
    """kansai was THE AC-non-convergent region (only solvable at x0.3-0.4
    demand). On the >=154 kV backbone it must converge natively with the
    full OCCTO-derived demand and physically sane voltages."""
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pipeline import build_and_solve

    result = build_and_solve("kansai", load_demand_config(),
                             topology="snapped", reconnect=True,
                             backbone_kv=154.0)
    assert result is not None
    _dc, dc_res, net_ac, ac_res, info, _geom = result

    bb = info["backbone"]
    assert bb["reduced"] is True and bb["effective_min_kv"] == 154.0
    assert bb["n_gens_moved"] > 100          # sub-grid generation aggregated
    assert info["total_load_mw"] > 20000     # full demand, NOT scaled down
    assert dc_res["converged"] is True
    assert ac_res["converged"] is True
    vmin = float(net_ac.res_bus[net_ac.bus["in_service"]]["vm_pu"].min())
    # measured 2026-06-10: 0.946 single-voltage, 0.838 multi-voltage — the
    # sag sits on the long 154 kV Kii-peninsula radial (Owase/Kumano), an
    # honest physical weak spot awaiting reactive/tap modelling (phase 5).
    assert 0.80 < vmin <= 1.05


def test_hokkaido_backbone_floor_is_66kv():
    """The mainland >=154 kV cut does not transfer to hokkaido (11 branches
    at 154 kV; the 66 kV layer with 591 branches IS the regional grid), so
    the default backbone request resolves to a 66 kV floor there — keeping
    the full 800-bus network — while an explicit value is honoured."""
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pipeline import DEFAULT_BACKBONE_KV, build_and_solve

    r = build_and_solve("hokkaido", load_demand_config(), topology="snapped",
                        reconnect=True, backbone_kv=DEFAULT_BACKBONE_KV)
    _dc, dc_res, _ac, ac_res, info, _ = r
    assert info["backbone"]["effective_min_kv"] == 66.0
    assert info["n_buses"] > 700
    assert dc_res["converged"] and ac_res["converged"]

    r2 = build_and_solve("hokkaido", load_demand_config(), topology="snapped",
                         reconnect=True, backbone_kv=187.0)   # explicit wins
    assert r2[4]["backbone"]["effective_min_kv"] == 187.0
