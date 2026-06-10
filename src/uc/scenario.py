"""全国UCシナリオビルダー — GeoJSON発電所データからUC入力を構築する。

scripts/gen_uc_regional.py のデータロード部を共通化したモジュール。
スクリプト群（ベンチマーク・図生成）が同一のロードロジックを共有することで、
データ品質改善が全スクリプトに一括反映され、KPI計測の物差しが揃う。

設計メモ:
- 太陽光・風力・蓄電池は OSM データを使わず OCCTO 統計ベースの参照容量
  （OCCTO_RE）で表現する（OSM は -1MW 欠損フラグ多数のため）。
- ロード時に重複（osm_id が複数地域スライスに出現）等のデータ品質統計を
  LoadStats として収集する。挙動はオプションで切り替え、デフォルトは
  従来スクリプトと同一（重複を除外しない）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from src.model.generator import Generator
from src.uc.interconnection_loader import InterconnectionLoader
from src.uc.models import DemandProfile, Interconnection, TimeHorizon, UCParameters

REGIONS = [
    "hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
    "kansai", "chugoku", "shikoku", "kyushu", "okinawa",
]

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
    0.60, 0.57, 0.55, 0.53, 0.55, 0.60, 0.68, 0.78,
    0.87, 0.93, 0.97, 1.00, 0.99, 0.98, 0.96, 0.93,
    0.90, 0.86, 0.82, 0.78, 0.74, 0.70, 0.66, 0.63,
])

# ── 太陽光CF: ベース曲線 × 地域別日照倍率 ────────────────────
SOLAR_CF_BASE = np.array([
    0, 0, 0, 0, 0, 0.02, 0.10, 0.25, 0.45, 0.65, 0.80, 0.90,
    0.92, 0.88, 0.78, 0.62, 0.40, 0.18, 0.04, 0, 0, 0, 0, 0,
])
# 年間水平面日射量 (GHI) 比による地域係数
SOLAR_MULT = {
    "hokkaido": 0.83, "tohoku": 0.92, "tokyo": 1.00, "chubu": 1.03,
    "hokuriku": 0.90, "kansai": 1.04, "chugoku": 1.06, "shikoku": 1.06,
    "kyushu": 1.10, "okinawa": 1.13,
}
SOLAR_CF_R = {r: np.minimum(SOLAR_CF_BASE * SOLAR_MULT[r], 1.0) for r in REGIONS}

# ── 風力CF: ベース曲線 × 地域別風況倍率 ──────────────────────
WIND_CF_BASE = np.array([
    0.38, 0.40, 0.41, 0.42, 0.40, 0.38, 0.34, 0.30,
    0.28, 0.27, 0.28, 0.29, 0.30, 0.31, 0.32, 0.33,
    0.35, 0.37, 0.38, 0.39, 0.40, 0.40, 0.39, 0.38,
])
WIND_MULT = {
    "hokkaido": 1.25, "tohoku": 1.20, "tokyo": 0.70, "chubu": 0.85,
    "hokuriku": 0.95, "kansai": 0.80, "chugoku": 0.90, "shikoku": 0.90,
    "kyushu": 1.00, "okinawa": 1.10,
}
WIND_CF_R = {r: WIND_CF_BASE * WIND_MULT[r] for r in REGIONS}

# ── 燃料コスト・分類 ──────────────────────────────────────────
FUEL_COST = {"coal": 4500, "lng": 7000, "oil": 9000, "nuclear": 1500,
             "hydro": 0, "pumped_hydro": 0, "battery": 0,
             "biomass": 3000, "geothermal": 0, "waste": 5000, "unknown": 5000}
FUEL_MAP = {"coal": "coal", "gas": "lng", "lng": "lng", "oil": "oil", "nuclear": "nuclear",
            "hydro": "hydro", "wind": "wind", "solar": "solar", "biomass": "biomass",
            "geothermal": "geothermal", "waste": "biomass", "battery": "battery"}

SU = {"nuclear": dict(hot=10000, warm=30000, cold=100000, wh=8, ch=48, mut=8, mdt=8),
      "coal":    dict(hot=5000,  warm=15000, cold=40000,  wh=4, ch=12, mut=4, mdt=4),
      "lng":     dict(hot=2000,  warm=5000,  cold=15000,  wh=2, ch=8,  mut=2, mdt=2),
      "oil":     dict(hot=1500,  warm=3000,  cold=8000,   wh=2, ch=6,  mut=1, mdt=1)}
THERMAL_DEFAULT = {"nuclear": 900, "coal": 600, "lng": 400, "gas": 400,
                   "oil": 200, "geothermal": 30, "waste": 15, "biomass": 20}

# 容量下限: これ未満の電源はUC対象外（小水力・自家発スケール）
MIN_UNIT_MW = 5.0


@dataclass
class LoadStats:
    """データロード時に収集する品質統計（ベンチマークKPIの素材）。"""

    n_features_scanned: int = 0
    n_thermal_loaded: int = 0
    thermal_capacity_mw: float = 0.0
    n_duplicates: int = 0              # osm_id が既出のエントリ数（除外はしない）
    duplicate_capacity_mw: float = 0.0
    n_capacity_defaulted: int = 0      # 容量欠損を THERMAL_DEFAULT で補完した台数
    n_skipped_small: int = 0           # MIN_UNIT_MW 未満で除外
    n_storage_units: int = 0           # is_storage な発電機（揚水等）
    storage_capacity_mwh: float = 0.0
    fuel_counts: dict = field(default_factory=dict)
    fuel_capacity_mw: dict = field(default_factory=dict)
    osm_id_regions: dict = field(default_factory=dict)  # osm_id -> [出現地域]

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "osm_id_regions"}
        d["n_unique_units"] = self.n_thermal_loaded - self.n_duplicates
        d["unique_capacity_mw"] = self.thermal_capacity_mw - self.duplicate_capacity_mw
        return d


def load_national_thermal_generators(
    data_dir: str = "data",
    stats: Optional[LoadStats] = None,
) -> list[Generator]:
    """GeoJSONから熱電源（太陽光・風力・蓄電池以外）をロードする。

    scripts/gen_uc_regional.py の従来ロジックと同一の挙動:
    - 太陽光・風力・蓄電池は除外（OCCTO参照値で別途表現）
    - 容量欠損・0以下は THERMAL_DEFAULT で補完、それでも MIN_UNIT_MW 未満は除外
    - 沖縄は OSM 容量記録がないため OCCTO 実績ベースの合成火力を追加
    - 揚水は fuel_type='pumped_hydro' のときのみ storage 扱い
      （注: 現状の OSM 抽出に pumped_hydro は存在しない = 既知の精度課題）
    """
    if stats is None:
        stats = LoadStats()
    all_gens: list[Generator] = []

    for r in REGIONS:
        p = os.path.join(data_dir, f"{r}_plants.geojson")
        if not os.path.exists(p):
            continue
        with open(p) as f:
            data = json.load(f)
        for i, feat in enumerate(data["features"]):
            props = feat["properties"]
            stats.n_features_scanned += 1
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
                if cap > 0:
                    stats.n_capacity_defaulted += 1
            if cap < MIN_UNIT_MW:
                stats.n_skipped_small += 1
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
            stats.n_thermal_loaded += 1
            stats.thermal_capacity_mw += cap
            stats.fuel_counts[fuel] = stats.fuel_counts.get(fuel, 0) + 1
            stats.fuel_capacity_mw[fuel] = stats.fuel_capacity_mw.get(fuel, 0.0) + cap
            if g.is_storage:
                stats.n_storage_units += 1
                stats.storage_capacity_mwh += g.storage_capacity_mwh
            oid = props.get("osm_id")
            if oid is not None:
                regs = stats.osm_id_regions.setdefault(oid, [])
                if regs:
                    stats.n_duplicates += 1
                    stats.duplicate_capacity_mw += cap
                regs.append(r)

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
                g = Generator(
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
                    storage_capacity_mwh=0.0,
                    charge_efficiency=0.88, discharge_efficiency=0.88,
                )
                all_gens.append(g)
                stats.n_thermal_loaded += 1
                stats.thermal_capacity_mw += cap_ow
                stats.fuel_counts[fuel] = stats.fuel_counts.get(fuel, 0) + 1
                stats.fuel_capacity_mw[fuel] = stats.fuel_capacity_mw.get(fuel, 0.0) + cap_ow

    return all_gens


def build_battery(region: str) -> Generator:
    """地域集約蓄電池（OCCTO参照容量）を1台のGeneratorとして構築する。"""
    from src.regions import REGION_JA

    batt_mw = OCCTO_RE[region]["batt_mw"]
    batt_mwh = OCCTO_RE[region]["batt_mwh"]
    return Generator(
        id=f"{region}_battery",
        name=f"{REGION_JA[region]}蓄電池",
        capacity_mw=batt_mw, fuel_type="battery", region=region,
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


@dataclass
class NationalScenario:
    """全国24時間UCシナリオ一式（発電機+需要+RE時系列+連系線）。"""

    generators: list[Generator]
    interconnections: list[Interconnection]
    gross_demand_r: dict[str, np.ndarray]
    solar_gen_r: dict[str, np.ndarray]
    wind_gen_r: dict[str, np.ndarray]
    load_stats: LoadStats
    num_periods: int = 24

    @property
    def net_demand_r(self) -> dict[str, np.ndarray]:
        return {
            r: np.maximum(self.gross_demand_r[r] - self.solar_gen_r[r] - self.wind_gen_r[r], 0.0)
            for r in self.gross_demand_r
        }

    @property
    def gross_demand_national(self) -> np.ndarray:
        return sum(self.gross_demand_r.values())

    @property
    def net_demand_national(self) -> np.ndarray:
        solar = sum(self.solar_gen_r.values())
        wind = sum(self.wind_gen_r.values())
        return np.maximum(self.gross_demand_national - solar - wind, 0.0)

    def to_uc_parameters(
        self,
        reserve_margin: float = 0.05,
        mip_gap: float = 0.01,
        solver_name: str = "highs",
    ) -> UCParameters:
        return UCParameters(
            generators=self.generators,
            demand=DemandProfile(demands=self.net_demand_national.tolist()),
            time_horizon=TimeHorizon(num_periods=self.num_periods),
            reserve_margin=reserve_margin,
            solver_name=solver_name,
            mip_gap=mip_gap,
            interconnections=self.interconnections,
            # 地域別純需要をノード別バランス制約に直接使用（容量比按分の代替）
            regional_demands={r: d.tolist() for r, d in self.net_demand_r.items()},
        )


def build_national_scenario(
    data_dir: str = "data",
    interconnections_path: str = "data/reference/interconnections.yaml",
) -> NationalScenario:
    """従来 scripts/gen_uc_regional.py と同一条件の全国24hシナリオを構築する。"""
    stats = LoadStats()
    gens = load_national_thermal_generators(data_dir, stats)
    for r in REGIONS:
        gens.append(build_battery(r))

    ics = InterconnectionLoader().load(interconnections_path)
    gross_demand_r = {r: DEMAND_SHAPE * OCCTO_RE[r]["peak_mw"] for r in REGIONS}
    solar_gen_r = {r: SOLAR_CF_R[r] * OCCTO_RE[r]["solar_mw"] for r in REGIONS}
    wind_gen_r = {r: WIND_CF_R[r] * OCCTO_RE[r]["wind_mw"] for r in REGIONS}

    return NationalScenario(
        generators=gens,
        interconnections=ics,
        gross_demand_r=gross_demand_r,
        solar_gen_r=solar_gen_r,
        wind_gen_r=wind_gen_r,
        load_stats=stats,
    )
