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
from dataclasses import dataclass, field, replace
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
# 容量欠損時の既定値。計測(2026-06-11)で欠損coal/gas/oilの実態は小規模自家発・
# 産業用IPPが大半と判明したため、火力は自家発スケール(100MW)とする。
# 大規模なのに欠損している例外は data/reference/capacity_patches.yaml で個別補正。
# （旧値 coal600/lng400 は欠損32機で19.2GWの幻容量を生んでいた）
# nuclear は nuclear_status.yaml が容量を上書きするため実質未使用。
THERMAL_DEFAULT = {"nuclear": 900, "coal": 100, "lng": 100, "gas": 100,
                   "oil": 100, "geothermal": 30, "waste": 15, "biomass": 20}

# 容量下限: これ未満の電源はUC対象外（小水力・自家発スケール）
MIN_UNIT_MW = 5.0

# ── 重複帰属解決: operator → 管内（10電力。派生社名は包含一致で判定） ──
OPERATOR_REGION = {
    "北海道電力": "hokkaido", "東北電力": "tohoku", "東京電力": "tokyo",
    "中部電力": "chubu", "北陸電力": "hokuriku", "関西電力": "kansai",
    "中国電力": "chugoku", "四国電力": "shikoku", "九州電力": "kyushu",
    "沖縄電力": "okinawa",
}


def _bbox_inner_margin(lon: float, lat: float, bbox: dict) -> float:
    """Pointがbbox内にあるとき、境界までの最小距離(度)。外なら負値。"""
    return min(
        lat - bbox["lat_min"], bbox["lat_max"] - lat,
        lon - bbox["lon_min"], bbox["lon_max"] - lon,
    )


def _resolve_home_region(props: dict, geometry: Optional[dict],
                         candidates: list[str]) -> str:
    """複数地域スライスに出現した発電所の帰属地域を決める。

    優先順: (1) operatorタグの10電力管内（東京電力→tokyo 等。
    「東京電力リニューアブルパワー」等の派生社名も包含一致で拾う）、
    (2) 発電所Pointのbbox内側マージン最大の地域（境界より奥にある方）、
    (3) 候補の先頭（REGIONS順の初出）。
    """
    operator = props.get("operator") or ""
    for op_name, region in OPERATOR_REGION.items():
        if op_name in operator and region in candidates:
            return region

    if geometry and geometry.get("type") == "Point":
        from src.regions import REGION_BBOX

        lon, lat = geometry["coordinates"][:2]
        best, best_margin = None, float("-inf")
        for r in candidates:
            bbox = REGION_BBOX.get(r)
            if not bbox:
                continue
            margin = _bbox_inner_margin(lon, lat, bbox)
            if margin > best_margin:
                best, best_margin = r, margin
        if best is not None:
            return best

    return candidates[0]


@dataclass
class LoadStats:
    """データロード時に収集する品質統計（ベンチマークKPIの素材）。"""

    dedup_enabled: bool = False
    n_features_scanned: int = 0
    n_thermal_loaded: int = 0          # Generator化された台数（dedup時はユニーク数）
    thermal_capacity_mw: float = 0.0
    n_duplicates: int = 0              # osm_id が既出のコピー数（dedup時は除去数）
    duplicate_capacity_mw: float = 0.0
    n_capacity_defaulted: int = 0      # 容量欠損を THERMAL_DEFAULT で補完した台数
    n_capacity_patched: int = 0        # capacity_patches.yaml で個別補正した台数
    n_skipped_small: int = 0           # MIN_UNIT_MW 未満で除外
    n_storage_units: int = 0           # is_storage な発電機（揚水等）
    storage_capacity_mwh: float = 0.0
    n_pumped_reclassified: int = 0     # 参照リストでhydro→揚水に再分類した台数
    n_pumped_added: int = 0            # 参照リストから新規追加した揚水台数
    pumped_capacity_mw: float = 0.0
    pumped_storage_mwh: float = 0.0
    n_nuclear_available: int = 0       # 稼働断面リストで起動可能とした原発数
    n_nuclear_excluded: int = 0        # 停止・廃炉・建設中として除外した原発数
    nuclear_available_mw: float = 0.0
    nuclear_excluded_mw: float = 0.0
    fuel_counts: dict = field(default_factory=dict)
    fuel_capacity_mw: dict = field(default_factory=dict)
    osm_id_regions: dict = field(default_factory=dict)  # osm_id -> [出現地域]

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "osm_id_regions"}
        if self.dedup_enabled:
            # Generator化済みが既にユニーク
            d["n_unique_units"] = self.n_thermal_loaded
            d["unique_capacity_mw"] = self.thermal_capacity_mw
        else:
            d["n_unique_units"] = self.n_thermal_loaded - self.n_duplicates
            d["unique_capacity_mw"] = self.thermal_capacity_mw - self.duplicate_capacity_mw
        return d


def load_national_thermal_generators(
    data_dir: str = "data",
    stats: Optional[LoadStats] = None,
    dedup: bool = True,
    capacity_patches_path: str = "data/reference/capacity_patches.yaml",
) -> list[Generator]:
    """GeoJSONから熱電源（太陽光・風力・蓄電池以外）をロードする。

    挙動:
    - 太陽光・風力・蓄電池は除外（OCCTO参照値で別途表現）
    - 容量欠損・0以下は THERMAL_DEFAULT で補完、それでも MIN_UNIT_MW 未満は除外
    - 沖縄は OSM 容量記録がないため OCCTO 実績ベースの合成火力を追加
    - 揚水は fuel_type='pumped_hydro' のときのみ storage 扱い
      （注: 現状の OSM 抽出に pumped_hydro は存在しない = 既知の精度課題）
    - dedup=True（デフォルト）: 地域スライスの重なりで複数地域に出現する
      osm_id を1回だけ採用する。帰属は operator→管内 / bbox内側マージンで決定
      （ベースライン計測 2026-06-11: 重複126機39.8GW=熱容量の14.8%が二重計上）。
      dedup=False で従来の二重計上挙動を再現できる。
    """
    if stats is None:
        stats = LoadStats()
    stats.dedup_enabled = dedup
    all_gens: list[Generator] = []

    capacity_patches: list[dict] = []
    if capacity_patches_path and os.path.exists(capacity_patches_path):
        import yaml

        with open(capacity_patches_path) as f:
            capacity_patches = (yaml.safe_load(f) or {}).get("patches", [])

    # パス1: 全スライスを読み、osm_id の出現地域から帰属地域を決める
    region_data: dict[str, dict] = {}
    occurrences: dict = {}  # osm_id -> [(region, props, geometry), ...]
    for r in REGIONS:
        p = os.path.join(data_dir, f"{r}_plants.geojson")
        if not os.path.exists(p):
            continue
        with open(p) as f:
            region_data[r] = json.load(f)
        for feat in region_data[r]["features"]:
            oid = feat["properties"].get("osm_id")
            if oid is not None:
                occurrences.setdefault(oid, []).append(
                    (r, feat["properties"], feat.get("geometry"))
                )
    home_region: dict = {
        oid: _resolve_home_region(occ[0][1], occ[0][2], [r for r, _, _ in occ])
        for oid, occ in occurrences.items()
        if len(occ) > 1
    }

    for r in REGIONS:
        if r not in region_data:
            continue
        data = region_data[r]
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
            # 欠損・負値の補完: 個別パッチ（大規模の例外）→ 燃料別既定値
            if cap <= 0:
                name_for_patch = props.get("name") or ""
                patch = next(
                    (pt for pt in capacity_patches if pt["match"] in name_for_patch),
                    None,
                )
                if patch is not None:
                    cap = float(patch["capacity_mw"])
                    stats.n_capacity_patched += 1
                else:
                    cap = THERMAL_DEFAULT.get(rf, 0.0)
                    if cap > 0:
                        stats.n_capacity_defaulted += 1
            if cap < MIN_UNIT_MW:
                stats.n_skipped_small += 1
                continue
            # 重複帰属の解決（UC入力相当=フィルタ通過コピーのみ統計に計上）
            oid = props.get("osm_id")
            if oid is not None:
                regs = stats.osm_id_regions.setdefault(oid, [])
                if regs:
                    stats.n_duplicates += 1
                    stats.duplicate_capacity_mw += cap
                regs.append(r)
                if dedup and oid in home_region and r != home_region[oid]:
                    continue  # 帰属地域のコピーのみ採用
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


def apply_pumped_storage_reference(
    gens: list[Generator],
    stats: Optional[LoadStats] = None,
    ref_path: str = "data/reference/pumped_storage.yaml",
) -> list[Generator]:
    """揚水参照リストを適用し、揚水をstorage付き電源として正しく表現する。

    背景（ベースライン計測 2026-06-11）: OSM抽出は ``plant:method`` を保持せず、
    揚水が全て一般水力（コスト0・貯水制約なしのフリー電源）に落ちていた。
    その結果 hydroシェア23.6%（実態~8%）の歪みが出ていた。

    処理:
    1) 名前マッチ: 参照エントリ名がhydro発電機名に含まれ、容量比 [0.3, 3.0] の
       範囲なら ``pumped_hydro`` に再分類。容量は参照値（現況出力）で補正
       （例: 葛野川 OSM1600(計画値)→1200(現況)）。regionも参照値を採用。
    2) 不一致の参照エントリは新規追加（OSM容量欠損で除外されていた
       奥多々良木1932MW等の大物がこちら）。
    3) MIN_UNIT_MW未満の参照エントリは追加しない。

    storage_capacity_mwh = capacity_mw × storage_h（既定6h、出典はYAML冒頭）。
    """
    import yaml

    with open(ref_path) as f:
        ref = yaml.safe_load(f)
    defaults = ref.get("defaults", {})
    h_default = float(defaults.get("storage_h", 6))
    eff_c = float(defaults.get("charge_efficiency", 0.84))
    eff_d = float(defaults.get("discharge_efficiency", 0.84))

    out = list(gens)
    hydro_idx = [i for i, g in enumerate(out) if g.fuel_type == "hydro"]
    used: set = set()
    n_re = n_add = 0
    total_mw = total_mwh = 0.0

    for e in sorted(ref["plants"], key=lambda e: -float(e["capacity_mw"])):
        cap = float(e["capacity_mw"])
        mwh = cap * float(e.get("storage_h", h_default))
        storage_kwargs = dict(
            fuel_type="pumped_hydro",
            capacity_mw=cap,
            fuel_cost_per_mwh=0,
            no_load_cost=0,
            startup_cost=0,
            shutdown_cost=0,
            p_min_mw=0.0,
            ramp_up_mw_per_h=cap,
            ramp_down_mw_per_h=cap,
            storage_capacity_mwh=mwh,
            charge_rate_mw=cap,
            discharge_rate_mw=cap,
            charge_efficiency=eff_c,
            discharge_efficiency=eff_d,
            initial_soc_fraction=0.5,
            # 日次定常運用: 初期エネルギーの食い潰しを許さない
            min_terminal_soc_fraction=0.5,
        )
        matched = None
        for i in hydro_idx:
            if i in used:
                continue
            g = out[i]
            if e["name"] in g.name and 0.3 <= (g.capacity_mw / cap) <= 3.0:
                matched = i
                break
        if matched is not None:
            used.add(matched)
            old = out[matched]
            out[matched] = replace(
                old, region=e.get("region", old.region), **storage_kwargs,
            )
            n_re += 1
            if stats is not None:
                stats.thermal_capacity_mw += cap - old.capacity_mw
                stats.fuel_counts["hydro"] = stats.fuel_counts.get("hydro", 1) - 1
                stats.fuel_counts["pumped_hydro"] = stats.fuel_counts.get("pumped_hydro", 0) + 1
                stats.fuel_capacity_mw["hydro"] = (
                    stats.fuel_capacity_mw.get("hydro", 0.0) - old.capacity_mw
                )
                stats.fuel_capacity_mw["pumped_hydro"] = (
                    stats.fuel_capacity_mw.get("pumped_hydro", 0.0) + cap
                )
        elif cap >= MIN_UNIT_MW:
            out.append(Generator(
                id=f"ps_{e['name']}",
                name=f"{e['name']}発電所(揚水)",
                region=e["region"],
                min_up_time_h=1,
                min_down_time_h=1,
                **storage_kwargs,
            ))
            n_add += 1
            if stats is not None:
                stats.n_thermal_loaded += 1
                stats.thermal_capacity_mw += cap
                stats.fuel_counts["pumped_hydro"] = stats.fuel_counts.get("pumped_hydro", 0) + 1
                stats.fuel_capacity_mw["pumped_hydro"] = (
                    stats.fuel_capacity_mw.get("pumped_hydro", 0.0) + cap
                )
        else:
            continue
        total_mw += cap
        total_mwh += mwh

    if stats is not None:
        stats.n_pumped_reclassified = n_re
        stats.n_pumped_added = n_add
        stats.pumped_capacity_mw = total_mw
        stats.pumped_storage_mwh = total_mwh
        stats.n_storage_units = sum(1 for g in out if g.is_storage)
        stats.storage_capacity_mwh = sum(
            g.storage_capacity_mwh for g in out if g.is_storage
        )
    return out


def apply_nuclear_status_reference(
    gens: list[Generator],
    stats: Optional[LoadStats] = None,
    ref_path: str = "data/reference/nuclear_status.yaml",
) -> list[Generator]:
    """原子力稼働状態リスト(data/reference/nuclear_status.yaml)を適用する。

    背景（ベースライン計測 2026-06-11）: OSM原子力21エントリ31.8GWには廃炉済み
    （福島第二・もんじゅ等）や長期停止中（柏崎刈羽・浜岡等）が含まれ全数起動
    可能扱い → nuclearシェア23%超（実態~9%）の歪み。

    処理:
    - operational に名前マッチ → 容量を稼働可能容量に補正（例: 川内900→1780）
    - マッチしない原子力 → 除外（停止・廃炉・建設中）
    - OSM側に無い operational エントリ → 追加
    """
    import yaml

    with open(ref_path) as f:
        ref = yaml.safe_load(f)
    entries = list(ref.get("operational", []))

    out: list[Generator] = []
    matched_entries: set = set()
    n_avail = n_excl = 0
    mw_avail = mw_excl = 0.0

    for g in gens:
        if g.fuel_type != "nuclear":
            out.append(g)
            continue
        entry = next(
            (e for e in entries
             if e["name"] in g.name and id(e) not in matched_entries),
            None,
        )
        if entry is None:
            n_excl += 1
            mw_excl += g.capacity_mw
            if stats is not None:
                stats.n_thermal_loaded -= 1
                stats.thermal_capacity_mw -= g.capacity_mw
                stats.fuel_counts["nuclear"] = stats.fuel_counts.get("nuclear", 1) - 1
                stats.fuel_capacity_mw["nuclear"] = (
                    stats.fuel_capacity_mw.get("nuclear", 0.0) - g.capacity_mw
                )
            continue
        matched_entries.add(id(entry))
        cap = float(entry["capacity_mw"])
        if stats is not None:
            stats.thermal_capacity_mw += cap - g.capacity_mw
            stats.fuel_capacity_mw["nuclear"] = (
                stats.fuel_capacity_mw.get("nuclear", 0.0) + cap - g.capacity_mw
            )
        out.append(replace(
            g,
            capacity_mw=cap,
            region=entry.get("region", g.region),
            p_min_mw=cap * 0.4,
            ramp_up_mw_per_h=cap * 0.1,
            ramp_down_mw_per_h=cap * 0.1,
        ))
        n_avail += 1
        mw_avail += cap

    # OSMに存在しない稼働炉を追加
    sp = SU["nuclear"]
    for e in entries:
        if id(e) in matched_entries:
            continue
        cap = float(e["capacity_mw"])
        out.append(Generator(
            id=f"nuc_{e['name']}",
            name=f"{e['name']}原子力発電所",
            capacity_mw=cap, fuel_type="nuclear", region=e["region"],
            fuel_cost_per_mwh=FUEL_COST["nuclear"],
            no_load_cost=500,
            startup_cost=sp["hot"], shutdown_cost=2000,
            min_up_time_h=sp["mut"], min_down_time_h=sp["mdt"],
            p_min_mw=cap * 0.4,
            ramp_up_mw_per_h=cap * 0.1, ramp_down_mw_per_h=cap * 0.1,
            hot_start_cost=sp["hot"], warm_start_cost=sp["warm"],
            cold_start_cost=sp["cold"],
            warm_start_h=sp["wh"], cold_start_h=sp["ch"],
            storage_capacity_mwh=0.0,
            charge_efficiency=0.88, discharge_efficiency=0.88,
        ))
        n_avail += 1
        mw_avail += cap
        if stats is not None:
            stats.n_thermal_loaded += 1
            stats.thermal_capacity_mw += cap
            stats.fuel_counts["nuclear"] = stats.fuel_counts.get("nuclear", 0) + 1
            stats.fuel_capacity_mw["nuclear"] = (
                stats.fuel_capacity_mw.get("nuclear", 0.0) + cap
            )

    if stats is not None:
        stats.n_nuclear_available = n_avail
        stats.n_nuclear_excluded = n_excl
        stats.nuclear_available_mw = mw_avail
        stats.nuclear_excluded_mw = mw_excl
    return out


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
    dedup: bool = True,
    pumped_storage: bool = True,
    pumped_storage_path: str = "data/reference/pumped_storage.yaml",
    nuclear_status: bool = True,
    nuclear_status_path: str = "data/reference/nuclear_status.yaml",
) -> NationalScenario:
    """全国24hシナリオを構築する（需要・RE条件は gen_uc_regional.py 互換）。"""
    stats = LoadStats()
    gens = load_national_thermal_generators(data_dir, stats, dedup=dedup)
    if pumped_storage and os.path.exists(pumped_storage_path):
        gens = apply_pumped_storage_reference(gens, stats, pumped_storage_path)
    if nuclear_status and os.path.exists(nuclear_status_path):
        gens = apply_nuclear_status_reference(gens, stats, nuclear_status_path)
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
