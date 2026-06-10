"""Regression pins for the topology / power-flow quality KPIs.

Two kinds of guards:

- **Exact pins** (okinawa, smallest region): the data files are tracked,
  so the builder output is deterministic — any change here is a real
  behaviour change and must be reviewed, not absorbed.
- **Quality floors** (other regions): bands that hold across deliberate
  data refreshes but catch regressions — coverage must not drop,
  fragmentation and synthetic-line rate must not grow.

The full 10-region solved sweep is gated behind AJGRID_SLOW_TESTS=1
(several minutes); CI keeps the fast subset.
"""

import os

import pytest

pytest.importorskip("pandapower")
pytest.importorskip("networkx")

from src.validation.topology_metrics import (  # noqa: E402
    compare,
    gather,
    render,
    solved_metrics,
    tag_coverage,
    topology_metrics,
)


# ── okinawa: exact pins (deterministic on tracked data) ──────────────────────

@pytest.fixture(scope="module")
def okinawa_topo():
    return topology_metrics("okinawa")


def test_okinawa_builder_pins(okinawa_topo):
    m = okinawa_topo
    assert m["builder"] == "snapped"
    assert m["n_real_subs"] == 59
    assert m["n_junctions"] == 22
    assert m["n_branches"] == 75
    assert m["n_gens"] == 16
    assert m["n_components"] == 11
    assert m["multi_circuit_branches"] == 6
    assert m["max_parallel"] == 3


def test_okinawa_quality_floors(okinawa_topo):
    m = okinawa_topo
    assert m["largest_comp_share"] >= 0.85
    assert m["unknown_kv_share"] <= 0.05


def test_okinawa_tag_coverage():
    t = tag_coverage("okinawa")
    assert t["n_line_features"] == 117
    assert t["voltage_fill"] >= 0.90
    # circuits is the unexploited direct evidence of parallel circuits —
    # if this jumps after a refetch, the builder should start consuming it.
    assert t["circuits_fill"] >= 0.40


def test_okinawa_solved_quality():
    s = solved_metrics("okinawa")
    assert s["dc_converged"] is True
    assert s["ac_converged"] is True
    # 4 = main island + genuinely separate islands (Miyako etc.); the
    # pipeline deliberately does NOT fabricate >5 km sea-strait bridges —
    # real islands are solved in place via multi_slack.
    assert s["n_components"] == 4
    assert s["synthetic_rate"] <= 0.15       # 2026-06 baseline: 7/57 = 12.3%
    assert 0.85 < s["ac_vm_min"] <= 1.05


# ── quality floors on a second (mid-size) region ─────────────────────────────

def test_shikoku_quality_floors():
    m = topology_metrics("shikoku")
    # 2026-06 baseline: 56 components, 56.8% coverage, 31.9% unknown kv.
    # Floors are set below baseline; improvements tighten them, regressions trip.
    assert m["n_components"] <= 70
    assert m["largest_comp_share"] >= 0.50
    assert m["unknown_kv_share"] <= 0.40


# ── report rendering / baseline diff (no data dependency) ────────────────────

def _row(region, comps, synth_rate, ac):
    return {
        "region": region,
        "tags": {"circuits_fill": 0.5},
        "topology": {"n_components": comps, "largest_comp_share": 0.9,
                     "unknown_kv_share": 0.1},
        "solved": {"n_buses": 10, "n_lines": 9, "n_synthetic_lines": 1,
                   "synthetic_rate": synth_rate, "dc_converged": True,
                   "ac_converged": ac, "ac_vm_min": 0.95,
                   "ac_max_loading_pct": 80.0},
    }


def test_render_includes_all_regions():
    out = render([_row("okinawa", 11, 0.12, True), _row("shikoku", 56, 0.05, False)])
    assert "okinawa" in out and "shikoku" in out
    assert "12.0%" in out  # synthetic rate is the headline KPI


def test_compare_flags_changes_and_unchanged():
    base = [_row("okinawa", 11, 0.12, True)]
    cur = [_row("okinawa", 5, 0.03, True)]
    out = compare(cur, base)
    assert "n_components: 11 -> 5" in out
    assert "synthetic_rate: 0.12 -> 0.03" in out
    same = compare(base, base)
    assert "unchanged" in same


def test_compare_handles_missing_baseline_region():
    out = compare([_row("tokyo", 100, 0.06, True)], [])
    assert "no baseline" in out


# ── full sweep (slow, opt-in) ────────────────────────────────────────────────

@pytest.mark.skipif(not os.environ.get("AJGRID_SLOW_TESTS"),
                    reason="set AJGRID_SLOW_TESTS=1 for the full 10-region sweep")
def test_all_regions_solved_sweep():
    from src.regions import REGIONS

    rows = gather(list(REGIONS), solve=True)
    assert len(rows) == len(REGIONS)
    for row in rows:
        s = row["solved"]
        assert s is not None, row["region"]
        assert s["dc_converged"] is True, row["region"]
        # Real islands stay separate components (no >5 km fabrication),
        # but fragmentation must stay bounded and bridging a small minority.
        assert s["n_components"] <= 25, row["region"]
        assert s["synthetic_rate"] <= 0.20, row["region"]
