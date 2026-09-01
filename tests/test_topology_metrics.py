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
    # Pinned values for the multi-voltage + evidence-based builder
    # (2026-06-10): substations split into one bus per voltage class
    # (59 sites -> 78 buses incl @u); OSM circuits/cables tags drive the
    # parallel counts (multi_circuit 4 -> 32); the 2.5 km terminal-vertex
    # snap radius reattaches yard-fence gaps (junctions 22 -> 16,
    # components 14 -> 11); the widened _SubIndex search ring fixed the
    # silent ~3 km cap on the 20 km big-plant lookup (gens 16 -> 22).
    # phase-10c: corridor voltage propagation types untagged segments from
    # their unique neighbouring class (unknown 3.3% -> 1.1%), which also
    # merges former @u buses into their classes (75 real subs, 87 branches).
    # 2026-06-11 tap snap (ledger 52): two dead-end stubs join their
    # neighbouring span mid-air (junctions 16 -> 14, branches 87 -> 85,
    # one merged parallel 32 -> 33) — the "bare polyline tee" fix.
    # 2026-06-12 OSM-faithful binding ON by default (ledger 85): polygon-
    # first vertex binding + tip joint + explicit lead-ins replace the
    # blind centroid radii (74 real subs / 28 junctions / 98 branches /
    # 10 components at that step; tokyo A/B: implicit wrong-binds
    # 3,365 -> 0, trunk rho .615 -> .647, 154 kV rho .095 -> .215).
    # 2026-06-12 name-evidence tip binding (ledger 91): 「X変電所~Y変電所線」
    # names bind dead-end tips to the named yards — okinawa gains two
    # name-claimed substations back (74 -> 76 real subs), their joins
    # absorb junction stubs (28 -> 20) and close fragments
    # (10 -> 6 components). Ledger 98: an unknown-kv tip may adopt the
    # NAME-CLAIMED substation's class (unknown->unknown stays forbidden) —
    # one more okinawa tip joins its named yard (21 -> 20 junctions); one more evidenced parallel merge lands a
    # 5-circuit corridor (35 -> 37 multi, max_parallel 4 -> 5).
    m = okinawa_topo
    assert m["builder"] == "snapped"
    # 2026-06-13 (ledger 106): mixed-voltage class expansion default-on —
    # 154;66 etc. under-built circuits restored to each class (76->78 real,
    # 20->21 jct, 98->114 branches). multi_circuit/max_parallel UNCHANGED:
    # circ_eff (ledger 105) keeps the main class's original circuits, so only
    # the added low-voltage circuit (parallel=1) appears — no de-aggregation.
    # 2026-08-16 OSM再抽出の基底データ刷新(0e1bd177 +524ノード / ec57bc3d 幽霊端点治癒)
    # がピン後(06-13)に入り、沖縄の基底が動いた。孤立6件(奥間/与根/宮古島市/
    # 竹富配電塔/知念久手堅/美浜三丁目)はいずれも離島または線路未マッピングで、
    # 主成分シェアは 0.941(floor 0.80)を維持している。
    # (78->79 real, 21->22 jct, 114->115 branches, 6->7 components,
    # 37->38 multi)。n_gens / max_parallel は不変。
    assert m["n_real_subs"] == 79
    assert m["n_junctions"] == 22
    assert m["n_branches"] == 115
    assert m["n_gens"] == 22
    assert m["n_components"] == 7
    assert m["multi_circuit_branches"] == 38
    assert m["max_parallel"] == 5


def test_okinawa_quality_floors(okinawa_topo):
    m = okinawa_topo
    assert m["largest_comp_share"] >= 0.80
    assert m["unknown_kv_share"] <= 0.03
    # circuits/cables tags must keep driving the parallel counts.
    # Floor recalibrated 0.40 -> 0.38 (ledger 85): tip joints and explicit
    # lead-ins are evidence-less single-circuit edges by design, diluting
    # the share (measured 0.3855) without weakening the tag-driven counts.
    assert m["evidenced_circuit_share"] >= 0.38
    # voltage provenance: tags must dominate any inference. The okinawa
    # prop count went 1 -> 0 at ledger 91 (the last untagged segment now
    # joins via its name-claimed tip and merges into the tagged corridor,
    # leaving nothing to propagate) — propagation itself stays covered by
    # the multi-region builds; here we only pin tag dominance.
    assert m["kv_provenance"]["tag"] > m["kv_provenance"].get("prop", 0)


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
    assert s["synthetic_rate"] <= 0.13       # phase-10c: 9/81 = 11.1%
    # full-model okinawa sags to 0.647: voltage propagation typed the
    # northern 66 kV spur (喜瀬/松田) that previously hid at an inferred
    # higher class — honest physics on a long uncompensated radial. The
    # AC product is the backbone model, asserted at >= 0.95 below.
    assert 0.60 < s["ac_vm_min"] <= 1.05


def test_okinawa_backbone_product_quality():
    s = solved_metrics("okinawa", backbone_kv=154.0)
    assert s["dc_converged"] is True and s["ac_converged"] is True
    assert s["ac_vm_min"] >= 0.95            # measured 1.006 (2026-06-10)


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


# ── external-flows sweep level (disclosure CSVs are local-only) ──────────────

def test_external_flow_metrics_skips_unconfigured_region():
    from src.validation.topology_metrics import external_flow_metrics
    assert external_flow_metrics("okinawa") is None


def test_render_and_compare_carry_external_flows():
    row = _row("tokyo", 100, 0.06, True)
    row["external_flows"] = {
        "interior_spearman_rho": 0.473, "trunk_spearman_rho": 0.615,
        "n_interior_trunk": 74, "kv154_spearman_rho": 0.089,
        "n_interior_154": 36, "kv66_spearman_rho": 0.145,
        "n_interior_66": 307,
    }
    out = render([row])
    assert "flows vs disclosure" in out and "0.473" in out

    base = [dict(row, external_flows=dict(row["external_flows"],
                                          kv66_spearman_rho=0.112))]
    diff = compare([row], base)
    assert "kv66_spearman_rho: 0.112 -> 0.145" in diff
    # rows without the level stay silent (CI has no disclosure CSVs)
    plain = _row("tokyo", 100, 0.06, True)
    assert "flows" not in render([plain])


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


def test_no_silent_unsolved_buses_okinawa_and_hokkaido():
    """Every in-service bus must carry a finite AC result. Pandas stats
    skip NaN, which hid hokkaido's 758 slack-stranded buses behind a
    'converged, vm 1.000' headline (ledger 25/26) — n_unsolved_buses
    pins the honest count at zero."""
    for region in ("okinawa", "hokkaido"):
        s = solved_metrics(region)
        assert s["ac_converged"] is True, region
        assert s["n_unsolved_buses"] == 0, region
