#!/usr/bin/env python3
"""試験(本命): LTC/LRT・調相のモデル化でアンテナ温存の厳密tol ACに届くか.

実系統では末端電圧をLTC(基幹変圧器タップ)・LRT(配変の負荷時タップ)・調相設備
(SC)が支える。モデルにはこの「電圧調整の物理」が無く、west全部入りは
tol10MVA緩解しか持てない(trial_trafo_impedance_antenna_2026-08-20.md)。

方式(タップ・プリソルブ): 緩解(tol=10MVA)の電圧プロファイルから各変圧器の
lv側電圧誤差を読み、タップ位置で補正(±12段×1.5%=±18%)→厳密tolを試行、
を数回反復する。これはLTC/LRTの静的運転点の近似。
変種+SC: それでも沈む負荷バス(vm<0.90)に力率改善コンデンサ
(q=0.35×P負荷・配変SCの標準的な規模)を追加。

usage: PYTHONPATH=. python3 scripts/diagnostics/trial_ltc.py [west]
"""
import copy
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandapower as pp  # noqa: E402
from scripts.export_matpower_canonical import build_canonical_net  # noqa: E402
from scripts.run_full_powerflow_from_db import ISLAND_FREQ  # noqa: E402

ISLAND = sys.argv[1] if len(sys.argv) > 1 else "west"
STEP = 1.5      # %/段
TMIN, TMAX = -12, 12

built = json.load(open(ROOT / "docs/data/built/all.json"))
net0 = build_canonical_net(ISLAND, built["nodes"], built["edges"],
                           ISLAND_FREQ[ISLAND])
print(f"built {ISLAND} {len(net0.bus)}バス {len(net0.trafo)}変圧器", flush=True)


def setup_taps(net):
    net.trafo["tap_side"] = "lv"
    net.trafo["tap_neutral"] = 0
    net.trafo["tap_pos"] = 0
    net.trafo["tap_min"] = TMIN
    net.trafo["tap_max"] = TMAX
    net.trafo["tap_step_percent"] = STEP
    net.trafo["tap_step_degree"] = 0.0
    if "tap_phase_shifter" in net.trafo.columns:
        net.trafo["tap_phase_shifter"] = False
    if "tap_changer_type" in net.trafo.columns:
        net.trafo["tap_changer_type"] = "Ratio"


def solve_loose(net):
    n = copy.deepcopy(net)
    pp.runpp(n, init="dc", calculate_voltage_angles=True, enforce_q_lims=False,
             numba=False, max_iteration=300, tolerance_mva=10.0)
    return n


def try_tight(net, tag):
    for init in ("dc", "flat"):
        n = copy.deepcopy(net)
        t0 = time.time()
        try:
            pp.runpp(n, init=init, calculate_voltage_angles=True,
                     enforce_q_lims=False, numba=False, max_iteration=100)
            vm = n.res_bus.vm_pu
            print(f"[{tag}] 厳密tol({init}): ✅ {time.time()-t0:.1f}s "
                  f"vm=[{vm.min():.3f},{vm.max():.3f}]", flush=True)
            return n
        except Exception as ex:  # noqa: BLE001
            print(f"[{tag}] 厳密tol({init}): ❌ {type(ex).__name__} "
                  f"{time.time()-t0:.1f}s", flush=True)
    return None


# ── 基準 ──
try_tight(net0, "基準(タップなし)")

# ── タップ符号の自動較正 ──
net = copy.deepcopy(net0)
setup_taps(net)
nl = solve_loose(net)
probe_t = None
for ti in net.trafo.index:
    lb = int(net.trafo.at[ti, "lv_bus"])
    if float(nl.res_bus.vm_pu.at[lb]) < 0.92:
        probe_t = ti
        break
sign = +1
if probe_t is not None:
    lb = int(net.trafo.at[probe_t, "lv_bus"])
    v_before = float(nl.res_bus.vm_pu.at[lb])
    n2 = copy.deepcopy(net)
    n2.trafo.at[probe_t, "tap_pos"] = 5
    v_after = float(solve_loose(n2).res_bus.vm_pu.at[lb])
    sign = +1 if v_after > v_before else -1
    print(f"タップ符号較正: probe lv vm {v_before:.3f} -> {v_after:.3f} "
          f"(pos=+5) => sign={sign:+d}", flush=True)

# ── LTC/LRTプリソルブ反復(成立後も精錬を継続) ──
prof = nl
solved = None
for rnd in range(1, 6):
    for ti in net.trafo.index:
        lb = int(net.trafo.at[ti, "lv_bus"])
        vm = float(prof.res_bus.vm_pu.at[lb]) if lb in prof.res_bus.index else 1.0
        if not np.isfinite(vm):
            continue
        want = (1.0 - vm) * 100.0 / STEP * sign
        cur = int(net.trafo.at[ti, "tap_pos"])
        net.trafo.at[ti, "tap_pos"] = int(np.clip(cur + round(want), TMIN, TMAX))
    n_moved = int((net.trafo.tap_pos != 0).sum())
    at_lim = int((net.trafo.tap_pos.abs() >= TMAX).sum())
    print(f"-- round {rnd}: タップ稼働 {n_moved}/{len(net.trafo)}基 "
          f"(上限張り付き{at_lim})", flush=True)
    res = try_tight(net, f"LTC round{rnd}")
    if res is not None:
        solved = res
        prof = res           # 真解プロファイルで次ラウンドを精錬
        vm = res.res_bus.vm_pu
        n_low = int((vm < 0.95).sum())
        print(f"   真解: vm_min={vm.min():.3f} vm<0.95={n_low}バス", flush=True)
        # 精錬継続は逆効果と実証済み(round2以降で不安定化・2026-08-20実測)。
        # 残存弱電圧は下のSCステップで扱う
        break
    else:
        prof = solve_loose(net)
        vm = prof.res_bus.vm_pu
        print(f"   緩解プロファイル vm=[{vm.min():.3f},{vm.max():.3f}]",
              flush=True)

# ── +調相(SC): 成立解の残存弱電圧バス(タップの届かない線のみアンテナ)へ ──
if solved is not None:
    vm_s = solved.res_bus.vm_pu
    weak = []
    for i in net.load.index:
        b = int(net.load.at[i, "bus"])
        vmv = float(vm_s.at[b]) if b in vm_s.index else 1.0
        if np.isfinite(vmv) and vmv < 0.95:
            weak.append((b, float(net.load.at[i, "p_mw"])))
    if weak:
        # タップはround1の成立状態に戻す(round2以降の過補正を除去)
        net_sc = copy.deepcopy(net0)
        setup_taps(net_sc)
        for ti in net_sc.trafo.index:
            lb = int(net_sc.trafo.at[ti, "lv_bus"])
            vmv = float(nl.res_bus.vm_pu.at[lb]) \
                if lb in nl.res_bus.index else 1.0
            if np.isfinite(vmv):
                want = (1.0 - vmv) * 100.0 / STEP * sign
                net_sc.trafo.at[ti, "tap_pos"] = int(
                    np.clip(round(want), TMIN, TMAX))
        for b, p in weak:
            pp.create_shunt(net_sc, bus=b, q_mvar=-0.35 * max(p, 1.0),
                            p_mw=0.0, name="trial_SC")
        print(f"+調相SC: 残存弱電圧の負荷バス {len(weak)}箇所に "
              f"q=0.35P を追加(タップはround1状態)", flush=True)
        res = try_tight(net_sc, "LTC(r1)+SC")
        if res is not None:
            solved = res

if solved is None:
    prof = solve_loose(net)
    weak = []
    lb_zone = net.load.bus.map(net.bus["zone"])
    for i in net.load.index:
        b = int(net.load.at[i, "bus"])
        vmv = float(prof.res_bus.vm_pu.at[b]) if b in prof.res_bus.index else 1.0
        if np.isfinite(vmv) and vmv < 0.90:
            weak.append((b, float(net.load.at[i, "p_mw"])))
    for b, p in weak:
        pp.create_shunt(net, bus=b, q_mvar=-0.35 * p, p_mw=0.0,
                        name="trial_SC")
    print(f"+調相SC: 弱電圧負荷バス {len(weak)}箇所に q=0.35P を追加", flush=True)
    solved = try_tight(net, "LTC+SC")

if solved is not None:
    vm = solved.res_bus.vm_pu
    n_low = int((vm < 0.95).sum())
    print(f"\n*** 厳密tol AC 成立(アンテナ温存) vm=[{vm.min():.3f},"
          f"{vm.max():.3f}] vm<0.95: {n_low}バス ***", flush=True)
else:
    print("\n*** 全変種で厳密tol未達 ***", flush=True)
