#!/usr/bin/env python3
"""第6幕アニメ: 発散が育つ(#38前) → 収束する(#38後) — NR反復の可視化GIF.

デッキ用「動いてわかる」素材(2026-08-30)。westフルネットを#38前後の2ベース
ラインで構築し、NRを max_iteration=k で止めた電圧場をフレーム化する。

出力: docs/slides/ajg/assets/west_ac_onset.gif
"""
import copy, json, os, sys
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, os.getcwd())
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

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
cfg = load_demand_config()
from src.powerflow.pref_demand import pref_zone_gwh

def build(freq_fix):
    built = json.load(open(BUILT))   # 毎回ロード(reattributeのin-place汚染回避)
    pref_gwh,_ = pref_zone_gwh(built["nodes"], freq_fix=freq_fix)
    geom={}
    net,bus_of,_ = build_island_net("west", built["nodes"], built["edges"],
                                    60.0, geom, freq_fix=freq_fix)
    attach_generators(net,bus_of,built["nodes"],"west",
                      attach_mode=GEN_ATTACH_DEFAULT)
    allocate_loads(net,cfg,pref_gwh=pref_gwh)
    add_reactive_compensation(net, factor=0.8)
    add_provisional_infeed(net)
    add_per_component_slacks(net)
    fz={r: uc_snapshot(uc, scn.generators, h, region=r) for r in regions}
    for r in regions:
        sp=(uc.regional_spill_mw.get(r) or []); v=float(sp[h]) if h<len(sp) else 0.0
        if v>1e-6:
            tot=sum(fz[r].values())
            if tot>v: fz[r]={k:mw*(tot-v)/tot for k,mw in fz[r].items()}
    inject_dispatch_by_zone(net, fz, {r: float(scn.net_demand_r[r][h]) for r in regions})
    return net

def geo_of(net):
    out={}
    for b in net.bus.index:
        try:
            g=json.loads(net.bus.at[b,"geo"]); out[b]=(g["coordinates"][0], g["coordinates"][1])
        except Exception: pass
    return out

def iter_fields(net, kmax=6):
    """[(k, {bus: vm}, converged)] を返す。"""
    frames=[]
    for k in range(1, kmax+1):
        n2=copy.deepcopy(net); conv=False
        try:
            pp.runpp(n2, numba=True, init="dc", max_iteration=k,
                     tolerance_mva=1e-2, enforce_q_lims=False)
            conv=True
            vm={b: float(v) for b,v in n2.res_bus.vm_pu.items() if np.isfinite(v)}
        except Exception:
            V=np.array(n2._ppc["internal"]["V"]); vma=np.abs(V)
            lookup=n2._pd2ppc_lookups["bus"]
            vm={}
            for b in n2.bus.index:
                i=int(lookup[int(b)])
                if 0<=i<len(vma): vm[int(b)]=float(vma[i])
        frames.append((k, vm, conv))
        if conv: break
    return frames

print("build #38前..."); net0=build(False)
print("build #38後..."); net1=build(True)
f0=iter_fields(net0); f1=iter_fields(net1)
g0, g1 = geo_of(net0), geo_of(net1)
segs=[]
for _,l in net1.line[net1.line.in_service].iterrows():
    a,b=g1.get(int(l.from_bus)), g1.get(int(l.to_bus))
    if a and b: segs.append([a,b])

BG="#0A0D1A"
def render(phase_label, sub, k, vm, geo, conv, frames):
    fig=plt.figure(figsize=(12.8,7.2), dpi=110); fig.patch.set_facecolor(BG)
    ax=fig.add_axes([0,0,1,1]); ax.set_facecolor(BG)
    ax.set_xlim(128.8,139.9); ax.set_ylim(30.4,38.4)
    ax.set_aspect(1.0/np.cos(np.radians(34.5))); ax.axis("off")
    ax.add_collection(LineCollection(segs, colors="#232A45", linewidths=0.4, alpha=0.8, zorder=1))
    xs,ys,cs=[],[],[]
    for b,(lon,lat) in geo.items():
        v=vm.get(b)
        if v is None: continue
        xs.append(lon); ys.append(lat); cs.append(min(abs(v-1.0),1.0))
    sc=ax.scatter(xs,ys,c=cs,s=6,cmap="inferno",vmin=0.0,vmax=0.6,zorder=5,linewidths=0)
    ax.text(0.03,0.95,phase_label,transform=ax.transAxes,color="#FFFFFF",
            fontsize=21,fontweight="bold",va="top")
    ax.text(0.03,0.885,sub,transform=ax.transAxes,color="#8E96B8",fontsize=12.5,va="top")
    st = "収束 ✓ 西日本フルAC成立" if conv else f"ニュートン反復 {k} 回目"
    ax.text(0.03,0.80,st,transform=ax.transAxes,
            color=("#69F0AE" if conv else "#FFD60A"),fontsize=17,fontweight="bold",va="top")
    vmax=max(cs) if cs else 0
    ax.text(0.03,0.74,f"|V|の1puからの逸脱 最大 {vmax:.2f}",transform=ax.transAxes,
            color="#8E96B8",fontsize=11,va="top")
    if not conv and phase_label.startswith("#38前"):
        ax.annotate("軽井沢・嬬恋ポケット(50Hz設備の混入)", xy=(138.45,36.35),
                    xytext=(132.0,36.05), color="#FF8A80", fontsize=12.5,
                    fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color="#FF8A80", lw=1.4))
    ax.text(0.03,0.03,"色=|V|の逸脱(暗=正常・明=暴走)。tolerance 1e-2 MVA / init=dc",
            transform=ax.transAxes,color="#5A648F",fontsize=9.5)
    fig.canvas.draw()
    img=np.asarray(fig.canvas.buffer_rgba())[...,:3].copy(); plt.close(fig)
    frames.append(img)
    return img

imgs=[]; durs=[]
for i,(k,vm,conv) in enumerate(f0):
    im=render("#38前 — 発散が育つ","誤帰属の50Hz設備がwest島に混入していた頃",k,vm,g0,conv,[])
    imgs.append(im); durs.append(1600 if i==len(f0)-1 else 750)
for k,vm,conv in f1:
    im=render("#38後 — 同じ系統、同じ手順","誤帰属275点を検挙(是正)しただけ",k,vm,g1,conv,[])
    imgs.append(im); durs.append(3400 if conv else 750)
from PIL import Image
ims=[Image.fromarray(f) for f in imgs]
out="docs/slides/ajg/assets/west_ac_onset.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=durs, loop=0, optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
