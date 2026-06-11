"""Tests for src/uc/capacity_bridge — UC容量較正のPF側適用。

dedup（bbox重複コピー）・容量パッチ（常時適用/廃止/燃料補正/zone帰属）・
nuclear_status（稼働=site容量/リスト外=停止）・zone override注入を
小さなpandapowerネットで検証する。
"""

import pandapower as pp
import pytest

from src.uc.capacity_bridge import apply_to_net, load_pf_calibration
from src.uc.pf_injection import inject_dispatch_by_zone


def _bridge_net():
    """west島診断の縮小模型: 重複コピー・欠損デフォルト置換・誤帰属を再現。"""
    net = pp.create_empty_network()
    b_shik = pp.create_bus(net, vn_kv=500.0, zone="shikoku")
    b_kan = pp.create_bus(net, vn_kv=500.0, zone="kansai")
    pp.create_line_from_parameters(net, b_shik, b_kan, length_km=50,
                                   r_ohm_per_km=0.01, x_ohm_per_km=0.3,
                                   c_nf_per_km=10, max_i_ka=2.0)
    pp.create_load(net, b_shik, p_mw=500.0, q_mvar=50.0)
    pp.create_load(net, b_kan, p_mw=1000.0, q_mvar=100.0)
    pp.create_gen(net, b_shik, p_mw=0.0, vm_pu=1.0, slack=True, name="slack",
                  type="lng", max_p_mw=5000.0, min_p_mw=0.0)
    # 橘湾相当: kansai zoneのバスに繋がった誤帰属 + bbox重複の2コピー
    pp.create_gen(net, b_kan, p_mw=100.0, vm_pu=1.0, name="橘湾火力発電所",
                  type="coal", max_p_mw=2100.0, min_p_mw=0.0)
    pp.create_gen(net, b_kan, p_mw=100.0, vm_pu=1.0, name="橘湾火力発電所",
                  type="coal", max_p_mw=2100.0, min_p_mw=0.0)  # 重複コピー
    # 欠損→デフォルト置換相当（実容量2360のはずが1000）
    pp.create_gen(net, b_kan, p_mw=500.0, vm_pu=1.0, name="玄海原子力発電所",
                  type="nuclear", max_p_mw=1000.0, min_p_mw=0.0)
    # 停止炉（リスト外）
    pp.create_gen(net, b_kan, p_mw=500.0, vm_pu=1.0, name="浜岡原子力発電所",
                  type="nuclear", max_p_mw=1000.0, min_p_mw=0.0)
    # 燃料誤タグ（七尾大田相当）
    pp.create_gen(net, b_shik, p_mw=10.0, vm_pu=1.0, name="七尾大田火力発電所",
                  type="biomass", max_p_mw=20.0, min_p_mw=0.0)
    # 廃止対象
    pp.create_gen(net, b_shik, p_mw=50.0, vm_pu=1.0, name="豊前火力発電所",
                  type="coal", max_p_mw=500.0, min_p_mw=0.0)
    # 帰属のみ補正の対象（四電橘湾相当: 容量はOSM正値、kansai zoneに誤帰属）
    pp.create_gen(net, b_kan, p_mw=100.0, vm_pu=1.0, name="橘湾発電所",
                  type="coal", max_p_mw=700.0, min_p_mw=0.0)
    return net


CALIB = {
    "patches": [
        {"match": "橘湾火力", "capacity_mw": 2100, "region": "shikoku",
         "override": True},
        {"match": "橘湾発電所", "region": "shikoku"},  # capacity_mw無し
        {"match": "七尾大田", "capacity_mw": 1200, "fuel": "coal",
         "override": True},
        {"match": "豊前火力", "capacity_mw": 0},
        {"match": "存在しない発電所", "capacity_mw": 999},
    ],
    "nuclear": [
        {"name": "玄海", "region": "kyushu", "capacity_mw": 2360},
    ],
}


class TestApplyToNet:
    def test_dedup_disables_duplicate_copy(self):
        net = _bridge_net()
        rep = apply_to_net(net, CALIB)
        assert rep["dedup_disabled"] == 1
        active_tachibana = net.gen[
            net.gen["name"].astype(str).str.contains("橘湾火力")
            & net.gen["in_service"]]
        assert len(active_tachibana) == 1  # 二重計上が解消

    def test_patch_capacity_fuel_retire(self):
        net = _bridge_net()
        rep = apply_to_net(net, CALIB)
        # 七尾大田: biomass→coal + 容量20→1200
        nanao = net.gen[net.gen["name"].astype(str).str.contains("七尾大田")]
        assert nanao.iloc[0]["type"] == "coal"
        assert nanao.iloc[0]["max_p_mw"] == pytest.approx(1200.0)
        assert rep["fuel_fixed"] == 1
        # 豊前: 廃止
        buzen = net.gen[net.gen["name"].astype(str).str.contains("豊前")]
        assert not bool(buzen.iloc[0]["in_service"])
        assert rep["retired"] == 1
        # matchしないパッチは開示
        assert "存在しない発電所" in rep["unmatched_patches"]

    def test_region_only_patch_keeps_capacity(self):
        net = _bridge_net()
        rep = apply_to_net(net, CALIB)
        # 「橘湾発電所」(capacity_mw無しパッチ): 容量はOSM正値のまま、帰属のみ
        shikoku_dento = net.gen[net.gen["name"].astype(str) == "橘湾発電所"]
        idx = int(shikoku_dento.index[0])
        assert shikoku_dento.iloc[0]["max_p_mw"] == pytest.approx(700.0)
        assert bool(shikoku_dento.iloc[0]["in_service"])  # retire誤判定しない
        assert rep["zone_override"][idx] == "shikoku"

    def test_nuclear_status_semantics(self):
        net = _bridge_net()
        rep = apply_to_net(net, CALIB)
        genkai = net.gen[net.gen["name"].astype(str).str.contains("玄海")]
        assert genkai.iloc[0]["max_p_mw"] == pytest.approx(2360.0)  # site容量
        hamaoka = net.gen[net.gen["name"].astype(str).str.contains("浜岡")]
        assert not bool(hamaoka.iloc[0]["in_service"])  # リスト外=停止
        assert rep["nuclear_set"] == 1
        assert rep["nuclear_stopped"] == 1

    def test_zone_override_routes_injection(self):
        net = _bridge_net()
        rep = apply_to_net(net, CALIB)
        # 橘湾はkansai zoneのバスだが、shikoku向け注入の受け皿になる
        reports = inject_dispatch_by_zone(
            net,
            {"shikoku": {"coal": 1500.0}, "kansai": {}},
            {"shikoku": 500.0, "kansai": 1000.0},
            gen_zone_override=rep["zone_override"],
        )
        assert reports["shikoku"]["injection"]["injected_mw"] == pytest.approx(1500.0)
        # 容量比例: 橘湾火力2100 / 七尾大田(coal化)1200 / 橘湾(四電)700 = 4000
        tachibana_active = net.gen[
            net.gen["name"].astype(str).str.contains("橘湾火力")
            & net.gen["in_service"]]
        assert float(tachibana_active.iloc[0]["p_mw"]) == pytest.approx(
            1500.0 * 2100 / 4000)
        nanao = net.gen[net.gen["name"].astype(str).str.contains("七尾大田")]
        assert float(nanao.iloc[0]["p_mw"]) == pytest.approx(
            1500.0 * 1200 / 4000)
        yonden = net.gen[net.gen["name"].astype(str) == "橘湾発電所"]
        assert float(yonden.iloc[0]["p_mw"]) == pytest.approx(
            1500.0 * 700 / 4000)


class TestLoadCalibration:
    def test_yaml_fallback_loads_references(self, tmp_path):
        # 存在しないDBパス → YAML正本フォールバック
        calib = load_pf_calibration(
            scenario_id="fy2023r2",
            db_path=str(tmp_path / "none" / "x.db"))
        assert len(calib["patches"]) >= 24
        assert any(p["match"] == "橘湾火力" for p in calib["patches"])
        assert len(calib["nuclear"]) >= 5
