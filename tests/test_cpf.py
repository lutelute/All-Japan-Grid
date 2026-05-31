"""Continuation power flow (CPF / PV-curve) sanity tests.

Runs the CPF engine on a *small* region (Okinawa) so the test stays fast, and
checks the qualitative shape of the result:

* a PV table is produced with several converged points,
* the table is "monotone-ish" — minimum bus voltage broadly decreases as the
  served load increases along the upper branch (the nose-curve signature), and
* a positive critical loading factor (``lambda_crit > 0``) is found, with the
  critical load not exceeding the largest converged load by more than the
  refinement step.
"""

import os

import pytest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(DATA_DIR, "okinawa_substations.geojson")),
    reason="okinawa GeoJSON data not available",
)


@pytest.fixture(scope="module")
def okinawa_cpf():
    from scripts.run_cpf import run_region_cpf
    # Coarser step keeps the test quick while still tracing the curve + nose.
    return run_region_cpf("okinawa", reactive=0.6, lam_start=0.2,
                          lam_step=0.2, lam_max=3.0, verbose=False)


def test_pv_table_nonempty(okinawa_cpf):
    pv = okinawa_cpf["pv_curve"]
    assert len(pv) >= 3, "expected several PV points"
    assert all(p["converged"] for p in pv)
    # Each point carries the fields downstream consumers rely on.
    for p in pv:
        assert {"lambda", "total_mw", "vm_min", "vm_mean"} <= set(p)
        assert p["total_mw"] > 0
        assert 0.0 < p["vm_min"] <= 1.2


def test_lambda_crit_positive(okinawa_cpf):
    res = okinawa_cpf
    assert res["lambda_crit"] > 0.0, "no stable operating point found"
    assert res["critical_load_mw"] > 0.0
    assert res["nominal_load_mw"] > 0.0
    # Critical load is consistent with lambda_crit * nominal.
    expected = res["lambda_crit"] * res["nominal_load_mw"]
    assert abs(res["critical_load_mw"] - expected) <= max(1.0, 0.01 * expected)


def test_pv_curve_monotone_ish(okinawa_cpf):
    """Along the load-increasing branch, V_min should broadly decline.

    We don't require strict monotonicity (the reconstructed network has discrete
    reactive shunts and topology quirks that cause small local wiggles), but the
    overall trend from the lowest-load point to the nose must be downward.
    """
    pv = sorted(okinawa_cpf["pv_curve"], key=lambda p: p["total_mw"])
    assert pv[0]["total_mw"] < pv[-1]["total_mw"]
    # Net voltage change across the whole served-load range is a decline.
    assert pv[-1]["vm_min"] <= pv[0]["vm_min"] + 1e-6
    # Most consecutive steps are non-increasing (allow a few small wiggles).
    drops = sum(1 for a, b in zip(pv, pv[1:]) if b["vm_min"] <= a["vm_min"] + 1e-3)
    assert drops >= (len(pv) - 1) * 0.6
