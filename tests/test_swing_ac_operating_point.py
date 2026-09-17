"""運転点込み古典モデル(トラックC③ 2026-09-02)のゲート。

  1. AC 収束解から組んだ E∠δ が運転点で平衡(Pe(δ0) = Pm・1e-6 pu)であること
  2. pandapower 内部順序への写像(lookup)が res_bus と整合すること(内部仕様の前提を固定)
  3. フラット経路(build_classical_model)が K_ij=−B_ij, K_ii=Σ_{j≠i}B_ij(行和ゼロ)であり、
     旧式(対角 −B_ii 余分・08-17 の帯)が legacy_diag=True で再現できること
  4. xd″ の機械ベース→系統ベース換算(E = V + j·xd″_sys·I)の単位ゲート
  5. swing_solver のベクトル化が二重ループ式と一致すること(後方互換)
  6. 解列(disconnect)が内部ノードの Kron 消去と一致し、残存機だけで安定判定すること
  7. モード解析の 2 質点検算
実データを使わない小系統なので速い。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

pp = pytest.importorskip("pandapower")

from src.dynamics import machine_agg as ma  # noqa: E402
from src.dynamics.swing_solver import GenDyn, SwingModel, run_transient  # noqa: E402


def _three_bus():
    """bus0: slack / bus1: ガス機 500MW / bus2: 石炭機 800MW。負荷は 1,2 に。"""
    net = pp.create_empty_network(sn_mva=100.0)
    b0 = pp.create_bus(net, vn_kv=275.0, name="slack275", zone="kansai")
    b1 = pp.create_bus(net, vn_kv=275.0, name="gas275", zone="kansai")
    b2 = pp.create_bus(net, vn_kv=275.0, name="coal275", zone="chugoku")
    for a, b, km in ((b0, b1, 40.0), (b1, b2, 80.0), (b0, b2, 120.0)):
        pp.create_line_from_parameters(net, a, b, length_km=km, r_ohm_per_km=0.03,
                                       x_ohm_per_km=0.3, c_nf_per_km=10.0, max_i_ka=2.0)
    pp.create_ext_grid(net, bus=b0, vm_pu=1.02, name="slack_0")
    pp.create_gen(net, bus=b1, p_mw=300.0, vm_pu=1.01, max_p_mw=500.0, name="ガス火力",
                  type="gas")
    pp.create_gen(net, bus=b2, p_mw=450.0, vm_pu=1.00, max_p_mw=800.0, name="石炭火力",
                  type="coal")
    pp.create_load(net, bus=b1, p_mw=250.0, q_mvar=60.0)
    pp.create_load(net, bus=b2, p_mw=600.0, q_mvar=150.0)
    pp.create_shunt(net, bus=b2, q_mvar=-30.0)          # シャントも Ybus 側に居ること
    pp.runpp(net, numba=False)
    assert net.converged
    return net


def test_lookup_maps_to_internal_voltage():
    net = _three_bus()
    lookup, V, Y, base = ma._internal_bus_index(net)
    assert base == pytest.approx(100.0)
    for b in net.bus.index:
        i = int(lookup[b])
        assert abs(V[i]) == pytest.approx(float(net.res_bus.at[b, "vm_pu"]), abs=1e-9)
        assert math.degrees(np.angle(V[i])) == pytest.approx(
            float(net.res_bus.at[b, "va_degree"]), abs=1e-7)
    assert Y.shape == (3, 3)


@pytest.mark.parametrize("slack_mode,n_expected", [("admittance", 2), ("infinite", 3)])
def test_ac_operating_point_is_an_equilibrium(slack_mode, n_expected):
    """Pe(δ0) = Pm が機械精度で成立(負荷・シャント・slack を運転点で正しく畳めている証拠)。"""
    net = _three_bus()
    cm = ma.build_classical_model_ac(net, 60.0, slack_mode=slack_mode)
    assert len(cm["sync"]) == n_expected
    Pe0 = ma.electrical_power(cm["Y_red"], cm["E"])
    assert np.max(np.abs(Pe0 - cm["Pm"])) < 1e-6, (Pe0, cm["Pm"])
    assert cm["stats"]["pe_pm_mismatch_pu_max"] < 1e-6
    # 機械出力は res_gen と一致(pu)
    by_bus = {s["bus"]: s for s in cm["sync"]}
    for gi, g in net.gen.iterrows():
        assert by_bus[int(g.bus)]["P_mw"] == pytest.approx(float(net.res_gen.at[gi, "p_mw"]))
    # 台帳: 負荷とシャント・slack の計上
    assert cm["stats"]["load_mw"] == pytest.approx(850.0)
    assert cm["stats"]["n_slack"] == 1


def test_xd2_is_converted_to_system_base():
    """E = V + j·xd″_sys·I, xd″_sys = xd″_mb·base/S。ガス 500MVA·0.22 → 0.044 pu@100MVA。"""
    net = _three_bus()
    cm = ma.build_classical_model_ac(net, 60.0)
    k = [i for i, s in enumerate(cm["sync"]) if s["bus"] == 1][0]
    s = cm["sync"][k]
    assert s["xd2"] == pytest.approx(0.22) and s["S_mva"] == pytest.approx(500.0)
    xd2_sys = s["xd2"] * 100.0 / s["S_mva"]
    assert xd2_sys == pytest.approx(0.044)
    vm = float(net.res_bus.at[1, "vm_pu"]); va = math.radians(float(net.res_bus.at[1, "va_degree"]))
    V = vm * np.exp(1j * va)
    S = (float(net.res_gen.at[0, "p_mw"]) + 1j * float(net.res_gen.at[0, "q_mvar"])) / 100.0
    E_expected = V + 1j * xd2_sys * np.conj(S / V)
    assert cm["E"][k] == pytest.approx(E_expected, abs=1e-9)
    # H も系統ベースへ: M = 2·H_mb·S/base/ωs
    assert cm["M"][k] == pytest.approx(2.0 * 5.5 * 5.0 / (2 * np.pi * 60))


def test_flat_path_is_the_zero_angle_limit_and_legacy_diag_is_reproducible():
    """build_classical_model(フラット)は K_ij=−B_ij, K_ii=Σ_{j≠i}B_ij(行和ゼロ・剛体回転モード)。

    E=1∠0 の synchronising_torque と同一。旧式(対角に −B_ii が余分)は legacy_diag=True
    で再現でき、剛体回転モードを失う(=08-17 の帯が上振れしていた機構)。
    """
    net = _three_bus()
    _lookup, _V, Y, base = ma._internal_bus_index(net)
    agg = ma.aggregate_machines(net)
    agg["sync"] = [dict(s, bus=int(_lookup[s["bus"]])) for s in agg["sync"]]
    freqs, M, K, sync = ma.build_classical_model(Y, agg, base, 60.0)
    assert K.shape == (2, 2) and len(freqs) == 1          # 2 機 → 剛体 1 + 振動 1
    yg = np.array([1.0 / (1j * s["xd2"] * base / s["S_mva"]) for s in sync])
    Y_red = ma._schur_to_internal(Y, yg, np.array([s["bus"] for s in sync]))
    B = Y_red.imag
    K_ref = -B.copy(); np.fill_diagonal(K_ref, 0.0); np.fill_diagonal(K_ref, -K_ref.sum(axis=1))
    assert np.allclose(K, K_ref, atol=1e-12)
    assert np.allclose(ma.synchronising_torque(Y_red, np.ones(2, complex)), K_ref, atol=1e-12)
    assert np.allclose(K.sum(axis=1), 0.0, atol=1e-9)
    # 旧式: 対角に −B_ii が余分 → 行和が −B_ii、剛体モードが消えて周波数が上がる
    f_old, _M, K_old, _s = ma.build_classical_model(Y, agg, base, 60.0, legacy_diag=True)
    assert np.allclose(K_old - K, -np.diag(np.diag(B)), atol=1e-12)
    assert len(f_old) == 2 and f_old.max() > freqs.max()


def test_vectorised_swing_solver_matches_loop_formulas():
    rng = np.random.default_rng(7)
    n = 4
    Y = rng.normal(size=(n, n)) + 1j * rng.normal(size=(n, n))
    Y = Y + Y.T
    gens = [GenDyn(bus=i, H=float(rng.uniform(2, 8)), D=float(rng.uniform(0, 3)),
                   E=float(rng.uniform(0.9, 1.2)), delta0=float(rng.uniform(-1, 1)),
                   Pm=float(rng.uniform(0, 2))) for i in range(n)]
    model = SwingModel(gens, Y, omega_s=2 * np.pi * 60, baseMVA=100.0)
    delta = rng.uniform(-1, 1, n)
    Pe_loop = np.zeros(n)
    for i in range(n):
        for j in range(n):
            d = delta[i] - delta[j]
            Pe_loop[i] += gens[i].E * gens[j].E * (Y[i, j].real * np.cos(d) + Y[i, j].imag * np.sin(d))
    assert np.allclose(model._Pe(delta), Pe_loop, atol=1e-12)
    d0 = np.array([g.delta0 for g in gens])
    K_loop = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i == j:
                for k in range(n):
                    if k != i:
                        d = d0[i] - d0[k]
                        K_loop[i, i] += gens[i].E * gens[k].E * (-Y[i, k].real * np.sin(d) + Y[i, k].imag * np.cos(d))
            else:
                d = d0[i] - d0[j]
                K_loop[i, j] = gens[i].E * gens[j].E * (Y[i, j].real * np.sin(d) - Y[i, j].imag * np.cos(d))
    A = model._linearise_A()
    Minv = np.diag([model.omega_s / (2 * g.H) for g in gens])
    assert np.allclose(A[n:, :n], -Minv @ K_loop, atol=1e-10)
    assert np.allclose(A[n:, n:], -Minv @ np.diag([g.D for g in gens]), atol=1e-12)
    assert np.allclose(A[:n, n:], np.eye(n))
    # 従来 trip 経路の右辺も同じ式
    y = np.concatenate([delta, rng.normal(size=n) * 0.1])
    r = model._rhs(0.0, y, trip_idx=2)
    Pm = np.array([g.Pm for g in gens]); Pm[2] = 0.0
    M = np.array([2 * g.H / model.omega_s for g in gens])
    assert np.allclose(r[n:], (Pm - Pe_loop - np.array([g.D for g in gens]) * y[n:]) / M, atol=1e-10)


def test_disconnect_is_kron_elimination_and_excludes_the_machine():
    net = _three_bus()
    cm = ma.build_classical_model_ac(net, 60.0, slack_mode="infinite")
    model = SwingModel.from_classical(cm)
    n = model.n
    idx = int(np.argmax([s["P_mw"] for s in cm["sync"] if not s["infinite"]]))
    Yp = model._post_trip_Y(idx)
    keep = [i for i in range(n) if i != idx]
    Y = np.asarray(cm["Y_red"])
    Y_ref = Y[np.ix_(keep, keep)] - Y[np.ix_(keep, [idx])] @ np.linalg.inv(Y[np.ix_([idx], [idx])]) @ Y[np.ix_([idx], keep)]
    assert np.allclose(Yp[np.ix_(keep, keep)], Y_ref, atol=1e-10)
    assert np.allclose(Yp[idx, :], 0.0) and np.allclose(Yp[:, idx], 0.0)
    # 解列前は平衡(擾乱なし → 角度不変)、解列後は残存機の判定のみ
    res0 = run_transient(model, t_end=0.5, fault="none")
    assert np.max(np.abs(res0.delta[:, -1] - res0.delta[:, 0])) < 1e-4
    res = run_transient(model, t_end=3.0, fault="disconnect", fault_bus=idx, t_fault=0.5, dt=0.02)
    assert res.fault_type == "disconnect"
    assert np.allclose(res.delta[idx, :], res.delta[idx, 0])          # 状態凍結
    assert res.max_angle_sep < np.pi and res.stable                      # 無限大母線つき 3 機は失歩しない
    assert np.isfinite(res.coi_delta).all()


def test_two_mass_mode_check():
    """M=[1,1], K=[[k,−k],[−k,k]] → 振動モード ω = √(2k)。D=None で ζ=0。"""
    k = 4.0
    modes = ma.electromechanical_modes(np.array([1.0, 1.0]), np.array([[k, -k], [-k, k]]))
    assert len(modes) == 1
    assert modes[0]["f_hz"] == pytest.approx(math.sqrt(2 * k) / (2 * math.pi))
    assert abs(modes[0]["zeta"]) < 1e-9
    assert modes[0]["shape"][0] * modes[0]["shape"][1] < 0            # 逆位相
    damped = ma.electromechanical_modes(np.array([1.0, 1.0]), np.array([[k, -k], [-k, k]]),
                                        D=np.array([0.4, 0.4]))
    assert 0 < damped[0]["zeta"] < 1
    assert ma.mode_band(0.4) == "inter-area" and ma.mode_band(1.5) == "local"


def test_off_and_over_capability_machines_stay_in_the_operating_point_as_admittance():
    """停止機(P≈0)と銘板超過機(|S|>S_mva)は古典機から外すが、その注入は定アドミタンスで
    残るので平衡は崩れない(2026-09-02 west 実測で踏んだ 2 つの穴を固定)。"""
    net = _three_bus()
    # bus2 に停止機(P=0・PV で Q を出す)、bus3(20km 線で bus2 に接続・電圧指令 1.04)に
    # 銘板 5MVA なのに電圧維持で大きな Q を負う小型機を足す(Q 制限なし PF の artifact の再現)
    pp.create_gen(net, bus=2, p_mw=0.0, vm_pu=1.00, max_p_mw=300.0, name="停止機", type="oil")
    b3 = pp.create_bus(net, vn_kv=275.0, name="small275", zone="chugoku")
    pp.create_line_from_parameters(net, 2, b3, length_km=20.0, r_ohm_per_km=0.03,
                                   x_ohm_per_km=0.3, c_nf_per_km=10.0, max_i_ka=2.0)
    pp.create_gen(net, bus=b3, p_mw=4.0, vm_pu=1.04, max_p_mw=5.0, name="小型機", type="hydro")
    pp.runpp(net, numba=False)
    assert net.converged
    q_small = float(net.res_gen.at[3, "q_mvar"])
    assert abs(4.0 + 1j * q_small) > 5.0, "テスト前提: 小型機が銘板超過の Q を負っていること"
    cm = ma.build_classical_model_ac(net, 60.0, committed_only=True, capability_check=True)
    names = [s["name"] for s in cm["sync"]]
    assert "停止機" not in " ".join(names) and "小型機" not in " ".join(names)
    assert cm["stats"]["n_gen_off_excluded"] == 1
    assert cm["stats"]["n_over_capability_excluded"] == 1
    assert cm["stats"]["pe_pm_mismatch_pu_max"] < 1e-6      # 外しても平衡は保たれる
    # 全機を古典機にすると小型機は非物理な運転点(|E| が大きく外れる)
    cm2 = ma.build_classical_model_ac(net, 60.0, committed_only=False, capability_check=False)
    k = [i for i, s in enumerate(cm2["sync"]) if "小型機" in s["name"]][0]
    assert not (0.5 < abs(cm2["E"][k]) < 1.5)
    assert cm2["stats"]["pe_pm_mismatch_pu_max"] < 1e-6
