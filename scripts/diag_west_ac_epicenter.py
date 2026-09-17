#!/usr/bin/env python3
"""西AC非収束の震源地診断 — 失敗NRの最終ミスマッチ上位バスを地図に落とす.

西AC正典化キャンペーン第2波(2026-08-30)の診断ツール。第1波(probe_west_ac.py)
と本診断で確定した事実:
  1. 介入#22の名寄せは健全(候補768ペア。名前不一致298ペアは隣接する別変電所
     — 繋げば捏造なのでレバーではない)
  2. 断片は無罪 — 主成分単独(7,436バス・65.5GW)でも非収束
  3. **backbone(≥154kV, 2,094バス)でも非収束** — 「西はbackboneならAC」は
     幻想だった(正典CLI uc_to_pf_built --model backbone でも t=17 dc_fallback)
  4. 震源地は名古屋圏の154/275kVメッシュ(安城市変電所_2・海部開閉所・
     西尾張・七宝・東名古屋)+大分臨海220kV(鶴崎・東大分)
  5. 筆頭が複製サフィックス付き「安城市変電所_2」— 重複ノード複製の関与疑い

第3波の候補: max_iteration=3 で止めた初期ミスマッチ地図(発散の芽)、
安城_2周辺の局所構造ダンプ、名古屋圏のみ切り出しAC。
"""
import copy, json, os, sys, time
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, os.getcwd())
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"]=["Hiragino Sans","sans-serif"]
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
net, led = build_backbone_net(base, threshold_kv=154.0)
add_per_component_slacks(net)
# スピル差引(正典と同じ) + 注入
fuel_by_zone={r: uc_snapshot(uc, scn.generators, h, region=r) for r in regions}
for r in regions:
    sp=(uc.regional_spill_mw.get(r) or [])
    v=float(sp[h]) if h<len(sp) else 0.0
    if v>1e-6:
        tot=sum(fuel_by_zone[r].values())
        if tot>v:
            fuel_by_zone[r]={k:mw*(tot-v)/tot for k,mw in fuel_by_zone[r].items()}
demand={r: float(scn.net_demand_r[r][h]) for r in regions}
inject_dispatch_by_zone(net, fuel_by_zone, demand)

try:
    pp.runpp(net, numba=True, init="dc", max_iteration=100, tolerance_mva=1e-2,
             enforce_q_lims=True)
    print("収束?!")
except Exception as e:
    print(f"非収束: {type(e).__name__}")
ppc = net._ppc; internal = ppc["internal"]
V = np.array(internal["V"]); Ybus = internal["Ybus"]; Sbus = np.array(internal["Sbus"])
mis = V*np.conj(Ybus.dot(V)) - Sbus     # pu(1MVA基準→MW)
lookup = net._pd2ppc_lookups["bus"]
rows=[]
import json as _json
for pos, pd_idx in enumerate(net.bus.index):
    b=int(lookup[int(pd_idx)])
    if not (0<=b<len(mis)): continue
    if not bool(net.bus.at[pd_idx,"in_service"]): continue
    try:
        g=_json.loads(net.bus.at[pd_idx,"geo"]); lon,lat=g["coordinates"]
    except Exception: lon=lat=float("nan")
    rows.append((abs(mis[b]), mis[b].real, mis[b].imag,
                 float(net.bus.at[pd_idx,"vn_kv"]),
                 str(net.bus.at[pd_idx,"zone"]),
                 str(net.bus.at[pd_idx,"name"])[:22], lon, lat, abs(V[b])))
rows.sort(key=lambda r:-r[0])
print(f"総ミスマッチ |ΣS|={sum(r[0] for r in rows):,.0f}MVA")
print(f"{'|ΔS|MVA':>9} {'ΔP':>9} {'ΔQ':>9} {'kV':>5} zone      |V|    名前")
for r in rows[:25]:
    print(f"{r[0]:9,.0f} {r[1]:9,.0f} {r[2]:9,.0f} {r[3]:5.0f} {r[4]:9s} "
          f"{r[8]:5.2f}  {r[5]}")
# 地図
fig,ax=plt.subplots(figsize=(9,8),dpi=130)
lons=[r[6] for r in rows]; lats=[r[7] for r in rows]
m=[r[0] for r in rows]
sc=ax.scatter(lons,lats,s=[min(400,3+v/20) for v in m],
              c=[np.log10(max(v,1e-3)) for v in m],cmap="inferno",alpha=0.8)
plt.colorbar(sc,label="log10 |ΔS| [MVA]")
ax.set_title(f"西backbone(154kV) AC非収束の震源地 — NR最終ミスマッチ (t={h})")
fig.savefig("docs/reports/west_ac_epicenter_2026-08-30.png")
print("-> docs/reports/west_ac_epicenter_2026-08-30.png")
