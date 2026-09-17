#!/usr/bin/env python3
"""西AC発散の初動診断 — 反復k=1..6でVが最初に暴れるバスを特定.

結果(2026-08-30): 初動は大阪北部154kVクラスタ(梅田・豊崎・小曽根・豊津・
正雀・茨木)。iter=1で|V|=0.63、以降振動発散(解なしパターン)。
詳細: docs/reports/west_ac_probe2_2026-08-30.md 第3波追記。
"""
import copy, json, os, sys
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, os.getcwd())
from scripts.run_full_powerflow_from_db import (BUILT, ISLAND_OF,
    add_per_component_slacks, allocate_loads, attach_generators,
    GEN_ATTACH_DEFAULT, build_island_net)
from scripts.uc_to_pf_built import build_backbone_net
from src.powerflow.load_estimator import load_demand_config
from src.powerflow.pipeline import add_reactive_compensation
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc
import pandapower as pp
import json as _json

scn = build_national_scenario(scenario="fy2023r2")
uc = solve_uc(scn.to_uc_parameters()); assert uc.is_optimal
regions = sorted(r for r,(i,_f) in ISLAND_OF.items() if i=="west")
h = int(np.argmax(sum(np.asarray(scn.net_demand_r[r]) for r in regions)))
built = json.load(open(BUILT)); cfg = load_demand_config()
from src.powerflow.pref_demand import pref_zone_gwh
pref_gwh,_ = pref_zone_gwh(built["nodes"])
geom={}
base,bus_of,_ = build_island_net("west", built["nodes"], built["edges"], 60.0, geom)
attach_generators(base,bus_of,built["nodes"],"west",attach_mode=GEN_ATTACH_DEFAULT)
allocate_loads(base,cfg,pref_gwh=pref_gwh)
add_reactive_compensation(base, factor=0.8)
netb, led = build_backbone_net(base, threshold_kv=154.0)
add_per_component_slacks(netb)
fuel_by_zone={r: uc_snapshot(uc, scn.generators, h, region=r) for r in regions}
for r in regions:
    sp=(uc.regional_spill_mw.get(r) or []); v=float(sp[h]) if h<len(sp) else 0.0
    if v>1e-6:
        tot=sum(fuel_by_zone[r].values())
        if tot>v: fuel_by_zone[r]={k:mw*(tot-v)/tot for k,mw in fuel_by_zone[r].items()}
inject_dispatch_by_zone(netb, fuel_by_zone,
    {r: float(scn.net_demand_r[r][h]) for r in regions})

def businfo(net, b_int, lookup):
    for pd_idx in net.bus.index:
        if int(lookup[int(pd_idx)])==b_int:
            return (str(net.bus.at[pd_idx,'name'])[:24],
                    float(net.bus.at[pd_idx,'vn_kv']),
                    str(net.bus.at[pd_idx,'zone']))
    return ("?",0,"?")

prevV=None
for it in range(1,7):
    net=copy.deepcopy(netb)
    try:
        pp.runpp(net, numba=True, init="dc", max_iteration=it,
                 tolerance_mva=1e-2, enforce_q_lims=False)
        print(f"iter={it}: 収束"); break
    except Exception:
        pass
    V=np.array(net._ppc["internal"]["V"])
    lookup=net._pd2ppc_lookups["bus"]
    vm=np.abs(V)
    bad=np.argsort(np.abs(vm-1.0))[::-1][:6]
    s=f"iter={it}: |V|範囲[{vm.min():.3f},{vm.max():.3f}] 上位:"
    print(s)
    for b in bad:
        nm,kv,z=businfo(net,int(b),lookup)
        print(f"    |V|={vm[b]:8.3f} {kv:5.0f}kV [{z}] {nm}")
