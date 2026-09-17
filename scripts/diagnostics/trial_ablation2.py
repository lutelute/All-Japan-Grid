#!/usr/bin/env python3
"""切り分け2: 緩い許容誤差の段(本体rung4-6相当)のどこで収束するか."""
import copy, json, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, str(ROOT))
import pandapower as pp
import src.powerflow.point_demand as pdm
from scripts.run_full_powerflow_from_db import (
    add_per_component_slacks, allocate_loads, attach_generators,
    balance_by_zone, build_island_net, load_demand_config)
from src.powerflow.pref_demand import pref_zone_gwh
from src.powerflow.pipeline import add_reactive_compensation

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
print(f"built {len(net0.bus)}バス(アンテナ込み)", flush=True)
for tag, opts in [
    ("rung4 tol=0.1MVA iter200", dict(algorithm="nr", init="dc", max_iteration=200, tolerance_mva=1e-1, numba=True)),
    ("rung5 tol=1.0MVA iter300", dict(algorithm="nr", init="dc", max_iteration=300, tolerance_mva=1.0, numba=True)),
    ("rung6 tol=10MVA iter300", dict(algorithm="nr", init="dc", max_iteration=300, tolerance_mva=10.0, numba=True)),
]:
    n = copy.deepcopy(net0)
    t0 = time.time()
    try:
        pp.runpp(n, **opts)
        vm = n.res_bus.vm_pu
        print(f"[{tag}] OK {time.time()-t0:.1f}s vm=[{vm.min():.3f},{vm.max():.3f}]", flush=True)
        break
    except Exception as ex:
        print(f"[{tag}] NG {type(ex).__name__} {time.time()-t0:.1f}s", flush=True)
