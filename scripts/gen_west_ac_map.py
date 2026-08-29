#!/usr/bin/env python3
"""西日本フルAC初成立の記念図 — vm熱地図 + 誤帰属検挙マップ(2026-08-30).

左: westフル(7,928バス)の収束AC解の電圧分布(介入#37/#38込み・fy2023r2ピーク)
右: 介入#38が検挙した誤帰属ノード(50Hz設備のwest混入)の分布(東西境界帯)

出力: docs/slides/ajg/assets/fig_west_ac_map.png
"""
import copy, json, os, sys
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, os.getcwd())
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from scripts.run_full_powerflow_from_db import (BUILT, ISLAND_OF,
    add_per_component_slacks, allocate_loads, attach_generators,
    GEN_ATTACH_DEFAULT, build_island_net)
from src.powerflow.load_estimator import load_demand_config
from src.powerflow.pipeline import add_reactive_compensation, add_provisional_infeed
from src.powerflow.region_attribution import reattribute_node_regions
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc
import pandapower as pp

built = json.load(open(BUILT))
# 検挙リスト: freq_fix 有無の差分
na, nb = copy.deepcopy(built["nodes"]), copy.deepcopy(built["nodes"])
reattribute_node_regions(na, freq_fix=False)
reattribute_node_regions(nb, freq_fix=True)
fixed = [(a["lat"], a["lon"], a["region"], b["region"])
         for a, b in zip(na, nb) if a["region"] != b["region"]]
print(f"検挙 {len(fixed)}件")

scn = build_national_scenario(scenario="fy2023r2")
uc = solve_uc(scn.to_uc_parameters()); assert uc.is_optimal
regions = sorted(r for r, (i, _f) in ISLAND_OF.items() if i == "west")
h = int(np.argmax(sum(np.asarray(scn.net_demand_r[r]) for r in regions)))
cfg = load_demand_config()
from src.powerflow.pref_demand import pref_zone_gwh
pref_gwh, _ = pref_zone_gwh(built["nodes"])
geom = {}
net, bus_of, _ = build_island_net("west", built["nodes"], built["edges"],
                                  60.0, geom)
attach_generators(net, bus_of, built["nodes"], "west",
                  attach_mode=GEN_ATTACH_DEFAULT)
allocate_loads(net, cfg, pref_gwh=pref_gwh)
add_reactive_compensation(net, factor=0.8)
add_provisional_infeed(net)
add_per_component_slacks(net)
fuel_by_zone = {r: uc_snapshot(uc, scn.generators, h, region=r) for r in regions}
for r in regions:
    sp = (uc.regional_spill_mw.get(r) or [])
    v = float(sp[h]) if h < len(sp) else 0.0
    if v > 1e-6:
        tot = sum(fuel_by_zone[r].values())
        if tot > v:
            fuel_by_zone[r] = {k: mw*(tot-v)/tot
                               for k, mw in fuel_by_zone[r].items()}
inject_dispatch_by_zone(net, fuel_by_zone,
                        {r: float(scn.net_demand_r[r][h]) for r in regions})
pp.runpp(net, numba=True, init="dc", max_iteration=100, tolerance_mva=1e-2,
         enforce_q_lims=False)
vm = net.res_bus.vm_pu
print(f"AC収束 vm[{vm.min():.3f},{vm.max():.3f}]")

def geo(b):
    try:
        g = json.loads(net.bus.at[b, "geo"])
        return float(g["coordinates"][0]), float(g["coordinates"][1])
    except Exception:  # noqa: BLE001
        return None

BG = "#0A0D1A"
fig = plt.figure(figsize=(16, 8.2), dpi=150)
fig.patch.set_facecolor(BG)
axL = fig.add_axes([0.005, 0.02, 0.62, 0.90]); axL.set_facecolor(BG)
axR = fig.add_axes([0.655, 0.10, 0.335, 0.72]); axR.set_facecolor("#11152A")
# 左: west vm 熱地図
segs = []
for _, l in net.line[net.line.in_service].iterrows():
    ga, gb = geo(int(l.from_bus)), geo(int(l.to_bus))
    if ga and gb:
        segs.append([ga, gb])
axL.add_collection(LineCollection(segs, colors="#2A3050", linewidths=0.4,
                                  alpha=0.7, zorder=1))
xs, ys, cs = [], [], []
for b in net.bus.index:
    g = geo(b)
    v = vm.get(b, np.nan)
    if g and np.isfinite(v):
        xs.append(g[0]); ys.append(g[1]); cs.append(v)
sc = axL.scatter(xs, ys, c=cs, s=4.5, cmap="RdYlBu", vmin=0.85, vmax=1.1,
                 zorder=5, linewidths=0)
axL.set_xlim(128.8, 139.6); axL.set_ylim(30.4, 38.2)
axL.set_aspect(1.0/np.cos(np.radians(34.5))); axL.axis("off")
cb = fig.colorbar(sc, ax=axL, fraction=0.025, pad=0.005)
cb.set_label("電圧 [pu]", color="#C8CDD8", fontsize=11)
cb.ax.tick_params(colors="#8E96B8", labelsize=9)
cb.outline.set_edgecolor("#3A4266")
axL.set_title("西日本 7,928バス — 史上初のAC解 (fy2023r2ピーク断面・6.6s収束)",
              color="#FFFFFF", fontsize=15, fontweight="bold", pad=8)
axL.text(0.01, 0.015, "介入#37 (仮)都心給電9件・#38 跨ぎ是正込み — 全件台帳開示 / "
         "served 100% / 低電圧2箇所は原因特定済(第7波)",
         transform=axL.transAxes, color="#5A648F", fontsize=9)
for nm, la, lo, tx, ty in [("江田島 0.67", 34.19, 132.47, 130.6, 32.6),
                           ("大阪三国 0.73", 34.74, 135.49, 136.4, 32.9)]:
    axL.annotate(nm, xy=(lo, la), xytext=(tx, ty), color="#FFB4A8",
                 fontsize=11, fontweight="bold",
                 arrowprops=dict(arrowstyle="->", color="#FF8A80", lw=1.1))
# 右: 検挙マップ
segs2 = [s2 for s2 in segs
         if 137.6 <= s2[0][0] <= 139.9 and 34.9 <= s2[0][1] <= 37.4]
axR.add_collection(LineCollection(segs2, colors="#2A3050", linewidths=0.6,
                                  alpha=0.8, zorder=1))
fx = [f[1] for f in fixed if f[3] == "tokyo"]
fy = [f[0] for f in fixed if f[3] == "tokyo"]
wx = [f[1] for f in fixed if f[3] != "tokyo"]
wy = [f[0] for f in fixed if f[3] != "tokyo"]
axR.scatter(fx, fy, marker="x", s=42, c="#FF5252", linewidths=1.4, zorder=6,
            label=f"west→east是正 {len(fx)}点")
axR.scatter(wx, wy, marker="x", s=42, c="#40C4FF", linewidths=1.4, zorder=6,
            label=f"east→west是正 {len(wx)}点")
axR.set_xlim(137.6, 139.9); axR.set_ylim(34.9, 37.4)
axR.set_aspect(1.0/np.cos(np.radians(36.0)))
axR.tick_params(colors="#8E96B8", labelsize=8)
for sp_ in axR.spines.values():
    sp_.set_color("#3A4266")
axR.set_title("介入#38の検挙簿 — 50/60Hz境界帯の誤帰属275点",
              color="#C8CDD8", fontsize=12.5, fontweight="bold")
axR.legend(loc="upper left", fontsize=9, facecolor="#11152A",
           labelcolor="#C8CDD8", edgecolor="#3A4266")
axR.text(0.02, 0.02, "×=抽出bboxこぼれの是正(座標の県の周波数が一意な場合のみ跨ぎ許可)\n"
         "旧・AC発散震源: 軽井沢・嬬恋66/77kVポケット(長野東信〜群馬)\n"
         "east→west是正9点は愛知・岐阜(図外)",
         transform=axR.transAxes, color="#7A84AF", fontsize=8.5)
out = "docs/slides/ajg/assets/fig_west_ac_map.png"
fig.savefig(out, facecolor=BG)
print(f"-> {out}")
