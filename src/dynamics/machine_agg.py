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

近似の明示: フラット運転点(潮流未反映)なので周波数は帯の推定。
運転点込みは次段(収束PFのδ/EでK再評価)。
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
                          freq_hz: float):
    """内部ノード増設+Schur縮約 → (freqs_hz, M, K, order) を返す。

    Y_pu: 系統ベースpuの網Ybus(n×n)。agg['sync']の各機械に内部ノードを立て、
    y_g = 1/(j·xd2·base/S) で接続。K = B_red(フラット近似)。
    """
    n = Y_pu.shape[0]
    sync = agg["sync"]
    m = len(sync)
    if m < 2:
        return np.array([]), None, None, sync
    yg = np.array([1.0 / (1j * s["xd2"] * base_mva / s["S_mva"]) for s in sync])
    buses = np.array([s["bus"] for s in sync], dtype=int)

    # 拡大系 [網+内部]: Y_ll = Y_pu + Σ diag(yg at bus), Y_gg = diag(yg),
    # Y_gl[k, bus_k] = -yg_k
    add = np.zeros(n, dtype=complex)
    for k, b in enumerate(buses):
        add[b] += yg[k]
    Y_ll = (Y_pu + sp.diags(add)).tocsc()
    # 非連結ゼロ行の正則化(SCRマップと同じ流儀)
    dg = np.abs(Y_ll.diagonal())
    if (dg < 1e-9).any():
        Y_ll = (Y_ll + sp.diags(np.where(dg < 1e-9, 1e-6j, 0))).tocsc()
    Y_gl = sp.csr_matrix((-yg, (np.arange(m), buses)), shape=(m, n)).tocsc()
    lu = splu(Y_ll)
    X = lu.solve(Y_gl.T.toarray())            # n×m
    Y_red = np.diag(yg) - (Y_gl @ X)          # m×m (Schur)

    B = np.imag(Y_red)
    K = -B + np.diag(B.sum(axis=1) - np.diag(B))   # フラット近似の同期化トルク
    # K_ij(i≠j) = E_iE_jB_ij cosδij ≈ B_ij → ∂Pe_i/∂δ_j = -B_ij, 対角=Σ_j B_ij
    omega_s = 2 * np.pi * freq_hz
    M = np.array([2.0 * (s["H_mb"] * s["S_mva"] / base_mva) / omega_s
                  for s in sync])
    A = np.linalg.eigvals(np.diag(1.0 / M) @ K)
    lam = np.sort(np.real(A))
    lam = lam[lam > 1e-8]
    freqs = np.sqrt(lam) / (2 * np.pi)
    return freqs, M, K, sync
