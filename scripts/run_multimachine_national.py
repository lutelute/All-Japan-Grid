#!/usr/bin/env python3
"""全島・全機動揺つき共シミュレーション — AGC30 → AGC-N を系統全体へ(2026-08-29).

オーナー指示「全部やって良い。系統までやりたい。COIだけでなく、全部の動揺が
みたい」「全ての発電機動揺の振動プロットして」。

hokkaido単島版(run_multimachine_hokkaido.py)の一般化:
  - 4同期島すべて。UCオンライン全プラント=1機(AGC30機種ガバナ+燃料別H/Xd')
  - 実網のKron縮約Ybus(疎LU)上で古典動揺方程式+GF+LFC+ラッチUFLSを共シミュレーション
  - 運転断面: hokkaido/east/okinawa = AC正典解。west = フルAC不成立が正典
    (docs/WEST_AC_ANALYSIS.md)のため **DC断面(V=1.0近似)** で初期化 —
    Pm=Pe(δ0)の自己無撞着初期化によりモデル内平衡は厳密で、近似は帳簿に開示
  - 初期化整合 max|Pe(δ0)−P_PF| を全島で出力(AC島は≈0が期待値)

出力:
  docs/slides/ajg/assets/fig_swing_<island>.png   (島別詳細: 全機f+拡大+相差角)
  docs/slides/ajg/assets/fig_swing_national.png   (4島×全機の振動プロット)
  docs/data/agc/multimachine_<island>.json        (帳簿)

Usage:
  PYTHONPATH=. python scripts/run_multimachine_national.py
  PYTHONPATH=. python scripts/run_multimachine_national.py --islands east
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from scipy.integrate import solve_ivp

from scripts.run_full_powerflow_from_db import (  # noqa: E402
    BUILT, ISLAND_OF, add_per_component_slacks, allocate_loads,
    attach_generators, GEN_ATTACH_DEFAULT, build_island_net)
from scripts.uc_to_pf_built import solve_hour  # noqa: E402
from src.powerflow.load_estimator import load_demand_config  # noqa: E402
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402
from src.dynamics.models.sync_generator import FUEL_DEFAULT_PARAMS  # noqa: E402
from src.dynamics.agc import (  # noqa: E402
    AGC30_CLASSES, FUEL_TO_CLASS, K_LOAD, S_BASE_MVA, UFLS_STEPS_HZ,
    UFLS_SHED_FRAC, LFC_KP, LFC_KI, LFC_TS, LFC_TLAG)

ISLAND_FREQ = {"hokkaido": 50.0, "east": 50.0, "west": 60.0, "okinawa": 60.0}
ISLAND_MODE = {"hokkaido": "ac", "east": "ac", "west": "dc", "okinawa": "ac"}
MIN_MACH_MW = 5.0
T_TRIP = 1.0
T_END = 60.0


def build_case(island, scn, uc, built, cfg, pref_gwh):
    regions = sorted(r for r, (isl, _f) in ISLAND_OF.items() if isl == island)
    f0 = ISLAND_FREQ[island]
    net_dem = sum(np.asarray(scn.net_demand_r[r]) for r in regions)
    h = int(np.argmax(net_dem))
    print(f"② [{island}] ネット構築+UC断面注入+{ISLAND_MODE[island].upper()}解 "
          f"(t={h}, 需要{net_dem[h]:,.0f}MW)...")
    geom = {}
    base, bus_of, _ = build_island_net(island, built["nodes"], built["edges"],
                                       f0, geom)
    attach_generators(base, bus_of, built["nodes"], island,
                      attach_mode=GEN_ATTACH_DEFAULT)
    allocate_loads(base, cfg, pref_gwh=pref_gwh)
    add_per_component_slacks(base)
    fuel_by_zone = {r: uc_snapshot(uc, scn.generators, h, region=r)
                    for r in regions}
    demand = {r: float(scn.net_demand_r[r][h]) for r in regions}
    net = copy.deepcopy(base)
    inject_dispatch_by_zone(net, fuel_by_zone, demand)
    net, mode = solve_hour(net, ISLAND_MODE[island])
    print(f"   PF mode={mode} served={float(net.res_load.p_mw.sum()):,.0f}MW")
    return net, mode, f0


def extract_model(net, mode, f0):
    """解いたネットから多機古典モデルを構築(疎Kron縮約)."""
    import pandapower as pp
    dc = (mode != "ac")

    # ── 結果配列を先に確保(Ybus組立のrunppがresを壊す前に) ──
    res_bus = net.res_bus.copy()
    res_gen = net.res_gen.copy()
    res_load = net.res_load.copy()
    res_sgen = net.res_sgen.copy() if len(net.sgen) else None
    res_ext = net.res_ext_grid.copy()

    # ── Ybus: 直近のrunppが残した内部行列(DC島は組立のためrunppを試す) ──
    if dc:
        try:
            pp.runpp(net, init="flat", numba=False, max_iteration=3)
        except Exception:  # noqa: BLE001 — 収束不要。Ybus組立だけが目的
            pass
    ppc = net._ppc
    internal = ppc["internal"]
    Ysp = internal["Ybus"]
    if Ysp is None or Ysp.shape[0] == 0:
        raise RuntimeError("Ybus not assembled")
    base_ppc = float(ppc["baseMVA"])
    Ysp = sp.csr_matrix(Ysp, dtype=complex) * (base_ppc / S_BASE_MVA)
    nb = Ysp.shape[0]
    lookup = net._pd2ppc_lookups["bus"]

    def ppb(pd_bus):
        return int(lookup[int(pd_bus)])

    # 主同期成分の判定 — 動揺方程式の対象は「同期して繋がっている島」のみ。
    # 断片上のプラントを機械にすると疎結合アーティファクト(過周波数暴走)に
    # なるため定注入へ折り込む(帳簿に台数を開示)
    from scipy.sparse.csgraph import connected_components
    ncomp, comp = connected_components(
        (abs(Ysp) > 1e-9).astype(np.int8), directed=False)
    main_comp = int(np.bincount(comp).argmax())

    # 電圧(ppc順)。DC断面は vm=1.0 近似(帳簿に開示)
    V = np.ones(nb, dtype=complex)
    for pos, pd_idx in enumerate(net.bus.index):
        b = ppb(pd_idx)
        if not (0 <= b < nb):
            continue
        vmv = res_bus.vm_pu.iloc[pos]
        vav = res_bus.va_degree.iloc[pos]
        vm = float(vmv) if np.isfinite(vmv) else 1.0
        va = float(vav) if np.isfinite(vav) else 0.0
        V[b] = vm * np.exp(1j * np.deg2rad(va))

    def num(x):
        return float(x) if np.isfinite(x) else 0.0

    machines = []
    mach_binj = np.zeros(nb, dtype=complex)
    slack_col = net.gen.get("slack")
    for gi in net.gen.index:
        p = num(res_gen.at[gi, "p_mw"])
        q = num(res_gen.at[gi, "q_mvar"])
        fuel = str(net.gen.at[gi, "type"] or "unknown").lower()
        b = ppb(net.gen.at[gi, "bus"])
        cls = FUEL_TO_CLASS.get(fuel, "unknown")
        is_slack = bool(slack_col.at[gi]) if slack_col is not None else False
        off_main = (comp[b] != main_comp)
        if is_slack or off_main or p < MIN_MACH_MW or \
                fuel in ("solar", "wind", "battery"):
            mach_binj[b] += (p + 1j * q) / S_BASE_MVA
            n_frag = extract_model.n_frag = \
                getattr(extract_model, "n_frag", 0) + (1 if off_main else 0)
            continue
        cap = float(net.gen.at[gi, "max_p_mw"]) \
            if np.isfinite(net.gen.at[gi, "max_p_mw"] or np.nan) else p
        cap = max(cap, p)
        # 容量疑義ガード: 定格が運転点の10倍超かつ+500MW超は容量DBの外れ値
        # (例: 22.9MW運転の廃棄物発電に定格3,000MW)とみなし、S・余力を
        # 運転点ベースへフォールバック(データ改変ではなく不使用+開示)
        if cap > 10.0 * p and cap - p > 500.0:
            extract_model.cap_sus = getattr(extract_model, "cap_sus", [])
            extract_model.cap_sus.append(
                f"{net.gen.at[gi, 'name']}: P={p:,.0f}MW cap={cap:,.0f}MW")
            cap = p
        S_i = cap / 0.9
        prm = FUEL_DEFAULT_PARAMS.get(fuel) or FUEL_DEFAULT_PARAMS["unknown"]
        lon = lat = float("nan")
        try:      # pandapower 3.x: bus.geo (GeoJSON文字列)
            import json as _json
            g = _json.loads(net.bus.at[int(net.gen.at[gi, "bus"]), "geo"])
            lon, lat = float(g["coordinates"][0]), float(g["coordinates"][1])
        except Exception:  # noqa: BLE001
            try:  # 旧API
                gd = net.bus_geodata.loc[int(net.gen.at[gi, "bus"])]
                lon, lat = float(gd["x"]), float(gd["y"])
            except Exception:  # noqa: BLE001
                pass
        machines.append(dict(
            name=str(net.gen.at[gi, "name"]), fuel=fuel, cls=cls, bus=b,
            lon=lon, lat=lat,
            P=p / S_BASE_MVA, Q=q / S_BASE_MVA, S=S_i,
            H=prm["H"], Ddyn=prm["D"],
            Xdp=prm["Xd_p"] * S_BASE_MVA / S_i,
            cap_pu=cap / S_BASE_MVA))
    n = len(machines)
    n_frag = getattr(extract_model, "n_frag", 0)
    extract_model.n_frag = 0
    sus = getattr(extract_model, "cap_sus", [])
    extract_model.cap_sus = []
    print(f"③ 機械 {n} 台 / バス {nb} (断片上のプラント{n_frag}件は定注入へ"
          f" / 容量疑義{len(sus)}件は運転点ベース)")
    for msg in sus:
        print(f"     容量疑義: {msg}")

    # 非機械の正味注入 → 定アドミタンス化
    S_bus = np.zeros(nb, dtype=complex)
    for df, res, sign in ((net.load, res_load, -1.0),
                          (net.sgen, res_sgen, +1.0)):
        if res is None:
            continue
        for i in df.index:
            if not bool(df.at[i, "in_service"]):
                continue
            b = ppb(df.at[i, "bus"])
            S_bus[b] += sign * (num(res.at[i, "p_mw"]) +
                                1j * num(res.at[i, "q_mvar"])) / S_BASE_MVA
    for i in net.ext_grid.index:
        b = ppb(net.ext_grid.at[i, "bus"])
        S_bus[b] += (num(res_ext.at[i, "p_mw"]) +
                     1j * num(res_ext.at[i, "q_mvar"])) / S_BASE_MVA
    S_bus += mach_binj
    yload = -np.conj(S_bus) / np.maximum(np.abs(V) ** 2, 1e-6)

    yshed = np.zeros(nb, dtype=complex)
    for i in net.load.index:
        if not bool(net.load.at[i, "in_service"]):
            continue
        b = ppb(net.load.at[i, "bus"])
        s = (num(res_load.at[i, "p_mw"]) +
             1j * num(res_load.at[i, "q_mvar"])) / S_BASE_MVA
        yshed[b] += np.conj(s) / np.maximum(np.abs(V[b]) ** 2, 1e-6)

    E = np.zeros(n, dtype=complex)
    for k, m in enumerate(machines):
        Vt = V[m["bus"]]
        I = np.conj((m["P"] + 1j * m["Q"]) / Vt)
        E[k] = Vt + 1j * m["Xdp"] * I
    delta0 = np.angle(E)
    Em = np.abs(E)

    idx = np.arange(nb)

    def kron(shed_frac, tripped=frozenset()):
        tripped = ({tripped} if isinstance(tripped, int) else
                   set(tripped or ()))
        diag = yload - shed_frac * yshed + 1e-8
        rows, cols, vals = [], [], []
        Yii = np.zeros((n, n), dtype=complex)
        for k, m in enumerate(machines):
            if k in tripped:
                continue
            ya = 1.0 / (1j * m["Xdp"])
            rows.append(m["bus"]); cols.append(m["bus"]); vals.append(ya)
            Yii[k, k] = ya
        Ybb = (Ysp + sp.diags(diag) +
               sp.csr_matrix((vals, (rows, cols)), shape=(nb, nb),
                             dtype=complex)).tocsc()
        lu = splu(Ybb)
        yintT = np.zeros((nb, n), dtype=complex)
        for k, m in enumerate(machines):
            if k in tripped:
                continue
            yintT[m["bus"], k] = -1.0 / (1j * m["Xdp"])
        X = lu.solve(yintT)
        Yred = Yii - yintT.T @ X       # yint = yintTᵀ (対称)
        return Yred

    load0_pu = float(res_load.p_mw.sum()) / S_BASE_MVA
    return machines, Em, delta0, kron, load0_pu


def simulate(island, f0, machines, Em, delta0, kron, load0_pu):
    n = len(machines)
    omega_s = 2.0 * math.pi * f0
    M = np.array([2 * m["H"] * m["S"] / S_BASE_MVA for m in machines])
    Dd = np.array([m["Ddyn"] * m["S"] / S_BASE_MVA for m in machines])
    Msum = M.sum()
    trip = int(np.argmax([m["P"] for m in machines]))
    print(f"④ トリップ: {machines[trip]['name']} "
          f"({machines[trip]['P']*S_BASE_MVA:,.0f} MW)")

    cls = [AGC30_CLASSES.get(m["cls"]) for m in machines]
    has_gov = np.array([c is not None for c in cls])
    Tg = np.array([c["Tg"] if c else 1.0 for c in cls])
    Tt = np.array([c["Tt"] if c else 1.0 for c in cls])
    gfw = np.array([(c["gf"] * m["S"] * c["resp_share"] / S_BASE_MVA)
                    if c else 0.0 for c, m in zip(cls, machines)])
    rate = np.array([(c["rate"] * m["S"] * c["resp_share"] / S_BASE_MVA / 60)
                     if c else 0.0 for c, m in zip(cls, machines)])
    invR = np.array([(m["S"] * (c["resp_share"] if c else 0) / S_BASE_MVA /
                      (c["R"] if c else 1)) if c else 0.0
                     for c, m in zip(cls, machines)])
    room = np.array([max(0.0, m["cap_pu"] - m["P"]) for m in machines])
    agc_ok = np.array([bool(c and c["agc"]) for c in cls])
    alpha = np.where(agc_ok, room, 0.0)
    alpha = alpha / max(alpha.sum(), 1e-9)

    print("⑤ 縮約Ybus事前計算(トリップ前後×UFLS 0..3段)...")
    t0 = time.monotonic()
    Y_pre = kron(0.0)
    Y_post = {k: kron(UFLS_SHED_FRAC * k, tripped={trip}) for k in range(4)}
    print(f"   {time.monotonic()-t0:.0f}s")

    def Pe(delta, Yred):
        Ev = Em * np.exp(1j * delta)
        return np.real(Ev * np.conj(Yred @ Ev))

    Pm0 = Pe(delta0, Y_pre)
    p_set = np.array([m["P"] for m in machines])
    err = np.abs(Pm0 - p_set)
    print(f"   初期化整合: max|Pe(δ0)−P_PF| = {err.max()*S_BASE_MVA:,.1f} MW "
          f"(中央値 {np.median(err)*S_BASE_MVA:,.1f} MW)")
    state = {"Yred": Y_pre, "stage": 0, "tripped": False}
    live = np.ones(n, bool)
    t_drop = np.full(n, np.inf)      # 各機の切離し時刻(表示マスク用)
    oos = set()          # 脱調保護で切り離した機(out-of-step)

    def rhs(t, y):
        d, w = y[:n], y[n:2 * n]
        x1, x2 = y[2 * n:3 * n], y[3 * n:4 * n]
        s = y[4 * n:5 * n]
        z, wi = y[5 * n], y[5 * n + 1]
        pe = Pe(d, state["Yred"])
        coi_w = float((M * w)[live].sum() / M[live].sum())
        u = -(LFC_KP * z + LFC_KI * wi)
        dx1 = np.where(has_gov, (-w * invR + s - x1) / Tg, 0.0)
        dx2 = np.where(has_gov, (x1 - x2) / Tt, 0.0)
        ds = np.clip((alpha * u * live - s) / LFC_TLAG, -rate, rate)
        dpm = np.clip(x2, -gfw, np.minimum(gfw + np.maximum(s, 0), room))
        pm = (Pm0 + dpm) * live
        load_now = load0_pu * (1.0 - UFLS_SHED_FRAC * state["stage"])
        dload = K_LOAD * load_now * coi_w
        dw = (pm - pe * live - Dd * w) / M - dload / Msum
        dd = omega_s * w
        ace = coi_w
        dzv = (ace - z) / LFC_TS
        dwi = z
        out = np.concatenate([dd, dw, dx1, dx2, ds, [dzv, dwi]])
        dead = ~live
        out[:n][dead] = 0.0
        out[n:2 * n][dead] = 0.0
        return out

    def ev_trip(t, y):
        return t - T_TRIP
    ev_trip.terminal = True
    ev_trip.direction = 1

    # 脱調保護(out-of-step): |δ_i − δ_COI| が180°を超えた機を切り離す。
    # 実系統の保護リレー相当 — 弱結合の小規模機はトリップ/UFLSの網変化で
    # 送出上限がPmを割って滑る(古典モデルの現実的挙動)ため、保護が要る
    dcoi0 = float((M * delta0).sum() / M.sum())
    rel0 = delta0 - dcoi0            # 初期の相対角(定常オフセット)

    def ev_oos(t, y):
        d = y[:n]
        dcoi = float((M * d)[live].sum() / M[live].sum())
        # 初期相対角からの「偏移」が180°を超えたら脱調(絶対角では
        # 初期の広がりに埋もれて検出できない)
        dev = np.abs((d - dcoi) - rel0)
        dev[~live] = 0.0
        return math.pi - float(dev.max())
    ev_oos.terminal = True
    ev_oos.direction = -1

    def mk_ufls(k):
        def ev(t, y):
            w = y[n:2 * n]
            coi = float((M * w)[live].sum() / M[live].sum()) * f0
            return coi - UFLS_STEPS_HZ[k]
        ev.terminal = True
        ev.direction = -1
        return ev

    y0 = np.concatenate([delta0, np.zeros(4 * n + 2)])
    t_all, tr_d, tr_w = [], [], []
    tcur = 0.0
    events_left = [("trip", ev_trip)] + [(f"UFLS 第{k+1}段", mk_ufls(k))
                                         for k in range(3)]
    log = []
    while tcur < T_END - 1e-6:
        evs = [e for _nm, e in events_left] + [ev_oos]
        sol = solve_ivp(rhs, (tcur, T_END), y0, method="RK45",
                        max_step=0.02, rtol=1e-6, atol=1e-8,
                        t_eval=np.arange(tcur, T_END, 0.02), events=evs)
        t_all.append(sol.t)
        tr_d.append(sol.y[:n])
        tr_w.append(sol.y[n:2 * n])
        hit = next((i for i, te in enumerate(sol.t_events) if len(te)), None)
        if hit is None:
            break
        te = float(sol.t_events[hit][0])
        y0 = sol.y_events[hit][0].copy()
        if hit == len(events_left):          # 脱調保護
            d_now = y0[:n]
            dcoi = float((M * d_now)[live].sum() / M[live].sum())
            dev = np.abs((d_now - dcoi) - rel0)
            dev[~live] = 0.0
            k_oos = int(dev.argmax())
            live[k_oos] = False
            t_drop[k_oos] = te
            oos.add(k_oos)
            state["Yred"] = kron(
                UFLS_SHED_FRAC * state["stage"]
                if state["tripped"] else 0.0,
                tripped=({trip} | oos) if state["tripped"] else oos)
            log.append((te, f"脱調保護: {machines[k_oos]['name']}"
                        f"({machines[k_oos]['P']*S_BASE_MVA:,.0f}MW)"))
            tcur = te
            continue
        name = events_left[hit][0]
        if name == "trip":
            state["tripped"] = True
            live[trip] = False
            t_drop[trip] = te
            state["Yred"] = kron(UFLS_SHED_FRAC * state["stage"],
                                 tripped={trip} | oos) if oos \
                else Y_post[state["stage"]]
            log.append((te, f"トリップ: {machines[trip]['name']}"))
        else:
            state["stage"] += 1
            state["Yred"] = kron(UFLS_SHED_FRAC * state["stage"],
                                 tripped={trip} | oos) if oos \
                else Y_post[state["stage"]]
            log.append((te, name))
        events_left.pop(hit)
        tcur = te
    t = np.concatenate(t_all)
    d = np.concatenate(tr_d, axis=1)
    w = np.concatenate(tr_w, axis=1)
    for te, msg in log:
        print(f"   t={te:6.2f}s  {msg}")
    # 暴走診断: 終端|Δf|>2Hz の機を列挙し、トリップ前後の結合強度を比較
    coi_fin = float((M * w[:, -1])[live].sum() / max(M[live].sum(), 1e-9))
    bad = [k for k in range(n)
           if live[k] and abs(w[k, -1] - coi_fin) * f0 > 2.0]
    for k in bad:
        m = machines[k]
        print(f"   COI乖離>2Hz: {m['name'][:24]:24s} {m['fuel']:8s} "
              f"P={m['P']*S_BASE_MVA:8,.1f}MW S={m['S']:6,.0f}MVA "
              f"Xdp={m['Xdp']:.4f}")
    # 切離し後は描画しない(凍結トレースが軸を支配して本体動揺が潰れるため)
    for k in range(n):
        if np.isfinite(t_drop[k]):
            w[k, t > t_drop[k]] = np.nan
            d[k, t > t_drop[k]] = np.nan
    return dict(t=t, d=d, w=w, M=M, live=live, trip=trip, log=log,
                oos=sorted(machines[k]["name"] for k in oos),
                err_mw=float(err.max() * S_BASE_MVA))


def island_figure(island, f0, machines, r):
    t, d, w, M, live, trip, log = (r["t"], r["d"], r["w"], r["M"], r["live"],
                                   r["trip"], r["log"])
    n = len(machines)
    coi = (M[live][:, None] * w[live]).sum(axis=0) / M[live].sum()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11.5, 7.6), dpi=150,
                                   sharex=True,
                                   gridspec_kw={"height_ratios": [3, 2]})
    cmap = plt.cm.turbo(np.linspace(0.05, 0.95, n))
    for k in range(n):
        if k == trip:
            continue
        ax1.plot(t, f0 + w[k] * f0, lw=0.5, color=cmap[k], alpha=0.5)
    ax1.plot(t, f0 + coi * f0, lw=2.4, color="#111111",
             label=f"系統平均(COI) — {int(live.sum())}機")
    for te, _msg in log:
        ax1.axvline(te, color="#C62828", lw=0.9, ls=":", alpha=0.7)
    axz = ax1.inset_axes([0.42, 0.12, 0.55, 0.55])
    for k in range(n):
        if k == trip:
            continue
        axz.plot(t, f0 + w[k] * f0, lw=0.6, color=cmap[k], alpha=0.55)
    axz.plot(t, f0 + coi * f0, lw=1.6, color="#111111")
    axz.set_xlim(0.5, 9.0)
    lo = float(np.nanmin((f0 + coi * f0)[(t > 0.5) & (t < 9.0)]))
    axz.set_ylim(lo - 0.25, f0 + 0.2)
    axz.set_title("拡大: 事故直後の全機動揺", fontsize=10)
    axz.grid(alpha=0.3)
    for te, msg in log:
        axz.axvline(te, color="#C62828", lw=0.8, ls=":", alpha=0.7)
        axz.text(te + 0.05, lo - 0.15, msg, rotation=90, fontsize=8,
                 color="#C62828", va="bottom")
    ax1.indicate_inset_zoom(axz, edgecolor="#888888")
    ax1.set_ylabel("各機の周波数 [Hz]", fontsize=11)
    ax1.legend(fontsize=10, loc="lower right")
    ax1.grid(alpha=0.25)
    ax1.set_title(
        f"{island}: {machines[trip]['name']}"
        f"({machines[trip]['P']*S_BASE_MVA:,.0f} MW)脱落 / 機械{n}台・"
        f"AGC30機種モデル×実網Kron縮約", fontsize=12)
    dcoi = (M[live][:, None] * d[live]).sum(axis=0) / M[live].sum()
    for k in range(n):
        if k == trip:
            continue
        ax2.plot(t, np.rad2deg(d[k] - dcoi), lw=0.5, color=cmap[k],
                 alpha=0.5)
    ax2.set_xlabel("時間 [秒]  (t=1sでトリップ)", fontsize=11)
    ax2.set_ylabel("相差角 δ−δ_COI [deg]", fontsize=11)
    ax2.grid(alpha=0.25)
    fig.tight_layout()
    out = f"docs/slides/ajg/assets/fig_swing_{island}.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"-> {out}")


def national_figure(results):
    order = ["hokkaido", "east", "west", "okinawa"]
    have = [i for i in order if i in results]
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.2), dpi=150)
    for ax, island in zip(axes.ravel(), have):
        machines, r, f0 = results[island]
        t, d, w, M, live, trip = (r["t"], r["d"], r["w"], r["M"], r["live"],
                                  r["trip"])
        n = len(machines)
        coi = (M[live][:, None] * w[live]).sum(axis=0) / M[live].sum()
        cmap = plt.cm.turbo(np.linspace(0.05, 0.95, n))
        for k in range(n):
            if k == trip:
                continue
            ax.plot(t, f0 + w[k] * f0, lw=0.45, color=cmap[k], alpha=0.5)
        ax.plot(t, f0 + coi * f0, lw=2.0, color="#111111")
        ax.set_xlim(0, 30)
        # y軸は本体(生存機)の帯に合わせる — 脱調機は保護動作の瞬間まで
        # 根本だけ見え、枠外へ抜ける(全経過は島別詳細図とログにある)
        lo = float(np.nanmin(f0 + w[live] * f0))
        ax.set_ylim(lo - 0.25, f0 + 0.8)
        ax.grid(alpha=0.25)
        note = "" if r["err_mw"] < 1 else "・DC断面初期化"
        oosn = len(r["oos"])
        oostxt = f"・脱調保護{oosn}機" if oosn else ""
        ax.set_title(f"{island} ({f0:.0f} Hz) — {machines[trip]['name']} "
                     f"−{machines[trip]['P']*S_BASE_MVA:,.0f} MW / "
                     f"{int(live.sum())}機{note}{oostxt}", fontsize=10.5)
        ax.set_ylabel("f [Hz]", fontsize=10)
        ax.set_xlabel("時間 [秒]", fontsize=10)
    fig.suptitle("全島・全機の動揺 — 最大オンラインプラント脱落(各同期島・"
                 "AGC30機種モデル×実網Kron縮約・黒=COI)", fontsize=13)
    fig.tight_layout()
    out = "docs/slides/ajg/assets/fig_swing_national.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"-> {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="+",
                    default=["hokkaido", "east", "west", "okinawa"])
    args = ap.parse_args()
    print("① UC求解...")
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    assert uc.is_optimal
    built = json.load(open(BUILT))
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(built["nodes"])

    results = {}
    for island in args.islands:
        t0 = time.monotonic()
        net, mode, f0 = build_case(island, scn, uc, built, cfg, pref_gwh)
        machines, Em, delta0, kron, load0 = extract_model(net, mode, f0)
        r = simulate(island, f0, machines, Em, delta0, kron, load0)
        island_figure(island, f0, machines, r)
        results[island] = (machines, r, f0)
        doc = {"note": ("多機(AGC-N)共シミュレーション帳簿。AGC30機種定数×"
                        "UCオンライン全機×実網Kron縮約。負荷=定Z・UFLS=負荷Y"
                        "一様縮小(ラッチ)・S=定格/0.9・H,Xd',D=典型値。"
                        + ("westはDC断面(V=1近似)初期化 — AC不成立が正典のため"
                           if mode != "ac" else "AC正典解で初期化")),
               "island": island, "pf_mode": mode,
               "n_machines": len(machines),
               "init_err_max_mw": r["err_mw"],
               "tripped": machines[r["trip"]]["name"],
               "trip_mw": round(machines[r["trip"]]["P"] * S_BASE_MVA, 1),
               "out_of_step_tripped": r["oos"],
               "events": [{"t_s": round(te, 2), "event": m}
                          for te, m in r["log"]]}
        json.dump(doc, open(f"docs/data/agc/multimachine_{island}.json", "w"),
                  ensure_ascii=False, indent=1)
        # 伝播アニメ等の下流用に全機トレースを保存(再生成可能・gitignore)
        np.savez_compressed(
            f"docs/data/agc/mm_traces_{island}.npz",
            t=r["t"], w=r["w"], f0=f0, trip=r["trip"],
            lon=np.array([m["lon"] for m in machines]),
            lat=np.array([m["lat"] for m in machines]),
            S=np.array([m["S"] for m in machines]),
            M=r["M"], live=r["live"],
            names=np.array([m["name"] for m in machines]),
            ev_t=np.array([te for te, _m in r["log"]]),
            ev_s=np.array([m for _te, m in r["log"]]))
        print(f"   [{island}] 計 {time.monotonic()-t0:.0f}s")
    national_figure(results)


if __name__ == "__main__":
    main()
