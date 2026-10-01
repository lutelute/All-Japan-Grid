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


def test_tsunami_cause_keeps_shaking_flag_for_timing():
    """津波で原因が上書きされても、揺れでも止まった発電機・変電所は shake フラグを持つ(停止時刻を津波の到達まで遅らせない)。"""
    import numpy as np
    from nankai.fragility import FragilityModel
    fm = FragilityModel(); rng = np.random.default_rng(1); n = 400
    cls = np.array(["thermal"] * n); pga = np.full(n, 0.8); inten = np.full(n, 6.8); ts = np.full(n, 4)
    out_days, ds, cause = fm.generator_state(cls, pga, inten, ts, rng)
    sh = fm.last_gen_shake
    assert ((cause == 2) & sh).any(), "揺れでも止まり、原因が津波に上書きされた発電機があるはず"
    assert not (sh & (out_days <= 0) & (ds == 0)).any()
    sds, scause = fm.substation_ds(np.full(n, 275.0), pga, ts, rng, intensity=inten)
    assert ((scause == 2) & fm.last_site_shake).any()


def test_ufls_restore_is_staged_conditional_and_rearms_relays():
    """UFLS で切った負荷は、待ち時間の後に、周波数が落ち着いた島で、上げ代と 1 回の上限の範囲で、戻せる母線だけ戻り、その母線の段は再び動く。"""
    import copy
    cfg = copy.deepcopy(CFG)
    load = np.array([300.0, 300.0, 300.0])
    c = FreqCore(cfg, 50.0, ["thermal", "thermal"], [0, 1], [500.0, 400.0], [700.0, 600.0], load)
    c.restorable = np.array([True, True, False])              # 母線 2 は浸水域(戻さない)
    c.shed[:] = 0.3; c.shed_t[:] = 100.0; c.rel_done[:, 0] = True
    rs = dict(after_s=3600, step_s=300, block_mw=90, f_tol_hz=0.2, headroom_margin=0.8)
    c.t = 1000.0
    assert c.restore_ufls(rs) == 0.0                           # まだ待ち時間の中
    c.t = 4000.0; c.df[:] = 0.5
    assert c.restore_ufls(rs) == 0.0                           # 周波数が落ち着いていない
    c.df[:] = 0.0
    got = c.restore_ufls(rs)                                   # 1 回の上限 90 MW: 90 MW の母線 1 つだけ
    assert abs(got - 90.0) < 1e-6 and c.shed[0] == 0.0 and c.shed[1] == 0.3 and not c.rel_done[0, 0] and c.rel_done[1, 0]
    got2 = c.restore_ufls(rs)
    assert abs(got2 - 90.0) < 1e-6 and c.shed[1] == 0.0 and c.shed[2] == 0.3      # 浸水域の母線 2 は戻らない
    assert c.restore_ufls(rs) == 0.0
    assert any(e[1] == "UFLS_restore" for e in c.log)


def test_ufls_restore_partial_when_bus_load_exceeds_block():
    import copy
    c = FreqCore(copy.deepcopy(CFG), 50.0, ["thermal"], [0], [500.0], [900.0], np.array([1000.0]))
    c.shed[:] = 0.3; c.shed_t[:] = 0.0; c.t = 5000.0
    rs = dict(after_s=3600, step_s=300, block_mw=100, f_tol_hz=0.2, headroom_margin=0.8)
    assert abs(c.restore_ufls(rs) - 100.0) < 1e-6 and abs(c.shed[0] - 0.2) < 1e-9      # 300 MW のうち 100 MW だけ戻る
    c.rel_done[0, 0] = True; c.restore_ufls(rs)
    assert c.rel_done[0, 0]                                                              # 一部だけなら段の再使用は完全復電まで待つ


def test_ufls_restore_limited_by_headroom():
    import copy
    cfg = copy.deepcopy(CFG)
    load = np.array([1000.0])
    c = FreqCore(cfg, 50.0, ["thermal"], [0], [500.0], [520.0], load)   # 上げ代 20 MW → 8 割で 16 MW
    c.shed[:] = 0.1; c.shed_t[:] = 0.0; c.t = 5000.0
    rs = dict(after_s=3600, step_s=300, block_mw=500, f_tol_hz=0.2, headroom_margin=0.8)
    assert abs(c.restore_ufls(rs) - 16.0) < 1e-6 and abs(c.shed[0] - 0.084) < 1e-9   # 上げ代 20 MW の 8 割 = 16 MW だけ戻る
