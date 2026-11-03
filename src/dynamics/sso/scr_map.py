"""臨界 SCR を AGJ の各点に当てる — SSO 第 2 段 段 C(2026-11-02).

計画: docs/reports/sso_ibr_literature_2026-10-31.md の「段 C」。
段 A の GFL 1 台の模型(gfl.py。3 つの道で確かめた)で、制御の定数の幅・力率・網の X/R・
定格周波数ごとに臨界 SCR(SCR を下げていき、振動が育ち始める SCR)の表を作る。
各点の短絡容量 S_sc と X/R(src/powerflow/short_circuit.py)に当てると、
その点に 1 か所でつなぐとき、何 MVA で振動が育ち始めるか(S_on = S_sc / SCR_crit)が出る。
インバータが近くに集まる所は、一般化 SCR(GSCR2018)で見る。

言えないこと:
  - 実機の制御の定数は公開されていない。答えは「この定数の幅なら」の地図で、予言ではない。
  - 外側の制御(P・Q)は入れていない。段 B の続きで、入れると臨界が動くのを見た。
  - 網はテブナン等価(1 つの R + L)。ケーブルの容量や網の共振(super 側)は見ない。
"""
from __future__ import annotations

import itertools
import math

import numpy as np

from . import gfl

# ── 典型値の表(この段で振る幅はここだけに置く) ─────────────────────────────
# PLL の固有周波数 ω_n/2π [Hz](ζ 0.707)。上は段 A の走査の端(100 Hz)。下は REAL20HZ2022 の
# PLL の帯域(本文 16・20・33 Hz、段 B で計算と一致)を 2 次の PLL の ω_n に直した値の下の端
# (ζ 0.707 の −3 dB 帯域は 2.06 ω_n なので 16 Hz → 約 8 Hz)。
PLL_HZ = (8.0, 15.0, 25.0, 40.0, 70.0, 100.0)
# 電流制御の帯域 α_cc/2π [Hz]。段 A と同じ(内部モデル制御の規則、HARNEFORS1998)。
CC_HZ = (150.0, 300.0, 600.0)
# 連系点の電圧のフィードフォワード(段 A の k_ff)。無し・有り。
FF = (0.0, 1.0)
# 力率(電流は定格 1 pu。符号 +1 はインバータが無効電力を吸う側、−1 は出す側)
PF_CASES = (("1.00", 1.0, 0), ("0.95 吸う", 0.95, 1), ("0.90 吸う", 0.90, 1), ("0.95 出す", 0.95, -1))
# 表を作る X/R(点の X/R はこの間を対数で補間し、外は端の値にする)
XR_GRID = (1.5, 2.0, 3.0, 5.0, 8.0, 13.0, 20.0, 30.0, 50.0)
SCR_LO, SCR_HI = 1.05, 10.0   # 臨界を探す範囲(1.05 未満は静的な限界に近く、模型の外)


def param_sets() -> list[dict]:
    """制御の定数の組(PLL × 電流制御 × フィードフォワード)。"""
    return [dict(f_pll=a, f_cc=b, k_ff=c) for a, b, c in itertools.product(PLL_HZ, CC_HZ, FF)]


def currents(pf: float, sign: int) -> tuple[float, float]:
    """定格電流 1 pu で力率 pf のときの (i_d, i_q)。i_q > 0 で網から無効電力を吸う。"""
    return pf, sign * math.sqrt(max(1.0 - pf * pf, 0.0))


def critical_scr(p: gfl.GFLParams) -> float:
    """臨界 SCR。SCR_HI でも育つなら inf、SCR_LO まで下げても育たないなら SCR_LO(静的な限界が先)。"""
    if gfl.critical_mode(gfl.eigenvalues(p.replace(scr=SCR_HI))).real >= 0:
        return math.inf
    c = gfl.critical_scr_eig(p, lo=SCR_LO, hi=SCR_HI)
    return SCR_LO if c is None else float(c)


def critical_point(p: gfl.GFLParams) -> tuple[float, float]:
    """(臨界 SCR, そこで育つモードの網の dq の周波数 f_dq [Hz])。臨界が SCR_LO・inf なら f_dq は nan。

    相の量では f0 − f_dq と f0 + f_dq の組で出る。f_dq < f0 なら片方が f0 より下(sub の帯)。
    """
    c = critical_scr(p)
    if not SCR_LO < c < math.inf:
        return c, math.nan
    return c, float(gfl.critical_mode(gfl.eigenvalues(p.replace(scr=c))).imag / (2 * math.pi))


def critical_table(f0: float, sets: list[dict] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """臨界 SCR と、そこでのモードの f_dq の表。形はどちらも (定数の組, 力率, X/R)。"""
    sets = param_sets() if sets is None else sets
    scr = np.empty((len(sets), len(PF_CASES), len(XR_GRID)))
    fdq = np.empty_like(scr)
    for i, kw in enumerate(sets):
        for j, (_lab, pf, sg) in enumerate(PF_CASES):
            i_d, i_q = currents(pf, sg)
            base = gfl.GFLParams(f0=f0, i_d_ref=i_d, i_q_ref=i_q, **kw)
            for k, xr in enumerate(XR_GRID):
                scr[i, j, k], fdq[i, j, k] = critical_point(base.replace(xr_g=xr))
    return scr, fdq


def summarize(scr: np.ndarray, fdq: np.ndarray, f0: float) -> dict:
    """定数の組をまたいだ要約(力率 × X/R)。

    max: すべての組の最大。max_sub: 臨界のモードが sub の帯(f_dq < f0)の組だけの最大
    (無ければ SCR_LO)。median・min: すべての組の中央値と最小。
    """
    sub = np.where(fdq < f0, scr, np.nan)
    with np.errstate(all="ignore"):
        max_sub = np.where(np.isfinite(sub).any(0), np.nanmax(np.where(np.isfinite(sub), sub, -np.inf), 0), SCR_LO)
    return dict(max=scr.max(0), max_sub=max_sub, median=np.median(scr, 0), min=scr.min(0))


def at_xr(curve, xr) -> np.ndarray:
    """X/R の格子の上の値 curve を、点の X/R で対数補間する(格子の外は端の値)。"""
    x = np.log(np.clip(np.asarray(xr, dtype=float), XR_GRID[0], XR_GRID[-1]))
    return np.interp(x, np.log(XR_GRID), np.asarray(curve, dtype=float))


def onset_mva(s_sc_mva, scr_crit) -> np.ndarray:
    """1 か所でつなぐとき、振動が育ち始めるインバータの定格 [MVA](= S_sc / SCR_crit)。"""
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.asarray(s_sc_mva, dtype=float) / np.asarray(scr_crit, dtype=float)


def gscr(z_pu: np.ndarray, s_mva: np.ndarray, base_mva: float) -> tuple[np.ndarray, np.ndarray]:
    """一般化 SCR(GSCR2018)。diag(S)⁻¹ · base · Z⁻¹ の固有値の大きさを小さい順に、
    各固有ベクトルの点ごとの重み(|v|²、列の和が 1)と返す。

    1 点なら S_sc/S と一致する。GSCR2018 は無損失の網で定義する。ここでは Z の偏角が点で違っても
    そのまま複素の固有値の大きさを取る(偏角がそろえば無損失の定義と同じ値)。
    """
    y = np.linalg.inv(z_pu) * base_mva
    lam, vec = np.linalg.eig(y / np.asarray(s_mva, dtype=float)[:, None])
    order = np.argsort(np.abs(lam))
    w = np.abs(vec[:, order]) ** 2
    return np.abs(lam[order]), w / w.sum(axis=0)
