#!/usr/bin/env python3
"""west全部入り+電圧調整(LTCタップr1+調相SC)のMATPOWERケースを出力.

trial_ltc.pyで厳密tol AC成立を確認した構成をそのまま .mat 化する
(タップ→branch TAP列・SC→bus BS列)。MATPOWER実機検証用。
出力: dist/matpower_canonical/west_vr.mat ほかサイドカー
"""
import copy
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandapower as pp  # noqa: E402
from scripts.export_matpower_canonical import build_canonical_net  # noqa: E402
from scripts.export_national_matpower import export_net  # noqa: E402

STEP, TMIN, TMAX = 1.5, -12, 12

built = json.load(open(ROOT / "docs/data/built/all.json"))
net = build_canonical_net("west", built["nodes"], built["edges"], 60)
print(f"built west {len(net.bus)}バス", flush=True)

# タップ機構
net.trafo["tap_side"] = "lv"
net.trafo["tap_neutral"] = 0
net.trafo["tap_pos"] = 0
net.trafo["tap_min"] = TMIN
net.trafo["tap_max"] = TMAX
net.trafo["tap_step_percent"] = STEP
net.trafo["tap_step_degree"] = 0.0
if "tap_changer_type" in net.trafo.columns:
    net.trafo["tap_changer_type"] = "Ratio"

# 緩解プロファイル → タップr1(trial_ltcと同一・sign=+1は較正済み)
nl = copy.deepcopy(net)
pp.runpp(nl, init="dc", calculate_voltage_angles=True, enforce_q_lims=False,
         numba=False, max_iteration=300, tolerance_mva=10.0)
for ti in net.trafo.index:
    lb = int(net.trafo.at[ti, "lv_bus"])
    vm = float(nl.res_bus.vm_pu.at[lb]) if lb in nl.res_bus.index else 1.0
    if np.isfinite(vm):
        net.trafo.at[ti, "tap_pos"] = int(
            np.clip(round((1.0 - vm) * 100.0 / STEP), TMIN, TMAX))
print(f"タップ稼働 {(net.trafo.tap_pos != 0).sum()}/{len(net.trafo)}基", flush=True)

# 厳密tol(タップのみ)で解き、残存弱電圧負荷バスへSC
ns = copy.deepcopy(net)
pp.runpp(ns, init="dc", calculate_voltage_angles=True, enforce_q_lims=False,
         numba=False, max_iteration=100)
weak = []
for i in net.load.index:
    b = int(net.load.at[i, "bus"])
    v = float(ns.res_bus.vm_pu.at[b]) if b in ns.res_bus.index else 1.0
    if np.isfinite(v) and v < 0.95:
        weak.append((b, float(net.load.at[i, "p_mw"])))
for b, p in weak:
    pp.create_shunt(net, bus=b, q_mvar=-0.35 * max(p, 1.0), p_mw=0.0,
                    name="vr_SC")
print(f"調相SC {len(weak)}箇所", flush=True)

# 最終厳密解
nf = copy.deepcopy(net)
pp.runpp(nf, init="dc", calculate_voltage_angles=True, enforce_q_lims=False,
         numba=False, max_iteration=100)
vm = nf.res_bus.vm_pu
print(f"最終厳密解: vm=[{vm.min():.3f},{vm.max():.3f}]", flush=True)

out = str(ROOT / "dist/matpower_canonical")
rec = export_net("west_vr", nf, True, out, validate=True,
                 regions=["west"], frequency=60)
print("export:", {k: rec.get(k) for k in ("island", "n_bus", "n_branch",
                                          "ac_converged")})
print("validation:", rec.get("validation"))
