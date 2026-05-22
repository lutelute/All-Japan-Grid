"""
全国783機UC（cold/warm/hot 3状態起動コスト）を実行して
papers/figs/fig_uc_3state.png を生成する
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

REGIONS = ["hokkaido","tohoku","tokyo","chubu","hokuriku",
           "kansai","chugoku","shikoku","kyushu","okinawa"]

DEMAND_SHAPE = np.array([
    0.60,0.57,0.55,0.53,0.55,0.60,
    0.68,0.78,0.87,0.93,0.97,1.00,
    0.99,0.98,0.96,0.93,0.90,0.86,
    0.82,0.78,0.74,0.70,0.66,0.63,
])

FUEL_COST = {"coal":4500,"gas":7000,"lng":7000,"oil":9000,"nuclear":1500,
             "hydro":0,"pumped_hydro":0,"wind":0,"solar":0,"biomass":3000,
             "geothermal":0,"waste":5000,"battery":0,"mixed":5000,"unknown":5000}
FUEL_MAP  = {"coal":"coal","gas":"lng","lng":"lng","oil":"oil","nuclear":"nuclear",
             "hydro":"hydro","wind":"wind","solar":"solar","biomass":"biomass",
             "geothermal":"geothermal","waste":"biomass","battery":"pumped_hydro"}
FUEL_COLORS = {
    "nuclear":"#7B2D8E","coal":"#4A4A4A","lng":"#E8832A","oil":"#C44E52",
    "hydro":"#2196F3","pumped_hydro":"#64B5F6","wind":"#4CAF50","solar":"#FFD700",
    "biomass":"#8BC34A","geothermal":"#FF5722","battery":"#00BCD4",
    "mixed":"#999","unknown":"#CCCCCC",
}
FUEL_ORDER = ["nuclear","coal","lng","oil","pumped_hydro","hydro",
              "biomass","geothermal","wind","solar","battery","mixed","unknown"]
FUEL_JP    = {"nuclear":"原子力","coal":"石炭","lng":"LNG","oil":"石油",
              "pumped_hydro":"揚水","hydro":"水力","biomass":"バイオ",
              "geothermal":"地熱","wind":"風力","solar":"太陽光",
              "battery":"蓄電池","mixed":"複合","unknown":"不明"}

# ── 3状態起動コスト ───────────────────────────────────
SU_PARAMS = {
    "nuclear": dict(hot=10000, warm=30000, cold=100000, warm_h=8,  cold_h=48,
                    mut=8, mdt=8),
    "coal":    dict(hot= 5000, warm=15000, cold= 40000, warm_h=4,  cold_h=12,
                    mut=4, mdt=4),
    "lng":     dict(hot= 2000, warm= 5000, cold= 15000, warm_h=2,  cold_h= 8,
                    mut=2, mdt=2),
    "oil":     dict(hot= 1500, warm= 3000, cold=  8000, warm_h=2,  cold_h= 6,
                    mut=1, mdt=1),
}

# ── 発電機ロード ────────────────────────────────────
print("発電機データ読み込み中...")
all_gens = []
THERMAL_DEFAULT = {"nuclear":900,"coal":600,"lng":400,"gas":400,
                   "oil":200,"geothermal":30,"waste":15,"biomass":20}

for region in REGIONS:
    path = f"data/{region}_plants.geojson"
    if not os.path.exists(path):
        continue
    with open(path) as f:
        data = json.load(f)
    for i, feat in enumerate(data["features"]):
        props = feat["properties"]
        raw_cap = props.get("capacity_mw")
        try:
            cap = float(raw_cap) if raw_cap else 0.0
        except:
            cap = 0.0
        raw_fuel_raw = (props.get("fuel_type") or props.get("plant:source") or "").lower()
        if cap < 5.0:
            cap = THERMAL_DEFAULT.get(raw_fuel_raw, 0.0)
            if cap < 5.0:
                continue
        if raw_fuel_raw.startswith("http"):
            raw_fuel_raw = "unknown"
        fuel = FUEL_MAP.get(raw_fuel_raw, "unknown")
        sp = SU_PARAMS.get(fuel, {})
        name = (props.get("name") or f"{region}_{fuel}_{i}")[:40]

        # 蓄電池（揚水）のSOC設定
        is_storage = fuel == "pumped_hydro"
        stor_cap = cap * 6.0 if is_storage else 0.0   # 6h分

        g = Generator(
            id=f"{region}_g{i}", name=name, capacity_mw=cap,
            fuel_type=fuel, region=region,
            fuel_cost_per_mwh=FUEL_COST.get(fuel, 5000),
            no_load_cost=0 if fuel in ("wind","solar") else 500,
            startup_cost=0 if fuel in ("wind","solar","hydro") else sp.get("hot",5000),
            shutdown_cost=0 if fuel in ("wind","solar","hydro") else 2000,
            min_up_time_h=sp.get("mut", 2),
            min_down_time_h=sp.get("mdt", 2),
            ramp_up_mw_per_h=cap * 0.3,
            ramp_down_mw_per_h=cap * 0.3,
            hot_start_cost=sp.get("hot", 0),
            warm_start_cost=sp.get("warm", 0),
            cold_start_cost=sp.get("cold", 0),
            warm_start_h=sp.get("warm_h", 0),
            cold_start_h=sp.get("cold_h", 0),
            storage_capacity_mwh=stor_cap,
            charge_efficiency=0.88,
            discharge_efficiency=0.88,
        )
        all_gens.append(g)

total_cap = sum(g.capacity_mw for g in all_gens)
n_thermal = sum(1 for g in all_gens if g.has_thermal_startup)
print(f"  発電機数: {len(all_gens)}, 総容量: {total_cap:,.0f} MW, 3状態: {n_thermal}機")

demands = (DEMAND_SHAPE * total_cap * 0.65).tolist()

loader = InterconnectionLoader()
ics = loader.load("data/reference/interconnections.yaml")

th = TimeHorizon(num_periods=24)
dp = DemandProfile(demands=demands)
params = UCParameters(
    generators=all_gens, demand=dp, time_horizon=th,
    reserve_margin=0.05, solver_name="highs", mip_gap=0.01,
    interconnections=ics,
)

print("UC求解中（3状態起動コスト・蓄電池SOC・連系線制約）...")
t0 = time.monotonic()
result = solve_uc(params)
elapsed = time.monotonic() - t0
print(f"  Status: {result.status}, Cost: ¥{result.total_cost:,.0f}, Time: {elapsed:.2f}s")

if not result.is_optimal:
    print("最適解未取得"); sys.exit(1)

# ── 起動種別カウント ─────────────────────────────────
from pulp import value
# y_hot/y_warm/y_cold は solver内で作られるが結果には直接入っていないので
# commitment パターンから cold/warm/hot を推定する

gen_map = {g.id: g for g in all_gens}

def classify_start(g, commitment):
    """commitment[t]から各時刻の起動種別を推定"""
    starts = {"hot":0,"warm":0,"cold":0}
    for t in range(1, len(commitment)):
        if commitment[t] == 1 and commitment[t-1] == 0:
            # 何時間オフだったか遡る
            off_dur = 0
            for s in range(t-1, -1, -1):
                if commitment[s] == 0:
                    off_dur += 1
                else:
                    break
            if g.cold_start_h > 0 and off_dur >= g.cold_start_h:
                starts["cold"] += 1
            elif g.warm_start_h > 0 and off_dur >= g.warm_start_h:
                starts["warm"] += 1
            else:
                starts["hot"] += 1
    return starts

total_starts = {"hot":0,"warm":0,"cold":0}
for s in result.schedules:
    g = gen_map[s.generator_id]
    if not g.has_thermal_startup:
        continue
    sc = classify_start(g, s.commitment)
    for k in sc:
        total_starts[k] += sc[k]

print(f"  起動種別: 熱間={total_starts['hot']}, 温間={total_starts['warm']}, 冷間={total_starts['cold']}")

# ── 可視化：全国24時間発電スタック + 起動種別 ──────────
hours = np.arange(24)
fuel_power = {ft: np.zeros(24) for ft in FUEL_ORDER}
for sched in result.schedules:
    g = gen_map[sched.generator_id]
    ft = g.fuel_type
    if ft not in fuel_power:
        ft = "unknown"
    fuel_power[ft] += np.array(sched.power_output_mw)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5), facecolor="white",
                                 gridspec_kw={"width_ratios":[2,1],"wspace":0.12})

# 左：24時間スタック
bottom = np.zeros(24)
handles = []
for ft in FUEL_ORDER:
    vals = fuel_power[ft]
    if vals.sum() < 1:
        continue
    ax1.bar(hours, vals/1000, bottom=bottom/1000, color=FUEL_COLORS.get(ft,"#ccc"),
            label=FUEL_JP.get(ft,ft), width=0.9, zorder=2)
    bottom += vals
    handles.append(mpatches.Patch(color=FUEL_COLORS.get(ft,"#ccc"), label=FUEL_JP.get(ft,ft)))
ax1.plot(hours, np.array(demands)/1000, "k--", lw=1.5, label="需要", zorder=5)
ax1.set_xlabel("時刻 (h)", fontsize=9)
ax1.set_ylabel("発電量 (GW)", fontsize=9)
ax1.set_title(f"全国24時間発電スタック（{len(all_gens)}機・3状態起動コスト）", fontsize=10)
ax1.legend(handles=handles, fontsize=7, loc="upper left", ncol=3,
           facecolor="white", edgecolor="#bbb")
ax1.grid(axis="y", color="#ddd", lw=0.5)
ax1.set_axisbelow(True)
for sp in ax1.spines.values(): sp.set_color("#ccc")

# 右：起動種別 + コスト内訳
ax2.set_facecolor("white")
labels = ["熱間\n(Hot)", "温間\n(Warm)", "冷間\n(Cold)"]
values = [total_starts["hot"], total_starts["warm"], total_starts["cold"]]
colors = ["#FFA726","#FF7043","#5C6BC0"]
bars = ax2.bar(labels, values, color=colors, width=0.55, zorder=2)
for bar, v in zip(bars, values):
    ax2.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.2, str(v),
             ha="center", va="bottom", fontsize=10, fontweight="bold")
ax2.set_ylabel("起動回数", fontsize=9)
ax2.set_title("起動種別内訳（熱力系のみ）", fontsize=10)
ax2.grid(axis="y", color="#ddd", lw=0.5)
ax2.set_axisbelow(True)
for sp in ax2.spines.values(): sp.set_color("#ccc")

cost_b = result.total_cost / 1e8
plt.suptitle(f"全国UC結果（3状態起動コスト・蓄電池SOC・連系線制約）｜総費用 ¥{cost_b:.2f}億/日｜求解 {elapsed:.1f}s",
             fontsize=9.5, y=1.02)
plt.tight_layout()
out = f"{OUT}/fig_uc_3state.png"
plt.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
plt.close()
print(f"Saved: {out}")
print(f"総費用: ¥{result.total_cost/1e8:.2f}億/日, 求解: {elapsed:.1f}s")
