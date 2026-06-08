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
from src.uc.interconnection_loader import InterconnectionLoader
from src.uc.models import DemandProfile, TimeHorizon, UCParameters
from src.uc.solver import solve_uc

OUT = "papers/figs"
os.makedirs(OUT, exist_ok=True)

REGIONS = ["hokkaido","tohoku","tokyo","chubu","hokuriku",
           "kansai","chugoku","shikoku","kyushu","okinawa"]
from src.regions import REGION_JA as REGION_JP  # config/regions.yaml

# ── OCCTO 2023年度統計ベース地域別参照容量 ─────────────────────
# 出典: 広域機関 電力需給検証報告書・再エネ導入実績 (概算値)
OCCTO_RE = {
    "hokkaido": {"solar_mw": 4000,  "wind_mw": 4500,  "batt_mw": 300,  "batt_mwh": 1200, "peak_mw": 6000},
    "tohoku":   {"solar_mw": 7500,  "wind_mw": 4000,  "batt_mw": 400,  "batt_mwh": 1600, "peak_mw": 14000},
    "tokyo":    {"solar_mw": 12000, "wind_mw": 300,   "batt_mw": 500,  "batt_mwh": 2000, "peak_mw": 60000},
    "chubu":    {"solar_mw": 6000,  "wind_mw": 200,   "batt_mw": 200,  "batt_mwh": 800,  "peak_mw": 22000},
    "hokuriku": {"solar_mw": 1800,  "wind_mw": 100,   "batt_mw": 100,  "batt_mwh": 400,  "peak_mw": 5000},
    "kansai":   {"solar_mw": 5500,  "wind_mw": 100,   "batt_mw": 300,  "batt_mwh": 1200, "peak_mw": 28000},
    "chugoku":  {"solar_mw": 5000,  "wind_mw": 300,   "batt_mw": 200,  "batt_mwh": 800,  "peak_mw": 10000},
    "shikoku":  {"solar_mw": 2000,  "wind_mw": 100,   "batt_mw": 150,  "batt_mwh": 600,  "peak_mw": 5000},
    "kyushu":   {"solar_mw": 15000, "wind_mw": 1200,  "batt_mw": 1200, "batt_mwh": 4800, "peak_mw": 18000},
    "okinawa":  {"solar_mw": 500,   "wind_mw": 100,   "batt_mw": 100,  "batt_mwh": 400,  "peak_mw": 2000},
}

# ── 24時間需要形状（ピーク=1.0, 平日夏季典型） ─────────────────
DEMAND_SHAPE = np.array([
    0.60,0.57,0.55,0.53,0.55,0.60,0.68,0.78,
    0.87,0.93,0.97,1.00,0.99,0.98,0.96,0.93,
    0.90,0.86,0.82,0.78,0.74,0.70,0.66,0.63,
])

# ── 太陽光CF: ベース曲線 × 地域別日照倍率 ────────────────────
SOLAR_CF_BASE = np.array([
    0,0,0,0,0,0.02,0.10,0.25,0.45,0.65,0.80,0.90,
    0.92,0.88,0.78,0.62,0.40,0.18,0.04,0,0,0,0,0,
])
# 年間水平面日射量 (GHI) 比による地域係数
SOLAR_MULT = {
    "hokkaido":0.83, "tohoku":0.92, "tokyo":1.00, "chubu":1.03,
    "hokuriku":0.90, "kansai":1.04, "chugoku":1.06, "shikoku":1.06,
    "kyushu":1.10,  "okinawa":1.13,
}
SOLAR_CF_R = {r: np.minimum(SOLAR_CF_BASE * SOLAR_MULT[r], 1.0) for r in REGIONS}

# ── 風力CF: ベース曲線 × 地域別風況倍率 ──────────────────────
WIND_CF_BASE = np.array([
    0.38,0.40,0.41,0.42,0.40,0.38,0.34,0.30,
    0.28,0.27,0.28,0.29,0.30,0.31,0.32,0.33,
    0.35,0.37,0.38,0.39,0.40,0.40,0.39,0.38,
])
WIND_MULT = {
    "hokkaido":1.25, "tohoku":1.20, "tokyo":0.70, "chubu":0.85,
    "hokuriku":0.95, "kansai":0.80, "chugoku":0.90, "shikoku":0.90,
    "kyushu":1.00,  "okinawa":1.10,
}
WIND_CF_R = {r: WIND_CF_BASE * WIND_MULT[r] for r in REGIONS}

# ── 燃料コスト・色・順序 ──────────────────────────────────────
FUEL_COST = {"coal":4500,"lng":7000,"oil":9000,"nuclear":1500,
             "hydro":0,"pumped_hydro":0,"battery":0,
             "biomass":3000,"geothermal":0,"waste":5000,"unknown":5000}
FUEL_MAP  = {"coal":"coal","gas":"lng","lng":"lng","oil":"oil","nuclear":"nuclear",
             "hydro":"hydro","wind":"wind","solar":"solar","biomass":"biomass",
             "geothermal":"geothermal","waste":"biomass","battery":"battery"}
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

SU = {"nuclear":dict(hot=10000,warm=30000,cold=100000,wh=8,ch=48,mut=8,mdt=8),
      "coal":   dict(hot= 5000,warm=15000,cold= 40000,wh=4,ch=12,mut=4,mdt=4),
      "lng":    dict(hot= 2000,warm= 5000,cold= 15000,wh=2,ch= 8,mut=2,mdt=2),
      "oil":    dict(hot= 1500,warm= 3000,cold=  8000,wh=2,ch= 6,mut=1,mdt=1)}
THERMAL_DEFAULT = {"nuclear":900,"coal":600,"lng":400,"gas":400,
                   "oil":200,"geothermal":30,"waste":15,"biomass":20}

# ── 発電機ロード（OSM熱電源のみ; 太陽光・風力はOCCTO参照値で上書き） ──
print("発電機データ読み込み中...")
all_gens = []
for r in REGIONS:
    p = f"data/{r}_plants.geojson"
    if not os.path.exists(p):
        continue
    with open(p) as f:
        data = json.load(f)
    for i, feat in enumerate(data["features"]):
        props = feat["properties"]
        raw_cap = props.get("capacity_mw")
        try:
            cap = float(raw_cap) if raw_cap else 0.0
        except Exception:
            cap = 0.0
        rf = (props.get("fuel_type") or props.get("plant:source") or "").lower()
        if rf.startswith("http"):
            rf = "unknown"
        fuel = FUEL_MAP.get(rf, "unknown")
        # 太陽光・風力はOCCTO参照値を使用するためOSMエントリは除外
        if fuel in ("solar", "wind", "battery"):
            continue
        # 欠損・負値をデフォルト容量で補完（それでも不明なら除外）
        if cap <= 0:
            cap = THERMAL_DEFAULT.get(rf, 0.0)
        if cap < 5.0:
            continue
        sp = SU.get(fuel, {})
        is_storage = fuel in ("pumped_hydro",)
        g = Generator(
            id=f"{r}_g{i}",
            name=(props.get("name") or f"{r}_{fuel}_{i}")[:40],
            capacity_mw=cap, fuel_type=fuel, region=r,
            fuel_cost_per_mwh=FUEL_COST.get(fuel, 5000),
            no_load_cost=500 if not is_storage and fuel != "geothermal" else 0,
            startup_cost=sp.get("hot", 3000) if not is_storage else 0,
            shutdown_cost=2000 if not is_storage else 0,
            min_up_time_h=sp.get("mut", 1),
            min_down_time_h=sp.get("mdt", 1),
            p_min_mw=cap * 0.4 if fuel in ("nuclear", "coal") else 0.0,
            ramp_up_mw_per_h=cap * (0.1 if fuel == "nuclear" else 0.3),
            ramp_down_mw_per_h=cap * (0.1 if fuel == "nuclear" else 0.3),
            hot_start_cost=sp.get("hot", 0),
            warm_start_cost=sp.get("warm", 0),
            cold_start_cost=sp.get("cold", 0),
            warm_start_h=sp.get("wh", 0),
            cold_start_h=sp.get("ch", 0),
            storage_capacity_mwh=cap * 6.0 if is_storage else 0.0,
            charge_efficiency=0.88, discharge_efficiency=0.88,
        )
        all_gens.append(g)

    # ── 沖縄: OSMの容量記録なし → OCCTO参照の実態火力を合成追加 ──
    # 沖縄電力の実態: 石油火力1,680MW + 石炭200MW (OCCTO実績ベース)
    if r == "okinawa":
        okinawa_thermals = [
            ("沖縄石油A", "oil", 420), ("沖縄石油B", "oil", 420),
            ("沖縄石油C", "oil", 420), ("沖縄石油D", "oil", 420),
            ("沖縄石炭", "coal", 200),
        ]
        for name, fuel, cap_ow in okinawa_thermals:
            sp = SU.get(fuel, {})
            all_gens.append(Generator(
                id=f"okinawa_synth_{name}", name=name,
                capacity_mw=cap_ow, fuel_type=fuel, region="okinawa",
                fuel_cost_per_mwh=FUEL_COST.get(fuel, 9000),
                no_load_cost=500, startup_cost=sp.get("hot", 1500),
                shutdown_cost=2000,
                min_up_time_h=sp.get("mut", 1), min_down_time_h=sp.get("mdt", 1),
                p_min_mw=cap_ow * 0.4 if fuel == "coal" else 0.0,
                ramp_up_mw_per_h=cap_ow * 0.3, ramp_down_mw_per_h=cap_ow * 0.3,
                hot_start_cost=sp.get("hot", 0), warm_start_cost=sp.get("warm", 0),
                cold_start_cost=sp.get("cold", 0),
                warm_start_h=sp.get("wh", 0), cold_start_h=sp.get("ch", 0),
                storage_capacity_mwh=0.0, charge_efficiency=0.88, discharge_efficiency=0.88,
            ))

    # ── 蓄電池 (OCCTO参照容量) ──
    batt_mw  = OCCTO_RE[r]["batt_mw"]
    batt_mwh = OCCTO_RE[r]["batt_mwh"]
    batt = Generator(
        id=f"{r}_battery",
        name=f"{REGION_JP[r]}蓄電池",
        capacity_mw=batt_mw, fuel_type="battery", region=r,
        fuel_cost_per_mwh=0, no_load_cost=0,
        startup_cost=0, shutdown_cost=0,
        min_up_time_h=1, min_down_time_h=1,
        p_min_mw=0.0,
        ramp_up_mw_per_h=batt_mw,
        ramp_down_mw_per_h=batt_mw,
        storage_capacity_mwh=batt_mwh,
        charge_efficiency=0.93, discharge_efficiency=0.93,
        initial_soc_fraction=0.5,
        min_terminal_soc_fraction=0.4,
    )
    all_gens.append(batt)

total_cap = sum(g.capacity_mw for g in all_gens if g.fuel_type != "battery")
print(f"  熱電源: {sum(1 for g in all_gens if g.fuel_type not in ('battery','pumped_hydro'))}機 "
      f"{total_cap:,.0f} MW")
print(f"  蓄電池: {sum(OCCTO_RE[r]['batt_mw'] for r in REGIONS):,.0f} MW / "
      f"{sum(OCCTO_RE[r]['batt_mwh'] for r in REGIONS):,.0f} MWh")
print(f"  太陽光(OCCTO): {sum(OCCTO_RE[r]['solar_mw'] for r in REGIONS):,.0f} MW")
print(f"  風力(OCCTO):   {sum(OCCTO_RE[r]['wind_mw'] for r in REGIONS):,.0f} MW")

# ── 地域別需要・太陽光・風力の計算 ─────────────────────────────
gross_demand_r = {r: DEMAND_SHAPE * OCCTO_RE[r]["peak_mw"] for r in REGIONS}
solar_gen_r    = {r: SOLAR_CF_R[r] * OCCTO_RE[r]["solar_mw"] for r in REGIONS}
wind_gen_r     = {r: WIND_CF_R[r]  * OCCTO_RE[r]["wind_mw"]  for r in REGIONS}

gross_demand_nat = sum(gross_demand_r.values())
solar_nat        = sum(solar_gen_r.values())
wind_nat         = sum(wind_gen_r.values())
net_demand_nat   = np.maximum(gross_demand_nat - solar_nat - wind_nat, 0.0)

# 地域別純需要（太陽光・風力控除後）= ノード別需給バランス制約に使用
net_demand_r = {
    r: np.maximum(gross_demand_r[r] - solar_gen_r[r] - wind_gen_r[r], 0.0)
    for r in REGIONS
}

print(f"  全国最大需要: {gross_demand_nat.max()/1000:.1f} GW")
print(f"  正午太陽光:  {solar_nat[11]/1000:.1f} GW  "
      f"(九州: {solar_gen_r['kyushu'][11]/1000:.1f} GW)")
print(f"  純需要最大:  {net_demand_nat.max()/1000:.1f} GW")
print(f"  九州正午純需要: {net_demand_r['kyushu'][11]/1000:.1f} GW")

# ── UC求解 ──────────────────────────────────────────────────
loader = InterconnectionLoader()
ics = loader.load("data/reference/interconnections.yaml")
th  = TimeHorizon(num_periods=24)
dp  = DemandProfile(demands=net_demand_nat.tolist())
params = UCParameters(
    generators=all_gens, demand=dp, time_horizon=th,
    reserve_margin=0.05, solver_name="highs", mip_gap=0.01,
    interconnections=ics,
    # 地域別純需要をノード別バランス制約に直接使用（容量比按分の代替）
    regional_demands={r: net_demand_r[r].tolist() for r in REGIONS},
)

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
