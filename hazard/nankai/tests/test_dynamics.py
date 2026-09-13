"""dynamics.FreqCore の単体テスト(物理の式どおりに動くか)。"""
import copy, os
import numpy as np, yaml
from nankai.dynamics import FreqCore, Link

CFG = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "config", "dynamics_default.yaml"), encoding="utf-8"))


def _core(cfg=None, load=1000.0, p=(600.0, 400.0), cls=("thermal", "thermal"), pmax=None):
    cfg = copy.deepcopy(cfg or CFG)
    pmax = pmax or [x * 1.2 for x in p]
    return FreqCore(cfg, 50.0, list(cls), [0] * len(p), list(p), pmax, np.array([load]))


def test_rocof_matches_swing_equation():
    c = _core()
    E = float(c.E.sum())
    c.trip_gens([1])                                   # 400 MW 脱落
    c.step(0.001)
    rocof = c.df[0] / 0.001
    assert abs(rocof - (-50.0 * 400.0 / (2 * (E - c.E[1])))) < 0.05


def test_steady_state_with_governor_and_damping():
    cfg = copy.deepcopy(CFG)
    cfg["ufls"]["stages"] = []                          # UFLS を切って整定値だけ見る
    cfg["governor"]["up_share"]["thermal"] = 0.5        # 上げ代で頭打ちにならないように
    c = _core(cfg, load=1000.0, p=(500.0, 500.0), pmax=[1000.0, 1000.0])
    c.p0[1] -= 20.0                                     # 20 MW の不足
    c.run_until(200.0)
    K = 1000.0 * CFG["load"]["damping_pct_per_hz"]["value"] / 100 + 1000.0 / (0.05 * 50.0)   # D [MW/Hz] + ガバナ(運転中 1 台 pmax 1000 / R) [MW/Hz]
    K += 1000.0 / (0.05 * 50.0)
    assert abs(c.df[0] - (-20.0 / K)) < 0.01


def test_ufls_fires_after_delay_and_resets():
    cfg = copy.deepcopy(CFG)
    cfg["ufls"]["stages"] = [{"ratio": 0.99, "delay_s": [1.0, 1.0], "shed_frac": 0.2, "n_relays": 1}]
    cfg["generator_protection"]["under"] = {"default": {"ratio": 0.0, "delay_s": 1.0}}
    cfg["governor"]["up_share"]["thermal"] = 0.0
    c = _core(cfg)
    c.trip_gens([1]); c.run_until(0.5)
    assert c.shed.max() == 0.0                          # 遅延前は動かない
    c.run_until(5.0)
    assert abs(c.shed.max() - 0.2) < 1e-9               # 遅延後に 20% 遮断


def test_island_without_synchronous_machine_collapses():
    c = _core(cls=("solar", "wind"))
    c.step(0.02)
    assert c.collapsed.all()


def test_external_afc_supports_until_capacity():
    cfg = copy.deepcopy(CFG); cfg["ufls"]["stages"] = []; cfg["governor"]["up_share"]["thermal"] = 0.0
    c = _core(cfg, p=(850.0, 150.0))                    # 150 MW 脱落 > 融通容量 100 MW(崩壊しない大きさ)
    c.links.append(Link("dc", 100.0, "external", np.array([0])))
    c.trip_gens([1]); c.run_until(120.0)
    assert not c.collapsed.any()
    assert abs(c.links[0].flow - 100.0) < 1e-6          # 容量まで受電する
