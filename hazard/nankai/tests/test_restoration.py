import numpy as np, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from nankai.restoration import RestorationModel
from nankai.fragility import FragilityModel, p_exceed


def test_schedule_respects_crews_and_priority():
    rm = RestorationModel({"crews": {"base": {"z": 2}, "mutual_aid_factor": 1.0, "mutual_aid_start_d": 1e9},
                           "substation": {"ds": {}}, "line": {"ds": {}}, "generator": {"ds": {}},
                           "priority": [], "generation_availability": {}, "timeline_days": [0]})
    jobs = [{"id": i, "zone": "z", "kv": kv, "load_mw": 1, "duration_d": 1.0} for i, kv in enumerate([66, 500, 154, 275])]
    done = rm.schedule(jobs, np.random.default_rng(0))
    assert done[1] == 1.0 and done[3] == 1.0      # 500kV, 275kV が先(2班)
    assert done[2] == 2.0 and done[0] == 2.0


def test_fragility_monotone():
    p = p_exceed(np.array([0.05, 0.2, 0.5, 1.0]), 0.3, 0.5)
    assert np.all(np.diff(p) > 0) and p[0] < 0.01 and p[-1] > 0.98
    fm = FragilityModel()
    rng = np.random.default_rng(0)
    ds, cause = fm.substation_ds(np.array([66.0] * 2000 + [500.0] * 2000), np.array([0.05] * 2000 + [0.8] * 2000), np.zeros(4000, int), rng)
    assert (ds[:2000] >= 3).mean() < 0.02 and (ds[2000:] >= 3).mean() > 0.2
