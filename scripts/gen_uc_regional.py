"""
10地域別UC 24時間日間プロファイル (fig_uc_regional.png)

改訂版: OCCTO統計ベース地域別RE容量・地域別太陽光CF・蓄電池追加
- 太陽光/風力: OSMデータ（-1MW欠損フラグ多数）を廃止しOCCTO参照容量を使用
- 蓄電池: 地域別に明示的なGeneratorとして追加（SOC制約付き）
- 需要: OCCTO最大需要実績ベースの地域別プロファイル
"""
import json, os, sys, time, platform
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.model.generator import Generator
from src.uc.models import DemandProfile, TimeHorizon, UCParameters
from src.uc.scenario import (
    DEMAND_SHAPE, OCCTO_RE, REGIONS, SOLAR_CF_R, WIND_CF_R,
    build_national_scenario,
)
from src.uc.solver import solve_uc

OUT = "papers/figs"
os.makedirs(OUT, exist_ok=True)

from src.regions import REGION_JA as REGION_JP  # config/regions.yaml

# ── 色・順序（表示用; データ系定数は src/uc/scenario.py に集約） ──
FUEL_COLORS = {
    "nuclear":"#7B2D8E","coal":"#333333","lng":"#E8832A","oil":"#C44E52",
    "pumped_hydro":"#64B5F6","battery":"#00BCD4",
    "hydro":"#2196F3","biomass":"#8BC34A","geothermal":"#FF5722",
    "solar":"#FFD700","wind":"#4CAF50","unknown":"#CCCCCC",
}
FUEL_ORDER = ["nuclear","coal","lng","oil","pumped_hydro","battery","hydro",
              "biomass","geothermal","solar","wind","unknown"]
FUEL_JP = {"nuclear":"原子力","coal":"石炭","lng":"LNG","oil":"石油",
           "pumped_hydro":"揚水","battery":"蓄電池","hydro":"水力","biomass":"バイオ",
           "geothermal":"地熱","solar":"太陽光","wind":"風力","unknown":"その他"}

# ── 発電機ロード+シナリオ構築（src/uc/scenario.py に共通化） ──
print("発電機データ読み込み中...")
scn = build_national_scenario()
all_gens = scn.generators

total_cap = sum(g.capacity_mw for g in all_gens if g.fuel_type != "battery")
print(f"  熱電源: {sum(1 for g in all_gens if g.fuel_type not in ('battery','pumped_hydro'))}機 "
      f"{total_cap:,.0f} MW")
print(f"  蓄電池: {sum(OCCTO_RE[r]['batt_mw'] for r in REGIONS):,.0f} MW / "
      f"{sum(OCCTO_RE[r]['batt_mwh'] for r in REGIONS):,.0f} MWh")
print(f"  太陽光(OCCTO): {sum(OCCTO_RE[r]['solar_mw'] for r in REGIONS):,.0f} MW")
print(f"  風力(OCCTO):   {sum(OCCTO_RE[r]['wind_mw'] for r in REGIONS):,.0f} MW")

# ── 地域別需要・太陽光・風力（シナリオから取得） ─────────────────
gross_demand_r = scn.gross_demand_r
solar_gen_r    = scn.solar_gen_r
wind_gen_r     = scn.wind_gen_r
net_demand_r   = scn.net_demand_r

gross_demand_nat = scn.gross_demand_national
solar_nat        = sum(solar_gen_r.values())
wind_nat         = sum(wind_gen_r.values())
net_demand_nat   = scn.net_demand_national

print(f"  全国最大需要: {gross_demand_nat.max()/1000:.1f} GW")
print(f"  正午太陽光:  {solar_nat[11]/1000:.1f} GW  "
      f"(九州: {solar_gen_r['kyushu'][11]/1000:.1f} GW)")
print(f"  純需要最大:  {net_demand_nat.max()/1000:.1f} GW")
print(f"  九州正午純需要: {net_demand_r['kyushu'][11]/1000:.1f} GW")

# ── UC求解 ──────────────────────────────────────────────────
params = scn.to_uc_parameters(reserve_margin=0.05, mip_gap=0.01, solver_name="highs")

print("UC求解中...")
t0 = time.monotonic()
result = solve_uc(params)
elapsed = time.monotonic() - t0
print(f"  {result.status}, ¥{result.total_cost/1e8:.2f}億/日, {elapsed:.1f}s")
if not result.is_optimal:
    sys.exit(1)

# ── 地域別集計 ────────────────────────────────────────────────
gen_map = {g.id: g for g in all_gens}
region_fuel_power = {r: {ft: np.zeros(24) for ft in FUEL_ORDER} for r in REGIONS}

for sched in result.schedules:
    g  = gen_map[sched.generator_id]
    ft = g.fuel_type if g.fuel_type in FUEL_ORDER else "unknown"
    pwr = np.array(sched.power_output_mw)
    region_fuel_power[g.region][ft] += np.maximum(pwr, 0.0)  # 充電期間は0表示

# 太陽光・風力をOCCTO容量ベースで地域帰属
# 需要を超える分は出力抑制として表現（ピークで地域需要超過しないよう cap）
for r in REGIONS:
    region_fuel_power[r]["solar"] = solar_gen_r[r]
    region_fuel_power[r]["wind"]  = wind_gen_r[r]
    region_fuel_power[r]["_demand"]     = gross_demand_r[r]
    region_fuel_power[r]["_net_demand"] = np.maximum(
        gross_demand_r[r] - solar_gen_r[r] - wind_gen_r[r], 0.0)

# ── 沖縄スタンドアロンUC（孤立系統、連系なし） ────────────────
# 沖縄電力の実発電設備（2023年度時点、公開情報より）
ok_gens = [
    Generator(id="ok_yoshinoura1", name="吉の浦1号(LNG)", capacity_mw=350,
              fuel_type="lng", region="okinawa", fuel_cost_per_mwh=7000,
              no_load_cost=500, startup_cost=2000, shutdown_cost=2000,
              min_up_time_h=2, min_down_time_h=2, p_min_mw=140,
              ramp_up_mw_per_h=105, ramp_down_mw_per_h=105,
              hot_start_cost=2000, warm_start_cost=5000, cold_start_cost=15000,
              warm_start_h=2, cold_start_h=8, storage_capacity_mwh=0,
              charge_efficiency=0.88, discharge_efficiency=0.88),
    Generator(id="ok_yoshinoura2", name="吉の浦2号(LNG)", capacity_mw=350,
              fuel_type="lng", region="okinawa", fuel_cost_per_mwh=7000,
              no_load_cost=500, startup_cost=2000, shutdown_cost=2000,
              min_up_time_h=2, min_down_time_h=2, p_min_mw=140,
              ramp_up_mw_per_h=105, ramp_down_mw_per_h=105,
              hot_start_cost=2000, warm_start_cost=5000, cold_start_cost=15000,
              warm_start_h=2, cold_start_h=8, storage_capacity_mwh=0,
              charge_efficiency=0.88, discharge_efficiency=0.88),
    Generator(id="ok_gushikawa1", name="具志川1号(石油)", capacity_mw=103,
              fuel_type="oil", region="okinawa", fuel_cost_per_mwh=9000,
              no_load_cost=300, startup_cost=1500, shutdown_cost=1500,
              min_up_time_h=1, min_down_time_h=1, p_min_mw=0,
              ramp_up_mw_per_h=31, ramp_down_mw_per_h=31,
              hot_start_cost=1500, warm_start_cost=3000, cold_start_cost=8000,
              warm_start_h=2, cold_start_h=6, storage_capacity_mwh=0,
              charge_efficiency=0.88, discharge_efficiency=0.88),
    Generator(id="ok_gushikawa2", name="具志川2号(石油)", capacity_mw=103,
              fuel_type="oil", region="okinawa", fuel_cost_per_mwh=9000,
              no_load_cost=300, startup_cost=1500, shutdown_cost=1500,
              min_up_time_h=1, min_down_time_h=1, p_min_mw=0,
              ramp_up_mw_per_h=31, ramp_down_mw_per_h=31,
              hot_start_cost=1500, warm_start_cost=3000, cold_start_cost=8000,
              warm_start_h=2, cold_start_h=6, storage_capacity_mwh=0,
              charge_efficiency=0.88, discharge_efficiency=0.88),
    Generator(id="ok_gushikawa3", name="具志川3号(石油)", capacity_mw=103,
              fuel_type="oil", region="okinawa", fuel_cost_per_mwh=9000,
              no_load_cost=300, startup_cost=1500, shutdown_cost=1500,
              min_up_time_h=1, min_down_time_h=1, p_min_mw=0,
              ramp_up_mw_per_h=31, ramp_down_mw_per_h=31,
              hot_start_cost=1500, warm_start_cost=3000, cold_start_cost=8000,
              warm_start_h=2, cold_start_h=6, storage_capacity_mwh=0,
              charge_efficiency=0.88, discharge_efficiency=0.88),
    Generator(id="ok_gushikawa4", name="具志川4号(石油)", capacity_mw=103,
              fuel_type="oil", region="okinawa", fuel_cost_per_mwh=9000,
              no_load_cost=300, startup_cost=1500, shutdown_cost=1500,
              min_up_time_h=1, min_down_time_h=1, p_min_mw=0,
              ramp_up_mw_per_h=31, ramp_down_mw_per_h=31,
              hot_start_cost=1500, warm_start_cost=3000, cold_start_cost=8000,
              warm_start_h=2, cold_start_h=6, storage_capacity_mwh=0,
              charge_efficiency=0.88, discharge_efficiency=0.88),
    Generator(id="ok_ishikawa", name="石川火力(石炭)", capacity_mw=156,
              fuel_type="coal", region="okinawa", fuel_cost_per_mwh=4500,
              no_load_cost=400, startup_cost=5000, shutdown_cost=2000,
              min_up_time_h=4, min_down_time_h=4, p_min_mw=62,
              ramp_up_mw_per_h=47, ramp_down_mw_per_h=47,
              hot_start_cost=5000, warm_start_cost=15000, cold_start_cost=40000,
              warm_start_h=4, cold_start_h=12, storage_capacity_mwh=0,
              charge_efficiency=0.88, discharge_efficiency=0.88),
    Generator(id="ok_naha", name="那覇火力(石油)", capacity_mw=184,
              fuel_type="oil", region="okinawa", fuel_cost_per_mwh=9500,
              no_load_cost=300, startup_cost=1500, shutdown_cost=1500,
              min_up_time_h=1, min_down_time_h=1, p_min_mw=0,
              ramp_up_mw_per_h=55, ramp_down_mw_per_h=55,
              hot_start_cost=1500, warm_start_cost=3000, cold_start_cost=8000,
              warm_start_h=2, cold_start_h=6, storage_capacity_mwh=0,
              charge_efficiency=0.88, discharge_efficiency=0.88),
    Generator(id="ok_battery", name="沖縄蓄電池", capacity_mw=100,
              fuel_type="battery", region="okinawa", fuel_cost_per_mwh=0,
              no_load_cost=0, startup_cost=0, shutdown_cost=0,
              min_up_time_h=1, min_down_time_h=1, p_min_mw=0,
              ramp_up_mw_per_h=100, ramp_down_mw_per_h=100,
              storage_capacity_mwh=400, charge_efficiency=0.93, discharge_efficiency=0.93,
              initial_soc_fraction=0.5, min_terminal_soc_fraction=0.4),
]

ok_solar   = SOLAR_CF_R["okinawa"] * OCCTO_RE["okinawa"]["solar_mw"]
ok_wind    = WIND_CF_R["okinawa"]  * OCCTO_RE["okinawa"]["wind_mw"]
ok_peak_mw = 1800  # 沖縄電力 2022年夏季実績ピーク (設備容量2GWに対し実需要1,750-1,800MW)
ok_gross   = DEMAND_SHAPE * ok_peak_mw
ok_net     = np.maximum(ok_gross - ok_solar - ok_wind, 0.0)

print("沖縄スタンドアロンUC求解中 (7機+蓄電池)...")
ok_params = UCParameters(
    generators=ok_gens,
    demand=DemandProfile(demands=ok_net.tolist()),
    time_horizon=TimeHorizon(num_periods=24),
    reserve_margin=0.05, solver_name="highs", mip_gap=0.02,
)
ok_result = solve_uc(ok_params)
print(f"  {ok_result.status}, ¥{ok_result.total_cost/1e6:.1f}百万/日")

ok_fuel_power = {ft: np.zeros(24) for ft in FUEL_ORDER}
ok_gen_map = {g.id: g for g in ok_gens}
for sched in ok_result.schedules:
    g  = ok_gen_map[sched.generator_id]
    ft = g.fuel_type if g.fuel_type in FUEL_ORDER else "unknown"
    ok_fuel_power[ft] += np.maximum(np.array(sched.power_output_mw), 0.0)
ok_fuel_power["solar"] = ok_solar
ok_fuel_power["wind"]  = ok_wind
ok_fuel_power["_demand"]     = ok_gross
ok_fuel_power["_net_demand"] = ok_net
ok_solar_noon_pct_val = ok_solar[11] / ok_peak_mw * 100

# ── 描画（沖縄は孤立系統のため全国UCから除外して別途表示） ──
REGIONS_PLOT = [r for r in REGIONS if r != "okinawa"]  # 9地域
hours = np.arange(24)
fig, axes = plt.subplots(2, 5, figsize=(18, 6.5), facecolor="white",
                          sharex=True,
                          gridspec_kw={"hspace":0.48, "wspace":0.24})
axes_flat = axes.flatten()

# 10番目のパネル（沖縄）: スタンドアロンUC結果を表示
ax_ok = axes_flat[9]
ax_ok.set_facecolor("white")
ok_bottom = np.zeros(24)
for ft in FUEL_ORDER:
    vals = ok_fuel_power[ft]
    if vals.sum() < 0.01:
        continue
    ax_ok.bar(hours, vals / 1000, bottom=ok_bottom / 1000,
              color=FUEL_COLORS.get(ft, "#ccc"), width=0.88, zorder=2, linewidth=0)
    ok_bottom += vals
ax_ok.plot(hours, ok_fuel_power["_demand"] / 1000,     "k-",  lw=1.4, zorder=5)
ax_ok.plot(hours, ok_fuel_power["_net_demand"] / 1000, "k--", lw=0.9, zorder=5)
ax_ok.set_title(f"沖縄（孤立系統）\n太陽光@正午:{ok_solar_noon_pct_val:.0f}%",
                fontsize=9, fontweight="bold", pad=2)
ax_ok.set_xlim(-0.5, 23.5)
ax_ok.set_xticks([0, 6, 12, 18])
ax_ok.set_xticklabels(["0", "6", "12", "18"], fontsize=7)
ax_ok.tick_params(axis="y", labelsize=7)
ax_ok.grid(axis="y", color="#ddd", lw=0.4)
ax_ok.set_axisbelow(True)
ax_ok.set_ylim(bottom=0)
for sp in ax_ok.spines.values():
    sp.set_color("#bbb")

for idx, r in enumerate(REGIONS_PLOT):
    ax = axes_flat[idx]
    ax.set_facecolor("white")
    fp = region_fuel_power[r]

    bottom = np.zeros(24)
    for ft in FUEL_ORDER:
        vals = fp[ft]
        if vals.sum() < 0.01:
            continue
        ax.bar(hours, vals / 1000, bottom=bottom / 1000,
               color=FUEL_COLORS.get(ft, "#ccc"),
               width=0.88, zorder=2, linewidth=0)
        bottom += vals

    ax.plot(hours, fp["_demand"] / 1000,     "k-",  lw=1.4, zorder=5, label="総需要")
    ax.plot(hours, fp["_net_demand"] / 1000, "k--", lw=0.9, zorder=5, label="純需要")

    solar_noon = solar_gen_r[r][11] / 1000
    solar_pct  = solar_noon / (OCCTO_RE[r]["peak_mw"] / 1000) * 100
    ax.set_title(f"{REGION_JP[r]}\n太陽光@正午:{solar_pct:.0f}%",
                 fontsize=9, fontweight="bold", pad=2)
    ax.set_xlim(-0.5, 23.5)
    ax.set_xticks([0, 6, 12, 18])
    ax.set_xticklabels(["0", "6", "12", "18"], fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    if idx % 5 == 0:
        ax.set_ylabel("GW", fontsize=7)
    ax.grid(axis="y", color="#ddd", lw=0.4)
    ax.set_axisbelow(True)
    for sp in ax.spines.values():
        sp.set_color("#bbb")
    ax.set_ylim(bottom=0)

# 共通凡例
active_fuels = [ft for ft in FUEL_ORDER
                if any(region_fuel_power[r][ft].sum() > 0.01 for r in REGIONS)]
handles = [mpatches.Patch(color=FUEL_COLORS[ft], label=FUEL_JP[ft])
           for ft in active_fuels]
handles += [
    Line2D([0], [0], color="k", lw=1.5, label="総需要"),
    Line2D([0], [0], color="k", lw=1.0, linestyle="--", label="純需要(RE後)"),
]
fig.legend(handles=handles, loc="lower center", ncol=8,
           fontsize=8, facecolor="white", edgecolor="#bbb",
           bbox_to_anchor=(0.5, -0.05), framealpha=0.95)

total_solar_gw = sum(OCCTO_RE[r]["solar_mw"] for r in REGIONS) / 1000
total_wind_gw  = sum(OCCTO_RE[r]["wind_mw"] for r in REGIONS) / 1000
total_batt_gw  = sum(OCCTO_RE[r]["batt_mw"] for r in REGIONS) / 1000
fig.suptitle(
    f"10地域別UC 24時間プロファイル（OCCTO参照: 太陽光{total_solar_gw:.0f}GW・"
    f"風力{total_wind_gw:.0f}GW・蓄電池{total_batt_gw:.1f}GW, 9連系線制約）\n"
    f"総費用 ¥{result.total_cost/1e8:.1f}億/日，求解 {elapsed:.0f}s",
    fontsize=10, y=1.02,
)

out = f"{OUT}/fig_uc_regional.png"
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
plt.close()
print(f"Saved: {out}")
