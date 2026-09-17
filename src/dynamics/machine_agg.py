"""G_DB第一歩: 機械集約と古典モデルの正しい組立て(2026-08-17 オーナー「両方並列で」).

背景: swing_solver.from_pandapower は全機械に H_default=5s を与えるため、
FITの極小機(中央値0.05MW)が慣性アーティファクトを生み、電気機械モード
(0.2〜2.5Hz)が非物理な高周波モードに埋もれた(grid_strength_phase0レポート)。

本モジュール:
  1. aggregate_machines(net): net.gen をバス単位に集約。燃料種(net.gen.type)から
     型式判定 — 同期機は容量加重H(機械ベース)とxd″並列合成、インバータ(IBR)は
     動揺方程式から除外して別勘定(Phase 2のIBR層)。
  2. build_classical_model(Y_pu, agg, base_mva): 各同期機に内部ノード
     (y=1/(j·xd″_sys))を増設し、Schur補元で内部ノードへKron縮約。
     M=2H_sys/ωs(H_sys=H_mb·S/base=系統ベース換算・機械規模に比例)、
     K≈B_red(フラット近似・E=1, δ=0)で M⁻¹K の固有値から
     電気機械モード周波数を推定する。

近似の明示: build_classical_model はフラット運転点(潮流未反映)なので周波数は帯の推定。
**運転点込みは build_classical_model_ac(2026-09-02 トラックC③)**: 収束 AC 解
(res_bus V∠θ・res_gen P,Q)から古典機の内部電圧 E∠δ = V + j·xd″_sys·I を組み、
負荷・IBR・静的注入を運転点の定アドミタンスに変換した拡大網を内部ノードへ Schur 縮約、
K = ∂Pe/∂δ を運転点で評価する。運転点で Pe(δ0) = Pm が機械精度で成立する
(tests/test_swing_ac_operating_point.py がゲート)。
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu

# 燃料種 → (H[機械ベースs], xd''[pu機械ベース], IBRか)
# 典型値: IEEJ標準モデル/教科書帯。未知の小容量はFIT=IBR扱い(閾値2MW)
TYPE_PARAMS = {
    "nuclear": (6.0, 0.25, False),
    "coal": (5.0, 0.22, False),
    "gas": (5.5, 0.22, False),
    "lng": (5.5, 0.22, False),
    "oil": (4.5, 0.22, False),
    "hydro": (3.5, 0.25, False),
    "pumped_storage": (3.5, 0.25, False),
    "pumped-storage": (3.5, 0.25, False),
    "geothermal": (4.0, 0.22, False),
    "biomass": (4.0, 0.22, False),
    "waste": (4.0, 0.22, False),
    "solar": (0.0, 0.0, True),
    "photovoltaic": (0.0, 0.0, True),
    "wind": (0.0, 0.0, True),
    "battery": (0.0, 0.0, True),
}
SMALL_IBR_MW = 2.0     # 型式不明かつこれ未満はFIT由来IBRとみなす(帳簿に明示)


def classify(fuel, cap_mw: float):
    f = str(fuel or "").strip().lower()
    if f in TYPE_PARAMS:
        return TYPE_PARAMS[f]
    if cap_mw < SMALL_IBR_MW:
        return (0.0, 0.0, True)
    return (4.5, 0.25, False)      # 不明・中大型 → 同期機典型


def aggregate_machines(net) -> dict:
    """バス単位の同期機集約とIBR勘定。

    Returns: {'sync': [{bus,S_mva,H_mb,xd2,P_mw}], 'ibr': {bus: S_mva},
              'stats': {...}}
    """
    sync: dict[int, dict] = {}
    ibr: dict[int, float] = {}
    n_ibr = n_sync = 0
    for _, g in net.gen.iterrows():
        cap = float(g.get("max_p_mw") or g.get("p_mw") or 0.0)
        if cap <= 0:
            continue
        H, xd2, is_ibr = classify(g.get("type"), cap)
        b = int(g["bus"])
        if is_ibr:
            ibr[b] = ibr.get(b, 0.0) + cap
            n_ibr += 1
            continue
        n_sync += 1
        s = sync.setdefault(b, {"bus": b, "S_mva": 0.0, "_HS": 0.0,
                                "_invx": 0.0, "P_mw": 0.0})
        s["S_mva"] += cap
        s["_HS"] += H * cap
        s["_invx"] += cap / max(xd2, 1e-3)     # 並列合成(機械ベース→共通換算)
        s["P_mw"] += float(g.get("p_mw") or 0.0)
    out = []
    for s in sync.values():
        S = s["S_mva"]
        out.append({"bus": s["bus"], "S_mva": S, "H_mb": s["_HS"] / S,
                    "xd2": S / s["_invx"], "P_mw": s["P_mw"]})
    return {"sync": out, "ibr": ibr,
            "stats": {"n_machines_sync": n_sync, "n_machines_ibr": n_ibr,
                      "n_sync_buses": len(out),
                      "S_sync_mva": round(sum(o["S_mva"] for o in out)),
                      "S_ibr_mva": round(sum(ibr.values()))}}


def build_classical_model(Y_pu: sp.spmatrix, agg: dict, base_mva: float,
                          freq_hz: float, legacy_diag: bool = False):
    """内部ノード増設+Schur縮約 → (freqs_hz, M, K, order) を返す。

    Y_pu: 系統ベースpuの網Ybus(n×n)。agg['sync']の各機械に内部ノードを立て、
    y_g = 1/(j·xd2·base/S) で接続。K = B_red(フラット近似)。
    """
    sync = agg["sync"]
    m = len(sync)
    if m < 2:
        return np.array([]), None, None, sync
    yg = np.array([1.0 / (1j * s["xd2"] * base_mva / s["S_mva"]) for s in sync])
    buses = np.array([s["bus"] for s in sync], dtype=int)
    Y_red = _schur_to_internal(Y_pu.tocsc(), yg, buses)   # 内部ノードへ Schur 縮約

    # フラット近似(E=1, δ=0, G 無視)の同期化トルク: K_ij = −B_ij (i≠j), K_ii = Σ_{j≠i} B_ij
    # (∂Pe_i/∂δ_i = Σ_{j≠i} E_iE_j B_ij cos δ_ij → δ=0 で Σ_{j≠i} B_ij。行和ゼロ=剛体回転モード)
    # 2026-09-02 修正: 従来は K = −B + diag(ΣB − B_ii) で対角に −B_ii が余分に乗り、
    # 剛体回転モードが消えて周波数が上振れしていた(08-17 の帯は旧式・台帳に記録)。
    # legacy_diag=True で旧式を再現できる(比較用)。
    B = np.imag(Y_red)
    if legacy_diag:
        K = -B + np.diag(B.sum(axis=1) - np.diag(B))
    else:
        K = -B.copy()
        np.fill_diagonal(K, 0.0)
        np.fill_diagonal(K, -K.sum(axis=1))
    omega_s = 2 * np.pi * freq_hz
    M = np.array([2.0 * (s["H_mb"] * s["S_mva"] / base_mva) / omega_s
                  for s in sync])
    A = np.linalg.eigvals(np.diag(1.0 / M) @ K)
    lam = np.sort(np.real(A))
    lam = lam[lam > 1e-8]
    freqs = np.sqrt(lam) / (2 * np.pi)
    return freqs, M, K, sync


# ═══════════════════════════════════════════════════════════════════════════
#  運転点込み古典モデル(2026-09-02 トラックC③) — AC 収束解から E∠δ と K を組む
# ═══════════════════════════════════════════════════════════════════════════
D_MB_DEFAULT = 2.0      # 減衰係数の仮定値 [pu トルク / pu 速度偏差, 機械ベース]。
                        # 古典モデルの D は AVR/PSS/ガバナ/負荷の周波数依存の総和の
                        # 代理であり実測ではない — 減衰比は帯の目安(台帳に明記)。
COMMITTED_MIN_MW = 0.5  # |P| がこれ未満の機械は「停止(非同期)」として動揺系から外す


def _schur_to_internal(Y_ll: sp.spmatrix, yg: np.ndarray,
                       buses: np.ndarray) -> np.ndarray:
    """網 Y_ll(n×n, 機械のテブナン枝は未加算)に内部ノードを増設して Schur 縮約。

    拡大系 [網+内部]: Y_ll' = Y_ll + Σ diag(yg@bus), Y_gg = diag(yg),
    Y_gl[k, bus_k] = -yg_k。返り値 Y_red(m×m) = Y_gg - Y_gl Y_ll'^-1 Y_lg。
    build_classical_model(フラット)と build_classical_model_ac の共通部。
    """
    n = Y_ll.shape[0]
    m = len(yg)
    add = np.zeros(n, dtype=complex)
    for k, b in enumerate(buses):
        add[b] += yg[k]
    Y_aug = (Y_ll + sp.diags(add)).tocsc()
    dg = np.abs(Y_aug.diagonal())
    if (dg < 1e-9).any():                      # 非連結ゼロ行の正則化
        Y_aug = (Y_aug + sp.diags(np.where(dg < 1e-9, 1e-6j, 0))).tocsc()
    Y_gl = sp.csr_matrix((-yg, (np.arange(m), buses)), shape=(m, n)).tocsc()
    lu = splu(Y_aug)
    X = lu.solve(Y_gl.T.toarray())             # n×m
    return np.diag(yg) - (Y_gl @ X)            # m×m


def synchronising_torque(Y_red: np.ndarray, E: np.ndarray) -> np.ndarray:
    """K_ij = ∂Pe_i/∂δ_j を運転点 E∠δ で評価する(古典モデル・ベクトル化)。

    Pe_i = Σ_j |E_i||E_j| [G_ij cos δ_ij + B_ij sin δ_ij], δ_ij = δ_i − δ_j
    ∂Pe_i/∂δ_j (j≠i) = |E_i||E_j| [G_ij sin δ_ij − B_ij cos δ_ij]
    ∂Pe_i/∂δ_i        = −Σ_{j≠i} ∂Pe_i/∂δ_j
    フラット(G=0, δ=0, |E|=1)では build_classical_model の K = −B + diag(ΣB) に一致。
    """
    Em, dl = np.abs(E), np.angle(E)
    G, B = Y_red.real, Y_red.imag
    dij = dl[:, None] - dl[None, :]
    K = (Em[:, None] * Em[None, :]) * (G * np.sin(dij) - B * np.cos(dij))
    np.fill_diagonal(K, 0.0)
    np.fill_diagonal(K, -K.sum(axis=1))
    return K


def electrical_power(Y_red: np.ndarray, E: np.ndarray) -> np.ndarray:
    """Pe = Re(E ∘ conj(Y_red E)) [pu]。内部ノード網の出力(古典モデル)。"""
    return np.real(E * np.conj(Y_red @ E))


def _internal_bus_index(net) -> tuple[np.ndarray, np.ndarray, sp.csc_matrix, float]:
    """pandapower 解き済み net から (lookup pd→ppci, V_int, Y_int, base_mva) を取る。

    lookup は非通電・孤立バスで無効(-1 か範囲外)になり得るので、呼び手は
    V_int の有限性と範囲で弾く。整合は |V_int[lookup[b]]| == res_bus.vm_pu[b] で
    検証できる(テストがゲート)。
    """
    ppc = net._ppc
    internal = ppc["internal"]
    Y = internal["Ybus"]
    Y = Y.tocsc() if sp.issparse(Y) else sp.csc_matrix(Y)
    V = np.asarray(internal["V"], dtype=complex)
    base = float(ppc["baseMVA"])
    lookup = np.asarray(net._pd2ppc_lookups["bus"], dtype=int)
    return lookup, V, Y, base


def _main_component_mask(Y: sp.spmatrix) -> np.ndarray:
    import scipy.sparse.csgraph as csg
    pattern = (abs(Y) > 0).astype(np.int8)
    _n, labels = csg.connected_components(pattern, directed=False)
    big = np.bincount(labels).argmax()
    return labels == big


def build_classical_model_ac(net, freq_hz: float, *, committed_only: bool = True,
                             slack_mode: str = "admittance",
                             D_mb: float = D_MB_DEFAULT,
                             main_component_only: bool = True,
                             capability_check: bool = True,
                             exclude_buses=None) -> dict:
    """収束 AC 解 net(pp.runpp 済み・res_* 有り)から運転点込み古典モデルを組む。

    手順(全て運転点の値・捏造なし):
      1. 内部順序の網 Ybus(シャント込み)と V∠θ を取る
      2. 負荷(res_load)・静的注入(res_sgen)・IBR に分類された gen(res_gen)・
         slack(slack_mode="admittance" のとき res_ext_grid)を運転点の定アドミタンス
         y = conj(S)/|V|² として Ybus に加算(古典モデルの標準的扱い)
      3. 同期機(TYPE_PARAMS で非 IBR)をバス単位に集約: S_mva(容量)・H_mb(容量加重)・
         xd″(並列合成)。committed_only=True なら |P| ≥ COMMITTED_MIN_MW の機械だけ
         (停止機は動揺系にいない)。main_component_only=True なら網の最大連結成分の
         機械だけ(断片は別の同期系)
      4. 内部ノード増設 + Schur 縮約 → Y_red(m×m)
      5. E_k = V_k + j·xd″_sys·I_k, I_k = conj(S_k/V_k), Pm_k = P_k(pu)
      6. K = ∂Pe/∂δ(運転点)、M = 2H_sys/ωs、D = D_mb·(S/base)/ωs [pu/(rad/s)]

    exclude_buses: 古典機として組まない pd バス集合(注入は定アドミタンスへ)。過渡で失歩した
      弱連系機を外して「残りの同期系」を評価する等の感度用。件数を台帳 n_excluded_by_caller に出す
    capability_check=True: 運転点の皮相電力 |P+jQ| が銘板 S_mva を超える機械(**gen 行ごとに判定**)
      (Q 制限なしの PV 母線が小型機に数百 MVar を吸わせる PF 側の artifact —
      2026-09-02 west 実測: 本巣市 50MVA が −564MVar 等)は古典機として組まず定アドミタンスへ。
      内部電圧が非物理(|E|≪1 や K_ii<0=負の同期化トルク)になるため。件数と MVar を台帳に出す
    slack_mode: "admittance"(既定・slack 注入を定アドミタンスに) /
                "fold"(同一バスの同期機へ P,Q を合算・慣性は機械分のまま) /
                "infinite"(H=1e6 s の無限大母線として機械列に追加)
    Returns dict: Y_red, E, Pm, M, D, K, sync(list of dict: bus, name, zone, S_mva,
      H_mb, xd2, P_mw, Q_mvar), base_mva, omega_s, stats(帳簿)
    """
    if slack_mode not in ("admittance", "fold", "infinite"):
        raise ValueError("slack_mode は admittance/fold/infinite")
    lookup, V, Y, base = _internal_bus_index(net)
    n = Y.shape[0]
    omega_s = 2.0 * np.pi * freq_hz

    def int_idx(pd_bus: int):
        i = int(lookup[int(pd_bus)]) if 0 <= int(pd_bus) < len(lookup) else -1
        if i < 0 or i >= n or not np.isfinite(V[i]) or abs(V[i]) < 0.1:
            return None
        return i

    in_main = _main_component_mask(Y) if main_component_only else np.ones(n, bool)

    # ── 2. 運転点の定アドミタンス(負荷・静的注入・IBR・slack) ──
    y_add = np.zeros(n, dtype=complex)
    ledger = {"load_mw": 0.0, "sgen_mw": 0.0, "ibr_gen_mw": 0.0, "slack_mw": 0.0,
              "n_load": 0, "n_sgen": 0, "n_ibr_gen": 0, "n_slack": 0}

    def add_injection(pd_bus, p_mw, q_mvar):
        """注入(発電が正)を定アドミタンスへ: 消費 S_L = -(P+jQ) → y = conj(S_L)/|V|²"""
        i = int_idx(pd_bus)
        if i is None or not (np.isfinite(p_mw) and np.isfinite(q_mvar)):
            return False
        S_load = -(p_mw + 1j * q_mvar) / base
        y_add[i] += np.conj(S_load) / (abs(V[i]) ** 2)
        return True

    for li, r in net.load.iterrows():
        if not bool(r.get("in_service", True)):
            continue
        rl = net.res_load.loc[li] if li in net.res_load.index else None
        p = float(rl["p_mw"]) if rl is not None else float(r["p_mw"])
        q = float(rl["q_mvar"]) if rl is not None else float(r["q_mvar"])
        if add_injection(r["bus"], -p, -q):
            ledger["load_mw"] += p
            ledger["n_load"] += 1
    if len(net.sgen):
        for si, r in net.sgen.iterrows():
            if not bool(r.get("in_service", True)):
                continue
            rs = net.res_sgen.loc[si]
            if add_injection(r["bus"], float(rs["p_mw"]), float(rs["q_mvar"])):
                ledger["sgen_mw"] += float(rs["p_mw"])
                ledger["n_sgen"] += 1

    # ── 3. 同期機の集約(IBR は定アドミタンスへ) ──
    acc: dict[int, dict] = {}
    n_off = n_frag = n_over = n_excl = 0
    excl = {int(b) for b in (exclude_buses or ())}
    for gi, g in net.gen.iterrows():
        if not bool(g.get("in_service", True)):
            continue
        cap = float(g.get("max_p_mw") or g.get("p_mw") or 0.0)
        rg = net.res_gen.loc[gi]
        P, Q = float(rg["p_mw"]), float(rg["q_mvar"])
        b = int(g["bus"])
        if cap <= 0:
            # 容量ゼロの gen も PV 母線として Q を出している(運転点の一部) → 定アドミタンスへ。
            # 黙って落とすと平衡が崩れる(2026-09-02 west 実測: 藤生町 220kV で 28.6MVar)
            if add_injection(b, P, Q):
                ledger["zero_cap_gen_mvar"] = ledger.get("zero_cap_gen_mvar", 0.0) + Q
                ledger["n_zero_cap_gen"] = ledger.get("n_zero_cap_gen", 0) + 1
            continue
        H, xd2, is_ibr = classify(g.get("type"), cap)
        if is_ibr:
            if add_injection(b, P, Q):
                ledger["ibr_gen_mw"] += P
                ledger["n_ibr_gen"] += 1
            continue
        i = int_idx(b)
        if i is None:
            continue
        if not in_main[i]:
            n_frag += 1
            add_injection(b, P, Q)       # 断片は別の同期系 — その注入は断片側の定アドミタンスに
            continue
        if committed_only and abs(P) < COMMITTED_MIN_MW:
            # 停止機(P≈0)は動揺系から外すが、PV 母線として出している Q は運転点の
            # 一部なので定アドミタンス(同期調相機相当)として網に残す — 外すと平衡が崩れる
            n_off += 1
            add_injection(b, P, Q)
            ledger["off_gen_mvar"] = ledger.get("off_gen_mvar", 0.0) + Q
            continue
        if capability_check and abs(P + 1j * Q) > cap:
            # 銘板超過の運転点(Q 制限なし PF が小型機に数百 MVar を負わせる artifact)。
            # 古典機の内部電圧が非物理(|E|≪1・K_ii<0)になるため定アドミタンスへ(平衡は保つ)
            n_over += 1
            add_injection(b, P, Q)
            ledger["over_capability_mvar"] = ledger.get("over_capability_mvar", 0.0) + Q
            continue
        if b in excl:
            n_excl += 1
            add_injection(b, P, Q)
            ledger["excluded_by_caller_mw"] = ledger.get("excluded_by_caller_mw", 0.0) + P
            continue
        s = acc.setdefault(b, {"bus": b, "i": i, "S_mva": 0.0, "_HS": 0.0,
                               "_invx": 0.0, "P_mw": 0.0, "Q_mvar": 0.0,
                               "names": []})
        s["S_mva"] += cap
        s["_HS"] += H * cap
        s["_invx"] += cap / max(xd2, 1e-3)
        s["P_mw"] += P
        s["Q_mvar"] += Q
        nm = str(g.get("name") or "")
        if nm and len(s["names"]) < 3:
            s["names"].append(nm)

    # slack(ext_grid)の扱い
    for ei, r in net.ext_grid.iterrows():
        if not bool(r.get("in_service", True)):
            continue
        re_ = net.res_ext_grid.loc[ei]
        P, Q = float(re_["p_mw"]), float(re_["q_mvar"])
        b = int(r["bus"])
        i = int_idx(b)
        if i is None or not (np.isfinite(P) and np.isfinite(Q)):
            continue
        if slack_mode == "fold" and b in acc:
            acc[b]["P_mw"] += P
            acc[b]["Q_mvar"] += Q
            ledger["slack_mw"] += P
            ledger["n_slack"] += 1
        elif slack_mode == "infinite" and in_main[i]:
            s = acc.setdefault(b, {"bus": b, "i": i, "S_mva": 0.0, "_HS": 0.0,
                                   "_invx": 0.0, "P_mw": 0.0, "Q_mvar": 0.0,
                                   "names": [], "infinite": True})
            S_inf = max(abs(P), base)            # xd″ を base 相当に取る仮想機
            s["S_mva"] += S_inf
            s["_HS"] += 1e6 * S_inf              # H = 1e6 s → 動かない基準
            s["_invx"] += S_inf / 0.1
            s["P_mw"] += P
            s["Q_mvar"] += Q
            ledger["slack_mw"] += P
            ledger["n_slack"] += 1
        else:
            if add_injection(b, P, Q):
                ledger["slack_mw"] += P
                ledger["n_slack"] += 1

    sync = []
    for s in list(acc.values()):
        S = s["S_mva"]
        sync.append({"bus": s["bus"], "i": s["i"], "S_mva": S,
                     "H_mb": s["_HS"] / S, "xd2": S / s["_invx"],
                     "P_mw": s["P_mw"], "Q_mvar": s["Q_mvar"],
                     "name": " / ".join(s["names"]) or str(net.bus.at[s["bus"], "name"]),
                     "zone": (str(net.bus.at[s["bus"], "zone"])
                              if "zone" in net.bus.columns else None),
                     "vn_kv": float(net.bus.at[s["bus"], "vn_kv"]),
                     "infinite": bool(s.get("infinite", False))})
    m = len(sync)
    stats = {"n_sync_buses": m, "n_gen_off_excluded": n_off,
             "n_gen_fragment_excluded": n_frag,
             "n_over_capability_excluded": n_over,
             "n_excluded_by_caller": n_excl,
             "S_sync_mva": round(sum(x["S_mva"] for x in sync if not x["infinite"])),
             "P_sync_mw": round(sum(x["P_mw"] for x in sync)),
             "n_bus_internal": int(n), "n_bus_main": int(in_main.sum()),
             "base_mva": base, "D_mb": D_mb, "slack_mode": slack_mode,
             "committed_only": committed_only, **{k: (round(v, 1) if isinstance(v, float) else v)
                                                  for k, v in ledger.items()}}
    if m < 2:
        stats["pe_pm_mismatch_pu_max"] = 0.0
        return {"Y_red": np.zeros((m, m), complex), "E": np.zeros(m, complex),
                "Pm": np.zeros(m), "M": np.zeros(m), "D": np.zeros(m),
                "K": np.zeros((m, m)), "sync": sync, "base_mva": base,
                "omega_s": omega_s, "stats": stats, "y_add": y_add, "V": V,
                "buses": np.zeros(0, dtype=int)}

    # ── 4. 拡大網の縮約 ──
    Y_ll = (Y + sp.diags(y_add)).tocsc()
    xd2_sys = np.array([s["xd2"] * base / s["S_mva"] for s in sync])
    yg = 1.0 / (1j * xd2_sys)
    buses = np.array([s["i"] for s in sync], dtype=int)
    Y_red = _schur_to_internal(Y_ll, yg, buses)

    # ── 5. 内部電圧と機械出力(運転点) ──
    Vk = V[buses]
    Sk = (np.array([s["P_mw"] for s in sync]) + 1j * np.array([s["Q_mvar"] for s in sync])) / base
    Ik = np.conj(Sk / Vk)
    E = Vk + 1j * xd2_sys * Ik
    Pm = np.real(Sk)

    # ── 6. 線形化 ──
    K = synchronising_torque(Y_red, E)
    M = np.array([2.0 * (s["H_mb"] * s["S_mva"] / base) / omega_s for s in sync])
    # D: swing_solver の右辺は D·Δω [Δω は rad/s] なので、機械ベースの pu 減衰係数
    # D_mb [pu トルク / pu 速度偏差] を系統ベース・rad/s 単位へ: D = D_mb·(S/base)/ωs
    D = np.array([D_mb * s["S_mva"] / base / omega_s for s in sync])
    Pe0 = electrical_power(Y_red, E)
    stats["pe_pm_mismatch_pu_max"] = float(np.max(np.abs(Pe0 - Pm)))
    return {"Y_red": Y_red, "E": E, "Pm": Pm, "M": M, "D": D, "K": K,
            "sync": sync, "base_mva": base, "omega_s": omega_s, "stats": stats,
            "y_add": y_add, "V": V, "buses": buses}


def electromechanical_modes(M: np.ndarray, K: np.ndarray, D=None,
                            participation_top: int = 5) -> list[dict]:
    """A = [[0, I], [−M⁻¹K, −M⁻¹D]] の固有解析 → 振動モード(共役対の片側)。

    返り値の各要素: f_hz, zeta(減衰比), sigma, participants(参加率上位の機械index),
    participation(全機械の正規化参加率 δ+ω)、shape(δ 右固有ベクトル・最大成分を
    実正に回転した実部・|max|=1 正規化)。D=None なら無減衰(ζ=0)。
    """
    n = len(M)
    Minv = np.diag(1.0 / M)
    Dm = np.diag(np.zeros(n) if D is None else np.asarray(D, float))
    A = np.block([[np.zeros((n, n)), np.eye(n)],
                  [-Minv @ np.asarray(K, float), -Minv @ Dm]])
    lam, Phi = np.linalg.eig(A)
    Psi = np.linalg.inv(Phi)
    out = []
    for k in range(len(lam)):
        w = lam[k].imag
        if w <= 1e-9:
            continue
        pf = np.abs(Phi[:n, k] * Psi[k, :n]) + np.abs(Phi[n:, k] * Psi[k, n:])
        pf = pf / max(pf.max(), 1e-300)
        vd = Phi[:n, k]
        j = int(np.argmax(np.abs(vd)))
        vd = vd * np.exp(-1j * np.angle(vd[j]))
        shape = np.real(vd) / max(np.abs(vd).max(), 1e-300)
        out.append({"f_hz": float(w / (2 * np.pi)),
                    "zeta": float(-lam[k].real / abs(lam[k])),
                    "sigma": float(lam[k].real),
                    "participants": [int(i) for i in np.argsort(pf)[::-1][:participation_top]],
                    "participation": pf, "shape": shape})
    out.sort(key=lambda d: d["f_hz"])
    return out


def mode_band(f_hz: float) -> str:
    """慣用の帯: inter-area 0.1〜0.8Hz / local 0.8〜2.5Hz / それ以外は帯外。"""
    if 0.1 <= f_hz < 0.8:
        return "inter-area"
    if 0.8 <= f_hz <= 2.5:
        return "local"
    return "out-of-band"
