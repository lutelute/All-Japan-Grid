"""静止座標の PR 電流制御の GFL 1 台 + フィーダ・コンデンサ・電源の網 — SSO 第 2 段 段 B(2026-11-01).

公表例 REAL20HZ2022(Fan ほか、IEEE TEC 2022、doi:10.1109/tec.2022.3206795)の試験系統
(Hydro One の 44 kV フィーダの 3 つの太陽光 30 MW を 1 台に集約)を、本文の定数で組む。
段 A(gfl.py)と同じく 3 つの道で解き、本文の数字と突き合わせる:

  道 1  状態空間: 網の dq(ω1 で回る)の非線形の常微分方程式を平衡点で数値的に線形化し、固有値を出す。
  道 2  論文の線形模型(本文の式 (4)〜(15)): 静止座標の G1(s) = Z_grid/(Z_grid + Z_PV)·Z*_PV を
        dq に移した G1R(s) = [G1(s + jω1) + G1(s − jω1)]/2 と PLL の G_PLL(s) で、
        1 − G_PLL(s)·(i_d G1R(s) − i_q G1I(s)) = 0 の零点を出す。道 1 の固有値は種に使わない。
  道 3  時間領域: 静止座標(αβ)で非線形のまま積分し、abc の電流から行列ペンシル法で振動を読む。

単位: 30 MVA を基準にした pu。時間は秒。インダクタンスは pu·s(= x_pu / ω1)、容量は pu·s(= b_pu / ω1)。
空間ベクトルは複素数。電流 i はインバータから網へ向かう向き。

模型(本文の Fig. 4。平均値模型でスイッチングは入れない):
  回路   v ─ チョーク (R, L) ─ PCC ─ フィーダ ─ 変電所の母線(コンデンサ C)─ 電源 Z_g ─ 無限大母線 v_g
  電流   v = T_d(s) [v_pcc + PR(s)(i* − i)]、PR(s) = K_p + K_r 2ω_c s/(s² + 2ω_c s + ω1²)(静止座標)
         T_d(s) = (1 − sτ/2)/(1 + sτ/2)(Padé 1 次)
  PLL    v_q = Im(v_pcc e^{−jθ}) → LPF(1 次か 2 次)→ (K_p + K_i/s) → ω、dθ/dt = ω
  指令   i* = (i_d + j i_q) e^{jθ}(PLL の座標で一定。外側の制御は本文の線形模型と同じく入れない)
  外側   outer = "pq" か "pv" で足せる(段 B の続き)。本文の PI 0.2 + 20/s で、P と Q、または P と |v_pcc| を
         指令に保つ。測る量の濾波器は本文に書いていないので f_meas で選ぶ(0 は濾波しない。v_pcc が指令に
         よるので代数ループを解く)。
  制限   i_max(電流の指令の大きさ)・v_max(変換器の電圧の指令の大きさ = 変調の飽和)・df_max(PLL の周波数の
         偏差。積分は止める)。既定は無し(本文の EMT は PLL の制限を入れていない、本文 IV-C の Remarks)。

平衡点は PCC の電圧の大きさを v_pcc(既定 1 pu)に合わせ、無限大母線の電圧 v_g をそこから決める
(本文の線形模型は G_PLL を |v_pcc| = 1 で書いている)。
"""
from __future__ import annotations

import dataclasses
import math
from typing import Optional

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq, fsolve

from .gfl import _secant
from .pencil import matrix_pencil


@dataclasses.dataclass(frozen=True)
class PRParams:
    f0: float = 60.0
    # 回路(本文の Fig. 4 の説明。30 MVA 基準)
    r_f: float = 0.015          # チョーク
    x_f: float = 0.15
    r_feed: float = 0.0651      # 44 kV フィーダ
    x_feed: float = 0.1805
    b_c: float = 29.6 / 30.0    # 変電所の母線のコンデンサ [pu]。0 で無し
    r_g: float = 0.007          # 電源(変電所の母線の故障容量 430 MVA)
    x_g: float = 0.0698
    v_pcc: float = 1.0          # 平衡点の PCC の電圧の大きさ [pu]
    # 電流制御(本文の速い制御。遅い制御は K_p 0.35・K_r 2・τ 200 µs)
    kp_cc: float = 1.0
    kr_cc: float = 10.0
    f_c: float = 2.0            # ω_c = 2π f_c
    t_d: float = 50e-6          # 制御の遅れ τ [s]
    # PLL(本文の式 (19)、Case 2)
    kp_pll: float = 150.0
    ki_pll: float = 3000.0
    f_lpf: float = 25.0         # ω_n = 2π f_lpf
    lpf_order: int = 2
    zeta_lpf: float = 0.707
    # 電流の指令(PLL の座標)
    i_d: float = 0.1
    i_q: float = 0.0
    # 外側の制御(本文の Fig. 4「Outer control: 0.2 + 20/s」)。"" は入れない、"pq" は P と Q、"pv" は P と |v_pcc|。
    # 指令 p_ref・q_ref(pv では電圧)は with_outer() で平衡点にそろえる
    outer: str = ""
    kp_o: float = 0.2
    ki_o: float = 20.0
    p_ref: float = math.nan
    q_ref: float = math.nan
    f_meas: float = 0.0         # 測る P と Q(pv では |v_pcc|)の 1 次の濾波器の折れ点 [Hz]。0 は濾波しない
    kv_q: float = 0.0           # pq で Q の指令を dQ*/dt = kv_q (v_pcc − |v_pcc|) でゆっくり動かす。0 は一定
    # 制限(平衡点では効かない値にすること。線形化は制限の無い模型のまま)
    i_max: float = math.inf     # |i_d* + j i_q*| [pu]
    v_max: float = math.inf     # 遅れに入る前の変換器の電圧の指令 |v_pcc + PR(e)| [pu]
    df_max: float = math.inf    # PLL の周波数の偏差 [Hz]

    @property
    def w1(self) -> float:
        return 2 * math.pi * self.f0

    @property
    def shunt(self) -> bool:
        return self.b_c > 0.0

    def replace(self, **kw) -> "PRParams":
        return dataclasses.replace(self, **kw)


# 状態の並び(複素の量は実部・虚部の 2 つ)
def state_names(p: PRParams) -> tuple:
    c = lambda n: (n + ",d", n + ",q")
    names = c("i")
    if p.shunt:
        names += c("v_s") + c("i_g")
    names += c("x_pr1") + c("x_pr2") + c("w_d")
    names += ("v_f",) if p.lpf_order == 1 else ("v_f", "v_f'")
    if p.outer:
        names += ("x_P", "x_Q") + (("m_P", "m_Q") if p.f_meas > 0 else ()) + (("Q*",) if _kv(p) else ())
    return names + ("x_pll", "δ")


def _kv(p: PRParams) -> bool:
    return p.outer == "pq" and p.kv_q > 0


def _unpack(p: PRParams, x: np.ndarray) -> dict:
    z = lambda k: complex(x[k], x[k + 1])
    out, k = {"i": z(0)}, 2
    if p.shunt:
        out["v_s"], out["i_g"], k = z(2), z(4), 6
    out["x1"], out["x2"], out["w"] = z(k), z(k + 2), z(k + 4)
    k += 6
    out["vf"] = x[k:k + p.lpf_order]
    n_o = (4 if p.f_meas > 0 else 2) + (1 if _kv(p) else 0)
    out["x_o"] = x[k + p.lpf_order:k + p.lpf_order + n_o] if p.outer else None
    out["x_pll"], out["th"] = x[-2], x[-1]
    return out


def _lpf_rhs(p: PRParams, vf: np.ndarray, vq: float) -> list:
    wn = 2 * math.pi * p.f_lpf
    if p.lpf_order == 1:
        return [wn * (vq - vf[0])]
    return [vf[1], wn * wn * (vq - vf[0]) - 2 * p.zeta_lpf * wn * vf[1]]


def _outer_cmd(p: PRParams, x_o: np.ndarray, q_ref: float, c: complex, i: complex, a: complex, b: float) -> complex:
    """外側の制御の指令 i_d* + j i_q*。v_pcc = a + b i* e^{jθ} が指令によるので、2 変数のニュートン法で解く。"""
    kp, ic = p.kp_o, i.conjugate()
    dv = (b * c, 1j * b * c)                               # v_pcc の i_d*・i_q* による微分
    zd, zq = float(x_o[0]), float(x_o[1])
    for _ in range(30):
        v = a + b * c * complex(zd, zq)
        sp = v * ic
        g0 = x_o[0] + kp * (p.p_ref - sp.real)
        j00, j01 = -kp * (dv[0] * ic).real, -kp * (dv[1] * ic).real
        if p.outer == "pq":
            g1 = x_o[1] - kp * (q_ref - sp.imag)
            j10, j11 = kp * (dv[0] * ic).imag, kp * (dv[1] * ic).imag
        else:
            av = abs(v)
            g1 = x_o[1] - kp * (q_ref - av)
            j10, j11 = kp * (v.conjugate() * dv[0]).real / av, kp * (v.conjugate() * dv[1]).real / av
        r0, r1 = zd - g0, zq - g1
        m00, m01, m10, m11 = 1 - j00, -j01, -j10, 1 - j11
        det = m00 * m11 - m01 * m10
        dd, dq = (m11 * r0 - m01 * r1) / det, (m00 * r1 - m10 * r0) / det
        zd, zq = zd - dd, zq - dq
        if max(abs(dd), abs(dq)) < 1e-15:
            break
    return complex(zd, zq)


def _core(p: PRParams, x: np.ndarray, v_g: complex, t: Optional[float]) -> tuple:
    """(dx/dt, v_pcc, PLL の角速度の偏差)。t = None なら網の dq(ω1 で回る)、t を与えると静止座標
    (x[-1] は PLL の角 θ そのもの)。"""
    w1 = p.w1
    jw = 0.0 if t is not None else 1j * w1                 # 静止座標の線形の部分を dq に移すと −jω1 が付く
    vg = v_g * np.exp(1j * w1 * t) if t is not None else v_g
    s = _unpack(p, x)
    i, x1, x2, w = s["i"], s["x1"], s["x2"], s["w"]
    vf, th = s["vf"], s["th"]
    c = np.exp(1j * th)                                    # dq では δ(網の dq から見た PLL の角)、静止座標では θ
    wc = 2 * math.pi * p.f_c
    lf, la = p.x_f / w1, p.x_feed / w1
    ra = p.r_feed
    if p.shunt:
        vn = s["v_s"]
    else:
        vn, la, ra = vg, la + p.x_g / w1, ra + p.r_g
    lt, rt = lf + la, p.r_f + ra
    beta = la / lt
    # v = 2w − (v_pcc + y) と v_pcc = v_n + R_a i + L_a (di/dt + jω i) を連立して解くと v_pcc = a + b i*
    y0 = -p.kp_cc * i + p.kr_cc * 2 * wc * x2
    a = (vn * (1 - beta) + (ra - beta * rt) * i + beta * (2 * w - y0)) / (1 + beta)
    b = -beta * p.kp_cc / (1 + beta)
    x_o, filt = s["x_o"], p.outer and p.f_meas > 0
    q_ref = x_o[-1] if _kv(p) else p.q_ref
    if p.outer and not filt and not (math.isinf(p.i_max) and math.isinf(p.v_max)):
        raise ValueError("濾波しない外側の制御(f_meas = 0)と電流・電圧の制限は組み合わせられない")
    if filt:                                               # 濾波した量を測るので代数ループは無い
        i_cmd = complex(x_o[0] + p.kp_o * (p.p_ref - x_o[2]), x_o[1] - p.kp_o * (q_ref - x_o[3]))
    else:
        i_cmd = _outer_cmd(p, x_o, q_ref, c, i, a, b) if p.outer else complex(p.i_d, p.i_q)
    if abs(i_cmd) > p.i_max:
        i_cmd *= p.i_max / abs(i_cmd)
    i_ref = i_cmd * c
    e = i_ref - i
    y = y0 + p.kp_cc * i_ref
    if math.isinf(p.v_max):
        v_pcc = a + b * i_ref
        u = v_pcc + y                                      # 遅れに入る電圧の指令
    else:
        # u + β sat(u) = K を解く(飽和しなければ u = K/(1 + β)、すれば u は K と同じ向き)
        kk = vn * (1 - beta) + (ra - beta * rt) * i + 2 * beta * w + y
        if abs(kk) <= (1 + beta) * p.v_max:
            u = kk / (1 + beta)
        else:
            u = kk * p.v_max / abs(kk)
        v_pcc = kk - beta * u - y
    v = 2 * w - u
    didt = (v - vn - rt * i) / lt - jw * i
    dx1 = x2 - jw * x1
    dx2 = -w1 * w1 * x1 - 2 * wc * x2 + e - jw * x2
    dw = (u - w) / (p.t_d / 2) - jw * w
    vq = (v_pcc * c.conjugate()).imag
    dvf = _lpf_rhs(p, vf, vq)
    dom = p.kp_pll * vf[0] + s["x_pll"]
    dxp = p.ki_pll * vf[0]
    lim = 2 * math.pi * p.df_max
    if abs(dom) > lim:                                     # 周波数の制限。外へ向かう積分は止める
        dom = math.copysign(lim, dom)
        if dxp * dom > 0:
            dxp = 0.0
    dth = dom + (w1 if t is not None else 0.0)
    out = [didt.real, didt.imag]
    if p.shunt:
        cc, lg = p.b_c / w1, p.x_g / w1
        dvs = (i - s["i_g"]) / cc - jw * s["v_s"]
        dig = (s["v_s"] - vg - p.r_g * s["i_g"]) / lg - jw * s["i_g"]
        out += [dvs.real, dvs.imag, dig.real, dig.imag]
    out += [dx1.real, dx1.imag, dx2.real, dx2.imag, dw.real, dw.imag] + list(dvf)
    if p.outer:
        sp = v_pcc * i.conjugate()
        meas = (sp.real, sp.imag if p.outer == "pq" else abs(v_pcc))
        m = (x_o[2], x_o[3]) if filt else meas
        out += [p.ki_o * (p.p_ref - m[0]), -p.ki_o * (q_ref - m[1])]
        if filt:
            wm = 2 * math.pi * p.f_meas
            out += [wm * (meas[0] - m[0]), wm * (meas[1] - m[1])]
        if _kv(p):
            out += [p.kv_q * (p.v_pcc - abs(v_pcc))]
    return np.array(out + [dxp, dth]), v_pcc, dom


def _rhs(p: PRParams, x: np.ndarray, v_g: complex, t: Optional[float]) -> np.ndarray:
    return _core(p, x, v_g, t)[0]


# ---------------------------------------------------------------- 平衡点
@dataclasses.dataclass
class Equilibrium:
    x: np.ndarray       # 網の dq の状態(PLL の角 δ = 0 に網の dq をそろえる)
    v_g: complex        # 無限大母線の電圧(網の dq)
    i: complex          # インバータの電流
    p_out: float        # PCC でインバータが出す有効電力 [pu]
    q_out: float


def pr_tf(p: PRParams, s):
    wc = 2 * math.pi * p.f_c
    return p.kp_cc + p.kr_cc * 2 * wc * s / (s * s + 2 * wc * s + p.w1 ** 2)


def delay_tf(p: PRParams, s):
    return (1 - s * p.t_d / 2) / (1 + s * p.t_d / 2)


def equilibrium(p: PRParams) -> Equilibrium:
    """網の dq を PCC の電圧にそろえ(v_pcc は実数、δ = 0)、静止座標の s = jω1 の定常解から状態を決める。"""
    w1, sj = p.w1, 1j * p.w1
    vp = complex(p.v_pcc, 0.0)
    i_ref = complex(p.i_d, p.i_q)
    td, pr = delay_tf(p, sj), pr_tf(p, sj)
    zf = complex(p.r_f, p.x_f)
    i = ((td - 1) * vp + td * pr * i_ref) / (zf + td * pr)          # 本文の式 (4)
    v_s = vp - complex(p.r_feed, p.x_feed) * i
    if p.shunt:
        i_g = i - 1j * p.b_c * v_s
        v_g = v_s - complex(p.r_g, p.x_g) * i_g
    else:
        v_g = v_s - complex(p.r_g, p.x_g) * i
    e = i_ref - i
    wc = 2 * math.pi * p.f_c
    x1 = e / (2j * wc * w1)                                       # 定常で dx1 = dx2 = 0
    x2 = 1j * w1 * x1
    y = p.kp_cc * e + p.kr_cc * 2 * wc * x2
    w = (vp + y) / (1 + sj * p.t_d / 2)
    xs = [i.real, i.imag]
    if p.shunt:
        xs += [v_s.real, v_s.imag, i_g.real, i_g.imag]
    xs += [x1.real, x1.imag, x2.real, x2.imag, w.real, w.imag]
    s_out = vp * i.conjugate()
    xs += [0.0] * p.lpf_order + ([p.i_d, p.i_q] if p.outer else [])
    if p.outer and p.f_meas > 0:
        xs += [s_out.real, s_out.imag if p.outer == "pq" else p.v_pcc]
    if _kv(p):
        xs += [s_out.imag]
    xs += [0.0, 0.0]
    return Equilibrium(x=np.array(xs), v_g=v_g, i=i, p_out=s_out.real, q_out=s_out.imag)


def with_outer(p: PRParams, mode: str = "pv") -> PRParams:
    """外側の制御を足す。指令は平衡点(i_d, i_q, v_pcc)の P と Q(pv なら |v_pcc|)にそろえる。"""
    eq = equilibrium(p.replace(outer=""))
    return p.replace(outer=mode, p_ref=eq.p_out, q_ref=eq.q_out if mode == "pq" else p.v_pcc)


def at_source(p: PRParams, p_out: float, v_g: float = 1.0) -> PRParams:
    """無限大母線の電圧の大きさを v_g、PCC の電圧を p.v_pcc、有効電力を p_out にする (i_d, i_q) を解く。"""
    def f(z):
        eq = equilibrium(p.replace(i_d=z[0], i_q=z[1]))
        return [eq.p_out - p_out, abs(eq.v_g) - v_g]
    z, _, ier, msg = fsolve(f, [p_out, 0.3], full_output=True)
    if ier != 1:
        raise RuntimeError(msg)
    return p.replace(i_d=float(z[0]), i_q=float(z[1]))


# ---------------------------------------------------------------- 道 1: 状態空間
def state_matrix(p: PRParams, eq: Optional[Equilibrium] = None) -> np.ndarray:
    eq = eq or equilibrium(p)
    n = eq.x.size
    a = np.empty((n, n))
    for k in range(n):
        h = 1e-6 * max(1.0, abs(eq.x[k]))
        xp, xm = eq.x.copy(), eq.x.copy()
        xp[k] += h
        xm[k] -= h
        a[:, k] = (_rhs(p, xp, eq.v_g, None) - _rhs(p, xm, eq.v_g, None)) / (2 * h)
    return a


def eigenvalues(p: PRParams) -> np.ndarray:
    lam = np.linalg.eigvals(state_matrix(p))
    return lam[np.argsort(-lam.real)]


def critical_mode(lam: np.ndarray, f_min: float = 0.5, f_max: float = 200.0) -> complex:
    """虚部が f_min〜f_max Hz の固有値のうち、実部が最大のもの(遅れの近似や共振の速いモードは見ない)。"""
    osc = lam[(lam.imag > 2 * math.pi * f_min) & (lam.imag < 2 * math.pi * f_max)]
    return complex(osc[np.argmax(osc.real)])


def participation(p: PRParams, f_max: float = 200.0) -> tuple[complex, dict]:
    a = state_matrix(p)
    lam, v = np.linalg.eig(a)
    w = np.linalg.inv(v)
    osc = [k for k in range(lam.size) if 2 * math.pi * 0.5 < lam[k].imag < 2 * math.pi * f_max]
    k = max(osc, key=lambda j: lam[j].real)
    pf = np.abs(v[:, k] * w[k, :])
    pf /= pf.sum()
    names = state_names(p)
    return complex(lam[k]), {names[i]: float(pf[i]) for i in np.argsort(-pf)}


# ---------------------------------------------------------------- 道 2: 論文の線形模型
def z_pv(p: PRParams, s):
    """本文の式 (4): v_pcc = Z*_PV i* − Z_PV i(静止座標)。"""
    td, pr = delay_tf(p, s), pr_tf(p, s)
    zl = p.r_f + s * p.x_f / p.w1
    k = td / (1 - td)
    return k * pr, zl + k * (pr + zl)


def z_grid(p: PRParams, s):
    """本文の式 (5)(6)。"""
    zfeed = p.r_feed + s * p.x_feed / p.w1
    zg = p.r_g + s * p.x_g / p.w1
    if not p.shunt:
        return zfeed + zg
    return zfeed + 1 / (s * p.b_c / p.w1 + 1 / zg)


def _g1_nd(p: PRParams, s) -> tuple:
    """G1 = N/D を、割り算の無い多項式の値 (N, D) で返す。

    Z_grid = Z_n/Z_d、T_d = T_n/T_dd、PR = P_n/P_d と書き、G1 = Z_grid Z*_PV/(Z_grid + Z_PV) の分母と分子に
    (1 − T_d) Z_d T_dd P_d を掛けた形: N = Z_n T_n P_n、D = (Z_n + z_l Z_d)(T_dd − T_n) P_d + T_n (P_n + z_l P_d) Z_d。
    """
    w1, wc = p.w1, 2 * math.pi * p.f_c
    zl = p.r_f + s * p.x_f / w1
    zfeed = p.r_feed + s * p.x_feed / w1
    zgs = p.r_g + s * p.x_g / w1
    if p.shunt:
        zd = s * p.b_c / w1 * zgs + 1
        zn = zfeed * zd + zgs
    else:
        zd, zn = 1.0, zfeed + zgs
    tn, tdd = 1 - s * p.t_d / 2, 1 + s * p.t_d / 2
    pd = s * s + 2 * wc * s + w1 * w1
    pn = p.kp_cc * pd + p.kr_cc * 2 * wc * s
    return zn * tn * pn, (zn + zl * zd) * (tdd - tn) * pd + tn * (pn + zl * pd) * zd


def g1(p: PRParams, s):
    """本文の式 (8) の G1 = Z_grid Z*_PV/(Z_grid + Z_PV)(静止座標)。"""
    n, d = _g1_nd(p, s)
    return n / d


def g1_dq(p: PRParams, s) -> tuple:
    """(G1R, G1I): 網の dq の実の 2×2 [[G1R, −G1I], [G1I, G1R]] の要素(本文の式 (10))。"""
    a, b = g1(p, s + 1j * p.w1), g1(p, s - 1j * p.w1)
    return (a + b) / 2, (a - b) / 2j


def g_pll(p: PRParams, s, v: Optional[float] = None):
    """本文の式 (14): Δδ = G_PLL Δv_pcc,q、G_PLL = H/(1 + V H)、H = (K_p + K_i/s)/s · LPF。"""
    v = p.v_pcc if v is None else v
    wn = 2 * math.pi * p.f_lpf
    lpf = wn / (s + wn) if p.lpf_order == 1 else wn * wn / (s * s + 2 * p.zeta_lpf * wn * s + wn * wn)
    h = (p.kp_pll + p.ki_pll / s) / s * lpf
    return h / (1 + v * h)


def loop_char(p: PRParams, s) -> complex:
    """1 − G_PLL (i_d G1R − i_q G1I)。零点が閉ループの極。"""
    gr, gi = g1_dq(p, s)
    return complex(1 - g_pll(p, s) * (p.i_d * gr - p.i_q * gi))


def _loop_entire(p: PRParams, s) -> complex:
    """loop_char に (1 + V H) s² D_lpf(s) D(s + jω1) D(s − jω1) を掛けた極の無い関数 Φ(s)。

    Φ = [s² D_lpf + V (K_p s + K_i) N_lpf] D⁺D⁻ − (K_p s + K_i) N_lpf [i_d (N⁺D⁻ + N⁻D⁺)/2 − i_q (N⁺D⁻ − N⁻D⁺)/2j]。
    PLL と G1R の極を消してあるので、零点が極のすぐそば(結び付きの弱いモード)でも割線法が収束し、
    閉ループのモードを全部数えられる。
    """
    n_p, d_p = _g1_nd(p, s + 1j * p.w1)
    n_m, d_m = _g1_nd(p, s - 1j * p.w1)
    wn = 2 * math.pi * p.f_lpf
    n_l, d_l = (wn, s + wn) if p.lpf_order == 1 else (wn * wn, s * s + 2 * p.zeta_lpf * wn * s + wn * wn)
    pi = (p.kp_pll * s + p.ki_pll) * n_l
    ell = p.i_d * (n_p * d_m + n_m * d_p) / 2 - p.i_q * (n_p * d_m - n_m * d_p) / 2j
    return complex((s * s * d_l + p.v_pcc * pi) * d_p * d_m - pi * ell)


def loop_zeros(p: PRParams, f_max: float = 200.0,
               sigma: tuple = (-7000.0, -4000.0, -1000.0, -400.0, -150.0, -60.0, -25.0, -8.0, 0.0, 10.0, 40.0)) -> np.ndarray:
    """論文の線形模型の零点(0 < Im s ≤ 2π f_max)を、jω 軸の谷と格子(1 Hz おき)から割線法で探す。"""
    if p.outer:
        raise ValueError("道 2(本文の線形模型)は外側の制御を入れない")
    fun = lambda s: _loop_entire(p, s)
    seeds = []
    w = 2 * math.pi * np.geomspace(0.2, f_max, 800)
    mag = np.array([abs(fun(1j * x)) for x in w])
    for k in range(1, len(w) - 1):
        if mag[k] < mag[k - 1] and mag[k] < mag[k + 1]:
            seeds.append(1j * w[k])
    for sg in sigma:
        for fz in np.arange(1.0, f_max, 1.0) + 0.37:          # 静止座標の s = 0(dq の ±60 Hz)を避ける
            seeds.append(complex(sg, 2 * math.pi * fz))
    found: list[complex] = []
    for s0 in seeds:
        z = _secant(fun, s0, s0 * (1 + 1e-3) + 1e-3)
        if z is None or z.imag <= 1e-6 or z.imag > 2 * math.pi * f_max or abs(z.real) > 1e5:
            continue
        if abs(fun(z)) > 1e-8 * max(1.0, abs(fun(z + 1.0))):
            continue
        if all(abs(z - y) > 1e-6 * max(1.0, abs(z)) for y in found):
            found.append(z)
    out = np.array(found, dtype=complex)
    return out[np.argsort(-out.real)] if out.size else out


# ---------------------------------------------------------------- 道 3: 時間領域
@dataclasses.dataclass
class TimeResult:
    t: np.ndarray
    i_abc: np.ndarray
    di_a: np.ndarray
    modes: list
    fit: tuple


def simulate(p: PRParams, t_end: float = 1.0, d_theta: float = 1e-6, fs: float = 4000.0,
             t_fit: float = 0.08, amp_lin: float = 1e-3, n_modes: int = 16) -> TimeResult:
    """静止座標で非線形のまま積分する。t = 0 に PLL の角を d_theta だけずらす(段 A の simulate と同じ読み方)。"""
    eq = equilibrium(p)
    x0 = eq.x.copy()
    x0[-1] += d_theta
    t = np.arange(0.0, t_end, 1.0 / fs)
    sol = solve_ivp(lambda tt, xx: _rhs(p, xx, eq.v_g, tt), (0.0, t[-1]), x0, method="DOP853",
                    t_eval=t, rtol=1e-10, atol=1e-13)
    if not sol.success:
        raise RuntimeError(sol.message)
    t = sol.t
    i_ab = sol.y[0] + 1j * sol.y[1]
    a = np.exp(-2j * math.pi / 3)
    i_abc = np.vstack([(i_ab * a ** k).real for k in range(3)])
    di_a = i_abc[0] - (eq.i * np.exp(1j * p.w1 * t)).real
    over = np.nonzero(np.abs(di_a) > amp_lin)[0]
    t1 = t[over[0]] if over.size else t[-1]
    sel = (t >= t_fit) & (t < t1)
    modes = matrix_pencil(di_a[sel], 1.0 / fs, n_modes=n_modes)
    return TimeResult(t=t, i_abc=i_abc, di_a=di_a, modes=modes, fit=(t_fit, float(t1)))


@dataclasses.dataclass
class EventResult:
    t: np.ndarray
    p: np.ndarray        # PCC でインバータが出す有効電力 [pu]
    q: np.ndarray
    v: np.ndarray        # |v_pcc| [pu]
    f_pll: np.ndarray    # PLL の周波数 [Hz]
    i_abc: np.ndarray
    v_abc: np.ndarray


def simulate_event(p_pre: PRParams, p_post: PRParams, t_event: float = 0.2, t_end: float = 2.0,
                   fs: float = 10000.0, rtol: float = 1e-8, atol: float = 1e-10) -> EventResult:
    """p_pre の平衡点から始め、t_event に網を p_post に切り替える(線路が落ちるなど)。静止座標で非線形のまま積分する。

    無限大母線の電圧は切り替えの前後で同じ。p_pre と p_post は状態の並びが同じであること(コンデンサの有無や
    外側の制御をそろえる)。
    """
    if state_names(p_pre) != state_names(p_post):
        raise ValueError("p_pre と p_post の状態の並びが違う")
    eq = equilibrium(p_pre)
    t = np.arange(0.0, t_end, 1.0 / fs)
    t1, t2 = t[t < t_event], t[t >= t_event]
    xs, x0 = [], eq.x.copy()
    for pp, ta, tb, te in ((p_pre, 0.0, t_event, np.append(t1, t_event)), (p_post, t_event, t[-1], t2)):
        sol = solve_ivp(lambda tt, xx: _rhs(pp, xx, eq.v_g, tt), (ta, tb), x0, method="DOP853",
                        t_eval=te, rtol=rtol, atol=atol)
        if not sol.success:
            raise RuntimeError(f"{sol.message}(t = {sol.t[-1]:.3f} s)")
        x0 = sol.y[:, -1]
        xs.append(sol.y[:, :-1] if pp is p_pre else sol.y)
    x = np.hstack(xs)
    vp, dom = np.empty(t.size, complex), np.empty(t.size)
    for k, tt in enumerate(t):
        pp = p_pre if tt < t_event else p_post
        _, vp[k], dom[k] = _core(pp, x[:, k], eq.v_g, tt)
    i = x[0] + 1j * x[1]
    sp = vp * i.conjugate()
    a = np.exp(-2j * math.pi / 3)
    abc = lambda z: np.vstack([(z * a ** k).real for k in range(3)])
    return EventResult(t=t, p=sp.real, q=sp.imag, v=np.abs(vp), f_pll=p_pre.f0 + dom / (2 * math.pi),
                       i_abc=abc(i), v_abc=abc(vp))


# ---------------------------------------------------------------- 臨界の i_d(本文の「marginal gain」)
def critical_id_eig(p: PRParams, lo: float = 0.01, hi: float = 5.0, n: int = 60) -> Optional[float]:
    """i_d を lo から上げ、危ないモードの実部が初めて正になる値(道 1)。無ければ None。"""
    g = lambda d: critical_mode(eigenvalues(p.replace(i_d=d))).real
    ds = np.linspace(lo, hi, n)
    prev = g(ds[0])
    if prev > 0:
        return None
    for a, b in zip(ds[:-1], ds[1:]):
        cur = g(b)
        if cur > 0:
            return brentq(g, a, b, xtol=1e-6)
        prev = cur
    return None


def critical_id_loop(p: PRParams, lo: float, hi: float, f_max: float = 200.0) -> float:
    """道 2 の零点の実部の最大で、臨界の i_d を出す(lo と hi は道 1 と独立に与える)。"""
    def g(d):
        z = loop_zeros(p.replace(i_d=d), f_max=f_max)
        z = z[z.imag > 2 * math.pi * 0.5]
        return float(z.real.max())
    return brentq(g, lo, hi, xtol=1e-6)


# ---------------------------------------------------------------- 本文 III-B の簡単な例
# インバータを理想の電流源、網を純リアクタンス X_g = k / i_d とみる。PCC の電圧の大きさを 1 に保つ
# (無限大母線を v_g = √(1 + k²) にとる)と、本文の開ループ −i_d (s X_g/ω1) G_PLL は厳密な線形化になる:
#   1 − k (s/ω1) G_PLL(s) = 0、k = i_d X_g。PLL の定数だけを PRParams から使う。
def simple_roots(p: PRParams, k: float) -> np.ndarray:
    wn = 2 * math.pi * p.f_lpf
    n_l, d_l = ([wn], [1.0, wn]) if p.lpf_order == 1 else ([wn * wn], [1.0, 2 * p.zeta_lpf * wn, wn * wn])
    pi = np.polymul([p.kp_pll, p.ki_pll], n_l)
    den = np.polyadd(np.polymul([1.0, 0.0, 0.0], d_l), pi)          # s² D_lpf (1 + H)
    return np.roots(np.polyadd(den, -k / p.w1 * np.polymul([1.0, 0.0], pi)))


def simple_critical(p: PRParams, k_max: float = 5.0) -> Optional[tuple]:
    """(臨界の k = i_d X_g, そのときの振動の周波数 [Hz])。k_max まで不安定にならなければ None。"""
    g = lambda k: float(simple_roots(p, k).real.max())
    ks = np.linspace(1e-4, k_max, 2000)
    for a, b in zip(ks[:-1], ks[1:]):
        if g(b) > 0:
            k = brentq(g, a, b, xtol=1e-9)
            r = simple_roots(p, k)
            return k, abs(r[np.argmax(r.real)].imag) / (2 * math.pi)
    return None


def simple_simulate(p: PRParams, k: float, t_end: float = 2.0, d_delta: float = 1e-6, fs: float = 1000.0,
                    t_fit: float = 0.2, n_modes: int = 8) -> list:
    """簡単な例を非線形のまま積分する(v_q = −v_g sin δ + k ω/ω1)。δ のずれを行列ペンシルで読む。"""
    w1, wn = p.w1, 2 * math.pi * p.f_lpf
    vg = math.sqrt(1 + k * k)
    d0 = math.asin(k / vg)

    def rhs(t, x):
        vf, xi, dl = x[:p.lpf_order], x[-2], x[-1]
        om = w1 + p.kp_pll * vf[0] + xi
        vq = -vg * math.sin(dl) + k * om / w1
        dvf = [wn * (vq - vf[0])] if p.lpf_order == 1 else [vf[1], wn * wn * (vq - vf[0]) - 2 * p.zeta_lpf * wn * vf[1]]
        return dvf + [p.ki_pll * vf[0], om - w1]
    x0 = [0.0] * p.lpf_order + [0.0, d0 + d_delta]
    t = np.arange(t_fit, t_end, 1.0 / fs)
    sol = solve_ivp(rhs, (0.0, t_end), x0, method="DOP853", rtol=1e-10, atol=1e-13, dense_output=True)
    return matrix_pencil(sol.sol(t)[-1] - d0, 1.0 / fs, n_modes=n_modes)
