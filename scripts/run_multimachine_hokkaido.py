#!/usr/bin/env python3
"""北海道・全機動揺つき共シミュレーション — AGC30をAGC-Nへ(2026-08-29).

オーナー指示「周波数の落ちから戻っていくのに動揺がないのが違和感」
「大量の発電機の動揺もみたい」「AGC30からAGC100とかやって系統シミュレーション
できないの?」への回答実装。

AGC30 の機種モデル(GH1386)を、**UCがその時刻にオンラインにした全プラント**へ
1機ずつ与え(=AGC-N)、**実抽出網のKron縮約Ybus**の上で古典動揺方程式と
共シミュレーションする:

  δ̇_i = ω_s Δω_i
  M_i Δω̇_i = Pm_i + ΔPm_i^gov − Pe_i(δ) − D_i Δω_i
  Pe_i = Σ_j E_i E_j [G_ij cos(δ_i−δ_j) + B_ij sin(δ_i−δ_j)]

  ガバナ/タービン: AGC30機種別2次簡約(agc.pyと同一定数)・GF幅クリップ
  LFC: COI周波数に対するAGC30 PI(KP=1, KI=0.003)・余力比例参加・変化率制限
  UFLS: COI周波数のしきい値横断を積分イベントで検出し、負荷アドミタンスを
        段階的に縮小した縮約Ybusへ**切替**(ラッチ・遮断は戻らない)

モデル化の開示(捏造ゼロ):
  - 負荷は定インピーダンス化(古典モデルの標準仮定)。UFLSは負荷Yの一様縮小
    (どの変電所を切るかは非公開のため空間配分は一様)
  - S_i = 定格/0.9(力率仮定)・H,Xd',D は FUEL_DEFAULT_PARAMS(出典つき典型値)
  - Pm_i はAC解のPe_i(δ0)で自己無撞着に初期化(初期化残差ゼロ)
  - 同期しない電源(太陽光/風力)と5MW未満は定Z負荷側へ折込み
  - 各段の縮約Ybusは (トリップ前後)×(UFLS 0..3段) を事前計算し切替

出力:
  docs/slides/ajg/assets/fig_swing_hokkaido.png  (全機の周波数+COI / 相差角)
  docs/data/agc/multimachine_hokkaido.json       (帳簿)
"""
from __future__ import annotations

import copy
import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from scipy.integrate import solve_ivp

from scripts.run_full_powerflow_from_db import (  # noqa: E402
    BUILT, add_per_component_slacks, allocate_loads, attach_generators,
    GEN_ATTACH_DEFAULT, build_island_net)
from scripts.uc_to_pf_built import solve_hour  # noqa: E402
from src.powerflow.load_estimator import load_demand_config  # noqa: E402
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402
from src.dynamics.models.sync_generator import FUEL_DEFAULT_PARAMS  # noqa: E402
from src.dynamics.agc import (  # noqa: E402
    AGC30_CLASSES, FUEL_TO_CLASS, K_LOAD, S_BASE_MVA, UFLS_STEPS_HZ,
    UFLS_SHED_FRAC, LFC_KP, LFC_KI, LFC_TS, LFC_TLAG)

F0 = 50.0
OMEGA_S = 2.0 * math.pi * F0
MIN_MACH_MW = 5.0
T_TRIP = 1.0
T_END = 60.0


def build_case():
    """UC断面 → 北海道AC解 → 機械リスト・縮約Ybus一式."""
    print("① UC求解...")
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    assert uc.is_optimal
    h = int(np.argmax(np.asarray(scn.net_demand_r["hokkaido"])))
    built = json.load(open(BUILT))
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(built["nodes"])

    print("② 北海道ネット構築+UC断面注入+AC解...")
    geom = {}
    base, bus_of, _ = build_island_net("hokkaido", built["nodes"],
                                       built["edges"], F0, geom)
    attach_generators(base, bus_of, built["nodes"], "hokkaido",
                      attach_mode=GEN_ATTACH_DEFAULT)
    allocate_loads(base, cfg, pref_gwh=pref_gwh)
    add_per_component_slacks(base)
    fuel_by_zone = {"hokkaido": uc_snapshot(uc, scn.generators, h,
                                            region="hokkaido")}
    demand = {"hokkaido": float(scn.net_demand_r["hokkaido"][h])}
    net = copy.deepcopy(base)
    inject_dispatch_by_zone(net, fuel_by_zone, demand)
    net, mode = solve_hour(net, "ac")
    print(f"   PF mode={mode} served={float(net.res_load.p_mw.sum()):,.0f}MW")
    assert mode == "ac", "北海道AC解が前提"
    return net


def extract_model(net):
    """解いたACネットから多機古典モデルを構築."""
    import pandapower as pp
    from src.ac_powerflow.network_prep import prepare_network
    data = prepare_network(net)
    base_ppc = float(net._ppc["baseMVA"])
    # build_island_net は create_empty_network 既定の sn_mva=1.0 で作るため
    # ppc の Ybus は 1MVA 基準。本モデルは 100MVA 基準で組む:
    # y_pu(S2) = y_pu(S1)·(S1/S2)
    Y = np.array(data.Ybus.toarray(), dtype=complex) * (base_ppc / S_BASE_MVA)
    print(f"   ppc baseMVA={base_ppc} → Ybusを{S_BASE_MVA:.0f}MVA基準へ変換")
    nb = Y.shape[0]
    lookup = net._pd2ppc_lookups["bus"]

    def ppb(pd_bus):
        return int(lookup[int(pd_bus)])

    # 電圧を ppc バス番号順に並べ替える(res_bus は pandapower 行順。
    # これを取り違えると結合が嘘になり全機脱調する — 2026-08-29 初版のバグ)
    V = np.ones(nb, dtype=complex)
    for pos, pd_idx in enumerate(net.bus.index):
        b = int(lookup[int(pd_idx)])
        if 0 <= b < nb:
            vmv = net.res_bus.vm_pu.iloc[pos]
            vav = net.res_bus.va_degree.iloc[pos]
            if np.isfinite(vmv):
                V[b] = float(vmv) * np.exp(1j * np.deg2rad(float(vav)))

    # ── 機械の選定: net.gen の p_mw≥5MW・同期燃料 ──
    machines = []
    mach_binj = np.zeros(nb, dtype=complex)   # 機械としては扱わない分の注入
    slack_col = net.gen.get("slack")
    for gi in net.gen.index:
        p = float(net.res_gen.at[gi, "p_mw"])
        q = float(net.res_gen.at[gi, "q_mvar"])
        fuel = str(net.gen.at[gi, "type"] or "unknown").lower()
        b = ppb(net.gen.at[gi, "bus"])
        cls = FUEL_TO_CLASS.get(fuel, "unknown")
        is_slack = bool(slack_col.at[gi]) if slack_col is not None else False
        if is_slack or p < MIN_MACH_MW or fuel in ("solar", "wind", "battery"):
            mach_binj[b] += (p + 1j * q) / S_BASE_MVA
            continue
        cap = float(net.gen.at[gi, "max_p_mw"]) \
            if np.isfinite(net.gen.at[gi, "max_p_mw"] or np.nan) else p
        cap = max(cap, p)
        S_i = max(cap, p) / 0.9
        prm = FUEL_DEFAULT_PARAMS.get(fuel) or FUEL_DEFAULT_PARAMS["unknown"]
        machines.append(dict(
            name=str(net.gen.at[gi, "name"]), fuel=fuel, cls=cls, bus=b,
            P=p / S_BASE_MVA, Q=q / S_BASE_MVA, S=S_i,
            H=prm["H"], Ddyn=prm["D"],
            Xdp=prm["Xd_p"] * S_BASE_MVA / S_i,
            cap_pu=cap / S_BASE_MVA))
    n = len(machines)
    print(f"③ 機械 {n} 台 (≥{MIN_MACH_MW}MW・同期燃料) / バス {nb}")

    # ── 全バスの「非機械」正味注入を定アドミタンス化 ──
    yload = np.zeros(nb, dtype=complex)
    S_bus = np.zeros(nb, dtype=complex)
    for tbl, sign in (("load", -1.0), ("sgen", +1.0)):
        df = getattr(net, tbl)
        res = getattr(net, f"res_{tbl}")
        for i in df.index:
            if not bool(df.at[i, "in_service"]):
                continue
            b = ppb(df.at[i, "bus"])
            S_bus[b] += sign * (float(res.at[i, "p_mw"]) +
                                1j * float(res.at[i, "q_mvar"])) / S_BASE_MVA
    for i in net.ext_grid.index:      # slack残差は定注入として折込み
        b = ppb(net.ext_grid.at[i, "bus"])
        S_bus[b] += (float(net.res_ext_grid.at[i, "p_mw"]) +
                     1j * float(net.res_ext_grid.at[i, "q_mvar"])) / S_BASE_MVA
    S_bus += mach_binj
    # S = V·conj(I) → 等価アドミタンス y = conj(S)/|V|² (負荷は負のSで正のy)
    with np.errstate(divide="ignore", invalid="ignore"):
        yload = -np.conj(S_bus) / np.maximum(np.abs(V) ** 2, 1e-6)

    # 負荷側yと発電側y(遮断対象は負荷のみ)を分離: UFLSは load 表の分だけ縮小
    yshed = np.zeros(nb, dtype=complex)
    for i in net.load.index:
        if not bool(net.load.at[i, "in_service"]):
            continue
        b = ppb(net.load.at[i, "bus"])
        s = (float(net.res_load.at[i, "p_mw"]) +
             1j * float(net.res_load.at[i, "q_mvar"])) / S_BASE_MVA
        yshed[b] += np.conj(s) / np.maximum(np.abs(V[b]) ** 2, 1e-6)

    # ── 機械内部電圧・初期角 ──
    E = np.zeros(n, dtype=complex)
    for k, m in enumerate(machines):
        Vt = V[m["bus"]]
        I = np.conj((m["P"] + 1j * m["Q"]) / Vt)
        E[k] = Vt + 1j * m["Xdp"] * I
    delta0 = np.angle(E)
    Em = np.abs(E)

    def kron(shed_frac, tripped=None):
        """内部ノードへ縮約したYred(n×n)。shed_frac=負荷Yの縮小率、
        tripped=切り離す機械index(内部枝を外す)."""
        Ybb = Y.copy()
        Ybb[np.arange(nb), np.arange(nb)] += yload - shed_frac * yshed
        # 孤立バス(零行)対策の微小正則化 — 断片は本体と物理的に切れており
        # 縮約結果へ実質影響しない
        Ybb[np.arange(nb), np.arange(nb)] += 1e-8
        yint = np.zeros((n, nb), dtype=complex)
        for k, m in enumerate(machines):
            if k == tripped:
                continue
            ya = 1.0 / (1j * m["Xdp"])
            Ybb[m["bus"], m["bus"]] += ya
            yint[k, m["bus"]] = -ya
        Yii = np.zeros((n, n), dtype=complex)
        for k, m in enumerate(machines):
            if k != tripped:
                Yii[k, k] = 1.0 / (1j * machines[k]["Xdp"])
        # Yred = Y_II − Y_IB·Y_BB⁻¹·Y_BI (Y_BI = Y_IBᵀ)
        Yred = Yii - yint @ np.linalg.solve(Ybb, yint.T)
        return Yred

    return machines, Em, delta0, kron


def simulate(machines, Em, delta0, kron, load0_pu):
    n = len(machines)
    M = np.array([2 * m["H"] * m["S"] / S_BASE_MVA for m in machines])
    Dd = np.array([m["Ddyn"] * m["S"] / S_BASE_MVA for m in machines])
    trip = int(np.argmax([m["P"] for m in machines]))
    print(f"④ トリップ対象: {machines[trip]['name']} "
          f"({machines[trip]['P']*S_BASE_MVA:,.0f} MW)")

    # ガバナ/ LFC 定数(AGC30クラス・agc.pyと同一)
    cls = [AGC30_CLASSES.get(m["cls"]) for m in machines]
    has_gov = np.array([c is not None for c in cls])
    R = np.array([c["R"] if c else 1e9 for c in cls])
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

    # 事前計算した縮約Y: (フェーズ, 遮断段) → Yred
    print("⑤ 縮約Ybusを事前計算(トリップ前後×UFLS 0..3段)...")
    Y_pre = kron(0.0, tripped=None)
    Y_post = {k: kron(UFLS_SHED_FRAC * k, tripped=trip) for k in range(4)}

    def Pe(delta, Yred):
        Ev = Em * np.exp(1j * delta)
        return np.real(Ev * np.conj(Yred @ Ev))

    Pm0 = Pe(delta0, Y_pre)          # 自己無撞着初期化
    Msum = M.sum()
    p_set = np.array([m["P"] for m in machines])
    err = np.abs(Pm0 - p_set)
    print(f"   初期化整合: max|Pe(δ0)−P_PF| = {err.max()*S_BASE_MVA:,.1f} MW "
          f"(中央値 {np.median(err)*S_BASE_MVA:,.1f} MW)")
    for k in np.argsort(-err)[:6]:
        m = machines[k]
        same = [j for j, mm in enumerate(machines) if mm["bus"] == m["bus"]]
        print(f"     外れ: {m['name'][:20]:20s} {m['fuel']:8s} "
              f"P={m['P']*100:8,.1f}MW Pe0={Pm0[k]*100:8,.1f}MW "
              f"bus={m['bus']} Xdp={m['Xdp']:.3f} 同バス機={len(same)}")
    state = {"Yred": Y_pre, "stage": 0, "tripped": False}
    live = np.ones(n, bool)

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
        # 負荷周波数特性 K_L(AGC30): 定Z負荷は電圧依存のみで周波数依存を
        # 持たないため、COI項として全機にM比例で付加(COI版agc.pyと同一のD)
        load_now = load0_pu * (1.0 - UFLS_SHED_FRAC * state["stage"])
        dload = K_LOAD * load_now * coi_w        # pu
        dw = (pm - pe * live - Dd * w) / M - dload / Msum
        dd = OMEGA_S * w
        # ACE(単エリア=FFC相当): COI周波数のみ
        ace = coi_w                     # pu-f
        dzv = (ace - z) / LFC_TS
        dwi = z
        out = np.concatenate([dd, dw, dx1, dx2, ds, [dzv, dwi]])
        if state["tripped"]:
            out[trip] = 0.0             # δ固定
            out[n + trip] = 0.0         # ω固定(切離し後は表示から除外)
        return out

    # イベント: トリップ・UFLS各段(COI周波数の下方横断)
    def ev_trip(t, y):
        return t - T_TRIP
    ev_trip.terminal = True
    ev_trip.direction = 1

    def mk_ufls(k):
        def ev(t, y):
            w = y[n:2 * n]
            coi = float((M * w)[live].sum() / M[live].sum()) * F0
            return coi - UFLS_STEPS_HZ[k]
        ev.terminal = True
        ev.direction = -1
        return ev

    y0 = np.concatenate([delta0, np.zeros(4 * n + 2)])
    t_all, tr_d, tr_w = [], [], []
    t0 = 0.0
    events_left = [("trip", ev_trip)] + [(f"ufls{k+1}", mk_ufls(k))
                                         for k in range(3)]
    log = []
    while t0 < T_END - 1e-6:
        evs = [e for _nm, e in events_left]
        sol = solve_ivp(rhs, (t0, T_END), y0, method="RK45",
                        max_step=0.02, rtol=1e-6, atol=1e-8,
                        t_eval=np.arange(t0, T_END, 0.02), events=evs,
                        dense_output=False)
        t_all.append(sol.t)
        tr_d.append(sol.y[:n])
        tr_w.append(sol.y[n:2 * n])
        hit = next((i for i, te in enumerate(sol.t_events) if len(te)), None)
        if hit is None:
            break
        te = float(sol.t_events[hit][0])
        y0 = sol.y_events[hit][0].copy()
        name = events_left[hit][0]
        if name == "trip":
            state["tripped"] = True
            live[trip] = False
            state["Yred"] = Y_post[state["stage"]]
            log.append((te, f"トリップ: {machines[trip]['name']}"))
        else:
            state["stage"] += 1
            state["Yred"] = Y_post[state["stage"]]
            log.append((te, f"UFLS 第{state['stage']}段"))
        events_left.pop(hit)
        t0 = te
    t = np.concatenate(t_all)
    d = np.concatenate(tr_d, axis=1)
    w = np.concatenate(tr_w, axis=1)
    for te, msg in log:
        print(f"   t={te:6.2f}s  {msg}")
    return t, d, w, M, live, trip, log


def make_figure(machines, t, d, w, M, live, trip, log):
    n = len(machines)
    coi = (M[live][:, None] * w[live]).sum(axis=0) / M[live].sum()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11.5, 7.6), dpi=150,
                                   sharex=True,
                                   gridspec_kw={"height_ratios": [3, 2]})
    cmap = plt.cm.turbo(np.linspace(0.05, 0.95, n))
    for k in range(n):
        if k == trip:
            continue
        ax1.plot(t, F0 + w[k] * F0, lw=0.6, color=cmap[k], alpha=0.55)
    ax1.plot(t, F0 + coi * F0, lw=2.6, color="#111111",
             label=f"系統平均(COI) — {int(live.sum())}機")
    for te, msg in log:
        ax1.axvline(te, color="#C62828", lw=0.9, ls=":", alpha=0.7)
    # 動揺ズーム(トリップ直後)
    axz = ax1.inset_axes([0.42, 0.12, 0.55, 0.55])
    for k in range(n):
        if k == trip:
            continue
        axz.plot(t, F0 + w[k] * F0, lw=0.7, color=cmap[k], alpha=0.6)
    axz.plot(t, F0 + coi * F0, lw=1.8, color="#111111")
    axz.set_xlim(0.5, 9.0)
    lo = float((F0 + coi * F0)[(t > 0.5) & (t < 9.0)].min())
    axz.set_ylim(lo - 0.25, 50.2)
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
        f"北海道・全機動揺つき共シミュレーション — {machines[trip]['name']}"
        f"({machines[trip]['P']*S_BASE_MVA:,.0f} MW)脱落 / "
        f"機械{n}台・AGC30機種モデル×実網Kron縮約", fontsize=12)
    # 相差角(COI基準)
    dcoi = (M[live][:, None] * d[live]).sum(axis=0) / M[live].sum()
    for k in range(n):
        if k == trip:
            continue
        ax2.plot(t, np.rad2deg(d[k] - dcoi), lw=0.6, color=cmap[k],
                 alpha=0.55)
    ax2.set_xlabel("時間 [秒]  (t=1sでトリップ)", fontsize=11)
    ax2.set_ylabel("相差角 δ−δ_COI [deg]", fontsize=11)
    ax2.grid(alpha=0.25)
    fig.tight_layout()
    out = "docs/slides/ajg/assets/fig_swing_hokkaido.png"
    fig.savefig(out)
    print(f"-> {out}")
    return out


def main():
    t0 = time.monotonic()
    net = build_case()
    machines, Em, delta0, kron = extract_model(net)
    load0_pu = float(net.res_load.p_mw.sum()) / S_BASE_MVA
    t, d, w, M, live, trip, log = simulate(machines, Em, delta0, kron,
                                           load0_pu)
    make_figure(machines, t, d, w, M, live, trip, log)
    doc = {"note": ("多機(AGC-N)共シミュレーション帳簿。AGC30機種定数×"
                    "UCオンライン全機×実網Kron縮約。負荷=定Z・UFLS=負荷Y一様"
                    "縮小(ラッチ)・S=定格/0.9・H,Xd',DはFUEL_DEFAULT_PARAMS"
                    "典型値 — 構造実証"),
           "n_machines": len(machines),
           "tripped": machines[trip]["name"],
           "trip_mw": round(machines[trip]["P"] * S_BASE_MVA, 1),
           "events": [{"t_s": round(te, 2), "event": m} for te, m in log],
           "machines": [{"name": m["name"], "fuel": m["fuel"],
                         "p_mw": round(m["P"] * S_BASE_MVA, 1),
                         "H": m["H"]} for m in machines]}
    os.makedirs("docs/data/agc", exist_ok=True)
    json.dump(doc, open("docs/data/agc/multimachine_hokkaido.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"完了 ({time.monotonic()-t0:.0f}s) "
          f"-> docs/data/agc/multimachine_hokkaido.json")


if __name__ == "__main__":
    main()
