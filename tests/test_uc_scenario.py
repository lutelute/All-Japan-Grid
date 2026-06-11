"""Tests for src/uc/scenario.py — 全国UCシナリオビルダー。

scripts/gen_uc_regional.py から共通化したロードロジックの挙動を固定する。
「現状の既知課題」（重複の二重計上・揚水の非storage扱い）も回帰ピンとして
明示的にテストし、改善時にここが意図的に書き換わることを保証する。
"""

import json

import numpy as np
import pytest

from src.uc.scenario import (
    REGIONS,
    LoadStats,
    UCScenarioConfig,
    build_battery,
    build_national_scenario,
    load_national_thermal_generators,
    load_scenario_config,
)


def _write_geojson(path, features):
    path.write_text(json.dumps({"features": features}, ensure_ascii=False))


def _feat(name="P1", fuel="coal", cap=100.0, osm_id=1, operator=None, lonlat=None):
    f = {
        "properties": {
            "name": name,
            "fuel_type": fuel,
            "capacity_mw": cap,
            "osm_id": osm_id,
        }
    }
    if operator is not None:
        f["properties"]["operator"] = operator
    if lonlat is not None:
        f["geometry"] = {"type": "Point", "coordinates": list(lonlat)}
    return f


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

    def test_duplicate_osm_id_legacy_double_count(self, tmp_path):
        # dedup=False は従来の二重計上挙動を再現する（ベースライン比較用）
        _write_geojson(tmp_path / "tokyo_plants.geojson", [_feat("玉原", "hydro", 1200, 99)])
        _write_geojson(tmp_path / "tohoku_plants.geojson", [_feat("玉原", "hydro", 1200, 99)])
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats, dedup=False)
        assert len(gens) == 2
        assert stats.n_duplicates == 1
        assert stats.duplicate_capacity_mw == pytest.approx(1200)
        d = stats.as_dict()
        assert d["n_unique_units"] == 1
        assert d["unique_capacity_mw"] == pytest.approx(1200)

    def test_dedup_resolves_by_operator(self, tmp_path):
        # 玉原（東京電力RP運営、tohoku/tokyoスライス両方に出現）→ tokyo帰属で1台
        feat = _feat("玉原", "hydro", 1200, 99,
                     operator="東京電力リニューアブルパワー",
                     lonlat=(139.04, 36.80))
        _write_geojson(tmp_path / "tohoku_plants.geojson", [feat])
        _write_geojson(tmp_path / "tokyo_plants.geojson", [feat])
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)  # dedup=True
        assert len(gens) == 1
        assert gens[0].region == "tokyo"
        assert stats.n_duplicates == 1  # 検出（=除去）数
        assert stats.n_thermal_loaded == 1
        assert stats.as_dict()["n_unique_units"] == 1
        assert stats.as_dict()["unique_capacity_mw"] == pytest.approx(1200)

    def test_dedup_falls_back_to_bbox_margin(self, tmp_path):
        # operator不明（J-POWER等）→ Pointのbbox内側マージン最大の地域へ。
        # (137.0, 35.2) は chubu の奥 / hokuriku bbox外
        feat = _feat("無名揚水", "hydro", 800, 77, lonlat=(137.0, 35.2))
        _write_geojson(tmp_path / "chubu_plants.geojson", [feat])
        _write_geojson(tmp_path / "hokuriku_plants.geojson", [feat])
        gens = load_national_thermal_generators(str(tmp_path))
        assert len(gens) == 1
        assert gens[0].region == "chubu"

    def test_missing_capacity_defaulted_by_fuel(self, tmp_path):
        _write_geojson(tmp_path / "kansai_plants.geojson", [_feat("X", "coal", None, 5)])
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)
        assert len(gens) == 1
        # 欠損火力は自家発スケール100MW（THERMAL_DEFAULT["coal"]、2026-06-11較正）
        assert gens[0].capacity_mw == pytest.approx(100)
        assert stats.n_capacity_defaulted == 1

    def test_missing_capacity_patched_for_known_large_plants(self, tmp_path):
        # 苓北火力は容量欠損だが実態1,400MW → capacity_patches.yaml で個別補正
        _write_geojson(
            tmp_path / "kyushu_plants.geojson",
            [_feat("苓北火力発電所", "coal", None, 9)],
        )
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)
        assert len(gens) == 1
        assert gens[0].capacity_mw == pytest.approx(1400)
        assert stats.n_capacity_patched == 1
        assert stats.n_capacity_defaulted == 0

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


class TestApplyPumpedStorageReference:
    REF_YAML = """
defaults:
  storage_h: 6
  charge_efficiency: 0.84
  discharge_efficiency: 0.84
plants:
  - {name: 葛野川, operator: 東京電力, region: tokyo, capacity_mw: 1200}
  - {name: 奥多々良木, operator: 関西電力, region: kansai, capacity_mw: 1932}
  - {name: 池尻川, operator: 東北電力, region: tohoku, capacity_mw: 2.34}
"""

    def _ref(self, tmp_path):
        p = tmp_path / "ps.yaml"
        p.write_text(self.REF_YAML)
        return str(p)

    def _hydro(self, tmp_path, *feats):
        from src.uc.scenario import load_national_thermal_generators
        _write_geojson(tmp_path / "tokyo_plants.geojson", list(feats))
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)
        return gens, stats

    def test_reclassify_with_capacity_correction(self, tmp_path):
        from src.uc.scenario import apply_pumped_storage_reference
        # OSMの葛野川は計画値1600 → 参照の現況1200に補正してstorage化
        gens, stats = self._hydro(tmp_path, _feat("葛野川地下発電所", "hydro", 1600, 1))
        out = apply_pumped_storage_reference(gens, stats, self._ref(tmp_path))
        ps = [g for g in out if g.fuel_type == "pumped_hydro"]
        # 葛野川=再分類、奥多々良木=追加（池尻川は5MW未満で対象外）
        assert stats.n_pumped_reclassified == 1
        assert stats.n_pumped_added == 1
        kaz = next(g for g in ps if "葛野川" in g.name)
        assert kaz.capacity_mw == pytest.approx(1200)
        assert kaz.storage_capacity_mwh == pytest.approx(1200 * 6)
        assert kaz.is_storage
        assert kaz.region == "tokyo"
        assert kaz.fuel_cost_per_mwh == 0
        assert kaz.min_terminal_soc_fraction == pytest.approx(0.5)
        # 統計の容量補正 (1600→1200)
        assert stats.thermal_capacity_mw == pytest.approx(1200 + 1932)

    def test_missing_pumped_added_small_skipped(self, tmp_path):
        from src.uc.scenario import apply_pumped_storage_reference
        gens, stats = self._hydro(tmp_path, _feat("ただの水力", "hydro", 100, 2))
        out = apply_pumped_storage_reference(gens, stats, self._ref(tmp_path))
        names = [g.name for g in out if g.fuel_type == "pumped_hydro"]
        # 葛野川・奥多々良木は追加、池尻川(2.34MW)は追加されない
        assert any("葛野川" in n for n in names)
        assert any("奥多々良木" in n for n in names)
        assert not any("池尻川" in n for n in names)
        assert stats.n_pumped_added == 2
        # 非揚水hydroはそのまま
        assert any(g.fuel_type == "hydro" and g.name == "ただの水力" for g in out)

    def test_capacity_ratio_guard_prevents_false_match(self, tmp_path):
        from src.uc.scenario import apply_pumped_storage_reference
        # 名前は含むが容量が桁違い → 誤マッチせず参照値で別途追加
        gens, stats = self._hydro(tmp_path, _feat("葛野川第三小水力", "hydro", 8, 3))
        out = apply_pumped_storage_reference(gens, stats, self._ref(tmp_path))
        small = next(g for g in out if g.name == "葛野川第三小水力")
        assert small.fuel_type == "hydro"  # 再分類されない
        assert stats.n_pumped_reclassified == 0
        assert stats.n_pumped_added == 2

    def test_real_reference_yaml_loads(self):
        # リポジトリ同梱の参照リスト自体の妥当性
        import yaml
        with open("data/reference/pumped_storage.yaml") as f:
            ref = yaml.safe_load(f)
        plants = ref["plants"]
        assert len(plants) == 44
        total = sum(p["capacity_mw"] for p in plants)
        # エレクトリカル・ジャパン由来の現況合計 ~27.6GW
        assert 26_000 <= total <= 29_000
        regions = {p["region"] for p in plants}
        assert regions <= set(REGIONS)


class TestApplyNuclearStatusReference:
    REF_YAML = """
fiscal_year: 2023
operational:
  - {name: 川内, region: kyushu, capacity_mw: 1780}
  - {name: 高浜, region: kansai, capacity_mw: 3392}
"""

    def _ref(self, tmp_path):
        p = tmp_path / "nuc.yaml"
        p.write_text(self.REF_YAML)
        return str(p)

    def _load(self, tmp_path, *feats):
        from src.uc.scenario import load_national_thermal_generators
        _write_geojson(tmp_path / "kyushu_plants.geojson", list(feats))
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)
        return gens, stats

    def test_capacity_corrected_for_operational(self, tmp_path):
        from src.uc.scenario import apply_nuclear_status_reference
        # OSMの川内は1基分900MWのみ → 稼働2基分1780に補正
        gens, stats = self._load(tmp_path, _feat("川内原子力発電所", "nuclear", 900, 1))
        out = apply_nuclear_status_reference(gens, stats, self._ref(tmp_path))
        sendai = next(g for g in out if "川内" in g.name)
        assert sendai.capacity_mw == pytest.approx(1780)
        assert sendai.p_min_mw == pytest.approx(1780 * 0.4)
        assert stats.n_nuclear_available == 2  # 川内(補正) + 高浜(追加)
        assert stats.n_nuclear_excluded == 0

    def test_stopped_and_decommissioned_excluded(self, tmp_path):
        from src.uc.scenario import apply_nuclear_status_reference
        # 福島第二（廃炉）・柏崎刈羽（停止中）はリスト外 → 除外
        gens, stats = self._load(
            tmp_path,
            _feat("福島第二原子力発電所", "nuclear", 4400, 1),
            _feat("柏崎刈羽原子力発電所", "nuclear", 8212, 2),
        )
        out = apply_nuclear_status_reference(gens, stats, self._ref(tmp_path))
        nuc = [g for g in out if g.fuel_type == "nuclear"]
        names = [g.name for g in nuc]
        assert not any("福島" in n for n in names)
        assert not any("柏崎" in n for n in names)
        assert stats.n_nuclear_excluded == 2
        assert stats.nuclear_excluded_mw == pytest.approx(4400 + 8212)
        # リストの2サイトは追加される
        assert stats.n_nuclear_available == 2
        assert {g.region for g in nuc} == {"kyushu", "kansai"}

    def test_real_reference_yaml(self):
        import yaml
        with open("data/reference/nuclear_status.yaml") as f:
            ref = yaml.safe_load(f)
        ops = ref["operational"]
        total = sum(e["capacity_mw"] for e in ops)
        # 2023年度断面: 再稼働12基 約11.6GW
        assert total == pytest.approx(11608)
        assert ref["fiscal_year"] == 2023
        assert {e["region"] for e in ops} <= set(REGIONS)


class TestBuildBattery:
    def test_battery_fields_from_scenario_reference(self):
        cfg = load_scenario_config("fy2023")
        b = build_battery("kyushu", cfg)
        assert b.fuel_type == "battery"
        assert b.region == "kyushu"
        assert b.capacity_mw == cfg.battery["kyushu"]["mw"]
        assert b.storage_capacity_mwh == cfg.battery["kyushu"]["mwh"]
        assert b.is_storage
        assert b.initial_soc_fraction == pytest.approx(0.5)
        assert b.min_terminal_soc_fraction == pytest.approx(0.4)


class TestLoadScenarioConfig:
    def test_fy2023_loads_with_expected_values(self):
        cfg = load_scenario_config("fy2023")
        assert cfg.name == "fy2023"
        assert cfg.fiscal_year == 2023
        assert cfg.demand_shape.shape == (24,)
        assert cfg.demand_shape.max() == pytest.approx(1.0)
        assert set(cfg.regional_peak_mw) == set(REGIONS)
        # 旧ハードコード定数からの移行値の回帰ピン
        assert cfg.regional_peak_mw["tokyo"] == pytest.approx(60000)
        assert cfg.fuel_costs["coal"] == pytest.approx(4500)
        assert cfg.capacity_defaults["coal"] == pytest.approx(100)
        # startup_profiles はYAMLキーから内部短縮キーへ変換される
        assert cfg.startup_profiles["nuclear"]["mut"] == 8
        assert cfg.startup_profiles["lng"]["wh"] == 2
        # references がシナリオの一部
        assert "nuclear_status" in cfg.reference_paths

    def test_passthrough_and_default(self):
        cfg = load_scenario_config("fy2023")
        assert load_scenario_config(cfg) is cfg          # パススルー
        assert load_scenario_config(None).name == "fy2023"  # 既定

    def test_unknown_scenario_raises(self):
        with pytest.raises(FileNotFoundError, match="fy2023"):
            load_scenario_config("no_such_scenario")


class TestNationalScenario:
    def test_scenario_with_minimal_data(self, tmp_path):
        _write_geojson(
            tmp_path / "tokyo_plants.geojson",
            [_feat("A", "coal", 600, 1), _feat("B", "lng", 400, 2)],
        )
        scn = build_national_scenario(
            data_dir=str(tmp_path),
            interconnections_path="data/reference/interconnections.yaml",
            pumped_storage=False,
            nuclear_status=False,
        )
        # 熱電源2 + 地域蓄電池10
        assert len(scn.generators) == 12
        assert sum(1 for g in scn.generators if g.fuel_type == "battery") == len(REGIONS)
        # 需要・RE時系列は全地域・24期間
        assert set(scn.gross_demand_r) == set(REGIONS)
        for r in REGIONS:
            assert scn.gross_demand_r[r].shape == (24,)
            assert scn.gross_demand_r[r].max() == pytest.approx(
                scn.config.regional_peak_mw[r]
            )
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
        # 実データのフルロード（dedup+揚水適用後の現行デフォルト構成）
        scn = build_national_scenario()
        n_thermal = sum(
            1 for g in scn.generators
            if g.fuel_type not in ("battery", "pumped_hydro")
        )
        # 計測 (2026-06-11): dedup後510機 → 揚水再分類後の純熱電源492機
        # データ更新で微変動しうるため幅で固定
        assert 420 <= n_thermal <= 900
        assert scn.load_stats.n_duplicates > 0  # 重複の検出数（dedupで除去済み）
        # 揚水が参照リスト規模 (~27.6GW) でstorage表現されている
        ps_mw = sum(g.capacity_mw for g in scn.generators
                    if g.fuel_type == "pumped_hydro")
        assert 25_000 <= ps_mw <= 29_000
        ps_mwh = sum(g.storage_capacity_mwh for g in scn.generators
                     if g.fuel_type == "pumped_hydro")
        assert ps_mwh >= ps_mw * 5  # storage_h>=5h相当
        cap = sum(
            g.capacity_mw for g in scn.generators if g.fuel_type != "battery"
        )
        assert 200_000 <= cap <= 350_000


class TestFY2023R2Calibration:
    def test_r2_loads_with_calibrated_values(self):
        cfg = load_scenario_config("fy2023r2")
        # 較正の回帰ピン（出典は fy2023r2.yaml 冒頭 [S1]-[S5]）
        assert sum(cfg.wind_capacity_mw.values()) == pytest.approx(6000)   # [S3]
        assert sum(cfg.solar_capacity_mw.values()) == pytest.approx(69990)  # [S2][S3]
        assert sum(cfg.hydro_ror_capacity_mw.values()) == pytest.approx(2500)  # [S5]
        assert cfg.fuel_costs["coal"] == pytest.approx(7000)   # [S4]
        assert cfg.fuel_costs["lng"] == pytest.approx(11000)
        assert cfg.raw["reference_shares_pct"]["lng"] == pytest.approx(32.9)  # [S1]
        # solar年間エネルギーが実績92.1TWhに較正されていること（±5%）
        import numpy as np
        annual_twh = sum(
            float(np.minimum(cfg.solar_cf_base * cfg.solar_multiplier[r], 1.0).mean())
            * cfg.solar_capacity_mw[r] * 8760 / 1e6
            for r in cfg.solar_capacity_mw
        ) * 0.95  # 月別平均
        assert 85 <= annual_twh <= 100

    def test_hydro_ror_deducts_demand(self, tmp_path):
        _write_geojson(tmp_path / "tokyo_plants.geojson",
                       [_feat("A", "coal", 600, 1)])
        base = build_national_scenario(
            data_dir=str(tmp_path), scenario="fy2023",
            pumped_storage=False, nuclear_status=False,
        )
        r2 = build_national_scenario(
            data_dir=str(tmp_path), scenario="fy2023r2",
            pumped_storage=False, nuclear_status=False,
        )
        assert r2.hydro_ror_gen_r  # RoRが構築される
        # RoR控除で純需要が下がる（chubu: 600MW分）
        assert (r2.net_demand_r["chubu"] < base.net_demand_r["chubu"]).all()

    def test_retired_plants_excluded_via_zero_patch(self, tmp_path):
        # 廃止プラント（豊前等）は capacity_patches の 0 指定で除外される
        _write_geojson(
            tmp_path / "kyushu_plants.geojson",
            [_feat("豊前火力発電所", "oil", -1.0, None),
             _feat("新大分火力発電所", "gas", -1.0, None)],
        )
        stats = LoadStats()
        gens = load_national_thermal_generators(str(tmp_path), stats)
        names = [g.name for g in gens]
        assert not any("豊前" in n for n in names)      # 廃止 → 除外
        shin_oita = next(g for g in gens if "新大分" in g.name)
        assert shin_oita.capacity_mw == pytest.approx(2295)  # 公称値パッチ


class TestSyntheticMaintenance:
    def test_deterministic_and_in_low_season(self):
        from src.uc.scenario import load_scenario_config, synthesize_maintenance
        from src.model.generator import Generator
        cfg = load_scenario_config("fy2023r2")
        gens = [
            Generator(id=f"g{i}", name=f"g{i}", capacity_mw=500,
                      fuel_type=ft, region="tokyo", fuel_cost_per_mwh=5000)
            for i, ft in enumerate(["coal", "lng", "nuclear", "oil", "hydro"])
        ]
        out1 = synthesize_maintenance(gens, cfg)
        out2 = synthesize_maintenance(gens, cfg)
        spec = cfg.raw["maintenance"]
        weeks = spec["placement_weeks"]
        weeks_nuc = spec.get("placement_weeks_nuclear", weeks)
        durs = spec["duration_weeks_by_fuel"]
        for g1, g2 in zip(out1, out2):
            # 決定論: 同一入力 → 同一計画（乱数不使用の再現性担保）
            assert g1.maintenance_windows == g2.maintenance_windows
            if g1.fuel_type in durs:
                (s, e), = g1.maintenance_windows
                assert (e - s) == min(durs[g1.fuel_type] * 7 * 24, 8760 - s)
                allowed = weeks_nuc if g1.fuel_type == "nuclear" else weeks
                assert (s // (7 * 24)) in allowed
            else:
                assert g1.maintenance_windows == []  # hydro等は対象外

    @staticmethod
    def _anchor(region, mw=30000):
        # メンテ対象外の大容量アンカー（系統規模の文脈を作り、地域別の
        # 同時停止上限 = 域内容量×fraction を現実的な値にする）
        from src.model.generator import Generator
        return Generator(id=f"anchor_{region}", name="anchor", capacity_mw=mw,
                         fuel_type="hydro", region=region, fuel_cost_per_mwh=0)

    def test_round_robin_avoids_same_group_overlap(self):
        # 同一(地域×燃料)グループは輪番で別週に配置される
        # （md5独立配置の偶然同時停止 = r4 chunk10 infeasible の再発防止）
        from src.uc.scenario import load_scenario_config, synthesize_maintenance
        from src.model.generator import Generator
        cfg = load_scenario_config("fy2023r2")
        gens = [self._anchor("kyushu")] + [
            Generator(id=f"c{i}", name=f"c{i}", capacity_mw=1000 - i,
                      fuel_type="coal", region="kyushu", fuel_cost_per_mwh=5000)
            for i in range(4)
        ]
        out = synthesize_maintenance(gens, cfg)
        starts = [g.maintenance_windows[0][0] for g in out
                  if g.maintenance_windows]
        assert len(starts) == 4
        assert len(set(starts)) == 4  # 4機が全て異なる週に分散

    def test_outage_cap_skips_oversized_units(self):
        # 域内容量×fraction を超える配置は行われない（小地域の枯渇防止）。
        # 沖縄相当: 合計1.88GWの孤立系統では 420MW機は上限25%(0.47GW)内に
        # 1機ずつしか停止できず、収まらない機はメンテなしになる
        from src.uc.scenario import load_scenario_config, synthesize_maintenance
        from src.model.generator import Generator
        cfg = load_scenario_config("fy2023r2")
        gens = [
            Generator(id=f"o{i}", name=f"o{i}", capacity_mw=420,
                      fuel_type="oil", region="okinawa", fuel_cost_per_mwh=9000)
            for i in range(4)
        ] + [Generator(id="oc", name="oc", capacity_mw=200, fuel_type="coal",
                       region="okinawa", fuel_cost_per_mwh=4500)]
        out = synthesize_maintenance(gens, cfg)
        # 各週の同時停止が上限 (1880*0.25=470MW) を超えない
        from collections import defaultdict
        week_out = defaultdict(float)
        for g in out:
            for s, e in g.maintenance_windows:
                for wk in range(s // 168, (e + 167) // 168):
                    week_out[wk] += g.capacity_mw
        assert all(v <= 1880 * 0.25 + 1e-6 for v in week_out.values())

    def test_24h_snapshot_unaffected(self):
        # メンテは春秋配置（最早 週12=2016h〜）なので 24h断面 (t<24) に窓が無い
        from src.uc.scenario import load_scenario_config, synthesize_maintenance
        from src.model.generator import Generator
        cfg = load_scenario_config("fy2023r2")
        g = Generator(id="c1", name="c1", capacity_mw=500, fuel_type="coal",
                      region="tokyo", fuel_cost_per_mwh=5000)
        out = synthesize_maintenance([self._anchor("tokyo"), g], cfg)
        (s, e), = next(x for x in out if x.id == "c1").maintenance_windows
        assert s >= 24  # add_maintenance_constraints は t<24 に制約を張らない

    def test_nuclear_slots_never_overlap_within_region(self):
        # 原子力スロット間隔 >= duration(13週) → 同一地域サイトの停止が
        # 重ならない（r5 chunk02-04 春infeasibleの再発防止ピン）
        from src.uc.scenario import load_scenario_config, synthesize_maintenance
        from src.model.generator import Generator
        cfg = load_scenario_config("fy2023r2")
        spec = cfg.raw["maintenance"]
        slots = spec["placement_weeks_nuclear"]
        dur = spec["duration_weeks_by_fuel"]["nuclear"]
        assert all(b - a >= dur for a, b in zip(slots, slots[1:]))
        # 関西3サイト相当の輪番で窓が交差しないこと
        gens = [self._anchor("kansai")] + [
            Generator(id=n, name=n, capacity_mw=c, fuel_type="nuclear",
                      region="kansai", fuel_cost_per_mwh=1500)
            for n, c in [("takahama", 3392), ("ohi", 2360), ("mihama", 826)]]
        out = synthesize_maintenance(gens, cfg)
        wins = sorted(g.maintenance_windows[0] for g in out
                      if g.maintenance_windows)
        assert len(wins) == 3
        for (s1, e1), (s2, e2) in zip(wins, wins[1:]):
            assert e1 <= s2  # 交差なし
