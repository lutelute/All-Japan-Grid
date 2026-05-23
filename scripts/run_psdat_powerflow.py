"""All-Japan-Grid × psdat-python 統合: MATPOWER形式電力フロー + 古典スウィングモデル.

GeoJSONデータからMATPOWER形式のBUS/BRANCH/GEN配列を生成し、
psdat-pythonのAC潮流・固有値解析・過渡安定解析を実行する。

psdat-python (https://github.com/lutelute/psdat-python) が
sys.pathもしくはインストール済みであること。

Usage::

    python scripts/run_psdat_powerflow.py [--mode powerflow|modal|fault]
    python scripts/run_psdat_powerflow.py --mode all
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# パス設定
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# psdat-python パス検索: 兄弟ディレクトリ優先、次にGitHub配下を探す
for _candidate in [
    os.path.join(ROOT, "..", "psdat-python"),
    os.path.expanduser("~/Documents/GitHub/psdat-python"),
]:
    if os.path.isdir(_candidate) and os.path.isdir(os.path.join(_candidate, "psdat")):
        sys.path.insert(0, os.path.abspath(_candidate))
        break

# All-Japan-Grid エクスポーター
from src.matpower.exporter import build_matpower_case

OUT = "output/psdat"
os.makedirs(OUT, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
def run_powerflow(case: dict) -> dict:
    """AC潮流計算."""
    from psdat.models.powerflow import run_powerflow as pf_solve, build_ybus

    BUS    = case["BUS"]
    BRANCH = case["BRANCH"]
    GEN    = case["GEN"]
    baseMVA = case["baseMVA"]

    print("\n[1] AC 潮流計算 (psdat-python Newton-Raphson)")
    t0 = time.monotonic()
    pf = pf_solve(BUS, BRANCH, GEN, baseMVA=baseMVA)
    dt = time.monotonic() - t0

    if pf.get("converged"):
        V_all = pf["V"]
        Vm = np.abs(V_all); Va = np.degrees(np.angle(V_all))
        print(f"  収束: {pf['iterations']}反復, {dt:.2f}s")
        print(f"  電圧範囲: {Vm.min():.4f} – {Vm.max():.4f} pu")
        print(f"  角度範囲: {Va.min():.2f}° – {Va.max():.2f}°")
    else:
        print("  ⚠ 収束せず (初期値を維持)")

    return pf


def run_modal(case: dict, pf: dict) -> None:
    """クラシカルスウィングモデルによる小信号安定解析."""
    from psdat.simulation.classical import compute_internal_emf
    from psdat.models.powerflow import build_ybus
    from psdat.models.machine import MachineParams

    print("\n[2] モーダル解析 (古典スウィングモデル)")

    BUS = case["BUS"]; BRANCH = case["BRANCH"]; GEN = case["GEN"]
    MD = case["MD"]; ED = case["ED"]; TD = case["TD"]
    baseMVA = case["baseMVA"]
    n_gen = case["n_gen"]
    gen_buses_1idx = case["gen_buses_1idx"]

    V_all = pf["V"]
    Vm = np.abs(V_all); Va = np.angle(V_all)
    Ybus_arr = np.asarray(pf["Ybus"])

    # 発電機バスの0-indexedリスト
    gen_idx = [b - 1 for b in gen_buses_1idx]   # 0-indexed

    # 実際のPG/QGを電力フロー結果から取得 (発電機バスの正味注入)
    S_bus = V_all * np.conj(Ybus_arr @ V_all)
    PG_pu = S_bus[gen_idx].real
    QG_pu = S_bus[gen_idx].imag

    machine_params = [
        MachineParams(
            H=MD[0,i], Xd=MD[1,i], Xdp=MD[2,i], Xdpp=MD[3,i],
            Xq=MD[4,i], Xqp=MD[5,i], Xqpp=MD[6,i],
            Td0p=MD[7,i], Td0pp=MD[8,i], Tq0p=MD[9,i], Tq0pp=MD[10,i],
            Rs=MD[11,i], Xls=MD[12,i], Dm=MD[13,i]*0.005,
            KA=ED[0,i], TA=ED[1,i], KE=ED[2,i], TE=ED[3,i],
            KF=ED[4,i], TF=ED[5,i], Ax=ED[6,i], Bx=ED[7,i],
            TCH=TD[0,i], TSV=TD[1,i], RD=TD[2,i], ws=2*np.pi*50,
        )
        for i in range(n_gen)
    ]

    Vg_gen    = Vm[gen_idx]
    theta_gen = Va[gen_idx]
    E_prime, delta_0 = compute_internal_emf(Vg_gen, theta_gen, PG_pu, QG_pu, machine_params)
    E_p = np.abs(E_prime)
    print(f"  δ₀ 範囲: {np.degrees(delta_0.min()):.2f}° – {np.degrees(delta_0.max()):.2f}°")

    # 拡張Y行列でKron縮約 → Y_red
    Ybus_sp = build_ybus(BUS, BRANCH, baseMVA=baseMVA)
    Ybus_orig = np.asarray(Ybus_sp)
    n_bus = Ybus_orig.shape[0]
    P_load = BUS[:, 2] / baseMVA; Q_load = BUS[:, 3] / baseMVA
    Xdp_arr = MD[2, :]

    n_ext = n_bus + n_gen
    Y_ext = np.zeros((n_ext, n_ext), dtype=complex)
    Y_ext[:n_bus, :n_bus] = Ybus_orig.copy()
    for i in range(n_bus):
        Vm2 = max(abs(V_all[i])**2, 1e-6)
        Y_ext[i,i] += complex(P_load[i], -Q_load[i]) / Vm2
    for g, gb in enumerate(gen_buses_1idx):
        bi = gb - 1
        y_g = 1.0 / complex(0.0, max(Xdp_arr[g], 1e-6))
        Y_ext[bi, bi]           += y_g
        Y_ext[n_bus+g, n_bus+g] += y_g
        Y_ext[bi, n_bus+g]      -= y_g
        Y_ext[n_bus+g, bi]      -= y_g

    elim = np.arange(n_bus); keep = np.arange(n_bus, n_ext)
    Ykk = Y_ext[np.ix_(keep,keep)]; Ykl = Y_ext[np.ix_(keep,elim)]
    Yll = Y_ext[np.ix_(elim,elim)]; Ylk = Y_ext[np.ix_(elim,keep)]
    try:
        Y_red = Ykk - Ykl @ np.linalg.solve(Yll, Ylk)
    except np.linalg.LinAlgError:
        Y_red = Ykk - Ykl @ np.linalg.lstsq(Yll, Ylk, rcond=None)[0]

    Gred = Y_red.real; Bred = Y_red.imag

    # 同期化トルク行列K
    K = np.zeros((n_gen, n_gen))
    for i in range(n_gen):
        for j in range(n_gen):
            if i != j:
                dij = delta_0[i] - delta_0[j]
                K[i,j] = E_p[i]*E_p[j]*(Gred[i,j]*np.sin(dij) - Bred[i,j]*np.cos(dij))
        K[i,i] = -np.sum(K[i,:])

    H_arr = MD[0,:]; D_arr = MD[13,:] * 0.005; WS = 2*np.pi*50
    A = np.zeros((2*n_gen, 2*n_gen))
    A[:n_gen, n_gen:] = np.eye(n_gen)
    A[n_gen:, :n_gen] = -np.diag(WS / (2.0*H_arr)) @ K
    A[n_gen:, n_gen:] = -np.diag(D_arr / (2.0*H_arr))

    eigvals = np.linalg.eigvals(A)
    osc = eigvals[np.abs(eigvals.imag) > 0.1]
    pos = osc[osc.imag > 0]
    freq_hz = pos.imag / (2*np.pi)
    zeta = -pos.real / np.abs(pos)

    idx = np.argsort(freq_hz)
    freq_hz = freq_hz[idx]; zeta = zeta[idx]; pos = pos[idx]

    ia_mask = (freq_hz > 0.1) & (freq_hz < 2.0)
    print(f"\n  固有値マップ (上位 {min(len(pos), 12)} 振動モード):")
    print(f"  {'#':>3}  {'λ':>28}  {'f (Hz)':>8}  {'ζ':>7}")
    print("  " + "─" * 55)
    for k in range(min(len(pos), 12)):
        ev = pos[k]; f = freq_hz[k]; z = zeta[k]
        tag = "★" if 0.1 < f < 0.8 else ""
        print(f"  {k+1:>3}  {ev.real:+.4f}{ev.imag:+.4f}j  {f:>8.4f}  {z:>7.4f}  {tag}")

    ia_count = ia_mask.sum()
    print(f"\n  エリア間モード (0.1–0.8 Hz): {ia_count} 個")

    # 固有値マッププロット
    fig, ax = plt.subplots(figsize=(8, 7), facecolor="white")
    ax.scatter(pos.real, pos.imag, s=45, c="steelblue", zorder=3, label="モード")
    ax.scatter(pos.real, -pos.imag, s=45, c="steelblue", zorder=3)
    if ia_mask.any():
        ia_ev = pos[ia_mask]
        ax.scatter(ia_ev.real, ia_ev.imag, s=110, c="red", zorder=4,
                   label=f"エリア間 ({ia_count} 個)")
        ax.scatter(ia_ev.real, -ia_ev.imag, s=110, c="red", zorder=4)
    ax.axhline(0, color="k", lw=0.5); ax.axvline(0, color="k", lw=0.5)
    ax.set_xlabel("実部 σ (1/s)"); ax.set_ylabel("虚部 jω (rad/s)")
    ax.set_title(f"全国電力系統 ({n_gen} 発電機) — 固有値マップ (古典スウィングモデル)")
    ax.legend(); ax.grid(True, lw=0.3, alpha=0.5)
    plt.tight_layout()
    fig.savefig(f"{OUT}/agj_eigenvalues.png", dpi=150)
    plt.close()
    print(f"  → {OUT}/agj_eigenvalues.png")


def run_fault(case: dict, pf: dict) -> None:
    """代表バスへの3相地絡故障シミュレーション."""
    from psdat.simulation.classical import simulate_classical
    from psdat.models.powerflow import build_ybus
    from psdat.models.machine import MachineParams

    print("\n[3] 過渡安定シミュレーション (古典スウィングモデル)")

    BUS = case["BUS"]; BRANCH = case["BRANCH"]; GEN = case["GEN"]
    MD = case["MD"]; ED = case["ED"]; TD = case["TD"]
    baseMVA = case["baseMVA"]
    n_gen = case["n_gen"]
    gen_buses_1idx = case["gen_buses_1idx"]

    V_all = pf["V"]
    Vm = np.abs(V_all); Va = np.angle(V_all)
    Ybus_arr = np.asarray(pf["Ybus"])

    gen_idx = [b - 1 for b in gen_buses_1idx]
    S_bus = V_all * np.conj(Ybus_arr @ V_all)
    PG_pu = S_bus[gen_idx].real; QG_pu = S_bus[gen_idx].imag

    machine_params = [
        MachineParams(
            H=MD[0,i], Xd=MD[1,i], Xdp=MD[2,i], Xdpp=MD[3,i],
            Xq=MD[4,i], Xqp=MD[5,i], Xqpp=MD[6,i],
            Td0p=MD[7,i], Td0pp=MD[8,i], Tq0p=MD[9,i], Tq0pp=MD[10,i],
            Rs=MD[11,i], Xls=MD[12,i], Dm=MD[13,i]*0.005,
            KA=ED[0,i], TA=ED[1,i], KE=ED[2,i], TE=ED[3,i],
            KF=ED[4,i], TF=ED[5,i], Ax=ED[6,i], Bx=ED[7,i],
            TCH=TD[0,i], TSV=TD[1,i], RD=TD[2,i], ws=2*np.pi*50,
        )
        for i in range(n_gen)
    ]

    # 最大容量発電機のバスに地絡
    gen_caps = [GEN[g, 8] for g in range(n_gen)]  # PMAX
    fault_gen_idx = int(np.argmax(gen_caps))
    fault_bus_1idx = gen_buses_1idx[fault_gen_idx]
    print(f"  故障バス: {fault_bus_1idx} (Gen {fault_gen_idx+1}, PMAX={gen_caps[fault_gen_idx]:.0f} MW)")

    Ybus_sp = build_ybus(BUS, BRANCH, baseMVA=baseMVA)
    Ybus_orig = np.asarray(Ybus_sp)
    P_load = BUS[:, 2] / baseMVA; Q_load = BUS[:, 3] / baseMVA

    t0 = time.monotonic()
    result = simulate_classical(
        machines      = machine_params,
        Vg_pf         = Vm[gen_idx],
        theta_g_pf    = Va[gen_idx],
        PG            = PG_pu,
        QG            = QG_pu,
        Y_bus_pre     = Ybus_orig,
        gen_buses     = gen_buses_1idx,
        fault_bus     = fault_bus_1idx,
        t_fault       = 1.0,
        t_clear       = 1.10,   # 100 ms
        t_end         = 8.0,
        dt            = 0.005,
        omega0        = 2*np.pi*50,
        V_pf_all      = V_all,
        P_load_pu     = P_load,
        Q_load_pu     = Q_load,
    )
    print(f"  計算時間: {time.monotonic()-t0:.1f}s")

    t_arr     = result["t"]
    delta_arr = result["delta"]
    omega_arr = result["omega"]
    sep = delta_arr.max(axis=1) - delta_arr.min(axis=1)
    stable = sep[-1] < 180.0

    print(f"  ピーク角度分離: {sep.max():.2f}°")
    print(f"  最終角度分離:   {sep[-1]:.2f}°")
    print(f"  安定判定: {'STABLE ✓' if stable else 'UNSTABLE ✗'}")

    # 振動曲線プロット
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), facecolor="white",
                              gridspec_kw={"hspace": 0.35})
    colors = plt.cm.tab20(np.linspace(0, 1, n_gen))
    WS = 2*np.pi*50
    for i in range(n_gen):
        lbl = f"G{i+1}" if i < 8 else None
        axes[0].plot(t_arr, delta_arr[:, i], color=colors[i], lw=0.9, alpha=0.8, label=lbl)
        axes[1].plot(t_arr, (omega_arr[:, i]/WS - 1)*100, color=colors[i], lw=0.9, alpha=0.8)

    for ax in axes:
        ax.axvspan(1.0, 1.10, color="red", alpha=0.10)
        ax.axvline(1.0, color="red", lw=0.9, ls="--")
        ax.axvline(1.10, color="red", lw=0.9, ls="--")
        ax.grid(True, lw=0.3, alpha=0.5)

    axes[0].set_ylabel("回転子角度 δ (°)")
    axes[0].set_title(
        f"全国電力系統 — バス{fault_bus_1idx} 3相地絡 (t=1.0–1.1 s)\n"
        f"{n_gen} 発電機 | ピーク分離: {sep.max():.1f}° | {'安定' if stable else '不安定'}")
    axes[0].legend(fontsize=7, ncol=4, loc="upper right")
    axes[1].set_xlabel("時刻 (s)")
    axes[1].set_ylabel("周波数偏差 Δf (%)")
    axes[1].axhline(0, color="k", lw=0.7, ls=":")

    plt.tight_layout()
    fig.savefig(f"{OUT}/agj_fault_sim.png", dpi=150)
    plt.close()
    print(f"  → {OUT}/agj_fault_sim.png")


# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["powerflow","modal","fault","all"],
                        default="all")
    args = parser.parse_args()

    print("=" * 60)
    print("全国電力系統 × psdat-python 統合解析")
    print("=" * 60)

    # load_factor=0.15: 500+275 kV backbone 単体での安定収束に適した負荷率
    # (実際の負荷は154kV以下の配電系統に接続されるためEHVは低負荷率が現実的)
    case = build_matpower_case(voltage_levels=[500, 275], load_factor=0.15)
    print(f"\n系統規模: {case['n_bus']} バス, {case['n_gen']} 発電機")
    print(f"総発電容量: {sum(case['GEN'][:,8]):.0f} MW")
    print(f"総負荷:     {sum(case['BUS'][:,2]):.0f} MW")
    print(f"スラックバス: {case['slack_bus']}")

    pf = run_powerflow(case)

    if args.mode in ("modal", "all"):
        run_modal(case, pf)

    if args.mode in ("fault", "all"):
        run_fault(case, pf)

    print("\n完了.")


if __name__ == "__main__":
    main()
