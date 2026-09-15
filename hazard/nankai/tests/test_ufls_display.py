"""ufls_display: UFLS の遮断量を保ったまま、母線を丸ごと消灯と表示する変換。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np
from nankai.ufls_display import bus_priority, ufls_off_mask


def _case(n=400, seed=0):
    rng = np.random.default_rng(seed)
    load = rng.lognormal(3, 1, n)
    island = np.where(np.arange(n) < 300, 0, 1)
    return load, island, bus_priority([f"b{i}" for i in range(n)])


def test_shed_mw_is_kept_within_one_bus_per_island():
    load, island, pr = _case()
    e = np.where(island == 0, 0.76, 0.85)          # 島 0 は 24%、島 1 は 15% 遮断
    off = ufls_off_mask(e, island, load, pr)
    for k, s in ((0, 0.24), (1, 0.15)):
        m = island == k
        target = s * load[m].sum()
        got = load[m & off].sum()
        assert got >= target - 1e-6 and got - target <= load[m].max() + 1e-6


def test_selection_is_nested_as_shedding_grows():
    load, island, pr = _case()
    a = ufls_off_mask(np.full(len(load), 0.85), island, load, pr)
    b = ufls_off_mask(np.full(len(load), 0.70), island, load, pr)
    assert a.sum() < b.sum() and not (a & ~b).any()      # 15% で消えた母線は 30% でも消えている


def test_no_shedding_and_dead_buses_are_not_selected():
    load, island, pr = _case()
    assert not ufls_off_mask(np.ones(len(load)), island, load, pr).any()
    e = np.full(len(load), 0.7); e[:50] = 0.0                # 受電していない母線は対象外
    off = ufls_off_mask(e, island, load, pr)
    assert not off[:50].any()


def test_priority_is_stable_by_bus_id():
    assert np.array_equal(bus_priority(["x", "y"]), bus_priority(["x", "y"]))
