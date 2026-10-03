"""発散したニュートン・ラフソン反復で、プロセスごと落ちるのを防ぐ。

pandapower の NR はヤコビ行列の連立方程式を scipy の spsolve(SuperLU)で解く。反復が発散して
行列に非正規化数(~1e-310)や 1e10 を超える値が入ると、macOS(Accelerate)の BLAS は例外を出さず
「BLAS error: Parameter number 3 passed to cblas_dgemv had an invalid value」でプロセスを終了する。
Python の例外にならないので、run_powerflow の「次の解き方 → だめなら DC」の段取りが働かない。

実例(2026-10-03): 日別断面 2026-09-01 の西の島 21 時台。毎回同じ所で落ち、その日の断面が
作れなかった(scripts/export_day_flows.py)。落ちる直前の連立方程式は max|J|=1.6e10・
max|F|=1.1e11・min|diag|=4.9e-310。

ここでは spsolve の手前で、収束する計算では起きない入力(非有限・|F|>1e8・非正規化数の対角)を
LinAlgError にする。run_powerflow はそれを「この解き方は失敗」として次へ進む。
"""
from __future__ import annotations

import numpy as np

MAX_MISMATCH = 1e8   # p.u.。収束していく反復でこの大きさの不平衡は出ない
_TINY = 1e-200       # これより小さい非ゼロの対角は非正規化数 = 発散の末期


def _guarded(orig):
    def spsolve(A, b, *a, **k):
        data = getattr(A, "data", None)
        if data is not None and not np.isfinite(data).all():
            raise np.linalg.LinAlgError("NR 発散: ヤコビ行列に非有限値")
        bb = np.asarray(b)
        if not np.isfinite(bb).all() or (bb.size and np.abs(bb).max() > MAX_MISMATCH):
            raise np.linalg.LinAlgError("NR 発散: 不平衡が過大")
        if hasattr(A, "diagonal"):
            d = np.abs(A.diagonal())
            if ((d > 0) & (d < _TINY)).any():
                raise np.linalg.LinAlgError("NR 発散: 対角に非正規化数")
        return orig(A, b, *a, **k)
    spsolve._agj_guarded = True
    return spsolve


def install() -> None:
    """pandapower の NR が使う spsolve を一度だけ包む(何度呼んでもよい)。"""
    import pandapower.pypower.newtonpf as npf
    if not getattr(npf.spsolve, "_agj_guarded", False):
        npf.spsolve = _guarded(npf.spsolve)
