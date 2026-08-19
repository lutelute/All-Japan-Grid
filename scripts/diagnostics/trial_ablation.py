#!/usr/bin/env python3
"""切り分け: run_powerflowのACレシピのどの成分が west(アンテナ込み)を解くのか."""
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
    balance_by_zone, build_island_net, load_demand_config)
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
print(f"built {len(net0.bus)}バス(アンテナ込み)", flush=True)

CASES = [
    ("S1 本体第1段そのもの(dc init+Q制限+tol1e-2+iter100)",
     dict(algorithm="nr", init="dc", max_iteration=100, tolerance_mva=1e-2,
          enforce_q_lims=True, numba=True)),
    ("S2 = S1 - Q制限",
     dict(algorithm="nr", init="dc", max_iteration=100, tolerance_mva=1e-2,
          numba=True)),
    ("S3 = S1 だが厳しいtol(1e-5)",
     dict(algorithm="nr", init="dc", max_iteration=100, tolerance_mva=1e-5,
          enforce_q_lims=True, numba=True)),
    ("S4 = S1 だがflatスタート",
     dict(algorithm="nr", init="flat", max_iteration=100, tolerance_mva=1e-2,
          enforce_q_lims=True, numba=True)),
    ("S5 = S1 だがiter30",
     dict(algorithm="nr", init="dc", max_iteration=30, tolerance_mva=1e-2,
          enforce_q_lims=True, numba=True)),
]
for tag, opts in CASES:
    n = copy.deepcopy(net0)
    t0 = time.time()
    try:
        pp.runpp(n, **opts)
        vm = n.res_bus.vm_pu
        print(f"[{tag}] ✅ {time.time()-t0:.1f}s vm=[{vm.min():.3f},{vm.max():.3f}]",
              flush=True)
    except Exception as ex:  # noqa: BLE001
        print(f"[{tag}] ❌ {type(ex).__name__} {time.time()-t0:.1f}s", flush=True)
