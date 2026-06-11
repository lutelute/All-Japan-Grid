"""全国UCシナリオビルダー — シナリオ定義に基づきGeoJSONからUC入力を構築する。

設計原則（2026-06-11 オーナー指示「発電機の選定はシナリオ依存」）:
- **シナリオ = 第一級概念**。需要・RE容量・燃料コスト・起動費・容量既定値・
  発電機可用性（原子力断面・揚水・容量パッチ）の年度断面パッケージ。
- 正本は git 追跡の ``config/uc_scenarios/{name}.yaml``。
  ``load_scenario_config("fy2023")`` で読み、全ビルド関数が config 駆動で動く。
- 新断面（fy2024・将来計画）は YAML を複製して調整するだけで切り替わる。
- DB（grid.db の uc_scenarios / uc_scenario_generators）へは
  ``scripts/db/ingest_uc_scenarios.py`` で機械的に同期する（実行時ビュー）。

データ品質処理（計測ベース、docs/reports/uc_benchmark_*_2026-06-11.json）:
- osm_id 重複の帰属解決（地域スライス重なりの二重計上 126機39.8GW を除去）
- 揚水の storage 化（OSM は plant:method を保持せず全揚水が フリー水力だった）
- 原子力の年度断面適用（廃炉・停止中を除外）
- 容量欠損の較正（既定値=自家発スケール + 大規模例外の個別パッチ）
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional, Union

import numpy as np

from src.model.generator import Generator
from src.regions import REGIONS
from src.uc.interconnection_loader import InterconnectionLoader
from src.uc.models import DemandProfile, Interconnection, TimeHorizon, UCParameters

_REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = _REPO_ROOT / "config" / "uc_scenarios"
DEFAULT_SCENARIO = "fy2023"

# ── シナリオ非依存の定数 ──────────────────────────────────────
# OSM燃料タグの正規化（タグ体系の事実であり断面に依らない）
FUEL_MAP = {"coal": "coal", "gas": "lng", "lng": "lng", "oil": "oil", "nuclear": "nuclear",
            "hydro": "hydro", "wind": "wind", "solar": "solar", "biomass": "biomass",
            "geothermal": "geothermal", "waste": "biomass", "battery": "battery"}

# 容量下限: これ未満の電源はUC対象外（小水力・自家発スケール）
MIN_UNIT_MW = 5.0

# ── 重複帰属解決: operator → 管内（10電力。派生社名は包含一致で判定） ──
OPERATOR_REGION = {
    "北海道電力": "hokkaido", "東北電力": "tohoku", "東京電力": "tokyo",
    "中部電力": "chubu", "北陸電力": "hokuriku", "関西電力": "kansai",
    "中国電力": "chugoku", "四国電力": "shikoku", "九州電力": "kyushu",
    "沖縄電力": "okinawa",
}


# ── シナリオ設定 ──────────────────────────────────────────────
@dataclass
class UCScenarioConfig:
    """UCシナリオ定義（config/uc_scenarios/*.yaml の型付きビュー）。"""

    name: str
    fiscal_year: Optional[int]
    description: str
    demand_shape: np.ndarray                 # (24,) ピーク=1.0
    regional_peak_mw: dict[str, float]
    solar_capacity_mw: dict[str, float]
    solar_cf_base: np.ndarray
    solar_multiplier: dict[str, float]
    wind_capacity_mw: dict[str, float]
    wind_cf_base: np.ndarray
    wind_multiplier: dict[str, float]
    battery: dict[str, dict]                 # region -> {mw, mwh}
    fuel_costs: dict[str, float]
    startup_profiles: dict[str, dict]        # 内部形式 hot/warm/cold/wh/ch/mut/mdt
    capacity_defaults: dict[str, float]
    reference_paths: dict[str, str]
    # 中小水力 run-of-river（OSMモデル外の一般水力をsolar/windと同じ
    # 控除方式で表現。容量空なら無効 — fy2023r2以降の較正シナリオで使用）
    hydro_ror_capacity_mw: dict[str, float] = field(default_factory=dict)
    hydro_ror_cf_base: Optional[np.ndarray] = None
    hydro_ror_multiplier: dict[str, float] = field(default_factory=dict)
    annual: dict = field(default_factory=dict)  # 月別係数（8760h合成用）
    raw: dict = field(repr=False, default_factory=dict)  # 元YAML（DB ingest用）

    @property
    def solar_cf_r(self) -> dict[str, np.ndarray]:
        return {
            r: np.minimum(self.solar_cf_base * self.solar_multiplier[r], 1.0)
            for r in self.solar_multiplier
        }

    @property
    def wind_cf_r(self) -> dict[str, np.ndarray]:
        return {r: self.wind_cf_base * self.wind_multiplier[r]
                for r in self.wind_multiplier}

    @property
    def hydro_ror_cf_r(self) -> dict[str, np.ndarray]:
        if self.hydro_ror_cf_base is None:
            return {}
        return {
            r: self.hydro_ror_cf_base * self.hydro_ror_multiplier.get(r, 1.0)
            for r in self.hydro_ror_capacity_mw
        }

    def reference_path(self, key: str) -> Optional[str]:
        p = self.reference_paths.get(key)
        return str(p) if p else None


def load_scenario_config(
    scenario: Union[str, Path, UCScenarioConfig, None] = None,
) -> UCScenarioConfig:
    """シナリオ定義をロードする。

    Args:
        scenario: シナリオ名（``config/uc_scenarios/{name}.yaml`` を解決）、
            YAMLへのパス、ロード済み ``UCScenarioConfig``（パススルー）、
            または None（既定 ``fy2023``）。
    """
    if isinstance(scenario, UCScenarioConfig):
        return scenario
    name = scenario or DEFAULT_SCENARIO

    path = Path(name)
    if not path.suffix:  # 名前 → 標準ディレクトリ
        path = SCENARIO_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"UC scenario not found: {path}"
            f" (known: {sorted(p.stem for p in SCENARIO_DIR.glob('*.yaml'))})"
        )

    import yaml

    with open(path) as f:
        raw = yaml.safe_load(f)

    meta = raw.get("meta", {})
    demand = raw["demand"]
    solar = raw["renewables"]["solar"]
    wind = raw["renewables"]["wind"]
    hydro_ror = raw["renewables"].get("hydro_ror") or {}

    # 起動費プロファイル: YAMLの読みやすいキー → 内部短縮キー
    su: dict[str, dict] = {}
    for fuel, p in (raw.get("startup_profiles") or {}).items():
        su[fuel] = dict(
            hot=p["hot"], warm=p["warm"], cold=p["cold"],
            wh=p["warm_start_h"], ch=p["cold_start_h"],
            mut=p["min_up_h"], mdt=p["min_down_h"],
        )

    return UCScenarioConfig(
        name=meta.get("name", path.stem),
        fiscal_year=meta.get("fiscal_year"),
        description=meta.get("description", ""),
        demand_shape=np.asarray(demand["shape_24h"], dtype=float),
        regional_peak_mw={k: float(v) for k, v in demand["regional_peak_mw"].items()},
        solar_capacity_mw={k: float(v) for k, v in solar["capacity_mw"].items()},
        solar_cf_base=np.asarray(solar["cf_base_24h"], dtype=float),
        solar_multiplier={k: float(v) for k, v in solar["regional_multiplier"].items()},
        wind_capacity_mw={k: float(v) for k, v in wind["capacity_mw"].items()},
        wind_cf_base=np.asarray(wind["cf_base_24h"], dtype=float),
        wind_multiplier={k: float(v) for k, v in wind["regional_multiplier"].items()},
        battery=dict(raw.get("battery") or {}),
        fuel_costs={k: float(v) for k, v in (raw.get("fuel_costs_per_mwh") or {}).items()},
        startup_profiles=su,
        capacity_defaults={k: float(v) for k, v in (raw.get("capacity_defaults_mw") or {}).items()},
        reference_paths=dict(raw.get("references") or {}),
        hydro_ror_capacity_mw={
            k: float(v) for k, v in (hydro_ror.get("capacity_mw") or {}).items()
        },
        hydro_ror_cf_base=(
            np.asarray(hydro_ror["cf_base_24h"], dtype=float)
            if hydro_ror.get("cf_base_24h") else None
        ),
        hydro_ror_multiplier={
            k: float(v)
            for k, v in (hydro_ror.get("regional_multiplier") or {}).items()
        },
        annual=dict(raw.get("annual") or {}),
        raw=raw,
    )


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
    n_capacity_defaulted: int = 0      # 容量欠損を capacity_defaults で補完した台数
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
    capacity_patches_path: Optional[str] = None,
    config: Optional[UCScenarioConfig] = None,
) -> list[Generator]:
    """GeoJSONから熱電源（太陽光・風力・蓄電池以外）をロードする。

    挙動:
    - 太陽光・風力・蓄電池は除外（シナリオの参照容量で別途表現）
    - 容量欠損・0以下は個別パッチ → capacity_defaults で補完、
      それでも MIN_UNIT_MW 未満は除外
    - 沖縄は OSM 容量記録がないため OCCTO 実績ベースの合成火力を追加
    - dedup=True（デフォルト）: 地域スライスの重なりで複数地域に出現する
      osm_id を1回だけ採用する。帰属は operator→管内 / bbox内側マージンで決定
      （ベースライン計測 2026-06-11: 重複126機39.8GW=熱容量の14.8%が二重計上）。
      dedup=False で従来の二重計上挙動を再現できる。
    """
    config = load_scenario_config(config)
    fuel_cost = config.fuel_costs
    su_profiles = config.startup_profiles
    capacity_defaults = config.capacity_defaults

    if stats is None:
        stats = LoadStats()
    stats.dedup_enabled = dedup
    all_gens: list[Generator] = []

    patches_path = capacity_patches_path or config.reference_path("capacity_patches")
    capacity_patches: list[dict] = []
    if patches_path and os.path.exists(patches_path):
        import yaml

        with open(patches_path) as f:
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
            # 太陽光・風力はシナリオ参照値を使用するためOSMエントリは除外
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
                    cap = capacity_defaults.get(rf, 0.0)
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
            sp = su_profiles.get(fuel, {})
            is_storage = fuel in ("pumped_hydro",)
            g = Generator(
                id=f"{r}_g{i}",
                name=(props.get("name") or f"{r}_{fuel}_{i}")[:40],
                capacity_mw=cap, fuel_type=fuel, region=r,
                fuel_cost_per_mwh=fuel_cost.get(fuel, 5000),
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
                sp = su_profiles.get(fuel, {})
                g = Generator(
                    id=f"okinawa_synth_{name}", name=name,
                    capacity_mw=cap_ow, fuel_type=fuel, region="okinawa",
                    fuel_cost_per_mwh=fuel_cost.get(fuel, 9000),
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
    ref_path: Optional[str] = None,
    config: Optional[UCScenarioConfig] = None,
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

    if ref_path is None:
        config = load_scenario_config(config)
        ref_path = config.reference_path("pumped_storage")
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
    ref_path: Optional[str] = None,
    config: Optional[UCScenarioConfig] = None,
) -> list[Generator]:
    """原子力稼働状態リストを適用する（シナリオの年度断面）。

    背景（ベースライン計測 2026-06-11）: OSM原子力21エントリ31.8GWには廃炉済み
    （福島第二・もんじゅ等）や長期停止中（柏崎刈羽・浜岡等）が含まれ全数起動
    可能扱い → nuclearシェア23%超（実態~9%）の歪み。

    処理:
    - operational に名前マッチ → 容量を稼働可能容量に補正（例: 川内900→1780）
    - マッチしない原子力 → 除外（停止・廃炉・建設中）
    - OSM側に無い operational エントリ → 追加
    """
    import yaml

    config = load_scenario_config(config)
    if ref_path is None:
        ref_path = config.reference_path("nuclear_status")
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
    sp = config.startup_profiles.get("nuclear", {})
    for e in entries:
        if id(e) in matched_entries:
            continue
        cap = float(e["capacity_mw"])
        out.append(Generator(
            id=f"nuc_{e['name']}",
            name=f"{e['name']}原子力発電所",
            capacity_mw=cap, fuel_type="nuclear", region=e["region"],
            fuel_cost_per_mwh=config.fuel_costs.get("nuclear", 1500),
            no_load_cost=500,
            startup_cost=sp.get("hot", 10000), shutdown_cost=2000,
            min_up_time_h=sp.get("mut", 8), min_down_time_h=sp.get("mdt", 8),
            p_min_mw=cap * 0.4,
            ramp_up_mw_per_h=cap * 0.1, ramp_down_mw_per_h=cap * 0.1,
            hot_start_cost=sp.get("hot", 10000), warm_start_cost=sp.get("warm", 30000),
            cold_start_cost=sp.get("cold", 100000),
            warm_start_h=sp.get("wh", 8), cold_start_h=sp.get("ch", 48),
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


def synthesize_maintenance(
    gens: list[Generator],
    config: Optional[UCScenarioConfig] = None,
) -> list[Generator]:
    """定期検査・計画停止を決定論的に合成する（年間運用用）。

    シナリオの ``maintenance`` セクション（fuel別duration週・配置候補週）に
    基づき、対象燃料の各機に年1回の連続停止窓 ``(start_h, end_h)`` を付与する。

    配置は **(地域×燃料) グループ内で容量降順の輪番** — 実務の定検計画の
    平準化に相当し、同一地域の大容量機が同時に停止する事態を構造的に避ける
    （md5独立配置は秋の集中期に偶然の同時停止で infeasible を起こした、
    2026-06-11 r4 計測）。ソート+剰余のみで**乱数を使わない**ため、同じ
    シナリオ+同じ発電機集合なら常に同じ計画になる（再現性担保）。

    原子力は ``placement_weeks_nuclear``（あれば）の専用スロットを使う。
    24h断面（ベンチマーク）はメンテ窓の外なので影響しない。
    経済停止はモデル外（正直な残差として開示）。
    """
    from collections import defaultdict

    config = load_scenario_config(config)
    spec = (config.raw or {}).get("maintenance")
    if not spec:
        return gens
    weeks = list(spec.get("placement_weeks", []))
    weeks_nuclear = list(spec.get("placement_weeks_nuclear", weeks))
    durations = {k: int(v) for k, v in
                 (spec.get("duration_weeks_by_fuel") or {}).items()}
    if not weeks or not durations:
        return gens

    # ── 地域別の同時停止容量上限つきグリーディ配置 ──
    # 輪番だけではスロット間隔(1週) < duration(4-5週) のため隣接配置機が
    # 重なり、小地域（北陸: 域内2.9GW / 沖縄: 連系ゼロ）の供給力を割って
    # infeasible になる（2026-06-11 r6スモーク診断で実測）。週ごとの地域
    # 停止容量を追跡し、上限（域内容量×fraction）を超える配置はスロットを
    # ずらす。どのスロットにも収まらない機はメンテなし（skip、開示）。
    frac = float(spec.get("max_concurrent_outage_fraction", 0.25))
    cap_total: dict = defaultdict(float)
    for g in gens:
        cap_total[g.region] += g.capacity_mw
    limit = {r: c * frac for r, c in cap_total.items()}
    outage: dict = defaultdict(lambda: defaultdict(float))

    def _fits(g: Generator, week: int, dur: int) -> bool:
        return all(
            outage[g.region][wk] + g.capacity_mw <= limit[g.region]
            for wk in range(week, week + dur)
        )

    # 原子力（最長duration・最大単機容量）を先に、次いで火力を容量降順で
    targets = sorted(
        (g for g in gens if g.fuel_type in durations),
        key=lambda g: (0 if g.fuel_type == "nuclear" else 1,
                       -g.capacity_mw, g.id),
    )
    rr_index: dict = defaultdict(int)  # (region, fuel) -> 次に試すスロット
    start_week_of: dict = {}
    n_skipped = 0
    for g in targets:
        wlist = weeks_nuclear if g.fuel_type == "nuclear" else weeks
        dur = durations[g.fuel_type]
        key = (g.region, g.fuel_type)
        placed = None
        for k in range(len(wlist)):
            w = wlist[(rr_index[key] + k) % len(wlist)]
            if _fits(g, w, dur):
                placed = w
                rr_index[key] = (rr_index[key] + k + 1) % len(wlist)
                break
        if placed is None:
            n_skipped += 1  # 上限内に収まらない: メンテなしで稼働継続（開示）
            continue
        start_week_of[g.id] = placed
        for wk in range(placed, placed + dur):
            outage[g.region][wk] += g.capacity_mw

    out = []
    for g in gens:
        if g.id not in start_week_of:
            out.append(g)
            continue
        start_h = start_week_of[g.id] * 7 * 24
        end_h = start_h + durations[g.fuel_type] * 7 * 24
        out.append(replace(
            g, maintenance_windows=[(start_h, min(end_h, 8760))],
        ))
    return out


def build_battery(
    region: str,
    config: Optional[UCScenarioConfig] = None,
) -> Generator:
    """地域集約蓄電池（シナリオ参照容量）を1台のGeneratorとして構築する。"""
    from src.regions import REGION_JA

    config = load_scenario_config(config)
    spec = config.battery[region]
    batt_mw = float(spec["mw"])
    batt_mwh = float(spec["mwh"])
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
    config: Optional[UCScenarioConfig] = None
    hydro_ror_gen_r: dict[str, np.ndarray] = field(default_factory=dict)
    num_periods: int = 24

    def _deduction(self, r: str) -> np.ndarray:
        d = self.solar_gen_r[r] + self.wind_gen_r[r]
        if r in self.hydro_ror_gen_r:
            d = d + self.hydro_ror_gen_r[r]
        return d

    @property
    def net_demand_r(self) -> dict[str, np.ndarray]:
        return {
            r: np.maximum(self.gross_demand_r[r] - self._deduction(r), 0.0)
            for r in self.gross_demand_r
        }

    @property
    def gross_demand_national(self) -> np.ndarray:
        return sum(self.gross_demand_r.values())

    @property
    def net_demand_national(self) -> np.ndarray:
        ded = sum(self._deduction(r) for r in self.gross_demand_r)
        return np.maximum(self.gross_demand_national - ded, 0.0)

    def to_uc_parameters(
        self,
        reserve_margin: float = 0.05,
        mip_gap: float = 0.01,
        solver_name: str = "highs",
        extract_duals: bool = False,
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
            extract_duals=extract_duals,
        )


_DAYS_PER_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


@dataclass
class AnnualProfiles:
    """年間時系列（地域別 需要・太陽光・風力・中小水力、各 (hours,) 配列）。"""

    gross_demand_r: dict[str, np.ndarray]
    solar_gen_r: dict[str, np.ndarray]
    wind_gen_r: dict[str, np.ndarray]
    hydro_ror_gen_r: dict[str, np.ndarray] = field(default_factory=dict)
    hours: int = 8760

    def _deduction(self, r: str) -> np.ndarray:
        d = self.solar_gen_r[r] + self.wind_gen_r[r]
        if r in self.hydro_ror_gen_r:
            d = d + self.hydro_ror_gen_r[r]
        return d

    @property
    def net_demand_r(self) -> dict[str, np.ndarray]:
        return {
            r: np.maximum(self.gross_demand_r[r] - self._deduction(r), 0.0)
            for r in self.gross_demand_r
        }

    @property
    def net_demand_national(self) -> np.ndarray:
        gross = sum(self.gross_demand_r.values())
        ded = sum(self._deduction(r) for r in self.gross_demand_r)
        return np.maximum(gross - ded, 0.0)


def build_annual_profiles(
    config: Optional[UCScenarioConfig] = None,
    days: int = 365,
) -> AnnualProfiles:
    """合成年間時系列を構築する（月別係数 × 24h形状）。

    シナリオの ``annual`` セクション（月別係数）と既存の24h形状・地域容量
    から 365日×24h=8760h（``days`` 指定で短縮可、ローカル検証用）の
    需要・太陽光・風力プロファイルを合成する。

    近似であることを明示した Phase 1 実装（機構検証用）。
    OCCTOエリア需給実績（30分値）による実測置換は Phase 2。
    """
    config = load_scenario_config(config)
    ann = config.annual
    if not ann:
        raise ValueError(
            f"scenario '{config.name}' has no 'annual' section "
            "(monthly multipliers required for 8760h synthesis)"
        )
    dm = [float(x) for x in ann["demand_month_mult"]]
    sm = [float(x) for x in ann["solar_month_mult"]]
    wm = [float(x) for x in ann["wind_month_mult"]]
    rm = [float(x) for x in ann.get("hydro_ror_month_mult", [1.0] * 12)]

    # 各日の月indexを並べる（365日、閏日なし）
    month_of_day: list[int] = []
    for m, ndays in enumerate(_DAYS_PER_MONTH):
        month_of_day.extend([m] * ndays)
    month_of_day = month_of_day[:days]
    n_hours = len(month_of_day) * 24

    demand_mult = np.repeat([dm[m] for m in month_of_day], 24)
    solar_mult = np.repeat([sm[m] for m in month_of_day], 24)
    wind_mult = np.repeat([wm[m] for m in month_of_day], 24)
    ror_mult = np.repeat([rm[m] for m in month_of_day], 24)

    n_days = len(month_of_day)
    shape = np.tile(config.demand_shape, n_days)
    solar_cf_r = config.solar_cf_r
    wind_cf_r = config.wind_cf_r
    ror_cf_r = config.hydro_ror_cf_r

    gross_demand_r = {
        r: shape * demand_mult * config.regional_peak_mw[r] for r in REGIONS
    }
    solar_gen_r = {
        r: np.minimum(np.tile(solar_cf_r[r], n_days) * solar_mult, 1.0)
        * config.solar_capacity_mw[r]
        for r in REGIONS
    }
    wind_gen_r = {
        r: np.minimum(np.tile(wind_cf_r[r], n_days) * wind_mult, 1.0)
        * config.wind_capacity_mw[r]
        for r in REGIONS
    }
    hydro_ror_gen_r = {
        r: np.tile(ror_cf_r[r], n_days) * ror_mult
        * config.hydro_ror_capacity_mw[r]
        for r in config.hydro_ror_capacity_mw
        if r in ror_cf_r
    }
    return AnnualProfiles(
        gross_demand_r=gross_demand_r,
        solar_gen_r=solar_gen_r,
        wind_gen_r=wind_gen_r,
        hydro_ror_gen_r=hydro_ror_gen_r,
        hours=n_hours,
    )


def build_national_scenario(
    scenario: Union[str, Path, UCScenarioConfig, None] = None,
    data_dir: str = "data",
    interconnections_path: str = "data/reference/interconnections.yaml",
    dedup: bool = True,
    pumped_storage: bool = True,
    pumped_storage_path: Optional[str] = None,
    nuclear_status: bool = True,
    nuclear_status_path: Optional[str] = None,
) -> NationalScenario:
    """シナリオ定義に基づき全国24h UCシナリオを構築する。

    Args:
        scenario: シナリオ名（既定 fy2023）/ YAMLパス / ロード済みconfig。
        pumped_storage / nuclear_status: 参照リスト適用のon/off
            （off は比較計測・ベースライン再現用）。
        *_path: 参照リストの明示パス（既定はシナリオの references）。
    """
    config = load_scenario_config(scenario)
    stats = LoadStats()
    gens = load_national_thermal_generators(
        data_dir, stats, dedup=dedup, config=config,
    )
    ps_path = pumped_storage_path or config.reference_path("pumped_storage")
    if pumped_storage and ps_path and os.path.exists(ps_path):
        gens = apply_pumped_storage_reference(gens, stats, ps_path, config=config)
    ns_path = nuclear_status_path or config.reference_path("nuclear_status")
    if nuclear_status and ns_path and os.path.exists(ns_path):
        gens = apply_nuclear_status_reference(gens, stats, ns_path, config=config)
    # 定検・計画停止の決定論的合成（maintenanceセクションがある場合のみ。
    # 24h断面は春秋のメンテ窓外なので影響しない）
    gens = synthesize_maintenance(gens, config)
    for r in REGIONS:
        gens.append(build_battery(r, config=config))

    ics = InterconnectionLoader().load(interconnections_path)
    gross_demand_r = {
        r: config.demand_shape * config.regional_peak_mw[r] for r in REGIONS
    }
    solar_cf_r = config.solar_cf_r
    wind_cf_r = config.wind_cf_r
    solar_gen_r = {
        r: solar_cf_r[r] * config.solar_capacity_mw[r] for r in REGIONS
    }
    wind_gen_r = {
        r: wind_cf_r[r] * config.wind_capacity_mw[r] for r in REGIONS
    }
    ror_cf_r = config.hydro_ror_cf_r
    hydro_ror_gen_r = {
        r: ror_cf_r[r] * config.hydro_ror_capacity_mw[r]
        for r in config.hydro_ror_capacity_mw
        if r in ror_cf_r
    }

    return NationalScenario(
        generators=gens,
        interconnections=ics,
        gross_demand_r=gross_demand_r,
        solar_gen_r=solar_gen_r,
        wind_gen_r=wind_gen_r,
        hydro_ror_gen_r=hydro_ror_gen_r,
        load_stats=stats,
        config=config,
    )
