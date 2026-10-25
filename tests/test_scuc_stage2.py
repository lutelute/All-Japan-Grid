"""SCUC stage 2: line cuts injected through model_hook hold, and the lazy check finds what is over.

A made-up line carries the output of the two cheapest units of the synthetic case (G = 1 on them).
"""

import numpy as np
import pytest

pytest.importorskip("pandapower")
from scripts.scuc_stage2 import line_flows, line_hook, violations  # noqa: E402
from src.uc.benchmark_cases import synthetic_case  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402


def solved(params, **kw):
    params.solver_name, params.mip_gap = "HiGHS", 1e-6
    params.solver_options = {"threads": 1}
    for k, v in kw.items():
        setattr(params, k, v)
    return solve_uc(params)


def fake_line(params, ref, share=0.6):
    gens = sorted((g for g in params.generators if not g.is_storage), key=lambda g: g.fuel_cost_per_mwh)[:2]
    units = [g.id for g in params.generators]
    G = np.array([[1.0 if u in {g.id for g in gens} else 0.0 for u in units]])
    T = params.time_horizon.num_periods
    fm = {"mon": np.array([0]), "cap": np.array([1.0]), "units": units, "G": G, "dc": [], "D": np.zeros((1, 0)),
          "C": np.zeros((1, T))}
    fm["cap"] = np.array([share * float(line_flows(fm, ref).max())])
    return {"x": fm}


def test_lazy_cuts_hold_and_cost_more():
    ref_params = synthetic_case(16, 8, 17)
    ref = solved(ref_params)
    fms = fake_line(ref_params, ref)
    over = violations(fms, ref, {})
    assert over, "the made-up limit must bind the unconstrained plan"
    cuts = {key: float(fms["x"]["cap"][0]) for key, _, _ in over}
    params = synthetic_case(16, 8, 17)
    r = solved(params, model_hook=line_hook(fms, cuts, penalty=0))
    assert r.feasibility_verified
    F = line_flows(fms["x"], r)
    for (_, i, t) in cuts:
        assert abs(F[i, t]) <= fms["x"]["cap"][0] + 1e-4
    assert r.total_cost >= ref.total_cost - 1e-6


def test_soft_cuts_charge_the_penalty_for_what_stays_over():
    ref_params = synthetic_case(16, 8, 17)
    ref = solved(ref_params)
    fms = fake_line(ref_params, ref, share=0.0)                    # limit 0: the cheap units stop or pay
    cuts = {key: 0.0 for key, _, _ in violations(fms, ref, {})}
    params = synthetic_case(16, 8, 17)
    r = solved(params, model_hook=line_hook(fms, cuts, penalty=1e4))
    F = line_flows(fms["x"], r)
    over = sum(abs(F[i, t]) for (_, i, t) in cuts)
    assert r.secondary_objective == pytest.approx(r.total_cost + 1e4 * over, rel=1e-6)
