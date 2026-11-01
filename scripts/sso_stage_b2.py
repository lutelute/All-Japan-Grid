#!/usr/bin/env python3
"""SSO 第 2 段 段 B の続き: REAL20HZ2022 の Case 3 の EMT(27 Hz)を、外側の制御を足して解く(2026-11-01).

    python scripts/sso_stage_b2.py

段 B(scripts/sso_stage_b.py)では Case 3 の臨界の i_d は本文と合ったが、本文の EMT の 27 Hz は出なかった。
本文の図 12・13 から運転点を読み、外側の制御(本文の PI 0.2 + 20/s)と制限を足して確かめる。

出力(docs/reports/sso_ibr_stage_b2_2026-11-01/):
  results.json     図から読んだ値・計算した値
  trip.png         線路が落ちる場面(この模型。本文の図 13 と同じ量)
  modes.png        落ちた後のモードが、外側の制御の形でどこへ行くか
  spectrum.png     落ちた後の相電流と相電圧のスペクトル(本文の図 12(b)(c) と同じ量)
docs/reports/sso_ibr_stage_b2_2026-11-01.md の「<!-- 表:begin -->」から「<!-- 表:end -->」までを書き換える。
模型は src/dynamics/sso/gfl_pr.py(outer・f_meas・kv_q・i_max・v_max・df_max)。
"""
from __future__ import annotations

import json
import math
import re
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

OUT = ROOT / "docs/reports/sso_ibr_stage_b2_2026-11-01"
REPORT = ROOT / "docs/reports/sso_ibr_stage_b2_2026-11-01.md"

# 本文の値(REAL20HZ2022、OSTI 1897735 の著者版)。read_* は図から目で読んだ値で、読みの幅は ±0.05 pu ほど
PAPER = dict(
    rms_hz=27,                                                    # IV-C の本文
    phase_hz=(33, 87),                                            # IV-C の本文
    read_p=0.8,                                                   # 図 13 の P(落ちる前、両方)
    read_q=dict(shunt=(-0.55, -0.7), no_shunt=(-0.1, 0.0)),        # 図 13 の Q(落ちる前, 落ちた後)
    read_v_pll=1.0,                                               # 図 13 の V_PLL(落ちる前、両方)
    read_amp=dict(p=0.07, v_pll=0.05, f_hz=1.0),                  # 図 13 の 2.5〜4 s の振幅(片側)
    read_spec=dict(i=(3.0, 3.0), v=(1.0, 6.5)),                   # 図 12(b)(c) の 33・87 Hz [基本波の %]
    read_v_recover_s=0.4,                                         # 図 13 のコンデンサなしで V_PLL が 1 に戻るまで
)
PLL3 = dict(kp_pll=150.0, ki_pll=2000.0, lpf_order=1)          # 本文の Case 3: 1 次の LPF の PLL(段 B の PLL3)
PRE = dict(x_g=0.15, r_g=0.15 / 8)                             # 線路が 2 本(本文 IV-C)
POST = dict(x_g=0.37, r_g=0.37 / 8)                            # 1 本落ちた後
SHUNT = {"shunt": {}, "no_shunt": {"b_c": 0.0}}
P_OP = PAPER["read_p"]
P_SWEEP = (0.7, 0.75, 0.8, 0.85, 0.9)
KV = 7.0                                                       # 図 13 のコンデンサなしの電圧の戻り(約 0.4 s)に合わせた
KV_SWEEP = (5.0, 10.0)
T_EVENT, T_END, FS = 0.3, 2.3, 5000.0
# 外側の制御の形(落ちた後のモードを比べる)。kw は with_outer の後に足す
VARIANTS = [
    ("外側なし(本文の線形模型)", "", {}),
    ("P・Q(濾波なし)", "pq", {}),
    ("P・Q(濾波 100 Hz)", "pq", {"f_meas": 100.0}),
    (f"P・Q + Q の指令を電圧で(利得 {KV:g})", "pq", {"kv_q": KV}),
    ("P・V(濾波なし)", "pv", {}),
    ("P・V(濾波 10 Hz)", "pv", {"f_meas": 10.0}),
]
LIMITS = [("制限なし", {}), ("電流 1.1 pu", {"i_max": 1.1}), ("電圧の指令 1.2 pu", {"v_max": 1.2}),
          ("PLL の周波数 ±5 Hz", {"df_max": 5.0})]
COL = ["#1f4e8c", "#c06014", "#2a7f62", "#7a4a9e", "#8a6d1a", "#b0303a"]
INK, MUTED, GRID = "#1d2226", "#59616a", "#8a9099"
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]


def r6(x):
    return None if x is None else float(f"{x:.6g}")


def mode_in(p, lo=15.0, hi=45.0):
    lam = m.eigenvalues(p)
    osc = lam[(lam.imag > 2 * math.pi * lo) & (lam.imag < 2 * math.pi * hi)]
    return complex(osc[np.argmax(osc.real)]) if osc.size else None


def cpx(z):
    return None if z is None else dict(sigma=r6(z.real), f_hz=r6(z.imag / (2 * math.pi)))


def operating(net: dict, shunt: str, p_out: float = P_OP) -> m.PRParams:
    """電源 1 pu・|v_pcc| 1 pu・P = p_out の運転点(本文の図 13 の読みの仮説)。"""
    return m.at_source(m.PRParams(**net, **SHUNT[shunt], **PLL3), p_out, 1.0)


def variant(p: m.PRParams, outer: str, kw: dict) -> m.PRParams:
    return m.with_outer(p, outer).replace(**kw) if outer else p.replace(**kw)


# ---------------------------------------------------------------- 表
def op_rows() -> list:
    rows = []
    for sh in SHUNT:
        for k, net in enumerate((PRE, POST)):
            p = operating(net, sh)
            eq = m.equilibrium(p)
            rows.append(dict(shunt=sh, after_trip=bool(k), i_d=r6(p.i_d), i_q=r6(p.i_q), q=r6(eq.q_out),
                             q_read=PAPER["read_q"][sh][k], mode=cpx(mode_in(p, 0.5, 200.0))))
    return rows


def variant_rows() -> list:
    rows = []
    for lab, outer, kw in VARIANTS:
        z = {sh: mode_in(variant(operating(POST, sh), outer, kw)) for sh in SHUNT}
        pre = variant(operating(PRE, "shunt"), outer, kw)
        rows.append(dict(label=lab, outer=outer, **{k: r6(v) for k, v in kw.items()},
                         shunt=cpx(z["shunt"]), no_shunt=cpx(z["no_shunt"]),
                         pre_max_sigma=r6(float(m.eigenvalues(pre).real.max()))))
    return rows


def p_sweep_rows() -> list:
    rows = []
    for pv in P_SWEEP:
        p = operating(POST, "shunt", pv)
        rows.append(dict(p=pv, q=r6(m.equilibrium(p).q_out), none=cpx(mode_in(p)),
                         pq=cpx(mode_in(variant(p, "pq", {}))), pq100=cpx(mode_in(variant(p, "pq", {"f_meas": 100.0}))),
                         pq_kv=cpx(mode_in(variant(p, "pq", {"kv_q": KV})))))
    return rows


def route_rows() -> list:
    """落ちた後の運転点(i_q ≠ 0)で、道 1 と道 2、道 1 と道 3 がそろうか。"""
    p = operating(POST, "shunt")
    lam = m.eigenvalues(p)
    lam = lam[(lam.imag > 2 * math.pi * 0.5) & (lam.imag < 2 * math.pi * 200.0)]
    z = m.loop_zeros(p)
    rel = max(min(abs(x - y) for y in z) / abs(x) for x in lam)
    out = [dict(label="外側なし", route="1-2", n_eig=int(lam.size), n_zero=int(z.size), max_rel=r6(rel),
                passed=bool(lam.size == z.size and rel < 1e-6))]
    for lab, outer, kw in VARIANTS[1:4]:
        q = variant(p, outer, kw)
        a = m.state_matrix(q)
        ev, vec = np.linalg.eig(a)
        k = max((j for j in range(ev.size) if 2 * math.pi * 15 < ev[j].imag < 2 * math.pi * 45), key=lambda j: ev[j].real)
        f_dq = ev[k].imag / (2 * math.pi)
        r = m.simulate(q, t_end=0.6)
        (fs, ss), (fp, sp) = pair_from_modes(r.modes, q.f0, f_dq)
        df = max(abs(fs - (q.f0 - f_dq)), abs(fp - (q.f0 + f_dq)))
        ds = max(abs(ss - ev[k].real), abs(sp - ev[k].real))
        out.append(dict(label=lab, route="1-3", f_dq=r6(f_dq), sigma=r6(ev[k].real), df_hz=r6(df), dsigma=r6(ds),
                        passed=bool(df < 0.01 and ds < 0.05)))
    return out


def _read(r: m.EventResult, a: float, b: float) -> dict:
    sel = (r.t >= a) & (r.t < b)
    x = r.p[sel] - r.p[sel].mean()
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    fr = np.fft.rfftfreq(x.size, 1.0 / FS)
    k = int(np.argmax(spec[1:]) + 1)
    amp = np.ptp(r.p[sel]) / 2
    return dict(p=r6(r.p[sel].mean()), p_amp=r6(amp), f_hz=r6(fr[k]) if amp > 1e-3 else None, q=r6(r.q[sel].mean()),
                v=r6(r.v[sel].mean()), v_amp=r6(np.ptp(r.v[sel]) / 2), f_pll_amp=r6(np.ptp(r.f_pll[sel]) / 2))


def spectrum(r: m.EventResult, a: float, b: float):
    """相電流と相電圧の振幅のスペクトル [基本波の %]。"""
    sel = (r.t >= a) & (r.t < b)
    fr = np.fft.rfftfreq(int(sel.sum()), 1.0 / FS)
    out = {}
    for key, x in (("i", r.i_abc[0][sel]), ("v", r.v_abc[0][sel])):
        s = np.abs(np.fft.rfft(x * np.hanning(x.size)))
        out[key] = 100 * s / s[np.argmin(abs(fr - 60.0))]
    return fr, out


def event(p: m.PRParams) -> tuple:
    try:
        return m.simulate_event(p, p.replace(**POST), t_event=T_EVENT, t_end=T_END, fs=FS), None
    except RuntimeError as e:
        return None, str(e)


def event_rows() -> tuple:
    """線路が落ちる場面を非線形で解く。返り値は (表, 図に使う結果)。"""
    rows, keep = [], {}
    cases = [(f"P・Q + Q の指令を電圧で(利得 {KV:g})", sh, "pq", {"kv_q": KV}, {}) for sh in SHUNT]
    cases += [(f"同(利得 {kv:g})", "shunt", "pq", {"kv_q": kv}, {}) for kv in KV_SWEEP]
    cases += [("P・Q(Q の指令は一定)", "shunt", "pq", {}, {})]
    cases += [(f"P・V(濾波 10 Hz)・{lab}", "shunt", "pv", {"f_meas": 10.0}, lim) for lab, lim in LIMITS]
    for lab, sh, outer, kw, lim in cases:
        p = variant(operating(PRE, sh), outer, kw).replace(**lim)
        r, err = event(p)
        row = dict(label=lab, shunt=sh, error=err)
        if r is not None:
            row["early"] = _read(r, T_EVENT + 0.05, T_EVENT + 0.55)
            row["late"] = _read(r, T_END - 1.0, T_END)
            if kw.get("kv_q") == KV:
                keep[sh] = r
                if sh == "shunt":
                    fr, sp = spectrum(r, T_END - 1.0, T_END)
                    row["spec"] = {k: [r6(float(v[np.argmin(abs(fr - f))])) for f in PAPER["phase_hz"]] for k, v in sp.items()}
        rows.append(row)
    return rows, keep


# ---------------------------------------------------------------- 図
def _ax(ax):
    ax.grid(color=GRID, alpha=0.25, lw=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=9)


def fig_trip(path: Path, keep: dict) -> None:
    fig, axs = plt.subplots(4, 1, figsize=(7.4, 7.2), sharex=True)
    items = (("p", "P [pu]"), ("q", "Q [pu]"), ("v", "|v_pcc| [pu]"), ("f_pll", "PLL の周波数 [Hz]"))
    for sh, c, lab in (("no_shunt", COL[1], "コンデンサなし"), ("shunt", COL[0], "コンデンサあり")):
        r = keep[sh]
        for ax, (key, yl) in zip(axs, items):
            ax.plot(r.t - T_EVENT, getattr(r, key), color=c, lw=0.9, label=lab)
            ax.set_ylabel(yl, color=INK, fontsize=9)
    for ax in axs:
        _ax(ax)
        ax.axvline(0, color=MUTED, lw=0.6, ls=":")
    axs[0].legend(fontsize=8.5, frameon=False, loc="upper right", ncol=2)
    axs[-1].set_xlabel("線路が落ちてからの時間 [s]", color=INK)
    axs[0].set_title(f"線路が落ちる(X_g 0.15 → 0.37)。この模型: P・Q の PI 0.2 + 20/s、Q の指令を電圧で(利得 {KV:g})",
                     color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_modes(path: Path, var: list) -> None:
    fig, ax = plt.subplots(figsize=(7.4, 4.4))
    for k, row in enumerate(var):
        for sh, mk in (("shunt", "o"), ("no_shunt", "s")):
            z = row[sh]
            if z is None:
                continue
            ax.plot(z["f_hz"], z["sigma"], mk, color=COL[k], ms=7, mfc=COL[k] if sh == "shunt" else "white",
                    label=row["label"] if sh == "shunt" else None)
    ax.axhline(0, color=INK, lw=0.8)
    ax.axvline(PAPER["rms_hz"], color=MUTED, lw=0.8, ls="--")
    ax.annotate(f"本文の EMT {PAPER['rms_hz']} Hz", (PAPER["rms_hz"], -40), xytext=(4, 0),
                textcoords="offset points", color=MUTED, fontsize=8.5)
    ax.set_xlabel("周波数(網の dq)[Hz]", color=INK)
    ax.set_ylabel("実部 σ [1/s](正は育つ)", color=INK)
    ax.set_title("線路が落ちた後の 15〜45 Hz のモード。●コンデンサあり □なし", color=INK, fontsize=10.5, loc="left")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    _ax(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_spectrum(path: Path, r: m.EventResult) -> None:
    fr, sp = spectrum(r, T_END - 1.0, T_END)
    fig, axs = plt.subplots(1, 2, figsize=(8.0, 3.4), sharey=True)
    for ax, key, lab, c in ((axs[0], "v", "相電圧", COL[0]), (axs[1], "i", "相電流", COL[0])):
        sel = fr <= 150
        ax.plot(fr[sel], sp[key][sel], color=c, lw=1.0, label="この模型")
        ax.plot(PAPER["phase_hz"], PAPER["read_spec"][key], "v", color=COL[1], ms=7, label="本文の図 12 の読み")
        ax.set_ylim(0, 15)
        ax.set_xlabel("周波数(abc)[Hz]", color=INK)
        ax.set_title(f"{lab}(落ちた後の 1〜2 s)", color=INK, fontsize=10, loc="left")
        _ax(ax)
    axs[0].set_ylabel("基本波に対する % ", color=INK)
    axs[1].legend(fontsize=8, frameon=False, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- 報告の表
def _m(z):
    return "—" if z is None else f"{z['sigma']:.2f} / {z['f_hz']:.2f}"


def tables(res: dict) -> str:
    sh_lab = {"shunt": "あり", "no_shunt": "なし"}
    t = ["**表 1 運転点**(電源 1 pu・|v_pcc| 1 pu・P 0.8 と置いたときの Q と、本文の図 13 の読み)", "",
         "| コンデンサ | 線路 | i_d | i_q | Q(計算) | Q(図 13 の読み) | 一番右のモード σ [1/s] / f [Hz] |", "|---|---|---|---|---|---|---|"]
    for x in res["operating"]:
        t.append(f"| {sh_lab[x['shunt']]} | {'落ちた後' if x['after_trip'] else '落ちる前'} | {x['i_d']:.3f} | {x['i_q']:.3f} | "
                 f"{x['q']:.3f} | {x['q_read']:.2f} | {_m(x['mode'])} |")
    t += ["", "**表 2 落ちた後の 15〜45 Hz のモード**(σ [1/s] / f [Hz]。外側の制御の形を変える)", "",
          "| 外側の制御 | コンデンサあり | なし | 落ちる前の一番右の σ |", "|---|---|---|---|"]
    for x in res["variants"]:
        t.append(f"| {x['label']} | {_m(x['shunt'])} | {_m(x['no_shunt'])} | {x['pre_max_sigma']:.2f} |")
    t += ["", "**表 3 P の読みの幅**(コンデンサあり、落ちた後。σ / f)", "",
          "| P | Q | 外側なし | P・Q(濾波なし) | P・Q(濾波 100 Hz) | P・Q + 電圧で Q |", "|---|---|---|---|---|---|"]
    for x in res["p_sweep"]:
        t.append(f"| {x['p']:.2f} | {x['q']:.3f} | {_m(x['none'])} | {_m(x['pq'])} | {_m(x['pq100'])} | {_m(x['pq_kv'])} |")
    t += ["", "**表 4 線路が落ちる場面(非線形)**。前半は落ちて 0.05〜0.55 s、後半は 1〜2 s。振幅は片側", "",
          "| 場合 | コンデンサ | 後半の P | 振幅 | 周波数 [Hz] | 後半の Q | 後半の |v_pcc| | 振幅 | PLL の周波数の振幅 [Hz] | 前半の P の振幅 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for x in res["events"]:
        if x["error"]:
            tt = float(re.search(r"t = ([0-9.]+)", x["error"]).group(1)) - T_EVENT
            t.append(f"| {x['label']} | {sh_lab[x['shunt']]} | 発散(落ちて {tt:.2f} s) |  |  |  |  |  |  |  |")
            continue
        a, b = x["late"], x["early"]
        t.append(f"| {x['label']} | {sh_lab[x['shunt']]} | {a['p']:.3f} | {a['p_amp']:.3f} | {'—' if a['f_hz'] is None else f"{a['f_hz']:.1f}"} | {a['q']:.3f} | "
                 f"{a['v']:.3f} | {a['v_amp']:.3f} | {a['f_pll_amp']:.2f} | {b['p_amp']:.3f} |")
    rp = PAPER["read_amp"]
    t += ["", f"本文の図 13(2.5〜4 s)の読み: P 0.8 ± {rp['p']}、Q −0.7、V_PLL 1.0 ± {rp['v_pll']}、"
          f"周波数 ± {rp['f_hz']:g} Hz、{PAPER['rms_hz']} Hz(本文)。"]
    sp = next(x["spec"] for x in res["events"] if "spec" in x)
    t += ["", "**表 5 相電流・相電圧の 33 Hz と 87 Hz**(基本波の %)", "", "| | この模型 33 Hz | 87 Hz | 本文の図 12 の読み 33 Hz | 87 Hz |",
          "|---|---|---|---|---|"]
    for key, lab in (("v", "相電圧"), ("i", "相電流")):
        t.append(f"| {lab} | {sp[key][0]:.1f} | {sp[key][1]:.1f} | {PAPER['read_spec'][key][0]:g} | {PAPER['read_spec'][key][1]:g} |")
    t += ["", "**表 6 道のそろい**(落ちた後・コンデンサあり。道 1-2 は全モード、道 1-3 は 15〜45 Hz のモード)", "",
          "| 外側の制御 | 道 | 結果 | 合格 |", "|---|---|---|---|"]
    for x in res["routes"]:
        if x["route"] == "1-2":
            s = f"固有値 {x['n_eig']} 個・零点 {x['n_zero']} 個・相対差の最大 {x['max_rel']:.1e}"
        else:
            s = f"{x['sigma']:.2f} / {x['f_dq']:.2f} Hz、周波数の差 {x['df_hz']:.1e} Hz・σ の差 {x['dsigma']:.1e}"
        t.append(f"| {x['label']} | {x['route']} | {s} | {'○' if x['passed'] else '×'} |")
    return "\n".join(t)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    var = variant_rows()
    events, keep = event_rows()
    res = dict(paper=PAPER, kv_q=KV, operating=op_rows(), variants=var, p_sweep=p_sweep_rows(), routes=route_rows(),
               events=events)
    res["all_passed"] = all(x["passed"] for x in res["routes"])
    fig_trip(OUT / "trip.png", keep)
    fig_modes(OUT / "modes.png", var)
    fig_spectrum(OUT / "spectrum.png", keep["shunt"])
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if REPORT.exists():
        txt = REPORT.read_text(encoding="utf-8")
        a, b = txt.index("<!-- 表:begin -->"), txt.index("<!-- 表:end -->")
        REPORT.write_text(txt[:a] + "<!-- 表:begin -->\n\n" + tables(res) + "\n\n" + txt[b:], encoding="utf-8")
    print("all_passed:", res["all_passed"])
    print(tables(res))


if __name__ == "__main__":
    main()
