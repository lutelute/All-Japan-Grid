#!/usr/bin/env python3
"""図解用データ捕獲: west のアンテナ集約対象バス座標と、E0/E3 の電圧分布."""
import copy
import json
import sys
import warnings
from collections import Counter
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
print("built", len(net0.bus), flush=True)

# --- E0 ladder AC 解 ---
n = copy.deepcopy(net0)
_, dc, net_ac, ac = solve_island(n, max_ac_buses=99999)
vm0 = {int(b): float(v) for b, v in net_ac.res_bus.vm_pu.items()} if ac.get("converged") else {}
print("E0 ladder ac:", ac.get("converged"), flush=True)

# --- アンテナ抽出(trialと同一アルゴリズム・victim追跡) ---
net = copy.deepcopy(net0)
victims_all = set()
for _round in range(50):
    deg = Counter()
    nbr = {}
    for _, r in net.line.iterrows():
        if not r.in_service:
            continue
        a, b = int(r.from_bus), int(r.to_bus)
        deg[a] += 1
        deg[b] += 1
        nbr.setdefault(a, b)
        nbr.setdefault(b, a)
    for _, r in net.trafo.iterrows():
        if not r.in_service:
            continue
        a, b = int(r.hv_bus), int(r.lv_bus)
        deg[a] += 1
        deg[b] += 1
        nbr.setdefault(a, b)
        nbr.setdefault(b, a)
    protected = set(net.ext_grid.bus) | set(net.gen.bus)
    victims = [b for b in net.bus.index
               if deg.get(int(b), 0) == 1
               and float(net.bus.at[b, "vn_kv"]) < 100.0
               and int(b) not in protected]
    if not victims:
        break
    vs = set(int(v) for v in victims)
    victims_all |= vs
    for tbl in ("load", "sgen", "shunt"):
        df = getattr(net, tbl)
        for i in df.index:
            b = int(df.at[i, "bus"])
            if b in vs:
                df.at[i, "bus"] = nbr[b]
    drop = [i for i in net.line.index
            if int(net.line.at[i, "from_bus"]) in vs or int(net.line.at[i, "to_bus"]) in vs]
    net.line.drop(drop, inplace=True)
    drop_t = [i for i in net.trafo.index
              if int(net.trafo.at[i, "hv_bus"]) in vs or int(net.trafo.at[i, "lv_bus"]) in vs]
    net.trafo.drop(drop_t, inplace=True)
    net.bus.drop(list(vs), inplace=True)
print("victims:", len(victims_all), flush=True)

# --- E3 素朴AC 解 ---
pp.runpp(net, init="flat", calculate_voltage_angles=True,
         enforce_q_lims=False, numba=False, max_iteration=30)
vm3 = {int(b): float(v) for b, v in net.res_bus.vm_pu.items()}
print("E3 naive ac OK", flush=True)

# --- 出力: bus座標(geodata)・vn_kv・E0 vm・antenna判定 / E3 vm ---
out = {"buses": [], "vm3": vm3 and {str(k): round(v, 4) for k, v in vm3.items()}}
gd = net0.bus_geodata if hasattr(net0, "bus_geodata") else None
for b in net0.bus.index:
    x = y = None
    try:
        x, y = float(gd.at[b, "x"]), float(gd.at[b, "y"])
    except Exception:  # noqa: BLE001
        pass
    out["buses"].append({"b": int(b), "x": x, "y": y,
                         "kv": float(net0.bus.at[b, "vn_kv"]),
                         "ant": int(b) in victims_all,
                         "vm0": round(vm0.get(int(b), float("nan")), 4)})
p = Path(__file__).with_suffix(".json")
p.write_text(json.dumps(out))
print("saved", p)
