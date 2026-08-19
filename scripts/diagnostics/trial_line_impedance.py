#!/usr/bin/env python3
"""試験(#1本実装の第一歩): 様式5実測線路R/Xの適用が厳密tol ACに効くか.

crosswalk(both_resolved 411行)のうちモデル直結線に当たる分を適用し、
west(アンテナ込み)の厳密tol AC・緩tol解の質・east回帰を計測する。

usage: PYTHONPATH=. python3 scripts/diagnostics/trial_line_impedance.py [west|east]
"""
import copy
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pandapower as pp  # noqa: E402
from scripts.export_matpower_canonical import build_canonical_net  # noqa: E402
from scripts.run_full_powerflow_from_db import ISLAND_FREQ  # noqa: E402
from src.powerflow.line_impedance import apply_disclosed_line_impedance  # noqa: E402
import json  # noqa: E402

ISLAND = sys.argv[1] if len(sys.argv) > 1 else "west"
FREQ = ISLAND_FREQ[ISLAND]

built = json.load(open(ROOT / "docs/data/built/all.json"))
net0 = build_canonical_net(ISLAND, built["nodes"], built["edges"], FREQ)
print(f"built {ISLAND} {len(net0.bus)}バス", flush=True)

netL = copy.deepcopy(net0)
led = apply_disclosed_line_impedance(netL, freq_hz=FREQ)
print(f"適用: {led['n_applied']}本 (解決{led['n_rows_resolved']}行中・"
      f"バス不一致{led['n_no_bus_match']}・直結線なし{led['n_no_direct_line']})",
      flush=True)
print("sample:", led["sample"][:4], flush=True)


def probe(net, tag):
    for name, opts in [
        ("厳密tol(既定)・dc-init", dict(init="dc", max_iteration=60)),
        ("厳密tol(既定)・flat", dict(init="flat", max_iteration=60)),
        ("tol=1e-2・dc-init", dict(init="dc", max_iteration=100,
                                   tolerance_mva=1e-2)),
        ("tol=10・dc-init", dict(init="dc", max_iteration=300,
                                 tolerance_mva=10.0)),
    ]:
        n = copy.deepcopy(net)
        t0 = time.time()
        try:
            pp.runpp(n, calculate_voltage_angles=True, enforce_q_lims=False,
                     numba=False, **opts)
            vm = n.res_bus.vm_pu
            print(f"[{tag}] {name}: ✅ {time.time()-t0:.1f}s "
                  f"vm=[{vm.min():.3f},{vm.max():.3f}]", flush=True)
            break
        except Exception as ex:  # noqa: BLE001
            print(f"[{tag}] {name}: ❌ {type(ex).__name__} "
                  f"{time.time()-t0:.1f}s", flush=True)


probe(net0, "基準")
probe(netL, "実測R/X適用後")
