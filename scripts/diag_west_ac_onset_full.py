#!/usr/bin/env python3
"""第6波: westフルスケールAC発散の初動診断 — 66/77kV層の残存キラー特定.

backbone154は介入#37でAC成立(2026-08-30, reports/provisional_infeed_decision)。
フルはDCのまま → キラーは154kV未満の層に確定。本診断は#37適用後の新ベース
ラインでフルネットのNRを k=1..6 で止め、|V|が最初に暴れるバスを層別に追跡。

出力: docs/reports/west_ac_onset_full_2026-08-30.{md,json}
"""
import copy, json, os, sys
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, os.getcwd())
from scripts.run_full_powerflow_from_db import (BUILT, ISLAND_OF,
    add_per_component_slacks, allocate_loads, attach_generators,
    GEN_ATTACH_DEFAULT, build_island_net)
from src.powerflow.load_estimator import load_demand_config
from src.powerflow.pipeline import add_reactive_compensation, add_provisional_infeed
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc
import pandapower as pp

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
infeed = add_provisional_infeed(base)          # 介入#37 正典ON
print(f"介入#37: {len(infeed)}件 計{sum(l['load_mw'] for l in infeed):,.0f}MW")
add_per_component_slacks(base)
fuel_by_zone={r: uc_snapshot(uc, scn.generators, h, region=r) for r in regions}
for r in regions:
    sp=(uc.regional_spill_mw.get(r) or []); v=float(sp[h]) if h<len(sp) else 0.0
    if v>1e-6:
        tot=sum(fuel_by_zone[r].values())
        if tot>v: fuel_by_zone[r]={k:mw*(tot-v)/tot for k,mw in fuel_by_zone[r].items()}
inject_dispatch_by_zone(base, fuel_by_zone,
    {r: float(scn.net_demand_r[r][h]) for r in regions})

doc={"note":"第6波 onset診断(フル・#37適用後)","n_bus":int(len(base.bus)),
     "provisional_infeed":len(infeed),"iters":[]}
for it in range(1,7):
    net=copy.deepcopy(base)
    conv=False
    try:
        pp.runpp(net, numba=True, init="dc", max_iteration=it,
                 tolerance_mva=1e-2, enforce_q_lims=False)
        conv=True
        print(f"iter={it}: 収束"); doc["iters"].append({"iter":it,"converged":True})
        break
    except Exception:
        pass
    V=np.array(net._ppc["internal"]["V"]); vm=np.abs(V)
    lookup=net._pd2ppc_lookups["bus"]
    # ppc内部番号 → pandapowerバス (逆引きを一括構築)
    inv={}
    for pd_idx in net.bus.index:
        inv.setdefault(int(lookup[int(pd_idx)]), int(pd_idx))
    dev=np.abs(vm-1.0)
    bad=np.argsort(dev)[::-1][:40]
    # 層別集計: |V|偏差>0.15 のバスをkv層でカウント
    layers={}
    for b in np.where(dev>0.15)[0]:
        pd_idx=inv.get(int(b))
        if pd_idx is None: continue
        kv=float(net.bus.at[pd_idx,"vn_kv"])
        key=f"{kv:.0f}"
        layers[key]=layers.get(key,0)+1
    top=[]
    for b in bad[:25]:
        pd_idx=inv.get(int(b))
        if pd_idx is None: continue
        top.append({"vm":round(float(vm[b]),3),
                    "kv":float(net.bus.at[pd_idx,"vn_kv"]),
                    "zone":str(net.bus.at[pd_idx,"zone"]),
                    "name":str(net.bus.at[pd_idx,"name"])[:28]})
    print(f"iter={it}: |V|範囲[{vm.min():.3f},{vm.max():.3f}] "
          f"偏差>0.15: {sum(layers.values())}バス 層別={layers}")
    for r_ in top[:8]:
        print(f"    |V|={r_['vm']:7.3f} {r_['kv']:5.0f}kV [{r_['zone']}] {r_['name']}")
    doc["iters"].append({"iter":it,"vm_min":round(float(vm.min()),3),
                         "vm_max":round(float(vm.max()),3),
                         "n_dev15":int(sum(layers.values())),
                         "layers":layers,"top":top})
json.dump(doc, open("docs/reports/west_ac_onset_full_2026-08-30.json","w"),
          ensure_ascii=False, indent=1)
print("-> docs/reports/west_ac_onset_full_2026-08-30.json")
