"""Tests for src/uc/scenario.py — 全国UCシナリオビルダー。

scripts/gen_uc_regional.py から共通化したロードロジックの挙動を固定する。
「現状の既知課題」（重複の二重計上・揚水の非storage扱い）も回帰ピンとして
明示的にテストし、改善時にここが意図的に書き換わることを保証する。
"""

import json

import numpy as np
import pytest

from src.uc.scenario import (
    DEMAND_SHAPE,
    OCCTO_RE,
    REGIONS,
    LoadStats,
    build_battery,
    build_national_scenario,
    load_national_thermal_generators,
)


def _write_geojson(path, features):
    path.write_text(json.dumps({"features": features}, ensure_ascii=False))


def _feat(name="P1", fuel="coal", cap=100.0, osm_id=1):
    return {
        "properties": {
            "name": name,
            "fuel_type": fuel,
            "capacity_mw": cap,
            "osm_id": osm_id,
        }
    }


class TestLoadNationalThermalGenerators:
    def test_basic_load_and_fuel_normalisation(self, tmp_path):
        _write_geojson(
            tmp_path / "tokyo_plants.geojson",
            [_feat("A", "coal", 600, 1), _feat("B", "gas", 400, 2)],
        )
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)
        assert len(gens) == 2
        assert stats.n_thermal_loaded == 2
        assert stats.thermal_capacity_mw == pytest.approx(1000)
        assert stats.n_duplicates == 0
        # gas は lng に正規化される
        assert {g.fuel_type for g in gens} == {"coal", "lng"}

    def test_duplicate_osm_id_across_regions_counted(self, tmp_path):
        # 地域スライスの重なりで同一発電所が複数地域に出現するケース
        _write_geojson(tmp_path / "tokyo_plants.geojson", [_feat("玉原", "hydro", 1200, 99)])
        _write_geojson(tmp_path / "tohoku_plants.geojson", [_feat("玉原", "hydro", 1200, 99)])
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)
        # 現状挙動の回帰ピン: 重複を除外しない（既知の二重計上問題）
        assert len(gens) == 2
        assert stats.n_duplicates == 1
        assert stats.duplicate_capacity_mw == pytest.approx(1200)
        d = stats.as_dict()
        assert d["n_unique_units"] == 1
        assert d["unique_capacity_mw"] == pytest.approx(1200)

    def test_missing_capacity_defaulted_by_fuel(self, tmp_path):
        _write_geojson(tmp_path / "kansai_plants.geojson", [_feat("X", "coal", None, 5)])
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)
        assert len(gens) == 1
        assert gens[0].capacity_mw == pytest.approx(600)  # THERMAL_DEFAULT["coal"]
        assert stats.n_capacity_defaulted == 1

    def test_small_units_skipped(self, tmp_path):
        _write_geojson(tmp_path / "chubu_plants.geojson", [_feat("small", "hydro", 3.0, 7)])
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)
        assert gens == []
        assert stats.n_skipped_small == 1

    def test_solar_wind_battery_excluded(self, tmp_path):
        _write_geojson(
            tmp_path / "kyushu_plants.geojson",
            [
                _feat("S", "solar", 100, 1),
                _feat("W", "wind", 100, 2),
                _feat("B", "battery", 100, 3),
                _feat("C", "coal", 100, 4),
            ],
        )
        gens = load_national_thermal_generators(str(tmp_path))
        assert [g.fuel_type for g in gens] == ["coal"]

    def test_okinawa_synthetic_thermals_added(self, tmp_path):
        _write_geojson(tmp_path / "okinawa_plants.geojson", [])
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)
        # 合成 石油×4 (420MW) + 石炭×1 (200MW)
        assert len(gens) == 5
        assert sum(g.capacity_mw for g in gens) == pytest.approx(1880)
        assert stats.n_thermal_loaded == 5

    def test_hydro_not_treated_as_storage(self, tmp_path):
        # 既知課題の回帰ピン: OSM抽出に pumped_hydro が存在しないため
        # 大規模揚水（例: 葛野川）も非storageの一般水力として扱われる。
        # 揚水分離の改善時はこのテストを意図的に更新すること。
        _write_geojson(tmp_path / "tokyo_plants.geojson", [_feat("葛野川", "hydro", 1600, 1)])
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)
        assert gens[0].is_storage is False
        assert gens[0].fuel_cost_per_mwh == 0  # コスト0のフリー電源扱い
        assert stats.n_storage_units == 0


class TestBuildBattery:
    def test_battery_fields_from_occto_reference(self):
        b = build_battery("kyushu")
        assert b.fuel_type == "battery"
        assert b.region == "kyushu"
        assert b.capacity_mw == OCCTO_RE["kyushu"]["batt_mw"]
        assert b.storage_capacity_mwh == OCCTO_RE["kyushu"]["batt_mwh"]
        assert b.is_storage
        assert b.initial_soc_fraction == pytest.approx(0.5)
        assert b.min_terminal_soc_fraction == pytest.approx(0.4)


class TestNationalScenario:
    def test_scenario_with_minimal_data(self, tmp_path):
        _write_geojson(
            tmp_path / "tokyo_plants.geojson",
            [_feat("A", "coal", 600, 1), _feat("B", "lng", 400, 2)],
        )
        scn = build_national_scenario(
            data_dir=str(tmp_path),
            interconnections_path="data/reference/interconnections.yaml",
        )
        # 熱電源2 + 地域蓄電池10
        assert len(scn.generators) == 12
        assert sum(1 for g in scn.generators if g.fuel_type == "battery") == len(REGIONS)
        # 需要・RE時系列は全地域・24期間
        assert set(scn.gross_demand_r) == set(REGIONS)
        for r in REGIONS:
            assert scn.gross_demand_r[r].shape == (24,)
            assert scn.gross_demand_r[r].max() == pytest.approx(OCCTO_RE[r]["peak_mw"])
        # 純需要は非負
        for r, d in scn.net_demand_r.items():
            assert (d >= 0).all()
        nat = scn.net_demand_national
        assert nat.shape == (24,)
        assert (nat <= scn.gross_demand_national).all()

    def test_to_uc_parameters(self, tmp_path):
        _write_geojson(tmp_path / "tokyo_plants.geojson", [_feat("A", "coal", 600, 1)])
        scn = build_national_scenario(
            data_dir=str(tmp_path),
            interconnections_path="data/reference/interconnections.yaml",
        )
        params = scn.to_uc_parameters(reserve_margin=0.07, mip_gap=0.02)
        assert params.reserve_margin == pytest.approx(0.07)
        assert params.mip_gap == pytest.approx(0.02)
        assert params.time_horizon.num_periods == 24
        assert len(params.demand.demands) == 24
        assert set(params.regional_demands) == set(REGIONS)
        assert len(params.interconnections) > 0

    def test_real_data_smoke(self):
        # 実データのフルロード（gen_uc_regional.py 互換条件のスモーク）
        scn = build_national_scenario()
        n_thermal = sum(
            1 for g in scn.generators
            if g.fuel_type not in ("battery", "pumped_hydro")
        )
        # ベースライン計測 (2026-06-11): 熱電源636機・268,361MW・重複177機
        # データ更新で微変動しうるため幅で固定
        assert 500 <= n_thermal <= 900
        assert scn.load_stats.n_duplicates > 0  # 重複が現存する（改善対象）
        cap = sum(
            g.capacity_mw for g in scn.generators if g.fuel_type != "battery"
        )
        assert 200_000 <= cap <= 350_000
