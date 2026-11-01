"""行列ペンシル法(HUA1990)で、等間隔の信号を減衰する正弦の和に当てはめる。

y[k] ≈ Σ_i R_i z_i^k、z_i = exp(s_i Δt)、s_i = σ_i + j2πf_i。実数の信号では f_i が ± の組で出る。
雑音の無い数値積分の結果に使う前提で、特異値の打ち切りは相対値で決める。
"""
from __future__ import annotations

import numpy as np


def matrix_pencil(y: np.ndarray, dt: float, n_modes: int = 12, rel_tol: float = 1e-7) -> list:
    """[(f_hz, sigma, amp)] を振幅の大きい順に返す。f は 0 以上の側だけ。"""
    y = np.asarray(y, dtype=float)
    n = y.size
    lp = n // 3
    hank = np.lib.stride_tricks.sliding_window_view(y, lp + 1)
    _, sv, vh = np.linalg.svd(hank, full_matrices=False)
    m = int(min(n_modes, np.sum(sv > rel_tol * sv[0])))
    v = vh[:m].conj().T
    v1, v2 = v[:-1], v[1:]
    z = np.linalg.eigvals(np.linalg.pinv(v1) @ v2)
    s = np.log(z) / dt
    vander = z[None, :] ** np.arange(n)[:, None]
    amp = np.linalg.lstsq(vander, y.astype(complex), rcond=None)[0]
    out = []
    for si, ai in zip(s, amp):
        if si.imag >= 0:
            a = 2 * abs(ai) if si.imag > 1e-9 else abs(ai)
            out.append((float(si.imag / (2 * np.pi)), float(si.real), float(a)))
    out.sort(key=lambda x: -x[2])
    return out
