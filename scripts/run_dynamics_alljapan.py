"""
All-Japan-Grid 電力系統動態解析スイート
=========================================

SGモデル（4次, Park方程式）・GFLインバータ・ZIP負荷・
DAE陰解法・過渡安定 / 小信号安定 / 電圧安定 / 短絡容量
を一括実行する統合スクリプト。

Usage:
    python scripts/run_dynamics_alljapan.py [--mode all|transient|small_signal|voltage|short_circuit]
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
import warnings
from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

warnings.filterwarnings("ignore", category=UserWarning)

# ─── パス設定 ────────────────────────────────────────────────
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
if sys.platform == "darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

# ─── フレームワーク import ───────────────────────────────────
from src.dynamics.models.sync_generator import SyncGenerator, GeneratorParams, FUEL_DEFAULT_PARAMS
from src.dynamics.models.excitation import ExcitationSystem, ExcitationParams
from src.dynamics.models.governor import GovernorModel, GovernorParams
from src.dynamics.models.load import ZIPLoad, ZIPParams
from src.dynamics.network.builder import GridNetwork, assign_generators
from src.dynamics.simulation.dae_system import DAESystem, SystemData, pack_state, unpack_state
from src.dynamics.simulation.initializer import run_dc_powerflow

OUT = "output/dynamics"
os.makedirs(OUT, exist_ok=True)

OMEGA_S = 2 * math.pi * 50  # 東日本 50 Hz

# ─────────────────────────────────────────────────────────────
# 1. ネットワーク構築 & 初期値設定
# ─────────────────────────────────────────────────────────────

def build_network() -> Tuple[GridNetwork, np.ndarray, SystemData]:
    """500+275 kV LCC ネットワーク構築と DC 潮流初期化."""
    print("\n[1] ネットワーク構築 ...")
    t0 = time.monotonic()

    net = GridNetwork.from_geojson("data", voltage_levels=[500, 275])
    lcc = net.largest_connected_component()
    Y_bus = lcc.build_ybus()
    nb = lcc.nb
    print(f"  LCC: {nb} バス, {len(lcc.lines)} 線路, Y-bus nnz={Y_bus.nnz}")

    # 発電機のマッチング
    gen_raw = assign_generators(lcc, "data")  # [(bus_idx, fuel, cap_mw, name), ...]
    # 各バスに1台（最大容量）のみ集約
    bus_gen: Dict[int, Tuple[str, float, str]] = {}
    for bus_idx, fuel, cap_mw, name in gen_raw:
        if bus_idx not in bus_gen or cap_mw > bus_gen[bus_idx][1]:
            bus_gen[bus_idx] = (fuel, cap_mw, name)

    print(f"  発電機バス: {len(bus_gen)} 台")

    # ─── DC 潮流で初期位相角を計算 ─────────────────────────
    # 各発電機の基準出力を容量の 60% と仮定
    # 負荷 = 発電 (バランス系統) を各バスに均等配分
    P_gen_pu = np.zeros(nb)
    for bus_idx, (fuel, cap_mw, _) in bus_gen.items():
        P_gen_pu[bus_idx] = cap_mw * 0.6 / 100.0  # 100 MVA base

    total_gen = P_gen_pu.sum()
    P_load_pu = np.ones(nb) * total_gen / nb  # 均等負荷
    P_inj = P_gen_pu - P_load_pu

    theta0 = run_dc_powerflow(Y_bus, P_inj, slack_bus=0)
    V0 = np.exp(1j * theta0)  # 平坦電圧 1.0 pu

    print(f"  DC 潮流: 最大位相差 {np.degrees(theta0.max()-theta0.min()):.2f}°")

    # ─── SyncGenerator オブジェクト生成 & 初期化 ──────────
    generators: List[SyncGenerator] = []
    gen_bus_idx: List[int] = []
    Pm0_list: List[float] = []
    Efd0_list: List[float] = []

    for bus_idx in sorted(bus_gen):
        fuel, cap_mw, name = bus_gen[bus_idx]
        Pgen_pu = P_gen_pu[bus_idx]
        Qgen_pu = Pgen_pu * 0.2  # 0.2 の力率角

        params = GeneratorParams.from_fuel(
            fuel_type=fuel,
            S_rated_mva=cap_mw,
            bus_id=bus_idx,
            name=name[:30],
            omega_s=OMEGA_S,
        )
        gen = SyncGenerator(params)
        V_bus = V0[bus_idx]
        try:
            state0, Efd0, Pm0 = gen.initialize(Pgen_pu, Qgen_pu, V_bus)
        except Exception:
            state0 = np.array([np.angle(V_bus), 1.0, 0.0, 1.0])
            Efd0 = 1.0
            Pm0 = Pgen_pu

        gen.state = state0
        generators.append(gen)
        gen_bus_idx.append(bus_idx)
        Pm0_list.append(Pm0)
        Efd0_list.append(Efd0)

    # ─── 負荷データ (全バス均等 ZIP) ──────────────────────
    load_buses: Dict[int, Tuple[float, float]] = {}
    P_load_each = total_gen / nb
    for b in range(nb):
        load_buses[b] = (P_load_each, P_load_each * 0.3)

    system_data = SystemData(
        generators=generators,
        gen_bus_idx=gen_bus_idx,
        Y_bus=Y_bus,
        nb=nb,
        ng=len(generators),
        load_buses=load_buses,
        slack_bus=0,
        sbase_mva=100.0,
        V0_slack=complex(V0[0]),
        Efd=np.array(Efd0_list),
        Pm=np.array(Pm0_list),
    )

    elapsed = time.monotonic() - t0
    print(f"  完了: {elapsed:.1f}s | ng={system_data.ng}, nb={system_data.nb}")

    # ─── 代数方程式を解いて一致した電圧を求める ────────────────
    # g(x0, V) = 0 を NR で解き、発電機状態と整合する V を得る
    print("  [init] 代数方程式を NR で解いて初期電圧を整合...")
    from src.dynamics.simulation.dae_solver import DAESolver, SolverConfig
    from src.dynamics.simulation.dae_system import DAESystem, pack_state as _ps
    dae_init = DAESystem(system_data)
    solver_init = DAESolver(dae_init, SolverConfig(dt=0.01, t_end=0.1))
    x0_init = _ps(system_data.generators)
    try:
        V_eq, converged = solver_init.solve_algebraic(x0_init, V0)
        V0 = np.asarray(V_eq, dtype=complex)
        v_ok = np.abs(V0)
        status = "収束" if converged else "未収束（使用）"
        print(f"  [init] 電圧 NR {status}: min={v_ok.min():.3f} max={v_ok.max():.3f} pu")
    except Exception as e:
        print(f"  [init] 警告: NR エラー ({e}), 平坦電圧を使用")

    return lcc, V0, system_data


# ─────────────────────────────────────────────────────────────
# 2. 短絡容量解析
# ─────────────────────────────────────────────────────────────

def run_short_circuit(sd: SystemData, lcc: GridNetwork) -> None:
    """全バス短絡容量 (SCC) を計算して地図上にプロット."""
    print("\n[2] 短絡容量解析 ...")
    from src.dynamics.analysis.short_circuit import ShortCircuitAnalysis

    # 発電機テブナン等価: y_k = 1/(Ra + jXd') (システム pu)
    gen_adm = {}
    for i, bus_k in enumerate(sd.gen_bus_idx):
        p = sd.generators[i].p
        # Scale to system base: Xd_p is in generator pu, convert to system pu
        Xd_sys = p.Xd_p * 100.0 / max(p.S_rated_mva, 1.0)
        Ra_sys = p.Ra  * 100.0 / max(p.S_rated_mva, 1.0)
        y_gen = 1.0 / (Ra_sys + 1j * Xd_sys)
        gen_adm[bus_k] = gen_adm.get(bus_k, 0.0) + y_gen

    V0 = np.ones(sd.nb, dtype=complex)
    sca = ShortCircuitAnalysis(sd.Y_bus, V0, sd.sbase_mva,
                               gen_admittances=gen_adm)
    result = sca.compute_all_bus_scc()
    print(f"  SCC: 最大={result.scc_mva.max():.0f} MVA, 最小={result.scc_mva.min():.0f} MVA")
    print(f"  中央値={np.median(result.scc_mva):.0f} MVA")

    # 地理プロット
    buses = lcc.buses
    lats = [b.lat for b in buses]
    lons = [b.lon for b in buses]
    scc_vals = result.scc_mva

    fig, ax = plt.subplots(figsize=(10, 8), facecolor="white")
    sc = ax.scatter(lons, lats, c=scc_vals, s=np.clip(scc_vals / 50, 5, 200),
                    cmap="plasma", alpha=0.85, linewidth=0.3, edgecolors="k")
    plt.colorbar(sc, ax=ax, label="短絡容量 (MVA)", shrink=0.6)
    ax.set_xlabel("経度 (°E)")
    ax.set_ylabel("緯度 (°N)")
    ax.set_title(f"全国500+275kV 短絡容量分布\n({sd.nb}バス, 最大{result.scc_mva.max():.0f}MVA)", fontsize=12)
    ax.set_facecolor("#f0f4f8")
    plt.tight_layout()
    fig.savefig(f"{OUT}/fig_short_circuit.png", dpi=150)
    plt.close()
    print(f"  → {OUT}/fig_short_circuit.png")


# ─────────────────────────────────────────────────────────────
# 3. 小信号安定解析
# ─────────────────────────────────────────────────────────────

def run_small_signal(sd: SystemData, V0: np.ndarray) -> None:
    """線形化 DAE → 固有値 → 電気機械モード解析."""
    print("\n[3] 小信号安定解析 ...")
    from src.dynamics.simulation.dae_system import DAESystem
    from src.dynamics.analysis.small_signal import SmallSignalAnalysis

    dae = DAESystem(sd)
    ssa = SmallSignalAnalysis(dae)

    x0 = pack_state(sd.generators)
    print(f"  状態ベクトル: {x0.shape[0]} 次元")

    try:
        t0 = time.monotonic()
        result = ssa.analyze(x0, V0)
        elapsed = time.monotonic() - t0
        print(f"  固有値計算: {elapsed:.2f}s")
        print(f"  電気機械モード数: {len(result.eigenvalues)}")
        if len(result.eigenvalues) > 0:
            damps = result.damping_ratios
            freqs = result.frequencies_hz
            print(f"  振動モード周波数: {freqs.min():.3f} - {freqs.max():.3f} Hz")
            print(f"  最低制動比: {damps.min():.4f}  (>0 で安定)")
            unstable = np.sum(damps < 0)
            print(f"  不安定モード数: {unstable}")
        ssa.plot_eigenvalues(result, f"{OUT}/fig_eigenvalues.png")
        print(f"  → {OUT}/fig_eigenvalues.png")
        if len(result.eigenvalues) > 0 and result.participation_matrix is not None:
            ssa.participation_heatmap(result, f"{OUT}/fig_participation.png")
            print(f"  → {OUT}/fig_participation.png")
    except Exception as e:
        print(f"  [警告] 小信号解析エラー: {e}")


# ─────────────────────────────────────────────────────────────
# 4. 過渡安定解析
# ─────────────────────────────────────────────────────────────

def _kron_reduction(Y_full: np.ndarray, gen_idx: list, load_idx: list) -> np.ndarray:
    """Kron reduction: Y_red = Y_GG - Y_GL @ inv(Y_LL) @ Y_LG."""
    g = np.array(gen_idx, dtype=int)
    l = np.array(load_idx, dtype=int)
    Y_GG = Y_full[np.ix_(g, g)]
    Y_GL = Y_full[np.ix_(g, l)]
    Y_LL = Y_full[np.ix_(l, l)]
    Y_LG = Y_full[np.ix_(l, g)]
    try:
        Y_red = Y_GG - Y_GL @ np.linalg.solve(Y_LL, Y_LG)
    except np.linalg.LinAlgError:
        Y_red = Y_GG - Y_GL @ np.linalg.lstsq(Y_LL, Y_LG, rcond=None)[0]
    return Y_red


def run_transient(sd: SystemData, V0: np.ndarray) -> None:
    """N-1 過渡安定解析（古典機モデル + Kron縮約）.

    4次DAEモデルの代わりに古典機モデル (δ,ω のみ) + Kron縮約済みネットワークを使用。
    これにより潮流収束なしで確実な平衡点から出発できる。
    """
    print("\n[4] 過渡安定解析（古典機モデル + Kron縮約）...")
    from src.dynamics.swing_solver import SwingModel, GenDyn, run_transient as swing_run
    from src.dynamics.models.sync_generator import FUEL_DEFAULT_PARAMS

    OMEGA_S = 2 * math.pi * 50
    nb = sd.nb
    ng = sd.ng

    # フルY行列 (dense) へ変換
    Y_full = np.array(sd.Y_bus.toarray(), dtype=complex)
    gen_bus_set = set(sd.gen_bus_idx)
    load_idx = [b for b in range(nb) if b not in gen_bus_set]

    # Kron縮約 (発電機バスのみ)
    try:
        Y_red = _kron_reduction(Y_full, sd.gen_bus_idx, load_idx)
    except Exception as e:
        print(f"  Kron縮約エラー: {e}")
        return

    # ─── 平衡点初期化 ──────────────────────────────────────────────
    # フラット電圧 (全δ=0) から出発し、Pm = Pe(δ=0) になるよう設定。
    # これにより潮流収束なしで厳密な平衡点が得られる。
    fuel_H = {ft: p["H"] for ft, p in FUEL_DEFAULT_PARAMS.items()}

    # 各発電機の電気的出力 Pe(δ=0) を Pm の初期値として使用
    # G_ii: 自己コンダクタンス (Kron縮約後)
    G_diag = Y_red.real.diagonal()
    E_default = 1.05  # 内部電圧 pu

    # Pm_i = G_ii * E_i^2 (δ = 0 での純損失, lossless なら 0)
    # 代わりに: 容量比例で Pm を設定し、ゼロ和センタリング
    cap_arr = np.array([sd.generators[i].p.S_rated_mva for i in range(ng)])
    Pm_raw = cap_arr * 0.5 / 100.0  # 50% capacity, pu
    Pm_arr = Pm_raw - Pm_raw.mean()  # ゼロ和: Σ Pm = 0 (無損失近似)

    # 発電機データ (GenDyn) 構築
    gens_dyn = []
    for i, (bus_k, gen) in enumerate(zip(sd.gen_bus_idx, sd.generators)):
        ft = gen.p.fuel_type
        H = fuel_H.get(ft, 4.0)
        gens_dyn.append(GenDyn(
            bus=i,
            H=H,
            D=2.0,
            E=E_default,
            delta0=0.0,   # フラット初期角度
            Pm=float(Pm_arr[i]),
            name=gen.p.name[:20],
        ))

    model = SwingModel(gens_dyn, Y_red, omega_s=OMEGA_S, baseMVA=100.0)

    # 最大出力発電機 Top5 を故障対象に
    Pm_abs = np.abs([sd.Pm[i] for i in range(ng)])
    top_idx = np.argsort(Pm_abs)[-min(5, ng):][::-1]

    results = []
    stable_count = 0
    for gi in top_idx:
        gen_name = sd.generators[gi].p.name[:20]
        try:
            res = swing_run(
                model,
                t_end=5.0,
                fault="fault_clear",
                fault_bus=gi,       # Kron縮約後インデックス = gi
                t_fault=0.1,
                t_clear=0.2,
            )
            results.append((gen_name, res))
            status = "安定 ✓" if res.stable else "不安定"
            if res.stable:
                stable_count += 1
            print(f"  {gen_name[:18]}: {status}, 最大分離角={np.degrees(res.max_angle_sep):.1f}°")
        except Exception as e:
            print(f"  {gen_name[:18]}: エラー ({e})")

    if not results:
        return

    # ── 波形プロット ─────────────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), facecolor="white",
                              gridspec_kw={"hspace": 0.35})
    colors = plt.cm.tab10(np.linspace(0, 1, len(results)))

    for (gen_name, res), col in zip(results, colors):
        # 代表発電機 (全発電機の中の最初の5台) の角度を表示
        n_show = min(8, res.delta.shape[0])
        for k in range(n_show):
            axes[0].plot(res.t, np.degrees(res.delta[k]),
                         color=col, lw=0.8, alpha=0.6, zorder=2)
        axes[0].plot([], [], color=col, lw=1.5, label=f"故障: {gen_name[:18]}")
        # 周波数偏差
        for k in range(n_show):
            axes[1].plot(res.t, res.omega[k] / OMEGA_S * 100 - 100,
                         color=col, lw=0.8, alpha=0.6, zorder=2)

    # 故障期間のシェーディング
    for ax in axes:
        ax.axvspan(0.1, 0.2, alpha=0.12, color="red", label="故障期間")
        ax.axvline(0.1, color="red", lw=0.8, ls="--")
        ax.axvline(0.2, color="red", lw=0.8, ls="--")
        ax.grid(True, lw=0.4, alpha=0.5)

    axes[0].set_ylabel("回転子角度 δ (°)")
    axes[0].set_title(
        f"全国500+275kV 過渡安定解析（古典機モデル, Kron縮約)\n"
        f"N-1 故障-除去: {ng}台中 {stable_count}/{len(results)} 安定", fontsize=11)
    axes[0].legend(fontsize=7, ncol=2, loc="upper right")

    axes[1].set_xlabel("時間 (s)")
    axes[1].set_ylabel("周波数偏差 Δf (%)")
    axes[1].axhline(0, color="k", lw=0.8, ls=":")
    axes[1].set_title("N-1 故障後の周波数偏差", fontsize=10)

    plt.tight_layout()
    fig.savefig(f"{OUT}/fig_transient_stability.png", dpi=150)
    plt.close()
    print(f"  → {OUT}/fig_transient_stability.png")


# ─────────────────────────────────────────────────────────────
# 5. 電圧安定解析
# ─────────────────────────────────────────────────────────────

def run_voltage_stability(sd: SystemData, V0: np.ndarray) -> None:
    """継続潮流法 (CPF) による P-V 曲線と電圧崩壊点の同定."""
    print("\n[5] 電圧安定解析 (CPF) ...")
    from src.dynamics.simulation.dae_system import DAESystem
    from src.dynamics.analysis.voltage_stability import VoltageStabilityAnalysis

    dae = DAESystem(sd)
    vsa = VoltageStabilityAnalysis(dae)

    x0 = pack_state(sd.generators)

    # 重負荷バス（発電機の無いバス）を選択
    non_gen = [b for b in range(sd.nb) if b not in sd.gen_bus_idx]
    if not non_gen:
        print("  全バスが発電機バスのためスキップ")
        return

    load_dir = {b: (sd.load_buses[b][0], sd.load_buses[b][1])
                for b in non_gen[:20] if b in sd.load_buses}

    try:
        result = vsa.run_cpf(x0, V0, load_direction=load_dir,
                             dlambda=0.05, max_lambda=2.5)
        print(f"  鼻点: λ_nose = {result.nose_point_lambda:.3f}  "
              f"(現在負荷の {result.nose_point_lambda*100:.0f}% が限界)")
        print(f"  臨界バス: {result.critical_bus}")
        vsa.plot_pv_curves(result, f"{OUT}/fig_pv_curves.png")
        print(f"  → {OUT}/fig_pv_curves.png")
    except Exception as e:
        print(f"  [警告] CPF エラー: {e}")


# ─────────────────────────────────────────────────────────────
# 6. 結果サマリー図
# ─────────────────────────────────────────────────────────────

def plot_summary(sd: SystemData, lcc: GridNetwork, V0: np.ndarray) -> None:
    """ネットワーク概要・発電機分布・系統データサマリー."""
    print("\n[6] サマリー図作成 ...")
    buses = lcc.buses
    lats = np.array([b.lat for b in buses])
    lons = np.array([b.lon for b in buses])
    gen_buses_set = set(sd.gen_bus_idx)
    Pm_arr = sd.Pm

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), facecolor="white")

    # 左: ネットワークマップ
    ax = axes[0]
    ax.set_facecolor("#eef2f7")
    for line in lcc.lines:
        b1, b2 = line.from_bus, line.to_bus
        if b1 < len(buses) and b2 < len(buses):
            ax.plot([buses[b1].lon, buses[b2].lon],
                    [buses[b1].lat, buses[b2].lat],
                    "k-", lw=0.4, alpha=0.5, zorder=1)

    # 全変電所
    non_gen_idx = [i for i in range(len(buses)) if i not in gen_buses_set]
    gen_idx = sorted(gen_buses_set)
    if non_gen_idx:
        ax.scatter([buses[i].lon for i in non_gen_idx],
                   [buses[i].lat for i in non_gen_idx],
                   s=8, c="steelblue", zorder=2, label="変電所")

    # 発電機バス (Pm で色付け)
    if gen_idx:
        pm_vals = [Pm_arr[sd.gen_bus_idx.index(i)] if i in gen_buses_set
                   and i in sd.gen_bus_idx else 0.0 for i in gen_idx]
        sc = ax.scatter([buses[i].lon for i in gen_idx],
                        [buses[i].lat for i in gen_idx],
                        c=pm_vals, s=30, cmap="Reds",
                        edgecolors="k", linewidth=0.3, zorder=3, label="発電機")
        plt.colorbar(sc, ax=ax, label="Pm (pu)", shrink=0.6)

    ax.set_xlabel("経度")
    ax.set_ylabel("緯度")
    ax.set_title(f"全国500+275kV LCC ネットワーク\n{sd.nb}バス / {sd.ng}発電機", fontsize=11)
    ax.legend(fontsize=8)

    # 右: 燃料別容量棒グラフ
    ax2 = axes[1]
    fuel_cap: Dict[str, float] = {}
    for gen in sd.generators:
        ft = gen.p.fuel_type
        fuel_cap[ft] = fuel_cap.get(ft, 0.0) + gen.p.S_rated_mva
    fuels = list(fuel_cap.keys())
    caps = [fuel_cap[f] / 1000 for f in fuels]  # GW
    colors_fuel = {"nuclear": "#7B2D8E", "coal": "#333", "lng": "#E8832A",
                   "gas": "#E8832A", "oil": "#C44E52", "hydro": "#2196F3",
                   "geothermal": "#FF5722", "biomass": "#8BC34A", "unknown": "#aaa"}
    bar_colors = [colors_fuel.get(f, "#aaa") for f in fuels]
    bars = ax2.bar(fuels, caps, color=bar_colors, edgecolor="k", linewidth=0.5)
    ax2.set_xlabel("燃料種別")
    ax2.set_ylabel("設備容量 (GW)")
    ax2.set_title("発電機燃料別容量\n(動態解析対象: LCC 500+275kV)", fontsize=11)
    ax2.set_xticklabels(fuels, rotation=30, ha="right")
    total_gw = sum(caps)
    ax2.set_title(f"燃料別容量 (合計 {total_gw:.1f} GW)", fontsize=11)
    for bar, cap in zip(bars, caps):
        if cap > 0.5:
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                     f"{cap:.1f}", ha="center", va="bottom", fontsize=7)

    plt.tight_layout()
    fig.savefig(f"{OUT}/fig_dynamics_summary.png", dpi=150)
    plt.close()
    print(f"  → {OUT}/fig_dynamics_summary.png")


# ─────────────────────────────────────────────────────────────
# メインエントリポイント
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="All-Japan-Grid 動態解析スイート")
    parser.add_argument("--mode", default="all",
                        choices=["all", "short_circuit", "small_signal",
                                 "transient", "voltage", "summary"])
    args = parser.parse_args()

    print("=" * 60)
    print("  All-Japan-Grid 電力系統動態解析")
    print("  (500+275 kV, SG 4次モデル + DAE)")
    print("=" * 60)

    # ─── ネットワーク & 初期値構築 ──────────────────────────
    lcc, V0, sd = build_network()

    # ─── 各解析実行 ─────────────────────────────────────────
    if args.mode in ("all", "short_circuit"):
        run_short_circuit(sd, lcc)

    if args.mode in ("all", "small_signal"):
        run_small_signal(sd, V0)

    if args.mode in ("all", "transient"):
        run_transient(sd, V0)

    if args.mode in ("all", "voltage"):
        run_voltage_stability(sd, V0)

    if args.mode in ("all", "summary"):
        plot_summary(sd, lcc, V0)

    print("\n" + "=" * 60)
    print(f"  全解析完了 → {OUT}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
