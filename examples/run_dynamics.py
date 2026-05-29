"""Power system dynamic simulation demo — All-Japan-Grid.

Demonstrates:
1. Transient stability (N-1, N-2, three-phase fault & clear)
2. Modal analysis (eigenvalues, oscillation modes, damping ratios)

Runs on a single region (Hokkaido, 471 buses) for speed.
Full-national results require the GPU server (pws-gpu).

Usage::

    PYTHONPATH=. python examples/run_dynamics.py
    PYTHONPATH=. python examples/run_dynamics.py --region tokyo
    PYTHONPATH=. python examples/run_dynamics.py --nx 2   # N-2 contingency
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import platform

if platform.system() == 'Darwin':
    font_manager.fontManager.addfont('/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc')
    plt.rcParams['font.family'] = 'Hiragino Sans'
else:
    try:
        import japanize_matplotlib  # noqa: F401
    except ImportError:
        pass
plt.rcParams['axes.unicode_minus'] = False

import pandapower as pp
import importlib.util

from src.converter.pandapower_builder import PandapowerBuilder
from src.dynamics.swing_solver import SwingModel, run_transient, run_nx_contingency, modal_analysis

# run_powerflow_all.py の build_network_from_geojson を再利用
_pfmod_path = os.path.join(os.path.dirname(__file__), "run_powerflow_all.py")
_spec = importlib.util.spec_from_file_location("pfmodule", _pfmod_path)
_pfmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pfmod)
_build_network = _pfmod.build_network_from_geojson

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "dynamics")
os.makedirs(OUTPUT_DIR, exist_ok=True)

REGION_JP = {
    'hokkaido': '北海道', 'tohoku': '東北', 'tokyo': '東京',
    'chubu': '中部', 'hokuriku': '北陸', 'kansai': '関西',
    'chugoku': '中国', 'shikoku': '四国', 'kyushu': '九州', 'okinawa': '沖縄',
}
FREQ = {'hokkaido':50,'tohoku':50,'tokyo':50,
        'chubu':60,'hokuriku':60,'kansai':60,'chugoku':60,'shikoku':60,'kyushu':60,'okinawa':60}


def build_net(region: str):
    """Build pandapower network with generators from plants GeoJSON."""
    grid = _build_network(region)
    if grid is None:
        raise RuntimeError(f"Failed to load GeoJSON for {region}")
    builder = PandapowerBuilder()
    res = builder.build(grid)
    net = res.net
    try:
        pp.runpp(net, numba=False, verbose=False, max_iteration=50,
                 init="dc", tolerance_mva=1e-2)
    except Exception:
        try:
            pp.runpp(net, numba=False, verbose=False, max_iteration=100,
                     init="flat", tolerance_mva=0.1)
        except Exception:
            pass
    return net


def plot_transient(result, title, out_path, region_jp=""):
    n_gen = result.delta.shape[0]
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True, facecolor='white')

    # ロータ角
    ax = axes[0]
    cmap = plt.cm.tab20
    for i in range(min(n_gen, 20)):
        ax.plot(result.t, np.degrees(result.delta[i] - result.coi_delta),
                color=cmap(i / max(n_gen, 20)), lw=1.2, alpha=0.85)
    ax.axvline(x=1.0, color='red', lw=1.5, ls='--', label='擾乱発生')
    ax.set_ylabel('ロータ角偏差  Δδ (COI基準, °)', fontsize=12)
    ax.set_title(f'{region_jp}  {title}\n'
                 f'安定性: {"✓ 安定" if result.stable else "✗ 不安定"}  '
                 f'最大角度差: {np.degrees(result.max_angle_sep):.1f}°',
                 fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.3); ax.legend(fontsize=10)

    # 角速度偏差
    ax = axes[1]
    for i in range(min(n_gen, 20)):
        ax.plot(result.t, result.omega[i] * 60 / (2*np.pi),
                color=cmap(i / max(n_gen, 20)), lw=1.2, alpha=0.85)
    ax.axvline(x=1.0, color='red', lw=1.5, ls='--')
    ax.set_xlabel('時間 (s)', fontsize=12)
    ax.set_ylabel('角速度偏差 Δf (Hz)', fontsize=12)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=180, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"  Saved: {out_path}")


def plot_modes(modes, out_path, region_jp=""):
    osc_modes = [m for m in modes if m.mode_type != 'non-oscillatory' and m.freq_hz > 0.02]
    if not osc_modes:
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), facecolor='white')

    # 固有値プロット (s-plane)
    ax = axes[0]
    color_map = {'inter-area': '#C44E52', 'local': '#2196F3', 'control': '#4CAF50'}
    plotted_labels = set()
    for m in modes:
        c = color_map.get(m.mode_type, '#999')
        lbl = m.mode_type if m.mode_type not in plotted_labels else ""
        plotted_labels.add(m.mode_type)
        ax.scatter(m.eigenvalue.real, m.eigenvalue.imag, color=c, s=60,
                   alpha=0.85, label=lbl, zorder=3)
        ax.scatter(m.eigenvalue.real, -m.eigenvalue.imag, color=c, s=60,
                   alpha=0.85, zorder=3)
    ax.axvline(0, color='black', lw=1, ls='--')
    ax.axhline(0, color='black', lw=0.5)
    ax.set_xlabel('実部 σ (減衰)', fontsize=12)
    ax.set_ylabel('虚部 jω_d (振動)', fontsize=12)
    ax.set_title('固有値分布 (s平面)', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    # 周波数 vs 減衰比
    ax = axes[1]
    for m in osc_modes:
        c = color_map.get(m.mode_type, '#999')
        ax.scatter(m.freq_hz, m.damping_ratio * 100, color=c, s=80, alpha=0.85, zorder=3)
    ax.axhline(5, color='red', lw=1.5, ls='--', label='減衰比 5% (基準)')
    ax.set_xlabel('振動周波数 (Hz)', fontsize=12)
    ax.set_ylabel('減衰比 ζ (%)', fontsize=12)
    ax.set_title(f'{region_jp} 振動モード分布\n(全{len(osc_modes)}モード)', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=180, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"  Saved: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="hokkaido")
    parser.add_argument("--nx", type=int, default=1, help="N-x order")
    parser.add_argument("--t_end", type=float, default=10.0)
    args = parser.parse_args()

    region = args.region
    region_jp = REGION_JP.get(region, region)
    freq_hz = FREQ.get(region, 50)

    print(f"\n{'='*60}")
    print(f"  Power System Dynamics — {region_jp} ({freq_hz} Hz)")
    print(f"{'='*60}")

    print(f"\n[1] ネットワーク構築 ({region})...")
    t0 = time.monotonic()
    net = build_net(region)
    n_bus = len(net.bus)
    n_gen = len(net.gen) + len(net.ext_grid)
    print(f"    バス数: {n_bus},  発電機数: {n_gen}  ({time.monotonic()-t0:.1f}s)")

    print(f"\n[2] SwingModel 構築 (Ybus クロン縮約)...")
    t0 = time.monotonic()
    model = SwingModel.from_pandapower(net, freq_hz=freq_hz)
    n_gens = model.n
    print(f"    発電機ノード数: {n_gens}  ({time.monotonic()-t0:.1f}s)")

    if n_gens == 0:
        print("  発電機ノードが見つかりません。終了します。")
        return

    # ── N-1 発電機脱落 ────────────────────────────────────────────────────
    print(f"\n[3] N-1 過渡安定解析 (最大容量発電機脱落)...")
    t0 = time.monotonic()
    result_n1 = run_transient(model, t_end=args.t_end, fault="trip",
                               fault_bus=0, t_fault=1.0)
    elapsed = time.monotonic() - t0
    print(f"    安定: {result_n1.stable}  "
          f"最大角度差: {np.degrees(result_n1.max_angle_sep):.1f}°  "
          f"({elapsed:.2f}s)")
    plot_transient(result_n1, f"N-1 発電機脱落 (Gen #{0})",
                   os.path.join(OUTPUT_DIR, f"{region}_n1_trip.png"), region_jp)

    # ── 三相短絡→除去 ─────────────────────────────────────────────────────
    print(f"\n[4] 三相短絡→除去 (t_fault=1.0s, t_clear=1.15s)...")
    t0 = time.monotonic()
    result_fault = run_transient(model, t_end=args.t_end, fault="fault_clear",
                                  fault_bus=0, t_fault=1.0, t_clear=1.15)
    elapsed = time.monotonic() - t0
    print(f"    安定: {result_fault.stable}  "
          f"最大角度差: {np.degrees(result_fault.max_angle_sep):.1f}°  "
          f"({elapsed:.2f}s)")
    plot_transient(result_fault, "三相短絡→除去 (clearing 150ms)",
                   os.path.join(OUTPUT_DIR, f"{region}_fault_clear.png"), region_jp)

    # ── N-x contingency ──────────────────────────────────────────────────
    if args.nx >= 2 and n_gens >= 3:
        print(f"\n[5] N-{args.nx} 全組み合わせ解析 ({n_gens}C{args.nx})...")
        t0 = time.monotonic()
        nx_results = run_nx_contingency(model, n_out=args.nx,
                                         t_end=min(args.t_end, 6.0),
                                         t_fault=1.0)
        elapsed = time.monotonic() - t0
        n_unstable = sum(1 for _, r in nx_results if not r.stable)
        print(f"    組み合わせ数: {len(nx_results)}  "
              f"不安定: {n_unstable}件  ({elapsed:.1f}s)")
        # 最悪ケースをプロット
        worst_trips, worst_res = nx_results[0]
        plot_transient(worst_res, f"N-{args.nx} 最悪ケース (Gen {worst_trips})",
                       os.path.join(OUTPUT_DIR, f"{region}_n{args.nx}_worst.png"), region_jp)

    # ── モード解析 ──────────────────────────────────────────────────────────
    print(f"\n[6] モード解析 (固有値・振動モード)...")
    t0 = time.monotonic()
    modes = modal_analysis(model)
    elapsed = time.monotonic() - t0

    osc = [m for m in modes if m.mode_type != 'non-oscillatory' and m.freq_hz > 0.02]
    inter_area = [m for m in osc if m.mode_type == 'inter-area']
    local = [m for m in osc if m.mode_type == 'local']

    print(f"    全モード数: {len(modes)}")
    print(f"    振動モード: {len(osc)}  (系間: {len(inter_area)}, 局所: {len(local)})")
    print(f"    ({elapsed:.2f}s)")

    if osc:
        worst_mode = min(osc, key=lambda m: m.damping_ratio)
        print(f"    最低減衰モード: {worst_mode.freq_hz:.3f} Hz, "
              f"ζ = {worst_mode.damping_ratio*100:.2f}%  [{worst_mode.mode_type}]")

    plot_modes(modes, os.path.join(OUTPUT_DIR, f"{region}_modal.png"), region_jp)

    # ── サマリー出力 ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  完了: output/dynamics/{region}_*.png")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
