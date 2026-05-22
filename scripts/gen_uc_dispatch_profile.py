"""
全国UC 24時間日間プロファイル図
・太陽光/風力は非制御（固定availability profile）→ 純需要をUCへ
・熱力系・水力・揚水でUCを解く
・結果を発電スタックとして可視化
"""
import os, sys, json, time
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import platform

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

# ── 時刻別プロファイル ──────────────────────────────────
# 需要形状（日本標準的夏日パターン）
DEMAND_SHAPE = np.array([
    0.60,0.57,0.55,0.53,0.55,0.60,
    0.68,0.78,0.87,0.93,0.97,1.00,
    0.99,0.98,0.96,0.93,0.90,0.86,
    0.82,0.78,0.74,0.70,0.66,0.63,
])

# 太陽光設備利用率（夜間0、日中ベルカーブ）
SOLAR_CF = np.array([
    0.00,0.00,0.00,0.00,0.00,0.02,
    0.10,0.25,0.45,0.65,0.80,0.90,
    0.92,0.88,0.78,0.62,0.40,0.18,
    0.04,0.00,0.00,0.00,0.00,0.00,
])

# 風力設備利用率（夜間やや高め）
WIND_CF = np.array([
    0.38,0.40,0.41,0.42,0.40,0.38,
    0.34,0.30,0.28,0.27,0.28,0.29,
    0.30,0.31,0.32,0.33,0.35,0.37,
    0.38,0.39,0.40,0.40,0.39,0.38,
])

# 燃料コスト・マッピング
FUEL_COST = {"coal":4500,"lng":7000,"oil":9000,"nuclear":1500,
             "hydro":0,"pumped_hydro":0,"biomass":3000,
             "geothermal":0,"waste":5000,"battery":0,"unknown":5000}
FUEL_MAP  = {"coal":"coal","gas":"lng","lng":"lng","oil":"oil","nuclear":"nuclear",
             "hydro":"hydro","wind":"wind","solar":"solar","biomass":"biomass",
             "geothermal":"geothermal","waste":"biomass","battery":"pumped_hydro"}
FUEL_COLORS = {
    "nuclear":"#7B2D8E","coal":"#4A4A4A","lng":"#E8832A","oil":"#C44E52",
    "hydro":"#2196F3","pumped_hydro":"#64B5F6","biomass":"#8BC34A",
    "geothermal":"#FF5722","solar":"#FFD700","wind":"#4CAF50",
    "battery":"#00BCD4","unknown":"#CCCCCC",
}
FUEL_ORDER_DISP = ["nuclear","coal","lng","oil","pumped_hydro","hydro",
                   "biomass","geothermal","battery","unknown"]
FUEL_ORDER_RE   = ["solar","wind"]
FUEL_JP = {"nuclear":"原子力","coal":"石炭","lng":"LNG","oil":"石油",
           "pumped_hydro":"揚水","hydro":"水力","biomass":"バイオ",
           "geothermal":"地熱","solar":"太陽光","wind":"風力",
           "battery":"蓄電池","unknown":"不明"}

SU_PARAMS = {
    "nuclear": dict(hot=10000,warm=30000,cold=100000,warm_h=8, cold_h=48,mut=8,mdt=8),
    "coal":    dict(hot= 5000,warm=15000,cold= 40000,warm_h=4, cold_h=12,mut=4,mdt=4),
    "lng":     dict(hot= 2000,warm= 5000,cold= 15000,warm_h=2, cold_h= 8,mut=2,mdt=2),
    "oil":     dict(hot= 1500,warm= 3000,cold=  8000,warm_h=2, cold_h= 6,mut=1,mdt=1),
}
THERMAL_DEFAULT = {"nuclear":900,"coal":600,"lng":400,"gas":400,
                   "oil":200,"geothermal":30,"waste":15,"biomass":20}
REGIONS = ["hokkaido","tohoku","tokyo","chubu","hokuriku",
           "kansai","chugoku","shikoku","kyushu","okinawa"]

# ── 発電機ロード ────────────────────────────────────────
print("発電機データ読み込み中...")
dispatchable = []   # UC対象
solar_cap_total = 0.0
wind_cap_total  = 0.0

for region in REGIONS:
    path = f"data/{region}_plants.geojson"
    if not os.path.exists(path): continue
    with open(path) as f:
        data = json.load(f)
    for i, feat in enumerate(data["features"]):
        props = feat["properties"]
        raw_cap = props.get("capacity_mw")
        try:   cap = float(raw_cap) if raw_cap else 0.0
        except: cap = 0.0
        raw_fuel = (props.get("fuel_type") or props.get("plant:source") or "").lower()
        if cap < 5.0:
            cap = THERMAL_DEFAULT.get(raw_fuel, 0.0)
            if cap < 5.0: continue
        if raw_fuel.startswith("http"): raw_fuel = "unknown"
        fuel = FUEL_MAP.get(raw_fuel, "unknown")

        # 太陽光・風力は固定プロファイル → 除外
        if fuel == "solar":
            solar_cap_total += cap
            continue
        if fuel == "wind":
            wind_cap_total += cap
            continue

        sp = SU_PARAMS.get(fuel, {})
        is_storage = fuel == "pumped_hydro"
        stor_cap   = cap * 6.0 if is_storage else 0.0
        name = (props.get("name") or f"{region}_{fuel}_{i}")[:40]

        g = Generator(
            id=f"{region}_g{i}", name=name, capacity_mw=cap,
            fuel_type=fuel, region=region,
            fuel_cost_per_mwh=FUEL_COST.get(fuel, 5000),
            no_load_cost=500 if fuel not in ("hydro","pumped_hydro","geothermal") else 0,
            startup_cost=sp.get("hot",3000) if fuel not in ("hydro","pumped_hydro") else 0,
            shutdown_cost=2000 if fuel not in ("hydro","pumped_hydro") else 0,
            min_up_time_h=sp.get("mut",1),
            min_down_time_h=sp.get("mdt",1),
            p_min_mw=cap * 0.4 if fuel in ("nuclear","coal") else 0.0,
            ramp_up_mw_per_h=cap * (0.1 if fuel=="nuclear" else 0.3),
            ramp_down_mw_per_h=cap * (0.1 if fuel=="nuclear" else 0.3),
            hot_start_cost=sp.get("hot",0),
            warm_start_cost=sp.get("warm",0),
            cold_start_cost=sp.get("cold",0),
            warm_start_h=sp.get("warm_h",0),
            cold_start_h=sp.get("cold_h",0),
            storage_capacity_mwh=stor_cap,
            charge_efficiency=0.88,
            discharge_efficiency=0.88,
        )
        dispatchable.append(g)

total_disp_cap = sum(g.capacity_mw for g in dispatchable)
print(f"  制御可能: {len(dispatchable)}機 {total_disp_cap:,.0f} MW")
print(f"  太陽光固定: {solar_cap_total:,.0f} MW, 風力固定: {wind_cap_total:,.0f} MW")

# ── 固定再エネ出力（時刻別） ────────────────────────────
solar_mw = SOLAR_CF * solar_cap_total   # 24h
wind_mw  = WIND_CF  * wind_cap_total    # 24h
re_mw    = solar_mw + wind_mw          # 合計固定再エネ

# ── 純需要（総需要 - 固定再エネ）────────────────────────
PEAK_DEMAND = total_disp_cap * 0.75    # 制御可能容量の75%を総需要とする
gross_demand = DEMAND_SHAPE * PEAK_DEMAND
net_demand   = np.maximum(gross_demand - re_mw, 0.0)

print(f"  総需要ピーク: {gross_demand.max():,.0f} MW")
print(f"  純需要ピーク: {net_demand.max():,.0f} MW (再エネ控除後)")

# ── UC求解 ─────────────────────────────────────────────
loader = InterconnectionLoader()
ics = loader.load("data/reference/interconnections.yaml")

th = TimeHorizon(num_periods=24)
dp = DemandProfile(demands=net_demand.tolist())
params = UCParameters(
    generators=dispatchable, demand=dp, time_horizon=th,
    reserve_margin=0.05, solver_name="highs", mip_gap=0.01,
    interconnections=ics,
)

print("UC求解中...")
t0 = time.monotonic()
result = solve_uc(params)
elapsed = time.monotonic() - t0
print(f"  Status: {result.status}, Cost: ¥{result.total_cost/1e8:.2f}億/日, Time: {elapsed:.1f}s")

if not result.is_optimal:
    print("最適解未取得"); sys.exit(1)

# ── 発電量集計 ─────────────────────────────────────────
gen_map   = {g.id: g for g in dispatchable}
fuel_power = {ft: np.zeros(24) for ft in FUEL_ORDER_DISP + FUEL_ORDER_RE}
for sched in result.schedules:
    g  = gen_map[sched.generator_id]
    ft = g.fuel_type if g.fuel_type in fuel_power else "unknown"
    fuel_power[ft] += np.array(sched.power_output_mw)

# 固定再エネを追加
fuel_power["solar"] = solar_mw
fuel_power["wind"]  = wind_mw

# ── 図の描画 ───────────────────────────────────────────
hours = np.arange(24)
fig, ax = plt.subplots(figsize=(12, 5.5), facecolor="white")
ax.set_facecolor("white")

bottom = np.zeros(24)
handles = []
plot_order = FUEL_ORDER_DISP + FUEL_ORDER_RE   # 再エネを最上段に

for ft in plot_order:
    vals = fuel_power.get(ft, np.zeros(24))
    if vals.sum() < 0.5: continue
    ax.bar(hours, vals/1000, bottom=bottom/1000,
           color=FUEL_COLORS.get(ft,"#ccc"),
           label=FUEL_JP.get(ft,ft),
           width=0.88, zorder=2, linewidth=0)
    bottom += vals
    handles.append(mpatches.Patch(color=FUEL_COLORS.get(ft,"#ccc"),
                                   label=FUEL_JP.get(ft,ft)))

# 需要線
ax.plot(hours, gross_demand/1000, "k-",  lw=2.0, label="総需要", zorder=6)
ax.plot(hours, net_demand/1000,   "k--", lw=1.5, label="純需要（再エネ控除後）", zorder=6)

# 装飾
ax.set_xlabel("時刻 (h)", fontsize=11)
ax.set_ylabel("発電電力 (GW)", fontsize=11)
ax.set_xlim(-0.5, 23.5)
ax.set_xticks(range(0, 24, 3))
ax.set_xticklabels([f"{h}:00" for h in range(0, 24, 3)], fontsize=9)
ax.set_title("全国Unit Commitment 24時間日間プロファイル\n"
             f"（{len(dispatchable)}機・3状態起動コスト・蓄電池SOC・9連系線制約，"
             f"総費用¥{result.total_cost/1e8:.1f}億/日，求解{elapsed:.0f}s）",
             fontsize=10, pad=6)
ax.grid(axis="y", color="#ddd", lw=0.5, zorder=0)
ax.set_axisbelow(True)
for sp in ax.spines.values(): sp.set_color("#bbb")

# 凡例（需要線も含む）
from matplotlib.lines import Line2D
line_handles = [
    Line2D([0],[0], color="k",  lw=2.0, label="総需要"),
    Line2D([0],[0], color="k",  lw=1.5, linestyle="--", label="純需要（再エネ控除後）"),
]
ax.legend(handles=line_handles + handles[::-1],
          fontsize=8, loc="upper right", ncol=3,
          facecolor="white", edgecolor="#bbb", framealpha=0.95)

plt.tight_layout(pad=1.0)
out = f"{OUT}/fig_uc_dispatch.png"
plt.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
plt.close()
print(f"Saved: {out}")
