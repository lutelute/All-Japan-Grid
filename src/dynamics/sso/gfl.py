"""系統追従型(GFL)インバータ 1 台 + 網のテブナン等価の SSO の模型 — SSO 第 2 段 段 A(2026-11-01).

計画: docs/reports/sso_ibr_literature_2026-10-31.md の「段 A: 模型と 3 つの道」。
同じ振動を 3 つの道で求め、周波数と減衰がそろうかを確かめる:

  道 1  状態空間: 非線形の dq の常微分方程式(網の dq、ω0 で回る)を平衡点で数値的に線形化し、
        A の固有値を出す。
  道 2  アドミタンス: インバータの dq アドミタンス Y_c(s)(PLL による周波数の結合を含む 2×2)を
        周波数領域の式から直接組み、網の Y_g(s) と足した全体のアドミタンスの det の零点を出す
        (ADMIT2020)。RHP の零点の数は偏角の原理で別に数える。
  道 3  時間領域: 静止座標(αβ)で非線形のまま積分し、abc の電流から行列ペンシル法
        (pencil.py)で振動を読む。網の dq の振動 f_dq は abc では f0 − f_dq(sub)と
        f0 + f_dq(super)の組で出る(和が 2f0)。

単位: インバータの定格を基準にした pu。時間は秒。インダクタンスは pu·s(= x_pu / ω0)。
空間ベクトルは複素数 x = x_d + j x_q。網の dq は網の電圧を d 軸に置く。
電流 i はインバータから網へ向かう向き。

模型(dq の平均値模型。スイッチングと制御の遅れは入れない):
  回路   (L_f + L_g) di/dt = v_c − v_g − (R_f + R_g) i − jω0 (L_f + L_g) i
         v_pcc = v_g + (R_g + jω0 L_g) i + L_g di/dt
  PLL    v^c = v_pcc e^{−jδ},  dδ/dt = K_p v^c_q + x_pll,  dx_pll/dt = K_i v^c_q
  電流   v_c^c = K_p,cc (i_ref − i^c) + x_cc + jω0 L_f i^c + k_ff v_ff
         dx_cc/dt = K_i,cc (i_ref − i^c),  T_ff dv_ff/dt = v^c − v_ff,  v_c = v_c^c e^{jδ}
  状態 8 個: i(2)・x_cc(2)・v_ff(2)・x_pll・δ。電流の指令は一定(外側の制御は後で足す)。

定数の決め方(段 A の定数は道を確かめるための例で、実機の値ではない):
  - 電流制御は内部モデル制御の規則 K_p,cc = α_cc L_f、K_i,cc = α_cc R_f(HARNEFORS1998)。
  - PLL は s² + V K_p s + V K_i = s² + 2ζω_n s + ω_n²(V = 1 pu)で決める。
  - 網は SCR と X/R から |Z_g| = V_g² / SCR(インバータの定格を基準)。
"""
from __future__ import annotations

import dataclasses
import math
from typing import Optional

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

from .pencil import matrix_pencil

_I = np.eye(2)
_J = np.array([[0.0, -1.0], [1.0, 0.0]])


def _rot(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s], [s, c]])


def _vec(z: complex) -> np.ndarray:
    return np.array([z.real, z.imag])


@dataclasses.dataclass(frozen=True)
class GFLParams:
    f0: float = 50.0        # 定格周波数 [Hz]
    v_g: float = 1.0        # 網の電圧 [pu]
    x_f: float = 0.15       # フィルタのリアクタンス [pu]
    r_f: float = 0.005      # フィルタの抵抗 [pu]
    scr: float = 3.0        # 短絡容量比
    xr_g: float = 10.0      # 網の X/R
    i_d_ref: float = 1.0    # 電流の指令(d、PLL の座標) [pu]
    i_q_ref: float = 0.0    # 電流の指令(q) [pu]
    f_cc: float = 300.0     # 電流制御の帯域 α_cc/2π [Hz]
    f_pll: float = 40.0     # PLL の固有周波数 ω_n/2π [Hz]
    zeta_pll: float = 0.707
    t_ff: float = 1e-3      # 電圧のフィードフォワードの一次遅れ [s]
    k_ff: float = 0.0       # フィードフォワードの有無(1/0)

    @property
    def w0(self) -> float:
        return 2 * math.pi * self.f0

    @property
    def l_f(self) -> float:
        return self.x_f / self.w0

    @property
    def grid_rl(self) -> tuple[float, float]:
        z = self.v_g ** 2 / self.scr
        r = z / math.sqrt(1.0 + self.xr_g ** 2)
        return r, r * self.xr_g / self.w0

    @property
    def cc_gains(self) -> tuple[float, float]:
        a = 2 * math.pi * self.f_cc
        return a * self.l_f, a * self.r_f

    @property
    def pll_gains(self) -> tuple[float, float]:
        wn = 2 * math.pi * self.f_pll
        return 2 * self.zeta_pll * wn, wn * wn

    def replace(self, **kw) -> "GFLParams":
        return dataclasses.replace(self, **kw)


@dataclasses.dataclass(frozen=True)
class Equilibrium:
    x: np.ndarray       # 網の dq の状態 8 個
    delta: float        # PLL の角(網の電圧から)
    v_pcc: float        # 連系点の電圧の大きさ(PLL の座標では d 軸だけ)
    i_c: complex        # 電流(PLL の座標)
    vc_c: complex       # インバータの出力電圧(PLL の座標)


def equilibrium(p: GFLParams) -> Equilibrium:
    """平衡点を解析的に出す。電流の PI が i^c = i_ref に、PLL が v^c_q = 0 に寄せる。"""
    rg, lg = p.grid_rl
    i_c = complex(p.i_d_ref, p.i_q_ref)
    zi = complex(rg, p.w0 * lg) * i_c
    disc = p.v_g ** 2 - zi.imag ** 2
    if disc <= 0:
        raise ValueError(f"平衡点なし(静的な限界を超える): SCR={p.scr}")
    v = zi.real + math.sqrt(disc)
    delta = -np.angle(v - zi)
    vc_c = v + complex(p.r_f, p.w0 * p.l_f) * i_c
    x_cc = vc_c - 1j * p.w0 * p.l_f * i_c - p.k_ff * v
    i_g = i_c * np.exp(1j * delta)
    x = np.array([i_g.real, i_g.imag, x_cc.real, x_cc.imag, v, 0.0, 0.0, delta])
    return Equilibrium(x=x, delta=float(delta), v_pcc=float(v), i_c=i_c, vc_c=complex(vc_c))


def _rhs(p: GFLParams, x: np.ndarray, t: Optional[float]) -> np.ndarray:
    """t=None なら網の dq(道 1)、t を与えれば静止座標 αβ(道 3)。x[7] は前者で δ、後者で θ。"""
    rg, lg = p.grid_rl
    kp, ki = p.cc_gains
    kpp, kip = p.pll_gains
    lf, rf, w0 = p.l_f, p.r_f, p.w0
    i = complex(x[0], x[1])
    x_cc = complex(x[2], x[3])
    v_ff = complex(x[4], x[5])
    x_pll, ang = x[6], x[7]
    rot = complex(math.cos(ang), -math.sin(ang))   # e^{−j ang}
    i_c = i * rot
    e = complex(p.i_d_ref, p.i_q_ref) - i_c
    vc = (kp * e + x_cc + 1j * w0 * lf * i_c + p.k_ff * v_ff) / rot
    if t is None:
        vg = complex(p.v_g, 0.0)
        didt = (vc - vg - (rf + rg) * i - 1j * w0 * (lf + lg) * i) / (lf + lg)
        v_pcc = vg + (rg + 1j * w0 * lg) * i + lg * didt
        base = 0.0
    else:
        vg = p.v_g * complex(math.cos(w0 * t), math.sin(w0 * t))
        didt = (vc - vg - (rf + rg) * i) / (lf + lg)
        v_pcc = vg + rg * i + lg * didt
        base = w0
    vpc = v_pcc * rot
    vq = vpc.imag
    dx_cc = ki * e
    dv_ff = (vpc - v_ff) / p.t_ff
    dang = base + kpp * vq + x_pll
    return np.array([didt.real, didt.imag, dx_cc.real, dx_cc.imag,
                     dv_ff.real, dv_ff.imag, kip * vq, dang])


# ---------------------------------------------------------------- 道 1: 状態空間
def state_matrix(p: GFLParams, eq: Optional[Equilibrium] = None) -> np.ndarray:
    eq = eq or equilibrium(p)
    n = eq.x.size
    a = np.empty((n, n))
    for k in range(n):
        h = 1e-6 * max(1.0, abs(eq.x[k]))
        xp, xm = eq.x.copy(), eq.x.copy()
        xp[k] += h
        xm[k] -= h
        a[:, k] = (_rhs(p, xp, None) - _rhs(p, xm, None)) / (2 * h)
    return a


def eigenvalues(p: GFLParams) -> np.ndarray:
    lam = np.linalg.eigvals(state_matrix(p))
    return lam[np.argsort(-lam.real)]


def critical_mode(lam: np.ndarray, f_min: float = 0.5) -> complex:
    """虚部が正で f_min Hz 以上の固有値のうち、実部が最大のもの。"""
    osc = lam[lam.imag > 2 * math.pi * f_min]
    return complex(osc[np.argmax(osc.real)])


STATE_NAMES = ("i_D", "i_Q", "x_cc,d", "x_cc,q", "v_ff,d", "v_ff,q", "x_pll", "δ")


def participation(p: GFLParams) -> tuple[complex, dict]:
    """危ないモード(critical_mode)と、その参加率(和を 1 にした |右固有ベクトル × 左固有ベクトル|)。"""
    a = state_matrix(p)
    lam, v = np.linalg.eig(a)
    w = np.linalg.inv(v)
    osc = [k for k in range(lam.size) if lam[k].imag > 2 * math.pi * 0.5]
    k = max(osc, key=lambda j: lam[j].real)
    pf = np.abs(v[:, k] * w[k, :])
    pf /= pf.sum()
    return complex(lam[k]), {STATE_NAMES[i]: float(pf[i]) for i in np.argsort(-pf)}


# ---------------------------------------------------------------- 道 2: アドミタンス
def converter_admittance(p: GFLParams, eq: Equilibrium, s: complex) -> np.ndarray:
    """インバータを連系点から見た dq のアドミタンス Y_c(s)(2×2)。−Δi = Y_c Δv_pcc。

    状態行列は使わず、小信号の伝達関数を周波数領域で直接組む:
      Δδ   = G_pll(s) · Im(e^{−jδ0} Δv),  G_pll = (K_p s + K_i)/(s² + V0 K_p s + V0 K_i)
      Δx^c = e^{−jδ0} Δx − j x0^c Δδ       (PLL の座標への変換の線形化。周波数の結合の源)
      Δv_c^c = [−(K_p,cc + K_i,cc/s) + jω0 L_f] Δi^c + k_ff/(1 + sT_ff) Δv^c
      Δv_c = e^{jδ0}(Δv_c^c + j v_c0^c Δδ),  [(sL_f + R_f) + jω0 L_f] Δi = Δv_c − Δv
    """
    kpp, kip = p.pll_gains
    kp, ki = p.cc_gains
    v0 = eq.v_pcc
    g_pll = (kpp * s + kip) / (s * s + v0 * kpp * s + v0 * kip)
    rm, rp = _rot(-eq.delta), _rot(eq.delta)
    pt = g_pll * (np.array([0.0, 1.0]) @ rm)                    # Δδ = pt · Δv
    c = -(kp + ki / s) * _I + p.w0 * p.l_f * _J
    f = p.k_ff / (1.0 + s * p.t_ff)
    ji0 = _J @ _vec(eq.i_c)
    jv0 = _J @ _vec(complex(v0, 0.0))
    jvc0 = _J @ _vec(eq.vc_c)
    zf = (s * p.l_f + p.r_f) * _I + p.w0 * p.l_f * _J
    m = zf - rp @ c @ rm
    nn = rp @ (-c @ np.outer(ji0, pt) + f * (rm - np.outer(jv0, pt)) + np.outer(jvc0, pt)) - _I
    return -np.linalg.solve(m, nn)


def grid_admittance(p: GFLParams, s: complex) -> np.ndarray:
    rg, lg = p.grid_rl
    return np.linalg.inv((s * lg + rg) * _I + p.w0 * lg * _J)


def det_total(p: GFLParams, eq: Equilibrium, s: complex) -> complex:
    return complex(np.linalg.det(converter_admittance(p, eq, s) + grid_admittance(p, s)))


def _secant(fun, s0: complex, s1: complex, tol: float = 1e-10, it: int = 80) -> Optional[complex]:
    f0, f1 = fun(s0), fun(s1)
    for _ in range(it):
        if f1 == f0:
            return None
        s2 = s1 - f1 * (s1 - s0) / (f1 - f0)
        if not np.isfinite(s2):
            return None
        s0, f0, s1 = s1, f1, s2
        f1 = fun(s1)
        if abs(s1 - s0) < tol * max(1.0, abs(s1)):
            return s1
    return None


def admittance_zeros(p: GFLParams, f_max: float = 400.0, sigma: tuple = (-300.0, -60.0, -10.0, 10.0, 40.0)) -> np.ndarray:
    """det(Y_c + Y_g) の零点(虚部 ≥ 0)を、jω 軸の |det| の谷と粗い格子から割線法で探す。

    道 1 の固有値は種に使わない。0 < Im s ≤ 2π f_max の範囲で見つかったものを返す。
    """
    eq = equilibrium(p)
    fun = lambda s: det_total(p, eq, s)
    seeds = []
    w = 2 * math.pi * np.geomspace(0.2, f_max, 600)
    mag = np.array([abs(fun(1j * x)) for x in w])
    for k in range(1, len(w) - 1):
        if mag[k] < mag[k - 1] and mag[k] < mag[k + 1]:
            seeds.append(1j * w[k])
    for sg in sigma:
        for fz in (1.0, 3.0, 8.0, 15.0, 25.0, 40.0, 60.0, 90.0, 140.0, 220.0, 330.0):
            seeds.append(complex(sg, 2 * math.pi * fz))
    found: list[complex] = []
    for s0 in seeds:
        z = _secant(fun, s0, s0 * (1 + 1e-3) + 1e-3)
        if z is None or z.imag <= 1e-6 or z.imag > 2 * math.pi * f_max * 1.5 or abs(z.real) > 1e5:
            continue
        if abs(fun(z)) > 1e-8 * max(1.0, abs(fun(z + 1.0))):
            continue
        if all(abs(z - y) > 1e-6 * max(1.0, abs(z)) for y in found):
            found.append(z)
    out = np.array(found, dtype=complex)
    return out[np.argsort(-out.real)] if out.size else out


def rhp_zero_count(p: GFLParams, sigma_max: float = 3000.0, f_max: float = 3000.0, eps: float = 1e-2,
                   n: int = 6000) -> int:
    """偏角の原理: 長方形 [eps, σ_max] × [−ω_max, ω_max] を一周したときの det の巻き数。

    Y_c と Y_g の極は左半面にある(電流制御・PLL・遅れ・網の RL はそれぞれ安定)ので、
    巻き数がそのまま右半面の閉ループの極の数になる。s = 0 の積分器の極は eps で避ける。
    虚軸に沿う辺は対数の間隔で密に取る。境のすぐそば(零点が虚軸に近い)では数え違えうるので、
    臨界 SCR そのものは critical_scr_admittance(零点の追跡)で出し、これは両側の確かめに使う。
    """
    eq = equilibrium(p)
    wm = 2 * math.pi * f_max
    w = 2 * math.pi * np.geomspace(1e-4, f_max, n)
    left = np.concatenate([eps - 1j * w[::-1], eps + 1j * w])           # 下から上へ
    u = np.linspace(0.0, 1.0, 400)[1:]
    top = eps + (sigma_max - eps) * u + 1j * wm
    right = sigma_max + 1j * (wm - 2 * wm * u)
    bottom = sigma_max - (sigma_max - eps) * u - 1j * wm
    pts = np.concatenate([left, top, right, bottom])
    vals = np.array([det_total(p, eq, s) for s in pts])
    ph = np.unwrap(np.angle(vals))
    # 虚軸側を下から上へ回るので時計回り。巻き数は偏角の増分の符号を反転して数える
    return int(round(-(ph[-1] - ph[0]) / (2 * math.pi)))


# ---------------------------------------------------------------- 道 3: 時間領域
@dataclasses.dataclass
class TimeResult:
    t: np.ndarray
    i_abc: np.ndarray        # 3 × n
    di_a: np.ndarray         # a 相の電流の平衡からのずれ
    modes: list              # 行列ペンシルの結果 [(f_hz, sigma, amp)], f ≥ 0
    fit: tuple               # 当てはめの窓 [s]


def simulate(p: GFLParams, t_end: float = 1.0, d_theta: float = 1e-6, fs: float = 4000.0,
             t_fit: float = 0.08, amp_lin: float = 1e-3, n_modes: int = 12) -> TimeResult:
    """静止座標で非線形のまま積分する。t = 0 に PLL の角を d_theta だけずらす。

    当てはめの窓は t_fit から、a 相の電流のずれが amp_lin [pu] を超える手前まで
    (育つ場合も線形の範囲だけを読む。この模型には電流の制限が無い)。
    """
    eq = equilibrium(p)
    x0 = eq.x.copy()
    x0[7] += d_theta
    t = np.arange(0.0, t_end, 1.0 / fs)
    sol = solve_ivp(lambda tt, xx: _rhs(p, xx, tt), (0.0, t[-1]), x0, method="DOP853",
                    t_eval=t, rtol=1e-10, atol=1e-13)
    if not sol.success:
        raise RuntimeError(sol.message)
    t = sol.t
    i_ab = sol.y[0] + 1j * sol.y[1]
    a = np.exp(-2j * math.pi / 3)
    i_abc = np.vstack([(i_ab * a ** k).real for k in range(3)])
    i0 = complex(eq.x[0], eq.x[1])
    di_a = i_abc[0] - (i0 * np.exp(1j * p.w0 * t)).real
    over = np.nonzero(np.abs(di_a) > amp_lin)[0]
    t1 = t[over[0]] if over.size else t[-1]
    sel = (t >= t_fit) & (t < t1)
    modes = matrix_pencil(di_a[sel], 1.0 / fs, n_modes=n_modes)
    return TimeResult(t=t, i_abc=i_abc, di_a=di_a, modes=modes, fit=(t_fit, float(t1)))


def pair_from_modes(modes: list, f0: float, f_dq: float, rel_amp: float = 1e-3) -> tuple:
    """|f0 − f_dq| と f0 + f_dq に一番近いモードを返す((f_sub, σ_sub), (f_sup, σ_sup))。

    f_dq > f0 のとき、下の側は負の周波数(逆相の向き)で、abc では |f0 − f_dq| に出る。
    振幅が最大の rel_amp 倍に満たないモード(当てはめの余り)は見ない。
    """
    big = [m for m in modes if m[2] >= rel_amp * modes[0][2]]

    def near(target):
        m = min(big, key=lambda x: abs(x[0] - target))
        return m[0], m[1]
    return near(abs(f0 - f_dq)), near(f0 + f_dq)


# ---------------------------------------------------------------- 臨界 SCR
def critical_scr_eig(p: GFLParams, lo: float = 1.05, hi: float = 10.0) -> Optional[float]:
    """道 1: 危ないモードの実部が 0 になる SCR(SCR を下げると不安定になる側の境)。"""
    g = lambda scr: critical_mode(eigenvalues(p.replace(scr=scr))).real
    grid = np.geomspace(lo, hi, 40)
    vals = []
    for scr in grid:
        try:
            vals.append(g(scr))
        except ValueError:
            vals.append(np.nan)
    vals = np.array(vals)
    for k in range(len(grid) - 1, 0, -1):
        if np.isfinite(vals[k - 1]) and vals[k] < 0 <= vals[k - 1]:
            return brentq(g, grid[k - 1], grid[k], xtol=1e-6)
    return None


def critical_scr_admittance(p: GFLParams, lo: float, hi: float) -> float:
    """道 2: det(Y_c + Y_g) の零点のうち実部が最大のものが 0 になる SCR。lo は不安定、hi は安定の側。"""
    def g(scr):
        z = admittance_zeros(p.replace(scr=scr))
        z = z[z.imag > 2 * math.pi * 0.5]
        return float(z.real.max())
    return brentq(g, lo, hi, xtol=1e-6)
