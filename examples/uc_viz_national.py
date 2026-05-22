"""全国UC（757機）高品質可視化 — binary変数・地域別・連系線フロー"""
import os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap
import matplotlib.gridspec as gridspec
from matplotlib import font_manager

font_manager.fontManager.addfont('/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc')
plt.rcParams['font.family'] = 'Hiragino Sans'
plt.rcParams['axes.unicode_minus'] = False

from src.model.generator import Generator
from src.uc.interconnection_loader import InterconnectionLoader
from src.uc.models import DemandProfile, TimeHorizon, UCParameters
from src.uc.solver import solve_uc

REGIONS = ["hokkaido","tohoku","tokyo","chubu","hokuriku",
           "kansai","chugoku","shikoku","kyushu","okinawa"]
REGION_JP = {"hokkaido":"北海道","tohoku":"東北","tokyo":"東京","chubu":"中部",
             "hokuriku":"北陸","kansai":"関西","chugoku":"中国","shikoku":"四国",
             "kyushu":"九州","okinawa":"沖縄"}
DEMAND_SHAPE = np.array([
    0.60,0.57,0.55,0.53,0.55,0.60,
    0.68,0.78,0.87,0.93,0.97,1.00,
    0.99,0.98,0.96,0.93,0.90,0.86,
    0.82,0.78,0.74,0.70,0.66,0.63,
])
FUEL_COST = {"coal":4500,"gas":7000,"lng":7000,"oil":9000,"nuclear":1500,
             "hydro":0,"pumped_hydro":0,"wind":0,"solar":0,"biomass":3000,
             "geothermal":0,"waste":5000,"battery":0,"mixed":5000,"unknown":5000}
FUEL_MAP = {"coal":"coal","gas":"lng","lng":"lng","oil":"oil","nuclear":"nuclear",
            "hydro":"hydro","wind":"wind","solar":"solar","biomass":"biomass",
            "geothermal":"geothermal","waste":"biomass","battery":"pumped_hydro"}
FUEL_COLORS = {"nuclear":"#7B2D8E","coal":"#4A4A4A","lng":"#E8832A",
               "oil":"#C44E52","hydro":"#2196F3","pumped_hydro":"#64B5F6",
               "wind":"#4CAF50","solar":"#FFD700","biomass":"#8BC34A",
               "geothermal":"#FF5722","battery":"#00BCD4","mixed":"#999",
               "unknown":"#CCCCCC"}
FUEL_ORDER = ["nuclear","coal","lng","oil","pumped_hydro","hydro",
              "biomass","geothermal","wind","solar","battery","mixed","unknown"]
FUEL_JP = {"nuclear":"原子力","coal":"石炭","lng":"LNG","oil":"石油",
           "pumped_hydro":"揚水","hydro":"水力","biomass":"バイオ",
           "geothermal":"地熱","wind":"風力","solar":"太陽光",
           "battery":"蓄電池","mixed":"複合","unknown":"不明"}

# ── 発電機ロード（capacity_mw が実存のもののみ、5MW以上） ──────────
print("=== 全国UC 高品質可視化 ===")
print("発電機データ読み込み中（capacity_mw実存のみ）...")
all_gens = []
for region in REGIONS:
    path = f"data/{region}_plants.geojson"
    if not os.path.exists(path): continue
    with open(path) as f: data = json.load(f)
    for i, feat in enumerate(data["features"]):
        props = feat["properties"]
        raw_cap = props.get("capacity_mw")
        try: cap = float(raw_cap) if raw_cap else 0.0
        except: cap = 0.0
        if cap < 5.0:
            # 熱力系は燃料種別でデフォルト補完
            _THERMAL_DEFAULT = {"nuclear":900,"coal":600,"lng":400,"gas":400,
                                 "oil":200,"geothermal":30,"waste":15,"biomass":20}
            raw_fuel_tmp = (props.get("fuel_type") or props.get("plant:source") or "").lower()
            cap = _THERMAL_DEFAULT.get(raw_fuel_tmp, 0.0)
            if cap < 5.0: continue

        raw_fuel = (props.get("fuel_type") or props.get("plant:source") or "unknown").lower()
        if raw_fuel.startswith("http"): raw_fuel = "unknown"
        fuel = FUEL_MAP.get(raw_fuel, "unknown")
        cost = FUEL_COST.get(fuel, 5000)
        name = (props.get("name") or props.get("_display_name") or f"{region}_{fuel}_{i}")[:40]

        # Cold/warm/hot startup parameters by fuel type (¥, hours)
        _SU_PARAMS = {
            "nuclear": dict(hot=10000, warm=30000, cold=100000, warm_h=8,  cold_h=48),
            "coal":    dict(hot= 5000, warm=15000, cold= 40000, warm_h=4,  cold_h=12),
            "lng":     dict(hot= 2000, warm= 5000, cold= 15000, warm_h=2,  cold_h= 8),
            "gas":     dict(hot= 2000, warm= 5000, cold= 15000, warm_h=2,  cold_h= 8),
            "oil":     dict(hot= 1500, warm= 3000, cold=  8000, warm_h=2,  cold_h= 6),
        }
        sp = _SU_PARAMS.get(fuel, {})
        g = Generator(
            id=f"{region}_g{i}", name=name, capacity_mw=cap,
            fuel_type=fuel, region=region,
            startup_cost=0 if fuel in ("wind","solar","hydro") else 5000,
            shutdown_cost=0 if fuel in ("wind","solar","hydro") else 2000,
            min_up_time_h=4 if fuel in ("coal","nuclear") else 2,
            min_down_time_h=4 if fuel in ("coal","nuclear") else 2,
            fuel_cost_per_mwh=cost,
            no_load_cost=0 if fuel in ("wind","solar") else 500,
            ramp_up_mw_per_h=cap * 0.3,
            ramp_down_mw_per_h=cap * 0.3,
            hot_start_cost=sp.get("hot", 0),
            warm_start_cost=sp.get("warm", 0),
            cold_start_cost=sp.get("cold", 0),
            warm_start_h=sp.get("warm_h", 0),
            cold_start_h=sp.get("cold_h", 0),
        )
        all_gens.append(g)

total_cap = sum(g.capacity_mw for g in all_gens)
print(f"  発電機数: {len(all_gens)}, 総容量: {total_cap:,.0f} MW")

demands = (DEMAND_SHAPE * total_cap * 0.65).tolist()

loader = InterconnectionLoader()
ics = loader.load("data/reference/interconnections.yaml")

th = TimeHorizon(num_periods=24, period_duration_h=1.0)
dp = DemandProfile(demands=demands)
params = UCParameters(
    generators=all_gens, demand=dp, time_horizon=th,
    reserve_margin=0.05, solver_name="highs",
    interconnections=ics, mip_gap=0.01,
)

print("UC求解中...")
t0 = time.monotonic()
result = solve_uc(params)
elapsed = time.monotonic() - t0
print(f"  Status: {result.status}, Cost: ¥{result.total_cost:,.0f}, Time: {elapsed:.2f}s")

if not result.is_optimal:
    print("最適解未取得。終了。"); sys.exit(1)

os.makedirs("papers/figs", exist_ok=True)
hours = np.arange(24)
gen_map = {g.id: g for g in all_gens}

# ────────────────────────────────────────────────────────────────────────
# 図A: 地域別×燃料種別 発電スタック（2行×5列）
# ────────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(26, 14), facecolor="white")
gs = gridspec.GridSpec(2, 5, figure=fig, hspace=0.50, wspace=0.08)
axes = [fig.add_subplot(gs[i//5, i%5]) for i in range(10)]

for idx, region in enumerate(REGIONS):
    ax = axes[idx]
    fuel_power = {ft: np.zeros(24) for ft in FUEL_ORDER}
    region_scheds = [s for s in result.schedules if gen_map[s.generator_id].region == region]
    for sched in region_scheds:
        g = gen_map[sched.generator_id]
        ft = g.fuel_type or "unknown"
        if ft not in fuel_power: ft = "unknown"
        fuel_power[ft] += np.array(sched.power_output_mw)

    bottom = np.zeros(24)
    for ft in FUEL_ORDER:
        vals = fuel_power[ft]
        if vals.sum() < 0.5: continue
        ax.fill_between(hours, bottom, bottom + vals,
                        color=FUEL_COLORS[ft], alpha=0.9, linewidth=0)
        bottom += vals

    region_cap = sum(g.capacity_mw for g in all_gens if g.region == region)
    region_demand = np.array(demands) * (region_cap / total_cap)
    ax.plot(hours, region_demand, "k-", lw=2.0, zorder=5, label="需要")
    ax.fill_between(hours, region_demand, bottom,
                    color="gray", alpha=0.15, zorder=4, label="予備力")

    n_committed = sum(1 for s in region_scheds if any(s.commitment))
    ax.set_title(f"{REGION_JP[region]}\n({n_committed}機起動)", fontsize=11, fontweight="bold", pad=3)
    ax.set_xlim(0, 23); ax.set_ylim(bottom=0)
    ax.set_xlabel("時刻 (h)", fontsize=9)
    if idx % 5 == 0: ax.set_ylabel("出力 (MW)", fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)

legend_patches = []
for ft in FUEL_ORDER:
    total_mw = sum(sum(s.power_output_mw) for s in result.schedules
                   if gen_map[s.generator_id].fuel_type == ft)
    if total_mw > 1:
        legend_patches.append(mpatches.Patch(
            color=FUEL_COLORS[ft], label=f"{FUEL_JP.get(ft, ft)}"))
legend_patches += [plt.Line2D([0],[0], color="black", lw=2, label="需要")]

fig.legend(handles=legend_patches, loc="lower center", ncol=7,
           fontsize=11, facecolor="white", edgecolor="gray",
           bbox_to_anchor=(0.5, -0.03), handlelength=2)
fig.suptitle(f"全国Unit Commitment 24時間発電スケジュール\n"
             f"（{len(all_gens)}機・10地域・燃料種別）",
             fontsize=15, fontweight="bold", y=1.02)
plt.savefig("papers/figs/uc_regional_stack.png", dpi=180,
            bbox_inches="tight", facecolor="white")
plt.close()
print("  Saved: uc_regional_stack.png")

# ────────────────────────────────────────────────────────────────────────
# 図B: Binary変数ヒートマップ（発電機×24時間、全機）
# ────────────────────────────────────────────────────────────────────────
def sort_key(sched):
    g = gen_map[sched.generator_id]
    order = {"nuclear":0,"coal":1,"lng":2,"oil":3,"pumped_hydro":4,
             "hydro":5,"biomass":6,"geothermal":7,"wind":8,"solar":9}
    return (order.get(g.fuel_type or "unknown", 10), -g.capacity_mw)

sorted_scheds = sorted(result.schedules, key=sort_key)
n_gen = len(sorted_scheds)

# 負荷率マトリクス
matrix = np.zeros((n_gen, 24))
colors_left = []
for i, sched in enumerate(sorted_scheds):
    g = gen_map[sched.generator_id]
    for t in range(24):
        if sched.commitment[t]:
            lf = sched.power_output_mw[t] / max(g.capacity_mw, 1)
            matrix[i, t] = max(0.05, min(lf, 1.0))  # on=0.05以上で確実に可視
    colors_left.append(FUEL_COLORS.get(g.fuel_type or "unknown", "#ccc"))

cmap_arr = plt.cm.YlOrRd(np.linspace(0, 1, 256))
cmap_arr[0] = [0.92, 0.92, 0.92, 1.0]
custom_cmap = ListedColormap(cmap_arr)

fig_h = max(8, n_gen * 0.08)
fig, ax = plt.subplots(figsize=(20, min(fig_h, 22)), facecolor="white")

im = ax.imshow(matrix, aspect="auto", cmap=custom_cmap, vmin=0, vmax=1,
               interpolation="nearest")

# 燃料種別カラーバー（左端）
for i, c in enumerate(colors_left):
    ax.add_patch(plt.Rectangle((-2.8, i-0.5), 2.2, 1.0, color=c, clip_on=False))

# 燃料境界線
prev_ft = None
for i, sched in enumerate(sorted_scheds):
    ft = gen_map[sched.generator_id].fuel_type
    if ft != prev_ft and i > 0:
        ax.axhline(i-0.5, color="white", lw=1.5, zorder=4)
    prev_ft = ft

ax.set_xticks(np.arange(24))
ax.set_xticklabels([f"{h:02d}" for h in range(24)], fontsize=10)
ax.set_yticks([])
ax.set_xlabel("時刻 (h)", fontsize=13)

# 燃料種別ラベル（左）
fuel_groups = {}
for i, sched in enumerate(sorted_scheds):
    ft = gen_map[sched.generator_id].fuel_type or "unknown"
    if ft not in fuel_groups: fuel_groups[ft] = []
    fuel_groups[ft].append(i)
for ft, idxs in fuel_groups.items():
    mid = (idxs[0] + idxs[-1]) / 2
    ax.text(-4.5, mid, FUEL_JP.get(ft, ft), fontsize=9, va="center",
            fontweight="bold", color=FUEL_COLORS.get(ft, "#333"), clip_on=False)

ax.set_title(f"全国UC バイナリコミットメント＋負荷率ヒートマップ\n"
             f"（{n_gen}機 × 24時間 | 灰色=停止、赤=定格出力）",
             fontsize=14, fontweight="bold")

# 格子線
ax.set_xticks(np.arange(-0.5, 24, 1), minor=True)
ax.set_yticks(np.arange(-0.5, n_gen, 1), minor=True)
ax.grid(which="minor", color="white", lw=0.2, alpha=0.4)
ax.tick_params(which="minor", length=0)

cbar = fig.colorbar(im, ax=ax, shrink=0.5, pad=0.01, fraction=0.015)
cbar.set_label("負荷率 (0=停止, 1=定格)", fontsize=11)
cbar.set_ticks([0, 0.25, 0.5, 0.75, 1.0])
cbar.set_ticklabels(["停止", "25%", "50%", "75%", "定格"])

plt.tight_layout()
plt.savefig("papers/figs/uc_binary_heatmap.png", dpi=160,
            bbox_inches="tight", facecolor="white")
plt.close()
print("  Saved: uc_binary_heatmap.png")

# ────────────────────────────────────────────────────────────────────────
# 図C: 連系線フロー（9リンク × 24時間）
# ────────────────────────────────────────────────────────────────────────
if result.interconnection_flows:
    ic_labels = {
        "hokkaido-tohoku": "北海道↔東北\nHVDC 900 MW",
        "tohoku-tokyo":    "東北↔東京\nAC 5,550 MW",
        "tokyo-chubu":     "東京↔中部\nFC 2,100 MW",
        "chubu-kansai":    "中部↔関西\nAC 2,530 MW",
        "chubu-hokuriku":  "中部↔北陸\nAC 1,900 MW",
        "kansai-chugoku":  "関西↔中国\nAC 4,090 MW",
        "kansai-shikoku":  "関西↔四国\nAC 1,400 MW",
        "chugoku-shikoku": "中国↔四国\nAC 1,200 MW",
        "chugoku-kyushu":  "中国↔九州\nAC 2,780 MW",
    }
    ic_caps = {
        "hokkaido-tohoku":900,"tohoku-tokyo":5550,"tokyo-chubu":2100,
        "chubu-kansai":2530,"chubu-hokuriku":1900,"kansai-chugoku":4090,
        "kansai-shikoku":1400,"chugoku-shikoku":1200,"chugoku-kyushu":2780,
    }

    fig, axes = plt.subplots(3, 3, figsize=(20, 13), facecolor="white")
    axes = axes.flatten()

    for idx, ic_flow in enumerate(result.interconnection_flows[:9]):
        ax = axes[idx]
        ic_id = ic_flow.interconnection_id
        flows = np.array(ic_flow.flow_mw)
        cap = ic_caps.get(ic_id, float(max(abs(flows)) or 1))
        util = abs(flows) / cap * 100

        ax.fill_between(hours, 0, flows, where=flows >= 0,
                        color="#1565C0", alpha=0.75, label="正方向（輸出）")
        ax.fill_between(hours, 0, flows, where=flows < 0,
                        color="#B71C1C", alpha=0.75, label="逆方向（輸入）")
        ax.axhline(cap, color="#FF5722", ls="--", lw=1.5, label=f"容量限界")
        ax.axhline(-cap, color="#FF5722", ls="--", lw=1.5)
        ax.axhline(0, color="black", lw=0.8)

        # 飽和帯を強調
        ax.fill_between(hours, cap*0.95, cap*1.05,
                        color="#FF5722", alpha=0.15, label=None)
        ax.fill_between(hours, -cap*1.05, -cap*0.95,
                        color="#FF5722", alpha=0.15)

        label = ic_labels.get(ic_id, ic_id)
        max_util = float(np.max(util))
        ax.set_title(f"{label}\n最大利用率: {max_util:.0f}%{'  🔴飽和' if max_util >= 99 else ''}",
                     fontsize=10, fontweight="bold")
        ax.set_xlim(0, 23); ax.set_ylim(-cap*1.15, cap*1.15)
        ax.set_xlabel("時刻 (h)", fontsize=8); ax.set_ylabel("MW", fontsize=8)
        ax.tick_params(labelsize=8)
        ax.grid(alpha=0.3); ax.spines["top"].set_visible(False)
        if idx == 0:
            ax.legend(fontsize=8, loc="upper right")

    fig.suptitle("地域間連系線フロー（24時間）— 全9連系線が飽和（利用率100%）",
                 fontsize=14, fontweight="bold")
    plt.tight_layout(pad=1.5)
    plt.savefig("papers/figs/uc_ic_flow.png", dpi=180,
                bbox_inches="tight", facecolor="white")
    plt.close()
    print("  Saved: uc_ic_flow.png")

print(f"\n=== 完了 ===")
print(f"  発電機数: {len(all_gens)}, 総コスト: ¥{result.total_cost:,.0f}")
print(f"  計算時間: {elapsed:.2f}s")
