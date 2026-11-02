#!/usr/bin/env python3
"""SSO 第 2 段 段 C: 臨界 SCR を AGJ の全国の点に当てる(2026-11-02).

    python scripts/sso_stage_c.py

段 A の GFL 1 台の模型で臨界 SCR の表を作り(src/dynamics/sso/scr_map.py)、正典の 4 島の各点の
短絡容量 S_sc と X/R(src/powerflow/short_circuit.py、09-02 の IBR の SCR の報告と同じ網と電源)に当てる。
  - 1 か所でつなぐとき、何 MVA で振動が育ち始めるか(S_on = S_sc / SCR_crit)
  - 既設の IBR(machine_agg の勘定。OSM の容量)の SCR と臨界の比
  - 既設の IBR が集まる所の一般化 SCR(GSCR2018)

出力(docs/reports/sso_ibr_stage_c_2026-11-02/):
  results.json     臨界 SCR の表・島と電圧の帯ごとの集計・既設の IBR・一般化 SCR
  points.csv       点ごとの S_sc・X/R・既設の IBR・S_on(66 kV 以上)
  critical.png     臨界 SCR と X/R・力率(50 Hz と 60 Hz)
  map.png          S_on の地図(速い側の定数・力率 1)
docs/reports/sso_ibr_stage_c_2026-11-02.md の「<!-- 表:begin -->」から「<!-- 表:end -->」までを書き換える。
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
import time
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "sensitivity"))
from src.dynamics.sso import scr_map as sm  # noqa: E402

OUT = ROOT / "docs/reports/sso_ibr_stage_c_2026-11-02"
REPORT = ROOT / "docs/reports/sso_ibr_stage_c_2026-11-02.md"
ISLANDS = ("hokkaido", "east", "west", "okinawa")
KV_BANDS = [(60, 80, "66-77kV"), (100, 160, "110-154kV"), (180, 300, "187-275kV"), (450, 600, "500kV")]
MIN_KV = 66.0
PF_MAP = 0            # 地図と点の表で使う力率(PF_CASES の番号。0 = 1.00)
N_TOP = 12
# 力率の色(出す=青・1.00=灰・吸う=赤。dataviz の検証で CVD は 7.7 なので、線に名前を直接書く)
PF_COLORS = {"0.95 出す": "#2a78d6", "1.00": "#6b6a65", "0.95 吸う": "#e66767", "0.90 吸う": "#a12f2f"}


def r(x, n=3):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


# ── 臨界 SCR の表 ─────────────────────────────────────────────────────────
def tables() -> dict:
    sets = sm.param_sets()
    out = {}
    k5 = sm.XR_GRID.index(5.0)
    for f0 in (50.0, 60.0):
        t, f = sm.critical_table(f0, sets)
        sub = np.where(f[:, :, k5] < f0, t[:, :, k5], -np.inf)
        out[f0] = dict(table=t, fdq=f, **sm.summarize(t, f, f0),
                       argmax=[sets[int(i)] for i in t[:, :, k5].argmax(0)],
                       argmax_fdq=[float(f[int(i), j, k5]) for j, i in enumerate(t[:, :, k5].argmax(0))],
                       argmax_sub=[sets[int(i)] for i in sub.argmax(0)],
                       argmax_sub_fdq=[float(f[int(i), j, k5]) for j, i in enumerate(sub.argmax(0))],
                       n_lo=int((t == sm.SCR_LO).sum()), n_inf=int(np.isinf(t).sum()),
                       n_sub=int((f < f0).sum()), n_all=int(t.size))
    return out


CHECK_SETS = (dict(f_pll=100.0, f_cc=300.0, k_ff=1.0), dict(f_pll=40.0, f_cc=300.0, k_ff=0.0))


def checks() -> list:
    """表の臨界を、段 A の道 2(アドミタンスの零点)と道 3(静止座標の非線形の積分 + 行列ペンシル)で確かめる。

    X/R 5、力率 1 と 0.95 吸う、速い側と中ほどの組。臨界の 0.97 倍で育ち、1.03 倍で減るか。
    """
    from src.dynamics.sso import gfl
    rows = []
    for f0 in (50.0, 60.0):
        for j in (0, 1):
            lab, pf, sg = sm.PF_CASES[j]
            i_d, i_q = sm.currents(pf, sg)
            for kw in CHECK_SETS:
                p = gfl.GFLParams(f0=f0, i_d_ref=i_d, i_q_ref=i_q, xr_g=5.0, **kw)
                c, f_dq = sm.critical_point(p)
                adm = gfl.critical_scr_admittance(p, c * 0.97, c * 1.03)
                row = dict(f0=int(f0), pf=lab, f_pll=kw["f_pll"], f_cc=kw["f_cc"], k_ff=kw["k_ff"],
                           scr_eig=r(c, 4), scr_adm=r(adm, 4), rel=float(f"{abs(adm - c) / c:.1e}"), f_dq=r(f_dq, 1))
                for k, tag in ((0.97, "below"), (1.03, "above")):
                    q = p.replace(scr=c * k)
                    lc = gfl.critical_mode(gfl.eigenvalues(q))
                    sim = gfl.simulate(q, t_end=1.0)
                    (fs, ss), (fp, sp) = gfl.pair_from_modes(sim.modes, f0, lc.imag / (2 * math.pi))
                    row[tag] = dict(sigma_eig=r(lc.real, 2), sigma_sub=r(ss, 2), sigma_sup=r(sp, 2),
                                    f_sub=r(fs, 1), f_sup=r(fp, 1))
                row["passed"] = bool(row["rel"] < 1e-5 and row["below"]["sigma_sub"] > 0 > row["above"]["sigma_sub"]
                                     and row["below"]["sigma_sup"] > 0 > row["above"]["sigma_sup"])
                rows.append(row)
    return rows


# ── 島ごとの網と短絡容量 ─────────────────────────────────────────────────
def island_points(island: str, nodes, edges, cfg, pref_gwh) -> dict:
    """ibr_hosting_scr.run と同じ網・電源で、点ごとの S_sc・Z_th・既設の IBR・名前と座標を返す。"""
    from benchmark_sensitivity import main_component_subnet
    from ibr_hosting_scr import build_production_net
    from scripts.run_full_powerflow_from_db import ISLAND_FREQ
    from src.dynamics.machine_agg import aggregate_machines
    from src.powerflow.short_circuit import existing_ibr_mw, short_circuit_mva

    net, bus_of = build_production_net(island, nodes, edges, cfg, pref_gwh)
    sub, _ = main_component_subnet(net)
    agg = aggregate_machines(sub)
    sc = short_circuit_mva(sub, agg=agg)
    n = len(sc.s_sc_mva)
    ibr = np.zeros(n)
    for lbl, mw in existing_ibr_mw(sub, agg=agg).items():
        row = sc.bus_row_of_label.get(int(lbl))
        if row is not None:
            ibr[row] += mw
    lat = np.full(n, np.nan); lon = np.full(n, np.nan); kv = np.full(n, np.nan); names = [""] * n
    bus2node = {}
    for ni, b in (bus_of.items() if isinstance(bus_of, dict) else enumerate(bus_of)):
        if b is not None and b >= 0:
            bus2node.setdefault(int(b), int(ni))
    for lbl, row in sc.bus_row_of_label.items():
        kv[row] = float(sub.bus.at[lbl, "vn_kv"])
        ni = bus2node.get(int(lbl))
        if ni is not None and not names[row]:
            lat[row] = nodes[ni]["lat"]; lon[row] = nodes[ni]["lon"]
            names[row] = str(nodes[ni].get("name") or nodes[ni].get("id") or lbl)
    z = sc.z_th_pu
    with np.errstate(divide="ignore", invalid="ignore"):
        xr = np.abs(z.imag / z.real)
    return dict(island=island, f0=float(ISLAND_FREQ[island]), net=sub, agg=agg, base=sc.base_mva,
                label=np.array([sc.label_of_row[i] for i in range(n)]), s_sc=sc.s_sc_mva, xr=xr, kv=kv,
                lat=lat, lon=lon, names=names, ibr=ibr, n_src=sc.n_source, src_mva=sc.source_mva)


def apply_tables(pt: dict, tab: dict) -> dict:
    """点ごとの臨界 SCR(速い側・中央・遅い側)と S_on を力率ごとに足す。"""
    t = tab[pt["f0"]]
    xr = np.where(np.isfinite(pt["xr"]), pt["xr"], 5.0)
    for key in ("max", "max_sub", "median", "min"):
        pt[f"crit_{key}"] = np.stack([sm.at_xr(t[key][j], xr) for j in range(len(sm.PF_CASES))])
        pt[f"on_{key}"] = sm.onset_mva(pt["s_sc"][None, :], pt[f"crit_{key}"])
    pt["crit_worst"] = pt["crit_max"].max(0)           # 力率も定数も一番悪い側
    with np.errstate(divide="ignore", invalid="ignore"):
        pt["scr_now"] = np.where(pt["ibr"] > 0, pt["s_sc"] / np.where(pt["ibr"] > 0, pt["ibr"], 1.0), np.inf)
    pt["scope"] = np.isfinite(pt["s_sc"]) & (pt["kv"] >= MIN_KV - 0.5)
    return pt


def mark_twins(pts: list) -> None:
    """別の島に同じ座標(小数 5 桁)の点がある点に印を付ける(地域をまたぐ双子。正典の重複の疑い)。

    双子の片方に付いた発電所は、定格周波数の違う島に入っていることがある。既設の IBR の表と
    一般化 SCR からは外し、外した点と容量を数えておく。
    """
    keys = [{(round(a, 5), round(b, 5)) for a, b in zip(pt["lat"], pt["lon"]) if np.isfinite(a)} for pt in pts]
    for k, pt in enumerate(pts):
        other = set().union(*(keys[j] for j in range(len(pts)) if j != k))
        pt["twin"] = np.array([np.isfinite(a) and (round(a, 5), round(b, 5)) in other
                               for a, b in zip(pt["lat"], pt["lon"])])
        nm = pt["names"]
        pt["place"] = np.array([bool(x) and " junction " not in x for x in nm])   # 名前のある設備


def gscr_rows(pt: dict) -> dict:
    """既設の IBR がある点の一般化 SCR。一番小さい固有値と、その重みが大きい点(双子の点は外す)。"""
    from src.powerflow.short_circuit import thevenin_matrix
    m = (pt["ibr"] > 0) & np.isfinite(pt["s_sc"]) & ~pt["twin"]
    rows = np.where(m)[0]
    if len(rows) == 0:
        return dict(n_ibr_bus=0)
    z, base = thevenin_matrix(pt["net"], pt["label"][rows], agg=pt["agg"])
    lam, w = sm.gscr(z, pt["ibr"][rows], base)
    top = rows[np.argsort(-w[:, 0])[:5]]
    lead = top[0]
    single_min = float(np.min(pt["scr_now"][rows]))
    out = dict(n_ibr_bus=int(len(rows)), ibr_mw=r(pt["ibr"][rows].sum(), 1), gscr_min=r(lam[0]),
               gscr_next=[r(v) for v in lam[1:4]], scr_single_min=r(single_min),
               lead_bus=pt["names"][lead], lead_kv=r(pt["kv"][lead], 0), lead_xr=r(pt["xr"][lead], 2),
               lead_weight=r(w[rows.tolist().index(lead), 0]),
               top=[dict(name=pt["names"][i], kv=r(pt["kv"][i], 0), ibr_mw=r(pt["ibr"][i], 1),
                         weight=r(w[rows.tolist().index(i), 0])) for i in top],
               crit_worst_at_lead=r(pt["crit_worst"][lead]),
               scale_to_onset=r(lam[0] / pt["crit_worst"][lead], 2),
               scale_to_onset_sub=r(lam[0] / pt["crit_max_sub"].max(0)[lead], 2))
    return out


# ── 集計 ────────────────────────────────────────────────────────────────
def band_rows(pt: dict) -> list:
    out = []
    for lo, hi, lab in KV_BANDS:
        m = pt["scope"] & (pt["kv"] >= lo) & (pt["kv"] <= hi)
        if not m.any():
            continue
        out.append(dict(island=pt["island"], band=lab, n=int(m.sum()),
                        s_sc_med=r(np.median(pt["s_sc"][m]), 0), xr_med=r(np.nanmedian(pt["xr"][m]), 1),
                        on_sub_med=r(np.median(pt["on_max_sub"][PF_MAP][m]), 0),
                        on_sub_p10=r(np.percentile(pt["on_max_sub"][PF_MAP][m], 10), 0),
                        on_max_med=r(np.median(pt["on_max"][PF_MAP][m]), 0),
                        on_med_med=r(np.median(pt["on_median"][PF_MAP][m]), 0)))
    return out


def ibr_rows(pt: dict) -> dict:
    tw = pt["scope"] & (pt["ibr"] > 0) & pt["twin"]
    m = pt["scope"] & (pt["ibr"] > 0) & ~pt["twin"]
    margin = pt["scr_now"] / pt["crit_worst"]
    idx = np.where(m)[0][np.argsort(margin[m])][:N_TOP]
    tw_idx = np.where(tw)[0][np.argsort(margin[tw])][:3]
    return dict(island=pt["island"], n=int(m.sum()), mw=r(pt["ibr"][m].sum(), 1),
                n_twin=int(tw.sum()), mw_twin=r(pt["ibr"][tw].sum(), 1),
                twin_top=[dict(name=pt["names"][i], kv=r(pt["kv"][i], 0), ibr_mw=r(pt["ibr"][i], 1),
                               scr_now=r(pt["scr_now"][i], 2), margin=r(margin[i], 2)) for i in tw_idx],
                n_below_worst=int((m & (margin < 1)).sum()),
                n_below_sub=int((m & (pt["scr_now"] < pt["crit_max_sub"].max(0))).sum()),
                margin_min=r(margin[m].min() if m.any() else None, 2),
                top=[dict(name=pt["names"][i], kv=r(pt["kv"][i], 0), s_sc=r(pt["s_sc"][i], 0),
                          ibr_mw=r(pt["ibr"][i], 1), scr_now=r(pt["scr_now"][i], 2),
                          crit_worst=r(pt["crit_worst"][i], 2), margin=r(margin[i], 2)) for i in idx])


def weakest_rows(pts: list) -> list:
    """S_on(SSO の帯の速い側・力率 1)が小さい点。名前のある設備で双子でない点を、島をまたいで並べる。"""
    allr = []
    for pt in pts:
        for i in np.where(pt["scope"] & pt["place"] & ~pt["twin"])[0]:
            allr.append((float(pt["on_max_sub"][PF_MAP][i]), pt, i))
    allr.sort(key=lambda a: a[0])
    return [dict(island=pt["island"], name=pt["names"][i], kv=r(pt["kv"][i], 0), s_sc=r(pt["s_sc"][i], 0),
                 xr=r(pt["xr"][i], 1), on_sub=r(v, 0), on_max=r(pt["on_max"][PF_MAP][i], 0),
                 on_median=r(pt["on_median"][PF_MAP][i], 0), ibr_mw=r(pt["ibr"][i], 1))
            for v, pt, i in allr[:N_TOP]]


# ── 図 ──────────────────────────────────────────────────────────────────
def _ax(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(alpha=0.25, lw=0.6)


def fig_critical(path: Path, tab: dict, pts: list) -> None:
    """左: 定数の組ごとの臨界 SCR と、そこで育つモードの f_dq(力率 1・X/R 5)。右: SSO の帯の速い側と X/R・力率。"""
    k5 = sm.XR_GRID.index(5.0)
    ff_col = {0.0: "#1f5596", 1.0: "#c25e10"}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.9), gridspec_kw=dict(width_ratios=[1.15, 1]))
    sets = sm.param_sets()
    for f0, mk in ((50.0, "o"), (60.0, "^")):
        t = tab[f0]
        for i, kw in enumerate(sets):
            f, c = t["fdq"][i, 0, k5], t["table"][i, 0, k5]
            if np.isfinite(f):
                a1.scatter(f, c, s=34, marker=mk, color=ff_col[kw["k_ff"]], edgecolors="#fcfcfb", linewidths=0.8, zorder=3)
        a1.axvline(f0, color="#52514e", lw=0.9, ls=":")
        a1.text(f0 + 1.2, 3.0, f"f0 = {int(f0)} Hz", fontsize=8.5, color="#52514e", rotation=90, va="bottom")
    a1.axvspan(0, 50, color="#9a9890", alpha=0.10, lw=0)
    a1.text(25, 0.18, "SSO の帯\n(相の量の片方が f0 より下)", ha="center", fontsize=8.5, color="#52514e")
    a1.text(118, 0.25, "高い周波数(制御の遅れが効く。この模型では弱い)", ha="center", fontsize=9, color="#52514e")
    for ff, lab in ((0.0, "フィードフォワード 無"), (1.0, "フィードフォワード 有")):
        a1.scatter([], [], color=ff_col[ff], s=34, label=lab)
    a1.scatter([], [], marker="o", color="#6b6a65", s=30, label="50 Hz")
    a1.scatter([], [], marker="^", color="#6b6a65", s=30, label="60 Hz")
    a1.legend(loc="upper left", fontsize=8.5, frameon=False)
    a1.set_xlim(0, 180)
    a1.set_ylim(0, 4.8)
    a1.set_xlabel("臨界で育つモードの周波数 f_dq [Hz](網の dq。相の量では f0 ∓ f_dq)")
    a1.set_ylabel("臨界 SCR(これより弱いと育つ)")
    a1.set_title("定数の組 36 通り(力率 1・X/R 5)", fontsize=11, loc="left")
    _ax(a1)
    ends = []
    for j, (lab, _pf, _sg) in enumerate(sm.PF_CASES):
        c = PF_COLORS[lab]
        a2.plot(sm.XR_GRID, tab[50.0]["max_sub"][j], color=c, lw=2)
        a2.plot(sm.XR_GRID, tab[60.0]["max_sub"][j], color=c, lw=1.4, ls="--")
        ends.append([float(tab[50.0]["max_sub"][j][-1]), lab, c])
    ends.sort(key=lambda e: e[0])
    for k in range(1, len(ends)):                       # 名前が重ならないよう下から詰める
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + 0.07)
    for y, lab, c in ends:
        a2.text(sm.XR_GRID[-1] * 1.07, y, lab, color=c, fontsize=9, va="center")
    xr = [x for pt in pts for x in pt["xr"][pt["scope"]] if np.isfinite(x)]
    q1, q3 = np.percentile(xr, [10, 90])
    a2.axvspan(q1, q3, color="#9a9890", alpha=0.12, lw=0)
    a2.text(math.sqrt(q1 * q3), 1.08, "全国の点の X/R(10〜90%)", ha="center", fontsize=8.5, color="#52514e")
    a2.set_xscale("log")
    a2.set_xlim(1.4, 95)
    a2.set_ylim(1.0, 2.8)
    a2.set_xticks([2, 3, 5, 10, 20, 50])
    a2.set_xticklabels(["2", "3", "5", "10", "20", "50"])
    a2.set_xlabel("網の X/R(点から見たテブナン等価)")
    a2.set_ylabel("SSO の帯の速い側の臨界 SCR")
    a2.set_title("実線 50 Hz・破線 60 Hz", fontsize=11, loc="left")
    _ax(a2)
    top_sub = max(float(tab[f]["max_sub"].max()) for f in (50.0, 60.0))
    top_all = max(float(tab[f]["max"].max()) for f in (50.0, 60.0))
    fig.suptitle(f"育つモードが f0 より下(SSO の帯)なら臨界 SCR は最大 {top_sub:.1f}、上も入れると最大 {top_all:.1f}",
                 x=0.02, ha="left", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_map(path: Path, pts: list) -> None:
    from matplotlib.colors import LogNorm
    fig = plt.figure(figsize=(8.2, 7.6))
    ax = fig.add_axes([0.08, 0.07, 0.78, 0.86])
    ins = fig.add_axes([0.6, 0.11, 0.18, 0.2])
    cmap = plt.get_cmap("Blues_r")
    norm = LogNorm(50, 5000)
    for pt in pts:
        m = pt["scope"] & np.isfinite(pt["lat"])
        a = ins if pt["island"] == "okinawa" else ax
        o = np.argsort(-pt["on_max_sub"][PF_MAP][m])       # 弱い点を上に描く
        sc = a.scatter(pt["lon"][m][o], pt["lat"][m][o], c=np.clip(pt["on_max_sub"][PF_MAP][m][o], 50, 5000),
                       s=4 + pt["kv"][m][o] / 40, cmap=cmap, norm=norm, linewidths=0)
    ax.set_aspect(1.2)
    ax.set_xlim(128.5, 146.5)
    ax.set_ylim(30.8, 45.8)
    ins.set_aspect(1.2)
    ins.set_xticks([]); ins.set_yticks([])
    ins.set_title("沖縄", fontsize=9)
    ax.set_xlabel("経度"); ax.set_ylabel("緯度")
    ax.set_title("1 か所でつなぐとき、何 MVA で振動が育ち始めるか(SSO の帯の速い側・力率 1)",
                 fontsize=11, loc="left")
    _ax(ax)
    cb = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("S_on [MVA](濃いほど少ない容量で育つ)")
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ── 報告 ────────────────────────────────────────────────────────────────
def report_tables(res: dict) -> str:
    L = []
    L.append("**表 1 臨界 SCR(X/R 5 の点)。36 組の最大(高い周波数を含む)・SSO の帯の最大・中央値・最小。"
             "括弧は最大になった組(PLL・電流制御・フィードフォワード)と、そこで育つモードの f_dq**\n")
    L.append("| 定格周波数 | 力率 | 最大 | SSO の帯の最大 | 中央 | 最小 |")
    L.append("|---|---|---|---|---:|---:|")
    ff = lambda a: "有" if a["k_ff"] else "無"
    for f0, t in res["critical"].items():
        for j, (lab, *_r) in enumerate(sm.PF_CASES):
            a, b = t["argmax"][j], t["argmax_sub"][j]
            L.append(f"| {f0} Hz | {lab} | {t['xr5']['max'][j]:.2f}({a['f_pll']:.0f}・{a['f_cc']:.0f}・{ff(a)}、"
                     f"{t['argmax_fdq'][j]:.0f} Hz) | {t['xr5']['max_sub'][j]:.2f}({b['f_pll']:.0f}・{b['f_cc']:.0f}・"
                     f"{ff(b)}、{t['argmax_sub_fdq'][j]:.0f} Hz) | {t['xr5']['median'][j]:.2f} | {t['xr5']['min'][j]:.2f} |")
    L.append("")
    L.append("**表 2 島と電圧の帯ごとの S_on(力率 1)。SSO の帯の速い側の中央と下位 10%・高い周波数を含む最大の側の中央・中央の定数の中央**\n")
    L.append("| 島 | 帯 | 点 | S_sc 中央 [MVA] | X/R 中央 | S_on SSO の帯 中央 [MVA] | 同 下位 10% | S_on 最大の側 中央 | S_on 中央の定数 中央 |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for b in res["bands"]:
        L.append(f"| {b['island']} | {b['band']} | {b['n']:,} | {b['s_sc_med']:,.0f} | {b['xr_med']:.1f} | "
                 f"{b['on_sub_med']:,.0f} | {b['on_sub_p10']:,.0f} | {b['on_max_med']:,.0f} | {b['on_med_med']:,.0f} |")
    L.append("")
    L.append("**表 3 S_on(SSO の帯の速い側・力率 1)が小さい点。名前のある設備で、別の島に双子が無い点**\n")
    L.append("| 島 | 名前 | kV | S_sc [MVA] | X/R | S_on SSO の帯 [MVA] | S_on 最大の側 | S_on 中央の定数 | 模型の既設 IBR [MW] |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for w in res["weakest"]:
        L.append(f"| {w['island']} | {w['name']} | {w['kv']:.0f} | {w['s_sc']:,.0f} | {w['xr']:.1f} | "
                 f"{w['on_sub']:,.0f} | {w['on_max']:,.0f} | {w['on_median']:,.0f} | {w['ibr_mw']:,.1f} |")
    L.append("")
    L.append("**表 4 既設の IBR(OSM の容量)の SCR と、臨界(力率も定数も一番悪い側。高い周波数を含む)の比**\n")
    L.append("| 島 | 点 | 既設 [MW] | 比 < 1 の点 | SSO の帯の臨界を割る点 | 比の最小 | 比が最小の点 | 外した双子の点(MW) |")
    L.append("|---|---:|---:|---:|---:|---:|---|---:|")
    for b in res["ibr"]:
        t = b["top"][0] if b["top"] else None
        L.append(f"| {b['island']} | {b['n']:,} | {b['mw']:,.0f} | {b['n_below_worst']} | {b['n_below_sub']} | "
                 f"{b['margin_min']:.2f} | " + (f"{t['name']}({t['kv']:.0f} kV・{t['ibr_mw']:.0f} MW・SCR {t['scr_now']:.1f})" if t else "—")
                 + f" | {b['n_twin']}({b['mw_twin']:,.0f}) |")
    L.append("")
    L.append("**表 5 既設の IBR が集まる所の一般化 SCR(双子の点は外す)**\n")
    L.append("| 島 | IBR の点 | 既設 [MW] | 一般化 SCR | 1 点ずつの SCR の最小 | 重みが一番大きい点 | 臨界(一番悪い側) | 同じ並びで何倍まで | 同(SSO の帯) |")
    L.append("|---|---:|---:|---:|---:|---|---:|---:|---:|")
    for isl, g in res["gscr"].items():
        if not g.get("n_ibr_bus"):
            continue
        L.append(f"| {isl} | {g['n_ibr_bus']:,} | {g['ibr_mw']:,.0f} | {g['gscr_min']:.2f} | {g['scr_single_min']:.2f} | "
                 f"{g['lead_bus']}({g['lead_kv']:.0f} kV・重み {g['lead_weight']:.2f}) | {g['crit_worst_at_lead']:.2f} | "
                 f"{g['scale_to_onset']:.1f} | {g['scale_to_onset_sub']:.1f} |")
    L.append("")
    L.append("**表 6 臨界の確かめ(X/R 5)。道 1 = 固有値、道 2 = アドミタンスの零点、道 3 = 非線形の積分。"
             "σ は臨界の 0.97 倍 / 1.03 倍での a 相電流の sub と super の成分の減衰 [1/s]**\n")
    L.append("| 定格 | 力率 | 組(PLL・電流制御・FF) | 道 1 | 道 2 | 相対差 | f_dq [Hz] | 0.97 倍 σ(sub / super) | 1.03 倍 σ(sub / super) | 相の量 [Hz] |")
    L.append("|---|---|---|---:|---:|---:|---:|---|---|---|")
    for c in res["checks"]:
        b, a = c["below"], c["above"]
        L.append(f"| {c['f0']} Hz | {c['pf']} | {c['f_pll']:.0f}・{c['f_cc']:.0f}・{'有' if c['k_ff'] else '無'} | "
                 f"{c['scr_eig']:.4f} | {c['scr_adm']:.4f} | {c['rel']:.0e} | {c['f_dq']:.1f} | "
                 f"{b['sigma_sub']:+.2f} / {b['sigma_sup']:+.2f} | {a['sigma_sub']:+.2f} / {a['sigma_sup']:+.2f} | "
                 f"{b['f_sub']:.1f} と {b['f_sup']:.1f} |")
    return "\n".join(L)


def write_report(res: dict) -> None:
    if not REPORT.exists():
        return
    s = REPORT.read_text(encoding="utf-8")
    new = "<!-- 表:begin -->\n" + report_tables(res) + "\n<!-- 表:end -->"
    s2 = re.sub(r"<!-- 表:begin -->.*?<!-- 表:end -->", lambda _m: new, s, flags=re.S)
    REPORT.write_text(s2, encoding="utf-8")


def write_points(path: Path, pts: list) -> None:
    lab = sm.PF_CASES[PF_MAP][0]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["island", "bus", "name", "kv", "lat", "lon", "s_sc_mva", "x_over_r", "ibr_existing_mw",
                    f"scr_crit_sso_pf{lab}", f"s_on_sso_pf{lab}_mva", f"scr_crit_max_pf{lab}", f"s_on_max_pf{lab}_mva",
                    f"s_on_median_pf{lab}_mva", "scr_crit_worst_any_pf", "twin_in_other_island"])
        for pt in pts:
            for i in np.where(pt["scope"])[0]:
                w.writerow([pt["island"], int(pt["label"][i]), pt["names"][i], r(pt["kv"][i], 0),
                            r(pt["lat"][i], 5), r(pt["lon"][i], 5), r(pt["s_sc"][i], 1), r(pt["xr"][i], 2),
                            r(pt["ibr"][i], 2), r(pt["crit_max_sub"][PF_MAP][i]), r(pt["on_max_sub"][PF_MAP][i], 1),
                            r(pt["crit_max"][PF_MAP][i]), r(pt["on_max"][PF_MAP][i], 1),
                            r(pt["on_median"][PF_MAP][i], 1), r(pt["crit_worst"][i]), int(pt["twin"][i])])


def main() -> None:
    from scripts.run_full_powerflow_from_db import load_demand_config
    from ibr_hosting_scr import BUILT
    from src.powerflow.pref_demand import pref_zone_gwh

    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    tab = tables()
    sec_tab = time.perf_counter() - t0
    chk = checks()
    print(f"確かめ: {sum(c['passed'] for c in chk)}/{len(chk)} 通過", flush=True)
    d = json.load(open(BUILT, encoding="utf-8"))
    nodes, edges = d["nodes"], d["edges"]
    cfg = load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)
    pts = []
    for isl in ISLANDS:
        t1 = time.perf_counter()
        pt = apply_tables(island_points(isl, nodes, edges, cfg, pref_gwh), tab)
        pt["sec"] = time.perf_counter() - t1
        print(f"{isl}: 点 {int(pt['scope'].sum()):,}・既設 IBR {pt['ibr'].sum():,.0f} MW・{pt['sec']:.1f} 秒", flush=True)
        pts.append(pt)
    mark_twins(pts)
    gs = {pt["island"]: gscr_rows(pt) for pt in pts}
    k5 = sm.XR_GRID.index(5.0)
    res = dict(
        params=dict(pll_hz=sm.PLL_HZ, cc_hz=sm.CC_HZ, ff=sm.FF, pf=[c[0] for c in sm.PF_CASES],
                    xr_grid=sm.XR_GRID, scr_lo=sm.SCR_LO, scr_hi=sm.SCR_HI, n_sets=len(sm.param_sets())),
        critical={int(f0): dict(max=t["max"].round(3).tolist(), max_sub=t["max_sub"].round(3).tolist(),
                                median=t["median"].round(3).tolist(), min=t["min"].round(3).tolist(),
                                argmax=t["argmax"], argmax_fdq=[r(v, 1) for v in t["argmax_fdq"]],
                                argmax_sub=t["argmax_sub"], argmax_sub_fdq=[r(v, 1) for v in t["argmax_sub_fdq"]],
                                n_lo=t["n_lo"], n_inf=t["n_inf"], n_sub=t["n_sub"], n_all=t["n_all"],
                                fdq_pf1_xr5=[r(v, 1) for v in t["fdq"][:, 0, k5]],
                                scr_pf1_xr5=[r(v) for v in t["table"][:, 0, k5]],
                                xr5={k: [round(float(v), 3) for v in t[k][:, k5]] for k in ("max", "max_sub", "median", "min")})
                  for f0, t in tab.items()},
        islands={pt["island"]: dict(f0=pt["f0"], n_scope=int(pt["scope"].sum()), n_sync_src=pt["n_src"],
                                    n_twin=int((pt["scope"] & pt["twin"]).sum()),
                                    n_unnamed=int((pt["scope"] & ~pt["place"]).sum()),
                                    sync_mva=r(pt["src_mva"], 0), ibr_mw=r(pt["ibr"].sum(), 1))
                 for pt in pts},
        bands=[b for pt in pts for b in band_rows(pt)],
        weakest=weakest_rows(pts),
        ibr=[ibr_rows(pt) for pt in pts],
        gscr=gs,
        checks=chk,
    )
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    write_points(OUT / "points.csv", pts)
    fig_critical(OUT / "critical.png", tab, pts)
    fig_map(OUT / "map.png", pts)
    write_report(res)
    print(report_tables(res))
    print(f"表 {sec_tab:.0f} 秒・計 {time.perf_counter() - t0:.0f} 秒(時間は results.json に書かない。作り直しでバイトが同じになるように)")


if __name__ == "__main__":
    main()
