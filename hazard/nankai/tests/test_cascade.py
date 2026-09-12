import numpy as np, pandas as pd, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from nankai.grid import GridCase
from nankai.cascade import CascadeModel


def toy_case():
    # 0(G 100MW) -1- 1(L 50) -2- 2(L 50)   ; 3(G 10) -3- 4(L 30)  (別成分・小さいので fragment 扱い)
    bus = pd.DataFrame({"bus_id": [0, 1, 2, 3, 4], "name": ["g", "a", "b", "c", "d"], "site": ["g", "a", "b", "c", "d"],
                        "kv": [154] * 5, "zone": ["x"] * 5, "lat": [34, 34.1, 34.2, 35, 35.1], "lon": [135] * 5,
                        "pd_mw": [0, 50, 50, 0, 30.0], "is_slack": [False] * 5, "is_junction": [False] * 5,
                        "site_id": [0, 1, 2, 3, 4]})
    br = pd.DataFrame({"branch_id": [0, 1, 2], "kind": ["line"] * 3, "f_bus": [0, 1, 3], "t_bus": [1, 2, 4],
                       "x_pu": [0.05, 0.05, 0.05], "cap_mw": [200, 60, 50.0], "parallel": [1, 1, 1], "length_km": [10.0] * 3,
                       "name": ["l1", "l2", "l3"], "in_service": [True] * 3, "kv": [154.0] * 3, "f": [0, 1, 3], "t": [1, 2, 4]})
    gen = pd.DataFrame({"gen_id": [0, 1], "bus_id": [0, 3], "name": ["G1", "G2"], "p_mw": [100.0, 10.0], "pmax_mw": [120.0, 10.0],
                        "in_service": [True, True], "kind": ["gen", "gen"], "b": [0, 3], "cls": ["thermal", "hydro"]})
    return GridCase("toy", bus, br, gen)


def test_balance_and_islanding():
    cm = CascadeModel(toy_case(), fragment_size=2)
    ok = np.ones(5, bool); brok = np.ones(3, bool)
    r = cm.evaluate(ok, brok, np.array([100.0, 10.0]))
    assert np.isclose(r.served_mw[1], 50) and np.isclose(r.served_mw[2], 50)
    assert np.isclose(r.served_mw[4], 10)            # 供給不足 → 比例遮断
    # 線路 l1 が落ちると 1,2 は電源を失う
    r2 = cm.evaluate(ok, np.array([False, True, True]), np.array([100.0, 10.0]))
    assert r2.served_mw[1] == 0 and r2.served_mw[2] == 0
    # 母線 1 が落ちると 2 も孤立
    r3 = cm.evaluate(np.array([True, False, True, True, True]), brok, np.array([100.0, 10.0]))
    assert r3.served_mw[2] == 0 and r3.served_frac[1] == 0


def test_overload_cascade_trips_branch():
    case = toy_case()
    case.branch.loc[1, "cap_mw"] = 10.0             # l2 の容量を 10MW に → 50MW 流れて過負荷
    cm = CascadeModel(case, fragment_size=2, min_component_for_pf=2)
    r = cm.evaluate(np.ones(5, bool), np.ones(3, bool), np.array([100.0, 10.0]))
    assert 1 in r.tripped_branches and r.served_mw[2] == 0
