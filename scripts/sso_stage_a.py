#!/usr/bin/env python3
"""SSO 第 2 段 段 A: GFL インバータ 1 台 + テブナン等価で、3 つの道の答えがそろうかを確かめる(2026-11-01).

    python scripts/sso_stage_a.py

出力(docs/reports/sso_ibr_stage_a_2026-11-01/):
  results.json       4 つの点の 3 つの道の数字・合否、臨界 SCR の走査
  locus.png          SCR を下げたときの固有値(道 1)と det の零点(道 2)
  time.png           時間領域(道 3)の a 相の電流と、行列ペンシル法で読んだ振動
  critical_scr.png   臨界 SCR と PLL の速さ・電流制御の帯域
docs/reports/sso_ibr_stage_a_2026-11-01.md の「<!-- 表:begin -->」から「<!-- 表:end -->」までを書き換える。
模型と道は src/dynamics/sso/gfl.py。
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
from src.dynamics.sso import gfl  # noqa: E402

OUT = ROOT / "docs/reports/sso_ibr_stage_a_2026-11-01"
REPORT = ROOT / "docs/reports/sso_ibr_stage_a_2026-11-01.md"
CASES = {"FF なし": dict(k_ff=0.0), "FF あり": dict(k_ff=1.0, t_ff=1e-3)}
POINTS = [("FF なし", 1.6), ("FF なし", 1.3), ("FF あり", 2.5), ("FF あり", 1.8)]
# 合格の条件: 道 1 と道 2 は |Δs| ≤ 1e-6 |s|。道 1 と道 3 は周波数 0.01 Hz・σ 0.05 1/s 以内。
# abc の組は道 3 の数字だけで、符号付きの f_sub と f_sup の和が 2f0 になること(0.01 Hz 以内)。
TOL = dict(adm_rel=1e-6, f_hz=0.01, sigma=0.05, pair_hz=0.01)
F_PLL = [10, 15, 20, 30, 40, 50, 60, 80, 100]
F_CC = [150, 300, 600]
COL = ["#1f4e8c", "#c06014", "#2a7f62"]
INK, MUTED, GRID = "#1d2226", "#59616a", "#8a9099"
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]


def r6(x):
    return None if x is None else float(f"{x:.6g}")


def check_point(case: str, scr: float) -> dict:
    p = gfl.GFLParams(scr=scr, **CASES[case])
    lam = gfl.eigenvalues(p)
    lc = gfl.critical_mode(lam)
    z = gfl.admittance_zeros(p)
    z = z[z.imag > 2 * math.pi * 0.5]
    zc = complex(z[np.argmax(z.real)])
    f_dq = lc.imag / (2 * math.pi)
    sim = gfl.simulate(p, t_end=1.0)
    (fs, ss), (fp, sp) = gfl.pair_from_modes(sim.modes, p.f0, f_dq)
    sub_signed = fs if fp - p.f0 < p.f0 else -fs          # 道 3 の数字だけで符号を決める
    n_rhp = gfl.rhp_zero_count(p)
    ok12 = abs(zc - lc) <= TOL["adm_rel"] * abs(lc)
    ok13 = (abs(fs - abs(p.f0 - f_dq)) <= TOL["f_hz"] and abs(fp - (p.f0 + f_dq)) <= TOL["f_hz"]
            and abs(ss - lc.real) <= TOL["sigma"] and abs(sp - lc.real) <= TOL["sigma"])
    okpair = abs(sub_signed + fp - 2 * p.f0) <= TOL["pair_hz"]
    okrhp = n_rhp == int(np.sum(lam.real > 0))
    return dict(case=case, scr=scr, stable=bool(lc.real < 0),
                eig=dict(sigma=r6(lc.real), f_dq=r6(f_dq), n_rhp=int(np.sum(lam.real > 0))),
                adm=dict(sigma=r6(zc.real), f_dq=r6(zc.imag / (2 * math.pi)), rel_err=float(f"{abs(zc - lc) / abs(lc):.1e}"),
                         n_rhp_nyquist=n_rhp),
                time=dict(f_sub=r6(fs), sigma_sub=r6(ss), f_sup=r6(fp), sigma_sup=r6(sp),
                          fit_window_s=[r6(sim.fit[0]), r6(sim.fit[1])]),
                passed=dict(route12=bool(ok12), route13=bool(ok13), abc_pair=bool(okpair), rhp_count=bool(okrhp)),
                _sim=sim, _p=p, _lc=lc)


def sweep() -> list:
    rows = []
    for case, kw in CASES.items():
        for f_cc in F_CC:
            for f_pll in F_PLL:
                p = gfl.GFLParams(f_cc=f_cc, f_pll=f_pll, **kw)
                c1 = gfl.critical_scr_eig(p, lo=1.0)
                row = dict(case=case, f_cc=f_cc, f_pll=f_pll, scr_eig=r6(c1), scr_adm=None, f_dq=None)
                if c1 is not None:
                    lc, pf = gfl.participation(p.replace(scr=c1))
                    row["f_dq"] = r6(lc.imag / (2 * math.pi))
                    row["participation_top3"] = {k: round(v, 2) for k, v in list(pf.items())[:3]}
                    if f_cc == 300:
                        lo = max(c1 * 0.97, 1.0)
                        try:
                            row["scr_adm"] = r6(gfl.critical_scr_admittance(p, lo, c1 * 1.03))
                        except ValueError:
                            pass
                rows.append(row)
    return rows


def static_limit(p: gfl.GFLParams) -> float:
    """平衡点が無くなる SCR(電流の指令 1 pu で網の X·i が V_g に届く所)。"""
    return math.hypot(p.i_d_ref, p.i_q_ref) * p.xr_g / math.sqrt(1 + p.xr_g ** 2) / p.v_g


def fig_locus(path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    scrs = np.geomspace(5.0, 1.02, 70)
    for ax, (case, kw) in zip(axes, CASES.items()):
        for scr in scrs:
            lam = gfl.eigenvalues(gfl.GFLParams(scr=scr, **kw))
            lam = lam[(lam.imag > 2 * math.pi * 0.5) & (lam.imag < 2 * math.pi * 200)]
            c = plt.cm.Blues(0.35 + 0.6 * (5.0 - scr) / 4.0)
            ax.scatter(lam.real, lam.imag / (2 * math.pi), s=10, color=c, zorder=2, linewidths=0)
        for scr in (5.0, 3.0, 2.0, 1.5, 1.3):
            z = gfl.admittance_zeros(gfl.GFLParams(scr=scr, **kw))
            z = z[(z.imag > 2 * math.pi * 0.5) & (z.imag < 2 * math.pi * 200)]
            ax.scatter(z.real, z.imag / (2 * math.pi), marker="x", s=36, color=COL[1], linewidths=1.3, zorder=3)
            top = z[np.argmax(z.real)]
            ax.annotate(f"SCR {scr:g}", (top.real, top.imag / (2 * math.pi)), xytext=(4, 6 if scr != 5.0 else -13),
                        textcoords="offset points", fontsize=8, color=MUTED)
        ax.axvline(0, color=INK, lw=0.8)
        ax.set_xlim(-520, 230)
        ax.set_ylim(0, 200)
        ax.set_title(f"{case}(PLL 40 Hz・電流制御 300 Hz)", fontsize=10.5, loc="left", color=INK)
        ax.set_xlabel("実部 σ [1/s](右が不安定)", color=MUTED)
        ax.grid(color=GRID, alpha=0.25, lw=0.6)
    axes[0].set_ylabel("網の dq での振動 f_dq [Hz]\n(abc では f0 − f_dq と f0 + f_dq の組)", color=MUTED)
    axes[1].scatter([], [], s=14, color=plt.cm.Blues(0.75), label="道 1 固有値(SCR 5→1.02、濃いほど弱い網)")
    axes[1].scatter([], [], marker="x", s=36, color=COL[1], label="道 2 det(Y_c + Y_g) の零点")
    axes[1].legend(loc="upper right", fontsize=8.5, frameon=False)
    fig.suptitle("SCR を下げたときのモード: 道 1 の固有値と道 2 の零点は重なる", x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def fig_time(path: Path, pts: list) -> None:
    sel = [x for x in pts if x["case"] == "FF なし"]
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.2))
    for j, x in enumerate(sel):
        sim, p, lc = x["_sim"], x["_p"], x["_lc"]
        f_dq = lc.imag / (2 * math.pi)
        t1 = sim.fit[1]
        m = sim.t <= min(t1 * 1.05, sim.t[-1])
        ax = axes[0, j]
        ax.plot(sim.t[m], sim.di_a[m] * 1e6, color=COL[0], lw=0.7)
        ax.axvspan(sim.fit[0], t1, color=GRID, alpha=0.12, lw=0)
        ax.set_title(f"FF なし・SCR {x['scr']:g}({'安定' if x['stable'] else '不安定'})", fontsize=10.5, loc="left", color=INK)
        ax.set_xlabel("時間 [s](灰色が当てはめの窓)", color=MUTED)
        ax.set_ylabel("a 相の電流のずれ [10⁻⁶ pu]", color=MUTED)
        ax.grid(color=GRID, alpha=0.25, lw=0.6)
        ax = axes[1, j]
        big = [md for md in sim.modes if md[2] >= 1e-3 * sim.modes[0][2] and md[0] < 160]
        for f, s, a in big:
            ax.vlines(f, 1e-4, a / sim.modes[0][2], color=COL[2], lw=2.2)
        for f, lab, ha, dx in ((abs(p.f0 - f_dq), "sub", "right", -1.5), (p.f0 + f_dq, "super", "left", 1.5)):
            ax.axvline(f, color=COL[1], ls="--", lw=1.0)
            ax.text(f + dx, 1.6, f"{lab} {f:.2f} Hz", ha=ha, fontsize=8.5, color=INK)
        ax.axvline(p.f0, color=GRID, lw=0.8, ls=":")
        ax.set_yscale("log")
        ax.set_ylim(1e-4, 4)
        ax.set_xlim(0, 160)
        ax.set_xlabel("周波数 [Hz](緑: 道 3 で読んだ振動、破線: 道 1 から出る f0 ∓ f_dq)", color=MUTED)
        ax.set_ylabel("振幅(最大を 1)", color=MUTED)
        ax.text(0.99, 0.04, f"道 1: σ = {lc.real:.3f}\n道 3: σ = {x['time']['sigma_sub']:.3f} / {x['time']['sigma_sup']:.3f}",
                transform=ax.transAxes, ha="right", va="bottom", fontsize=8.5, color=INK)
        ax.grid(color=GRID, alpha=0.25, lw=0.6)
    fig.suptitle("静止座標の非線形の積分(道 3): 網の dq の 1 つの振動が abc では sub と super の組で出る",
                 x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def fig_critical(path: Path, rows: list) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    lim = static_limit(gfl.GFLParams())
    for ax, case in zip(axes, CASES):
        ends = []
        for k, f_cc in enumerate(F_CC):
            rr = [r for r in rows if r["case"] == case and r["f_cc"] == f_cc and r["scr_eig"] is not None]
            ax.plot([r["f_pll"] for r in rr], [r["scr_eig"] for r in rr], color=COL[k], lw=2,
                    marker="o", ms=3.5, label=f"道 1・電流制御 {f_cc} Hz")
            ends.append([rr[-1]["scr_eig"], f_cc, rr[-1]["f_pll"]])
        ends.sort()
        for j in range(1, len(ends)):                      # 右端のラベルが重ならないように少しずらす
            ends[j][0] = max(ends[j][0], ends[j - 1][0] + 0.14)
        for y, f_cc, x in ends:
            ax.text(x + 1.5, y, f"{f_cc} Hz", va="center", fontsize=8.5, color=INK)
        rr = [r for r in rows if r["case"] == case and r["scr_adm"] is not None]
        ax.scatter([r["f_pll"] for r in rr], [r["scr_adm"] for r in rr], s=70, facecolors="none",
                   edgecolors=INK, linewidths=1.0, zorder=4, label="道 2(300 Hz)")
        ax.axhline(lim, color=GRID, ls=":", lw=1)
        ax.text(101, lim + 0.06, "静的な限界(平衡点が無くなる)", fontsize=8, color=MUTED, ha="right")
        ax.set_title(case, fontsize=10.5, loc="left", color=INK)
        ax.set_xlabel("PLL の固有周波数 [Hz]", color=MUTED)
        ax.set_xlim(5, 112)
        ax.grid(color=GRID, alpha=0.25, lw=0.6)
    axes[0].set_ylabel("臨界 SCR(これより弱いと振動が育つ)", color=MUTED)
    axes[0].legend(loc="upper left", fontsize=8.5, frameon=False)
    fig.suptitle("臨界 SCR と PLL の速さ・電流制御の帯域(段 A の例の定数。実機の値ではない)",
                 x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def tables(pts: list, rows: list) -> str:
    ok = lambda b: "合" if b else "**否**"
    out = ["### 4 つの点で 3 つの道を比べる", "",
           "| 場合 | SCR | 道 1: σ [1/s] / f_dq [Hz] | 道 2: 相対誤差 | 道 3: sub [Hz] / σ | 道 3: super [Hz] / σ | 右半面の極(固有値 / 偏角) | 合否(1-2・1-3・組・極) |",
           "|---|---|---|---|---|---|---|---|"]
    for x in pts:
        e, a, t, ps = x["eig"], x["adm"], x["time"], x["passed"]
        out.append(f"| {x['case']} | {x['scr']:g} | {e['sigma']:.4f} / {e['f_dq']:.4f} | {a['rel_err']:.0e} | "
                   f"{t['f_sub']:.4f} / {t['sigma_sub']:.4f} | {t['f_sup']:.4f} / {t['sigma_sup']:.4f} | "
                   f"{e['n_rhp']} / {a['n_rhp_nyquist']} | {ok(ps['route12'])}・{ok(ps['route13'])}・{ok(ps['abc_pair'])}・{ok(ps['rhp_count'])} |")
    out += ["", "### 臨界 SCR(電流制御 300 Hz)", "",
            "| PLL [Hz] | FF なし: 道 1 | 道 2 | f_dq [Hz] | 効く状態 | FF あり: 道 1 | 道 2 | f_dq [Hz] | 効く状態 |",
            "|---|---|---|---|---|---|---|---|---|"]
    top = lambda r: "—" if not r.get("participation_top3") else "・".join(f"{k} {v:.2f}" for k, v in r["participation_top3"].items())
    fmt = lambda v, d=4: "—" if v is None else f"{v:.{d}f}"
    for f_pll in F_PLL:
        a = next(r for r in rows if r["case"] == "FF なし" and r["f_cc"] == 300 and r["f_pll"] == f_pll)
        b = next(r for r in rows if r["case"] == "FF あり" and r["f_cc"] == 300 and r["f_pll"] == f_pll)
        out.append(f"| {f_pll} | {fmt(a['scr_eig'])} | {fmt(a['scr_adm'])} | {fmt(a['f_dq'], 1)} | {top(a)} | "
                   f"{fmt(b['scr_eig'])} | {fmt(b['scr_adm'])} | {fmt(b['f_dq'], 1)} | {top(b)} |")
    out += ["", "### 臨界 SCR と電流制御の帯域(道 1)", "",
            "| PLL [Hz] | FF なし: 150 Hz | 300 Hz | 600 Hz | FF あり: 150 Hz | 300 Hz | 600 Hz |",
            "|---|---|---|---|---|---|---|"]
    for f_pll in F_PLL:
        cells = [fmt(next(r for r in rows if r["case"] == case and r["f_cc"] == f_cc and r["f_pll"] == f_pll)["scr_eig"])
                 for case in CASES for f_cc in F_CC]
        out.append(f"| {f_pll} | " + " | ".join(cells) + " |")
    none = any(r["scr_eig"] is None for r in rows)
    out += [""] + (["- 「—」は静的な限界まで振動が育たない(臨界 SCR が無い)。"] if none else []) + [
            "- 効く状態は、臨界 SCR での危ないモードの参加率の上位 3 つ(δ と x_pll が PLL、i が電流、x_cc が電流制御の積分、v_ff がフィードフォワード)。"]
    return "\n".join(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pts = [check_point(c, s) for c, s in POINTS]
    rows = sweep()
    fig_locus(OUT / "locus.png")
    fig_time(OUT / "time.png", pts)
    fig_critical(OUT / "critical_scr.png", rows)
    base = gfl.GFLParams()
    res = dict(params={k: getattr(base, k) for k in base.__dataclass_fields__}, cases=CASES,
               tolerance=TOL, static_limit_scr=r6(static_limit(base)),
               points=[{k: v for k, v in x.items() if not k.startswith("_")} for x in pts], sweep=rows,
               all_passed=all(all(x["passed"].values()) for x in pts))
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if REPORT.exists():
        txt = REPORT.read_text(encoding="utf-8")
        a, b = txt.index("<!-- 表:begin -->"), txt.index("<!-- 表:end -->")
        REPORT.write_text(txt[:a] + "<!-- 表:begin -->\n\n" + tables(pts, rows) + "\n\n" + txt[b:], encoding="utf-8")
    print("all_passed:", res["all_passed"])
    for x in pts:
        print(x["case"], x["scr"], x["passed"])


if __name__ == "__main__":
    main()
