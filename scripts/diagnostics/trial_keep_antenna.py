#!/usr/bin/env python3
"""試験: アンテナを残したまま素朴ACを収束させられるか(初期値の工夫).

A: init="dc"(DC角度+平坦電圧) / B: warm start(ladder AC解を初期値に)
C: fast-decoupled(fdbx) / いずれもアンテナ2,103バスは残す。
"""
import copy
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, str(ROOT))

import pandapower as pp  # noqa: E402
import src.powerflow.point_demand as pdm  # noqa: E402
from scripts.run_full_powerflow_from_db import (  # noqa: E402
    add_per_component_slacks, allocate_loads, attach_generators,
    balance_by_zone, build_island_net, load_demand_config, solve_island)
from src.powerflow.pref_demand import pref_zone_gwh  # noqa: E402
from src.powerflow.pipeline import add_reactive_compensation  # noqa: E402

built = json.loads((ROOT / "docs/data/built/all.json").read_text())
nodes, edges = built["nodes"], built["edges"]
cfg = load_demand_config()
pref_gwh, _ = pref_zone_gwh(nodes)
demand_pd = pdm.load_point_demand()
net0, bus_of, _ = build_island_net("west", nodes, edges, 60, {})
attach_generators(net0, bus_of, nodes, "west", attach_mode="cap", stats=True)
pinned, _ = pdm.match_buses(net0, demand_pd)
allocate_loads(net0, cfg, pref_gwh=pref_gwh, point_demand=pinned)
add_reactive_compensation(net0, factor=cfg.get("reactive_compensation_factor", 0.6))
add_per_component_slacks(net0)
balance_by_zone(net0, cfg, use_zone_src=True)
print(f"built {len(net0.bus)}バス(アンテナ込み・削除なし)", flush=True)


def attempt(tag, **kw):
    n = copy.deepcopy(net0)
    t0 = time.time()
    try:
        pp.runpp(n, calculate_voltage_angles=True, enforce_q_lims=False,
                 numba=False, max_iteration=kw.pop("max_iteration", 30), **kw)
        vm = n.res_bus.vm_pu
        print(f"[{tag}] ✅ 収束 {time.time()-t0:.1f}s vm=[{vm.min():.3f},{vm.max():.3f}]",
              flush=True)
        return n
    except Exception as ex:  # noqa: BLE001
        print(f"[{tag}] ❌ {type(ex).__name__} {time.time()-t0:.1f}s", flush=True)
        return None


attempt("A: init=dc", init="dc")
attempt("C: fast-decoupled(fdbx)+flat", algorithm="fdbx", init="flat",
        max_iteration=200)

# B: warm start — ladder解の電圧を初期値へ
n = copy.deepcopy(net0)
_, dc, net_ac, ac = solve_island(n, max_ac_buses=99999)
print(f"ladder AC(参照解): {ac.get('converged')}", flush=True)
if ac.get("converged"):
    nw = copy.deepcopy(net0)
    # res_busを移植してinit="results"
    nw.res_bus = net_ac.res_bus.copy()
    t0 = time.time()
    try:
        pp.runpp(nw, init="results", calculate_voltage_angles=True,
                 enforce_q_lims=False, numba=False, max_iteration=30)
        vm = nw.res_bus.vm_pu
        it_note = ""
        print(f"[B: warm start(ladder解)] ✅ 収束 {time.time()-t0:.1f}s "
              f"vm=[{vm.min():.3f},{vm.max():.3f}]{it_note}", flush=True)
    except Exception as ex:  # noqa: BLE001
        print(f"[B: warm start] ❌ {type(ex).__name__}", flush=True)

    # 焼き込み用: ladder解のvm/vaを保存(MATPOWER .mat warm start検証用)
    out = {"vm": [round(float(v), 5) for v in net_ac.res_bus.vm_pu],
           "va": [round(float(v), 4) for v in net_ac.res_bus.va_degree]}
    Path(__file__).with_suffix(".sol.json").write_text(json.dumps(out))
    print("解を保存(焼き込み用)", flush=True)
