#!/usr/bin/env python3
"""SSO 第 2 段 段 B: 公表例 REAL20HZ2022 を本文の定数で解き、本文の数字と突き合わせる(2026-11-01).

    python scripts/sso_stage_b.py

出力(docs/reports/sso_ibr_stage_b_2026-11-01/):
  results.json     本文の値・計算した値・3 つの道の一致
  pll.png          PLL の G_PLL と、本文 III-B の簡単な例の臨界
  case1.png        Case 1: Z_grid + Z_PV の谷と 22 Hz のモード(本文の定数と、K_p を 1/10 にした仮説)
  case3.png        Case 3: 臨界の i_d とコンデンサの有無
  signature.png    道 3 の相電流の sub と super の振幅(本文の「しるし」)
docs/reports/sso_ibr_stage_b_2026-11-01.md の「<!-- 表:begin -->」から「<!-- 表:end -->」までを書き換える。
模型と道は src/dynamics/sso/gfl_pr.py。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.dynamics.sso import gfl_pr as m  # noqa: E402
from src.dynamics.sso.gfl import pair_from_modes  # noqa: E402

OUT = ROOT / "docs/reports/sso_ibr_stage_b_2026-11-01"
REPORT = ROOT / "docs/reports/sso_ibr_stage_b_2026-11-01.md"

# 本文の値(REAL20HZ2022、OSTI 1897735 の著者版。節は本文の番号)
PAPER = dict(
    pll_bw={"PLL1": 16, "PLL2": 20, "PLL3": 33, "PLL4": 33},                 # III-B
    simple={"PLL4": dict(k=0.38, f=23), "PLL3": dict(gain_margin=1.87)},     # III-B
    case1_pll_poles="−47 ± j80(約 13 Hz)",                                     # IV-A
    case2_pll_poles="−7 ± j132",                                              # IV-B
    case3_critical_id=dict(shunt=1.18, no_shunt=3.31),                        # IV-C
    rms_hz=dict(case1=22, case2=20, case3=27),
)
# 本文の定数
SLOW = dict(kp_cc=0.35, kr_cc=2.0, t_d=200e-6)                  # Case 1 の遅い制御
FAST100 = dict(kp_cc=1.0, kr_cc=10.0, t_d=100e-6)               # Case 1 の比べる速い制御
PLL = {"PLL1": dict(kp_pll=60.0, ki_pll=1400.0, lpf_order=1), "PLL2": dict(kp_pll=60.0, ki_pll=1400.0, lpf_order=2),
       "PLL3": dict(kp_pll=150.0, ki_pll=2000.0, lpf_order=1), "PLL4": dict(kp_pll=150.0, ki_pll=2000.0, lpf_order=2)}
PLL_C1 = dict(kp_pll=100.0, ki_pll=2000.0, lpf_order=1)         # Case 1 の本文の式
PLL_C2 = dict(kp_pll=150.0, ki_pll=3000.0, lpf_order=2)         # Case 2 の式 (19)(PRParams の既定)
CASE3 = dict(x_g=0.37, r_g=0.37 / 8, t_d=50e-6)                 # Case 3: 線路が 1 本落ちた後
HYP_KP = 0.035                                                  # Case 1 の仮説: K_p を本文の 1/10
# 合格の条件(段 A と同じ): 道 1 と道 2 は |Δs| ≤ 1e-6 |s|・モードの数が同じ。道 1 と道 3 は周波数 0.01 Hz・
# σ 0.05 1/s・super/sub の振幅の比 1% 以内。
TOL = dict(rel=1e-6, f_hz=0.01, sigma=0.05, ratio_rel=0.01)
BAND = (0.5, 200.0)          # 比べるモードの周波数の範囲 [Hz](網の dq)
COL = ["#1f4e8c", "#c06014", "#2a7f62"]
INK, MUTED, GRID = "#1d2226", "#59616a", "#8a9099"
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]


def r6(x):
    return None if x is None else float(f"{x:.6g}")


def cpx(z):
    return None if z is None else [r6(z.real), r6(z.imag / (2 * math.pi))]


def band_modes(lam, lo=BAND[0], hi=BAND[1]):
    return lam[(lam.imag > 2 * math.pi * lo) & (lam.imag < 2 * math.pi * hi)]


def mode_in(p, lo, hi):
    """lo〜hi Hz の固有値のうち実部が最大のもの(無ければ None)。"""
    osc = band_modes(m.eigenvalues(p), lo, hi)
    return complex(osc[np.argmax(osc.real)]) if osc.size else None


# ---------------------------------------------------------------- B-1: PLL と簡単な例
def pll_rows() -> list:
    f = np.logspace(-1, 3, 40001)
    s = 2j * np.pi * f
    rows = []
    for name, kw in list(PLL.items()) + [("Case 1 の式", PLL_C1), ("Case 2 の式 (19)", PLL_C2)]:
        p = m.PRParams(**kw)
        g = np.abs(m.g_pll(p, s))
        bw = f[np.nonzero(g < 1 / math.sqrt(2))[0][0]]
        wn = 2 * math.pi * p.f_lpf
        d_l = [1.0, wn] if p.lpf_order == 1 else [1.0, 2 * p.zeta_lpf * wn, wn * wn]
        n_l = [wn] if p.lpf_order == 1 else [wn * wn]
        poles = np.roots(np.polyadd(np.polymul([1.0, 0.0, 0.0], d_l), np.polymul([p.kp_pll, p.ki_pll], n_l)))
        pc = poles[poles.imag > 0]
        rows.append(dict(name=name, kp=p.kp_pll, ki=p.ki_pll, lpf=p.lpf_order, bw_hz=r6(bw),
                         paper_bw_hz=PAPER["pll_bw"].get(name), peak_db=r6(20 * math.log10(g.max())),
                         peak_hz=r6(f[np.argmax(g)]), poles=[[r6(z.real), r6(z.imag)] for z in pc]))
    return rows


def simple_rows() -> list:
    rows = []
    for name in ("PLL3", "PLL4"):
        p = m.PRParams(**PLL[name])
        k, fc = m.simple_critical(p)
        chk, dev = [], 0.0
        for kk in (0.95 * k, 1.05 * k):
            r = m.simple_roots(p, kk)
            lc = r[np.argmax(r.real)]
            md = max((q for q in m.simple_simulate(p, kk) if q[0] > 5), key=lambda q: q[2])
            dev = max(dev, abs(lc.real - md[1]), abs(abs(lc.imag) / (2 * math.pi) - md[0]))
            chk.append(dict(k=r6(kk), lin=[r6(lc.real), r6(abs(lc.imag) / (2 * math.pi))], nonlin=[r6(md[1]), r6(md[0])]))
        rows.append(dict(name=name, k_crit=r6(k), f_hz=r6(fc), paper=PAPER["simple"][name], check=chk, max_dev=r6(dev)))
    return rows


# ---------------------------------------------------------------- B-2: Hydro One の試験系統
def case1_rows() -> list:
    f = np.linspace(5, 300, 29501)
    s = 2j * np.pi * f
    rows = []
    for lab, kp in (("本文の定数 K_p 0.35", SLOW["kp_cc"]), (f"仮説 K_p {HYP_KP}", HYP_KP)):
        p = m.PRParams(**{**SLOW, "kp_cc": kp}, **PLL_C1)
        tot = np.abs(m.z_grid(p, s) + m.z_pv(p, s)[1])
        k = int(np.argmin(tot))
        modes = {f"{d:g}": cpx(mode_in(p.replace(i_d=d), 15, 30)) for d in (0.0, 0.1, 0.5, 1.0)}
        rows.append(dict(label=lab, kp_cc=kp, dip_db=r6(20 * math.log10(tot[k])), dip_hz=r6(f[k]), mode_15_30hz=modes,
                         no_shunt=cpx(mode_in(p.replace(i_d=0.1, b_c=0.0), 15, 30)),
                         pll_case1_text=cpx(mode_in(p.replace(i_d=0.1), 15, 30)),
                         pll2=cpx(mode_in(p.replace(i_d=0.1, **PLL["PLL2"]), 15, 30))))
    fast = m.PRParams(**FAST100, **PLL_C1, i_d=0.1)
    rows.append(dict(label="速い制御(本文)", fast_mode_15_30hz=cpx(mode_in(fast, 15, 30))))
    return rows


def case2_rows() -> list:
    rows = []
    for lab, kw in (("本文の式 (19)(速い PLL・2 次の LPF)", PLL_C2), ("遅い PLL(60, 1400・2 次の LPF)", PLL["PLL2"]),
                    ("式 (19) の LPF を 1 次に", {**PLL_C2, "lpf_order": 1})):
        p = m.PRParams(**kw)
        rows.append(dict(label=lab, modes={f"{d:g}": cpx(mode_in(p.replace(i_d=d), 5, 60)) for d in (0.1, 0.5, 1.0)},
                         critical_id=r6(m.critical_id_eig(p, lo=0.05, hi=6.0))))
    return rows


def case3_rows() -> list:
    rows = []
    cands =[("Case 1 の式 (100, 2000)", PLL_C1), ("PLL1 (60, 1400)", PLL["PLL1"]), ("PLL3 (150, 2000)", PLL["PLL3"])]
    for lab, kw in cands:
        row = dict(label=lab)
        for key, extra in (("shunt", {}), ("no_shunt", {"b_c": 0.0})):
            p = m.PRParams(**CASE3, **kw, **extra)
            c = m.critical_id_eig(p, lo=0.05, hi=6.0)
            lc = m.critical_mode(m.eigenvalues(p.replace(i_d=c))) if c else None
            row[key] = dict(critical_id=r6(c), f_hz=r6(lc.imag / (2 * math.pi)) if lc else None)
        rows.append(row)
    sens = {}
    for v in (0.95, 1.05):
        p = m.PRParams(**CASE3, **PLL["PLL3"], v_pcc=v)
        sens[f"{v:g}"] = dict(shunt=r6(m.critical_id_eig(p, lo=0.05, hi=6.0)),
                              no_shunt=r6(m.critical_id_eig(p.replace(b_c=0.0), lo=0.05, hi=6.0)))
    return rows, sens


# ---------------------------------------------------------------- 3 つの道
ROUTE_POINTS = [
    ("Case 1 本文の定数 i_d 0.1", dict(**SLOW, **PLL_C1, i_d=0.1), False),
    ("Case 1 仮説 i_d 0.1", dict(**{**SLOW, "kp_cc": HYP_KP}, **PLL_C1, i_d=0.1), True),
    ("Case 2 i_d 1.0", dict(i_d=1.0), True),
    ("Case 3 PLL3 i_d 1.1", dict(**CASE3, **PLL["PLL3"], i_d=1.1), True),
    ("Case 3 PLL3 i_d 1.3", dict(**CASE3, **PLL["PLL3"], i_d=1.3), True),
]


def route_point(lab: str, kw: dict, td: bool) -> dict:
    p = m.PRParams(**kw)
    a = m.state_matrix(p)
    lam, vec = np.linalg.eig(a)
    osc = band_modes(lam)
    z = m.loop_zeros(p, f_max=BAND[1])
    z = z[z.imag > 2 * math.pi * BAND[0]]
    err = max(float(np.min(np.abs(osc - x)) / abs(x)) for x in z) if z.size else None
    out = dict(label=lab, n_eig=int(osc.size), n_zero=int(z.size), max_rel=r6(err),
               modes=[cpx(x) for x in sorted(osc, key=lambda x: -x.real)])
    out["passed"] = dict(route12=bool(z.size == osc.size and err is not None and err <= TOL["rel"]))
    if td:
        k = max((j for j in range(lam.size) if 2 * math.pi * 5 < lam[j].imag < 2 * math.pi * 60), key=lambda j: lam[j].real)
        lc = lam[k]
        ratio = abs(vec[0, k] + 1j * vec[1, k]) / abs(vec[0, k] - 1j * vec[1, k])       # 電流の super / sub
        f_dq = lc.imag / (2 * math.pi)
        sim = m.simulate(p, t_end=1.0)
        (fs, ss), (fp, sp) = pair_from_modes(sim.modes, p.f0, f_dq)
        a_sub = min(sim.modes, key=lambda q: abs(q[0] - fs))[2]
        a_sup = min(sim.modes, key=lambda q: abs(q[0] - fp))[2]
        out.update(route1=dict(sigma=r6(lc.real), f_dq=r6(f_dq), super_over_sub=r6(ratio)),
                   route3=dict(f_sub=r6(fs), sigma_sub=r6(ss), f_sup=r6(fp), sigma_sup=r6(sp),
                               super_over_sub=r6(a_sup / a_sub), fit=[r6(x) for x in sim.fit]))
        out["passed"]["route13"] = bool(abs(fs - (p.f0 - f_dq)) <= TOL["f_hz"] and abs(fp - (p.f0 + f_dq)) <= TOL["f_hz"]
                                        and abs(ss - lc.real) <= TOL["sigma"] and abs(sp - lc.real) <= TOL["sigma"]
                                        and abs(a_sup / a_sub / ratio - 1) <= TOL["ratio_rel"])
        out["_sim"] = sim
    return out


def critical_loop_rows() -> list:
    rows = []
    for key, extra in (("shunt", {}), ("no_shunt", {"b_c": 0.0})):
        p = m.PRParams(**CASE3, **PLL["PLL3"], **extra)
        c1 = m.critical_id_eig(p, lo=0.05, hi=6.0)
        c2 = m.critical_id_loop(p, c1 * 0.97, c1 * 1.03)
        rows.append(dict(key=key, route1=r6(c1), route2=r6(c2)))
    return rows


# ---------------------------------------------------------------- 図
def _ax(ax):
    ax.grid(color=GRID, alpha=0.25, lw=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=9)


def fig_pll(path: Path, simple: list) -> None:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 4.0))
    f = np.logspace(0, 2.5, 2000)
    s = 2j * np.pi * f
    sty = {"PLL1": (COL[0], "-"), "PLL2": (COL[0], "--"), "PLL3": (COL[1], "-"), "PLL4": (COL[1], "--")}
    for name, kw in PLL.items():
        c, ls = sty[name]
        a1.semilogx(f, 20 * np.log10(np.abs(m.g_pll(m.PRParams(**kw), s))), color=c, ls=ls, lw=1.6,
                    label=f"{name}({int(kw['kp_pll'])}, {int(kw['ki_pll'])}・{kw['lpf_order']} 次の LPF)")
    a1.axhline(-3, color=GRID, lw=0.8, ls=":")
    a1.set_xlabel("周波数 [Hz]", color=INK)
    a1.set_ylabel("|G_PLL| [dB]", color=INK)
    a1.set_ylim(-30, 18)
    a1.set_title("PLL の G_PLL(本文の Fig. 6(a) に当たる)", color=INK, fontsize=11, loc="left")
    a1.legend(fontsize=8, frameon=False, loc="lower left")
    _ax(a1)
    for row, c in zip(simple, (COL[1], COL[1])):
        p = m.PRParams(**PLL[row["name"]])
        ks = np.linspace(0.05, 2.6, 400)
        sg = [m.simple_roots(p, k).real.max() for k in ks]
        ls = "-" if row["name"] == "PLL3" else "--"
        a2.plot(ks, sg, color=c, ls=ls, lw=1.6, label=f"{row['name']}(計算の臨界 {row['k_crit']:.3f})")
        a2.plot([row["k_crit"]], [0], "o", color=c, ms=6)
    a2.axhline(0, color=INK, lw=0.8)
    for kx, txt in ((0.38, "本文: PLL4 は 0.38 で不安定"), (1.87, "本文: PLL3 の利得余裕 1.87")):
        a2.axvline(kx, color=MUTED, lw=1.0, ls=":")
        a2.text(kx + 0.03, -12, txt, rotation=90, va="bottom", ha="left", color=MUTED, fontsize=8.5)
    a2.set_xlabel("k = i_d X_g [pu]", color=INK)
    a2.set_ylabel("一番右の極の実部 σ [1/s]", color=INK)
    a2.set_title("簡単な例(理想の電流源 + 純リアクタンス)", color=INK, fontsize=11, loc="left")
    a2.legend(fontsize=8.5, frameon=False, loc="upper left")
    _ax(a2)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_case1(path: Path) -> None:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 4.0))
    f = np.linspace(5, 300, 3000)
    s = 2j * np.pi * f
    for (lab, kp), c in zip(((f"本文の定数 K_p {SLOW['kp_cc']}", SLOW["kp_cc"]), (f"仮説 K_p {HYP_KP}", HYP_KP)), (COL[0], COL[1])):
        p = m.PRParams(**{**SLOW, "kp_cc": kp}, **PLL_C1)
        a1.plot(f, 20 * np.log10(np.abs(m.z_grid(p, s) + m.z_pv(p, s)[1])), color=c, lw=1.6, label=lab)
    a1.plot([80], [-20], "s", color=MUTED, ms=6)
    a1.annotate("本文: 約 80 Hz で −20 dB に近い谷", (80, -20), xytext=(115, -17), color=MUTED, fontsize=8.5,
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6))
    a1.set_xlabel("周波数 [Hz](静止座標)", color=INK)
    a1.set_ylabel("|Z_grid + Z_PV| [dB]", color=INK)
    a1.set_title("Case 1: 遅い電流制御と網のインピーダンスの和", color=INK, fontsize=11, loc="left")
    a1.legend(fontsize=8.5, frameon=False, loc="upper right")
    _ax(a1)
    p = m.PRParams(**{**SLOW, "kp_cc": HYP_KP}, **PLL_C1)
    ds = np.linspace(0.0, 1.5, 31)
    loc = [mode_in(p.replace(i_d=d), 12, 30) for d in ds]
    a2.plot([z.real for z in loc], [z.imag / (2 * math.pi) for z in loc], "-o", color=COL[1], ms=3, lw=1.2)
    for d, z in zip(ds, loc):
        if d in (0.0, 0.5, 1.0, 1.5):
            a2.annotate(f"i_d {d:g}", (z.real, z.imag / (2 * math.pi)), xytext=(5, 4), textcoords="offset points",
                        color=MUTED, fontsize=8.5)
    a2.axvline(0, color=INK, lw=0.8)
    a2.set_xlabel("σ [1/s]", color=INK)
    a2.set_ylabel("網の dq の周波数 [Hz]", color=INK)
    a2.set_title(f"仮説 K_p {HYP_KP}: 22 Hz のモード(道 1)", color=INK, fontsize=11, loc="left")
    _ax(a2)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_case3(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    ds = np.linspace(0.05, 4.0, 160)
    for (lab, extra), c, key in ((("コンデンサあり", {}), COL[1], "shunt"), (("コンデンサなし", {"b_c": 0.0}), COL[0], "no_shunt")):
        p = m.PRParams(**CASE3, **PLL["PLL3"], **extra)
        sg = [m.eigenvalues(p.replace(i_d=d)).real.max() for d in ds]
        ax.plot(ds, sg, color=c, lw=1.6, label=lab)
        pv = PAPER["case3_critical_id"][key]
        ax.plot([pv], [0], "v", color=c, ms=7)
        ax.annotate(f"本文 {pv}", (pv, 0), xytext=(4, -16), textcoords="offset points", color=c, fontsize=8.5)
    ax.axhline(0, color=INK, lw=0.8)
    ax.set_xlabel("i_d [pu]", color=INK)
    ax.set_ylabel("一番右の固有値の実部 σ [1/s]", color=INK)
    ax.set_title("Case 3(SCR 約 1.8・PLL3): i_d を上げたときの一番右の固有値(道 1)", color=INK, fontsize=11, loc="left")
    ax.legend(fontsize=9, frameon=False, loc="upper left")
    _ax(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_signature(path: Path, pts: list) -> None:
    sel = [x for x in pts if "_sim" in x and x["label"] != "Case 3 PLL3 i_d 1.3"]
    fig, axes = plt.subplots(1, len(sel), figsize=(11.0, 3.6), sharey=True)
    for ax, x in zip(axes, sel):
        modes = x["_sim"].modes
        big = max(q[2] for q in modes)
        for q in modes:
            if q[2] < 1e-4 * big or q[0] > 150:
                continue
            on = abs(q[0] - x["route3"]["f_sub"]) < 0.01 or abs(q[0] - x["route3"]["f_sup"]) < 0.01
            ax.vlines(q[0], 1e-4, q[2] / big, color=COL[1] if on else GRID, lw=2.2 if on else 1.2)
            if on:
                ax.annotate(f"{q[0]:.1f} Hz", (q[0], q[2] / big), xytext=(0, 4), textcoords="offset points",
                            ha="center", color=INK, fontsize=8.5)
        ax.axvline(60, color=GRID, lw=0.6, ls=":")
        ax.set_yscale("log")
        ax.set_ylim(1e-4, 3)
        ax.set_xlim(0, 150)
        ax.set_xlabel("相電流の周波数 [Hz]", color=INK)
        ax.set_title(f"{x['label']}\nsuper/sub = {x['route3']['super_over_sub']:.3g}", color=INK, fontsize=10, loc="left")
        _ax(ax)
    axes[0].set_ylabel("振幅(最大で割る)", color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- 表
def _z(z):
    return "—" if z is None else f"{z[0]:.2f} / {z[1]:.2f} Hz"


def tables(res: dict) -> str:
    t = ["**表 1 PLL(本文 III-B と IV)**", "",
         "| PLL | K_p, K_i | LPF | 帯域(計算)| 帯域(本文)| 閉ループの極(計算)|", "|---|---|---|---|---|---|"]
    for r in res["pll"]:
        poles = ", ".join(f"{a:.2f} ± j{b:.2f}" for a, b in r["poles"])
        t.append(f"| {r['name']} | {r['kp']:g}, {r['ki']:g} | {r['lpf']} 次 | {r['bw_hz']:.1f} Hz | "
                 f"{'' if r['paper_bw_hz'] is None else str(r['paper_bw_hz']) + ' Hz'} | {poles} |")
    t.append(f"\n本文の極: Case 1 は {PAPER['case1_pll_poles']}、Case 2 は {PAPER['case2_pll_poles']}。\n")
    t += ["**表 2 簡単な例の臨界(本文 III-B)**", "",
          "| PLL | 臨界の k = i_d X_g(計算)| 振動 | 本文 | 非線形の積分との差(臨界の ±5% で σ [1/s] と f [Hz] の大きい方)|",
          "|---|---|---|---|---|"]
    for r in res["simple"]:
        pv = r["paper"]
        ptxt = f"k {pv['k']}・{pv['f']} Hz" if "k" in pv else f"利得余裕 {pv['gain_margin']}"
        t.append(f"| {r['name']} | {r['k_crit']:.4f} | {r['f_hz']:.2f} Hz | {ptxt} | {r['max_dev']:.1e} |")
    t += ["", "**表 3 Case 1(遅い電流制御、i_d は PLL の座標の電流の指令)**", "",
          "| 定数 | Z_grid+Z_PV の谷 | 15〜30 Hz のモード σ / f(i_d 0・0.1・0.5・1.0)| コンデンサなし(i_d 0.1)| PLL2 にしたとき |",
          "|---|---|---|---|---|"]
    for r in res["case1"][:2]:
        ms = "・".join(_z(r["mode_15_30hz"][k]) for k in ("0", "0.1", "0.5", "1"))
        t.append(f"| {r['label']} | {r['dip_db']:.1f} dB @ {r['dip_hz']:.1f} Hz | {ms} | {_z(r['no_shunt'])} | {_z(r['pll2'])} |")
    t.append(f"\n速い制御(本文の K_p 1・K_r 10・100 µs)の 15〜30 Hz のモード: {_z(res['case1'][2]['fast_mode_15_30hz'])}。\n")
    t += ["**表 4 Case 2(速い電流制御・50 µs)**", "",
          "| PLL | 5〜60 Hz のモード σ / f(i_d 0.1・0.5・1.0)| 臨界の i_d |", "|---|---|---|"]
    for r in res["case2"]:
        ms = "・".join(_z(r["modes"][k]) for k in ("0.1", "0.5", "1"))
        crit = "—" if r["critical_id"] is None else f"{r['critical_id']:.3f}"
        t.append(f"| {r['label']} | {ms} | {crit} |")
    t += ["", "**表 5 Case 3 の臨界の i_d(本文: コンデンサあり 1.18・なし 3.31)**", "",
          "| PLL(1 次の LPF)| コンデンサあり | コンデンサなし |", "|---|---|---|"]
    for r in res["case3"]:
        cell = lambda d: "—" if d["critical_id"] is None else f"{d['critical_id']:.3f}({d['f_hz']:.1f} Hz)"
        t.append(f"| {r['label']} | {cell(r['shunt'])} | {cell(r['no_shunt'])} |")
    sens = res["case3_vpcc"]
    t.append(f"\nPLL3 で PCC の電圧を 0.95 / 1.05 pu にすると: コンデンサあり {sens['0.95']['shunt']:.3f} / "
             f"{sens['1.05']['shunt']:.3f}、なし {sens['0.95']['no_shunt']:.3f} / {sens['1.05']['no_shunt']:.3f}。"
             f"道 2 で出した臨界: " + "、".join(f"{'あり' if r['key'] == 'shunt' else 'なし'} {r['route2']:.4f}(道 1 {r['route1']:.4f})"
                                         for r in res["case3_loop"]) + "。\n")
    t += ["**表 6 3 つの道**", "",
          f"| 点 | モードの数(道 1 / 道 2、{BAND[0]:g}〜{BAND[1]:g} Hz)| 道 1–2 の差(相対の最大)| 道 1: σ / f_dq / super÷sub | "
          "道 3: sub・super の周波数と σ / super÷sub | 合否 |", "|---|---|---|---|---|---|"]
    for x in res["routes"]:
        r1 = x.get("route1")
        r3 = x.get("route3")
        c1 = "—" if r1 is None else f"{r1['sigma']:.4f} / {r1['f_dq']:.4f} Hz / {r1['super_over_sub']:.4g}"
        c3 = "—" if r3 is None else (f"{r3['f_sub']:.4f} Hz {r3['sigma_sub']:.4f}・{r3['f_sup']:.4f} Hz {r3['sigma_sup']:.4f} / "
                                     f"{r3['super_over_sub']:.4g}")
        ok = "合" if all(x["passed"].values()) else "否"
        t.append(f"| {x['label']} | {x['n_eig']} / {x['n_zero']} | {x['max_rel']:.1e} | {c1} | {c3} | {ok} |")
    return "\n".join(t)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    simple = simple_rows()
    c3, sens = case3_rows()
    pts = [route_point(*x) for x in ROUTE_POINTS]
    res = dict(paper=PAPER, tolerance=TOL, pll=pll_rows(), simple=simple, case1=case1_rows(), case2=case2_rows(),
               case3=c3, case3_vpcc=sens, case3_loop=critical_loop_rows(),
               routes=[{k: v for k, v in x.items() if not k.startswith("_")} for x in pts])
    res["all_passed"] = all(all(x["passed"].values()) for x in res["routes"])
    fig_pll(OUT / "pll.png", simple)
    fig_case1(OUT / "case1.png")
    fig_case3(OUT / "case3.png")
    fig_signature(OUT / "signature.png", pts)
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if REPORT.exists():
        txt = REPORT.read_text(encoding="utf-8")
        a, b = txt.index("<!-- 表:begin -->"), txt.index("<!-- 表:end -->")
        REPORT.write_text(txt[:a] + "<!-- 表:begin -->\n\n" + tables(res) + "\n\n" + txt[b:], encoding="utf-8")
    print("all_passed:", res["all_passed"])
    for x in res["routes"]:
        print(x["label"], x["passed"])


if __name__ == "__main__":
    main()
