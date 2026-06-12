"""Tests for uc_to_pf_national の before/after GeoJSONエクスポート。

同一baseのdeepcopy 2断面から、バスvm・線loadingのGeoJSONと
差分（dvm/dloading）が正しく焼き込まれることを小さなACネットで検証する。
"""

import json

import pandapower as pp
import pytest

from scripts.uc_to_pf_national import export_before_after


def _solved_net(load_mw):
    """2バスAC網（geo座標つき）を作って解く。load_mwで断面を変える。"""
    net = pp.create_empty_network()
    b1 = pp.create_bus(net, vn_kv=154.0, zone="tokyo",
                       geodata=(139.7, 35.7), name="sub_a")
    b2 = pp.create_bus(net, vn_kv=154.0, zone="tokyo",
                       geodata=(140.0, 35.9), name="sub_b")
    pp.create_line_from_parameters(net, b1, b2, length_km=30,
                                   r_ohm_per_km=0.06, x_ohm_per_km=0.4,
                                   c_nf_per_km=10, max_i_ka=0.5,
                                   name="test_line")
    pp.create_load(net, b2, p_mw=load_mw, q_mvar=load_mw * 0.1)
    pp.create_ext_grid(net, b1, vm_pu=1.02)
    pp.runpp(net)
    return net


class TestExportBeforeAfter:
    def test_files_and_diff(self, tmp_path):
        net_before = _solved_net(60.0)
        net_after = _solved_net(110.0)   # 同一構造・別断面（重負荷）
        files = export_before_after(
            net_before, net_after, ["tokyo"], geom={},
            island_id="testisl", mode="ac", outdir=str(tmp_path))
        assert sorted(files) == [
            "testisl_after_buses.geojson", "testisl_after_lines.geojson",
            "testisl_before_buses.geojson", "testisl_before_lines.geojson",
        ]

        after_buses = json.load(
            open(tmp_path / "testisl_after_buses.geojson"))["features"]
        # 重負荷側は受電端vmが下がる → dvm < 0
        b2 = next(f for f in after_buses if f["properties"]["name"] == "sub_b")
        assert b2["properties"]["dvm"] is not None
        assert b2["properties"]["dvm"] < 0
        # before側featureにはdiffキーが無い
        before_buses = json.load(
            open(tmp_path / "testisl_before_buses.geojson"))["features"]
        assert "dvm" not in before_buses[0]["properties"]

        after_lines = json.load(
            open(tmp_path / "testisl_after_lines.geojson"))["features"]
        ln = after_lines[0]["properties"]
        assert ln["dloading"] == pytest.approx(
            ln["loading_pct"]
            - json.load(open(tmp_path / "testisl_before_lines.geojson"))
            ["features"][0]["properties"]["loading_pct"], abs=0.11)
        assert ln["dloading"] > 0   # 重負荷側はloading増

    def test_geometry_fallback_is_straight_line(self, tmp_path):
        net = _solved_net(60.0)
        export_before_after(net, net, ["tokyo"], geom={},
                            island_id="t2", mode="ac", outdir=str(tmp_path))
        lines = json.load(open(tmp_path / "t2_after_lines.geojson"))["features"]
        # geom未登録 → from/to座標の2点直線にフォールバック
        assert len(lines[0]["geometry"]["coordinates"]) == 2
