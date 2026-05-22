"""
10地域別UC 24時間日間プロファイル (fig_uc_regional.png)
前回のgen_uc_dispatch_profile.pyの結果を地域別に分解して可視化
"""
import json, os, sys, time, platform
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.model.generator import Generator
from src.uc.interconnection_loader import InterconnectionLoader
from src.uc.models import DemandProfile, TimeHorizon, UCParameters
from src.uc.solver import solve_uc

OUT = "papers/figs"
os.makedirs(OUT, exist_ok=True)

REGIONS = ["hokkaido","tohoku","tokyo","chubu","hokuriku",
           "kansai","chugoku","shikoku","kyushu","okinawa"]
REGION_JP = {"hokkaido":"北海道","tohoku":"東北","tokyo":"東京",
             "chubu":"中部","hokuriku":"北陸","kansai":"関西",
             "chugoku":"中国","shikoku":"四国","kyushu":"九州","okinawa":"沖縄"}

DEMAND_SHAPE = np.array([
    0.60,0.57,0.55,0.53,0.55,0.60,0.68,0.78,
    0.87,0.93,0.97,1.00,0.99,0.98,0.96,0.93,
    0.90,0.86,0.82,0.78,0.74,0.70,0.66,0.63,
])
SOLAR_CF = np.array([
    0,0,0,0,0,0.02,0.10,0.25,0.45,0.65,0.80,0.90,
    0.92,0.88,0.78,0.62,0.40,0.18,0.04,0,0,0,0,0,
])
WIND_CF = np.array([
    0.38,0.40,0.41,0.42,0.40,0.38,0.34,0.30,
    0.28,0.27,0.28,0.29,0.30,0.31,0.32,0.33,
    0.35,0.37,0.38,0.39,0.40,0.40,0.39,0.38,
])

FUEL_COST = {"coal":4500,"lng":7000,"oil":9000,"nuclear":1500,
             "hydro":0,"pumped_hydro":0,"biomass":3000,"geothermal":0,
             "waste":5000,"unknown":5000}
FUEL_MAP = {"coal":"coal","gas":"lng","lng":"lng","oil":"oil","nuclear":"nuclear",
            "hydro":"hydro","wind":"wind","solar":"solar","biomass":"biomass",
            "geothermal":"geothermal","waste":"biomass","battery":"pumped_hydro"}
FUEL_COLORS = {"nuclear":"#7B2D8E","coal":"#333333","lng":"#E8832A",
               "oil":"#C44E52","hydro":"#2196F3","pumped_hydro":"#64B5F6",
               "biomass":"#8BC34A","geothermal":"#FF5722",
               "solar":"#FFD700","wind":"#4CAF50","unknown":"#CCCCCC"}
FUEL_ORDER = ["nuclear","coal","lng","oil","pumped_hydro","hydro",
              "biomass","geothermal","solar","wind","unknown"]
FUEL_JP = {"nuclear":"原子力","coal":"石炭","lng":"LNG","oil":"石油",
           "pumped_hydro":"揚水","hydro":"水力","biomass":"バイオ",
           "geothermal":"地熱","solar":"太陽光","wind":"風力","unknown":"その他"}

SU = {"nuclear":dict(hot=10000,warm=30000,cold=100000,wh=8,ch=48,mut=8,mdt=8),
      "coal":   dict(hot= 5000,warm=15000,cold= 40000,wh=4,ch=12,mut=4,mdt=4),
      "lng":    dict(hot= 2000,warm= 5000,cold= 15000,wh=2,ch= 8,mut=2,mdt=2),
      "oil":    dict(hot= 1500,warm= 3000,cold=  8000,wh=2,ch= 6,mut=1,mdt=1)}
THERMAL_DEFAULT = {"nuclear":900,"coal":600,"lng":400,"gas":400,
                   "oil":200,"geothermal":30,"waste":15,"biomass":20}

# ── 発電機ロード ─────────────────────────────────────
print("発電機データ読み込み中...")
all_gens, solar_by_region, wind_by_region = [], {}, {}
for r in REGIONS:
    solar_by_region[r] = 0.0
    wind_by_region[r] = 0.0
    p = f"data/{r}_plants.geojson"
    if not os.path.exists(p): continue
    with open(p) as f: data = json.load(f)
    for i, feat in enumerate(data["features"]):
        props = feat["properties"]
        raw_cap = props.get("capacity_mw")
        try:   cap = float(raw_cap) if raw_cap else 0.0
        except: cap = 0.0
        rf = (props.get("fuel_type") or props.get("plant:source") or "").lower()
        if cap < 5.0:
            cap = THERMAL_DEFAULT.get(rf, 0.0)
            if cap < 5.0: continue
        if rf.startswith("http"): rf = "unknown"
        fuel = FUEL_MAP.get(rf, "unknown")
        if fuel == "solar": solar_by_region[r] += cap; continue
        if fuel == "wind":  wind_by_region[r]  += cap; continue
        sp = SU.get(fuel, {})
        g = Generator(
            id=f"{r}_g{i}", name=(props.get("name") or f"{r}_{fuel}_{i}")[:40],
            capacity_mw=cap, fuel_type=fuel, region=r,
            fuel_cost_per_mwh=FUEL_COST.get(fuel,5000),
            no_load_cost=500 if fuel not in("hydro","pumped_hydro","geothermal") else 0,
            startup_cost=sp.get("hot",3000) if fuel not in("hydro","pumped_hydro") else 0,
            shutdown_cost=2000 if fuel not in("hydro","pumped_hydro") else 0,
            min_up_time_h=sp.get("mut",1), min_down_time_h=sp.get("mdt",1),
            p_min_mw=cap*0.4 if fuel in("nuclear","coal") else 0.0,
            ramp_up_mw_per_h=cap*(0.1 if fuel=="nuclear" else 0.3),
            ramp_down_mw_per_h=cap*(0.1 if fuel=="nuclear" else 0.3),
            hot_start_cost=sp.get("hot",0), warm_start_cost=sp.get("warm",0),
            cold_start_cost=sp.get("cold",0),
            warm_start_h=sp.get("wh",0), cold_start_h=sp.get("ch",0),
            storage_capacity_mwh=cap*6.0 if fuel=="pumped_hydro" else 0.0,
            charge_efficiency=0.88, discharge_efficiency=0.88,
        )
        all_gens.append(g)

total_cap = sum(g.capacity_mw for g in all_gens)
total_solar = sum(solar_by_region.values())
total_wind  = sum(wind_by_region.values())
print(f"  制御可能: {len(all_gens)}機 {total_cap:,.0f} MW")
print(f"  太陽光: {total_solar:,.0f} MW, 風力: {total_wind:,.0f} MW")

solar_mw = SOLAR_CF * total_solar
wind_mw  = WIND_CF  * total_wind
gross_demand = DEMAND_SHAPE * total_cap * 0.75
net_demand   = np.maximum(gross_demand - solar_mw - wind_mw, 0.0)

loader = InterconnectionLoader()
ics = loader.load("data/reference/interconnections.yaml")
th = TimeHorizon(num_periods=24)
dp = DemandProfile(demands=net_demand.tolist())
params = UCParameters(generators=all_gens, demand=dp, time_horizon=th,
                      reserve_margin=0.05, solver_name="highs", mip_gap=0.01,
                      interconnections=ics)

print("UC求解中...")
t0 = time.monotonic()
result = solve_uc(params)
elapsed = time.monotonic() - t0
print(f"  {result.status}, ¥{result.total_cost/1e8:.2f}億/日, {elapsed:.1f}s")
if not result.is_optimal: sys.exit(1)

# ── 地域別集計 ────────────────────────────────────────
gen_map = {g.id: g for g in all_gens}
region_fuel_power = {r: {ft: np.zeros(24) for ft in FUEL_ORDER} for r in REGIONS}

for sched in result.schedules:
    g  = gen_map[sched.generator_id]
    ft = g.fuel_type if g.fuel_type in FUEL_ORDER else "unknown"
    region_fuel_power[g.region][ft] += np.array(sched.power_output_mw)

# 固定再エネを地域容量比で分配
for r in REGIONS:
    rc_solar = solar_by_region[r]
    rc_wind  = wind_by_region[r]
    region_fuel_power[r]["solar"] = SOLAR_CF * rc_solar
    region_fuel_power[r]["wind"]  = WIND_CF  * rc_wind

# 地域別需要（制御可能容量比例）
region_disp_cap = {r: sum(g.capacity_mw for g in all_gens if g.region == r)
                   for r in REGIONS}
for r in REGIONS:
    frac = region_disp_cap[r] / total_cap if total_cap > 0 else 0
    region_fuel_power[r]["_demand"]      = gross_demand * frac
    region_fuel_power[r]["_net_demand"]  = net_demand   * frac

# ── 描画 ────────────────────────────────────────────
hours = np.arange(24)
fig, axes = plt.subplots(2, 5, figsize=(16, 5.8), facecolor="white",
                          sharex=True,
                          gridspec_kw={"hspace":0.42,"wspace":0.22})
axes_flat = axes.flatten()

for idx, r in enumerate(REGIONS):
    ax = axes_flat[idx]
    ax.set_facecolor("white")
    fp = region_fuel_power[r]

    bottom = np.zeros(24)
    for ft in FUEL_ORDER:
        vals = fp[ft]
        if vals.sum() < 0.01: continue
        ax.bar(hours, vals/1000, bottom=bottom/1000,
               color=FUEL_COLORS.get(ft,"#ccc"),
               width=0.88, zorder=2, linewidth=0)
        bottom += vals

    # 需要線
    ax.plot(hours, fp["_demand"]/1000,     "k-",  lw=1.2, zorder=5)
    ax.plot(hours, fp["_net_demand"]/1000, "k--", lw=0.8, zorder=5)

    ax.set_title(REGION_JP[r], fontsize=11, fontweight="bold", pad=3)
    ax.set_xlim(-0.5, 23.5)
    ax.set_xticks([0,6,12,18])
    ax.set_xticklabels(["0","6","12","18"], fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_ylabel("GW", fontsize=7) if idx % 5 == 0 else None
    ax.grid(axis="y", color="#ddd", lw=0.4)
    ax.set_axisbelow(True)
    for sp in ax.spines.values(): sp.set_color("#bbb")

# 共通凡例
handles = [mpatches.Patch(color=FUEL_COLORS[ft], label=FUEL_JP[ft])
           for ft in FUEL_ORDER if any(
               region_fuel_power[r][ft].sum() > 0.01 for r in REGIONS)]
from matplotlib.lines import Line2D
handles += [Line2D([0],[0],color="k",lw=1.5,label="総需要"),
            Line2D([0],[0],color="k",lw=1.0,linestyle="--",label="純需要")]
fig.legend(handles=handles, loc="lower center", ncol=7,
           fontsize=8.5, facecolor="white", edgecolor="#bbb",
           bbox_to_anchor=(0.5, -0.04), framealpha=0.95)

fig.suptitle(f"10地域別UC 24時間日間プロファイル（3状態起動コスト・蓄電池SOC・9連系線制約）\n"
             f"総費用 ¥{result.total_cost/1e8:.1f}億/日，求解 {elapsed:.0f}s",
             fontsize=11, y=1.01)

out = f"{OUT}/fig_uc_regional.png"
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
plt.close()
print(f"Saved: {out}")
