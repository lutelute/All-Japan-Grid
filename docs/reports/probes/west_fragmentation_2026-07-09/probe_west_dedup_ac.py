#!/usr/bin/env python3
"""west + dedup + 無効補償で full AC が実用化するか(順序頑健性も)."""
import copy, json, os, sys, time
REPO="/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
sys.path.insert(0,REPO); os.chdir(REPO)
import pandapower as pp
from scripts.run_full_powerflow_from_db import (BUILT, ISLAND_OF,
    add_per_component_slacks, allocate_loads, attach_generators, build_island_net)
from scripts.uc_to_pf_built import ISLAND_FREQ, _bounded_ac
from src.powerflow.load_estimator import load_demand_config
from src.powerflow.pipeline import add_reactive_compensation
from src.powerflow.pref_demand import pref_zone_gwh
from src.powerflow.transforms import prune_dc_infeasible
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc

island="west"; regions=tuple(sorted(r for r,(i,_f) in ISLAND_OF.items() if i==island)); t=12
built=json.load(open(BUILT)); pw,_=pref_zone_gwh(built["nodes"])
out={"probe":"west-dedup-ac","dedup":True}
base,bus_of,st=build_island_net(island,built["nodes"],built["edges"],ISLAND_FREQ[island],{},dedup_nodes=True)
attach_generators(base,bus_of,built["nodes"],island)
allocate_loads(base,load_demand_config(),pref_gwh=pw)
add_per_component_slacks(base)
out["n_bus"]=int(len(base.bus)); out["merged"]=st["n_dedup_merged"]
scn=build_national_scenario(scenario="fy2023r2"); uc=solve_uc(scn.to_uc_parameters())
fbz={r:uc_snapshot(uc,scn.generators,t,region=r) for r in regions}
dem={r:float(scn.net_demand_r[r][t]) for r in regions}
# CLI順序(補償→注入): base に補償を先付け
res={}
for fac in (0.0,0.3,0.6):
    net0=copy.deepcopy(base)
    if fac>0: add_reactive_compensation(net0,factor=fac)
    net=copy.deepcopy(net0); inject_dispatch_by_zone(net,fbz,dem)
    pre=float(net.load.loc[net.load.in_service,"p_mw"].sum())
    verdict={"solver":"dc_fallback"}
    for thr in (None,45.,30.,20.):
        n=copy.deepcopy(net)
        if thr is not None:
            try: prune_dc_infeasible(n,angle_threshold=thr)
            except Exception: pass
        if _bounded_ac(n):
            served=float(n.res_load.p_mw.sum())
            if pre<=0 or served>=0.95*pre:
                verdict={"solver":"ac","thr":thr,"served_frac":round(served/pre,4),
                         "loss_mw":round(float(n.res_line.pl_mw.sum()+n.res_trafo.pl_mw.sum()),1),
                         "vm_min":round(float(n.res_bus.vm_pu.min()),4),
                         "vm_max":round(float(n.res_bus.vm_pu.max()),4)}
                break
    res[f"factor_{fac}"]=verdict
    print(f"CLI順序(補償→注入) dedup factor={fac}: {verdict}",flush=True)
out["cli_order"]=res
json.dump(out,open(sys.argv[1],"w"),ensure_ascii=False,indent=1)
print("->",sys.argv[1])
