#!/usr/bin/env python3
"""計測: E0(アンテナ込み)のladderはどの段で・何本外して解けているのか."""
import copy
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, str(ROOT))

import pandapower as pp  # noqa: E402
import src.powerflow.point_demand as pdm  # noqa: E402
from scripts.run_full_powerflow_from_db import (  # noqa: E402
    add_per_component_slacks, allocate_loads, attach_generators,
    balance_by_zone, build_island_net, load_demand_config, run_powerflow)
from src.powerflow.transforms import prune_dc_infeasible  # noqa: E402
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
n_line0 = int(net0.line.in_service.sum())
n_tr0 = int(net0.trafo.in_service.sum())
print(f"built {len(net0.bus)}バス line={n_line0} trafo={n_tr0}", flush=True)

for thr in (None, 45.0, 30.0, 20.0):
    n = copy.deepcopy(net0)
    cut_l = cut_t = 0
    if thr is not None:
        prune_dc_infeasible(n, angle_threshold=thr)
        cut_l = n_line0 - int(n.line.in_service.sum())
        cut_t = n_tr0 - int(n.trafo.in_service.sum())
    ac = run_powerflow(n, "ac")
    served = float(n.res_load.p_mw.sum()) if ac["converged"] and len(n.res_load) else 0.0
    pre = float(net0.load.loc[net0.load.in_service, "p_mw"].sum())
    print(f"[thr={thr}] 外した枝: line {cut_l} + trafo {cut_t} → "
          f"AC {'✅' if ac['converged'] else '❌'} "
          f"served={served/pre*100 if pre else 0:.1f}%", flush=True)
    if ac["converged"] and served / pre >= 0.95:
        # 外された枝の素性(電圧階級)
        if thr is not None:
            off_l = net0.line.in_service & ~n.line.in_service
            kvs = []
            for li in n.line.index[off_l]:
                fb = int(n.line.at[li, "from_bus"])
                kvs.append(round(float(n.bus.at[fb, "vn_kv"])))
            from collections import Counter
            print("  外した線の電圧階級:", dict(Counter(kvs)), flush=True)
        break
