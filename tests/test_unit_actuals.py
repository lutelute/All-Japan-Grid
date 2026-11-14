"""発電機の出力をユニット別の発電実績で置く直し(介入 #63 の案)の試験。"""
from __future__ import annotations

import datetime as dt

import pytest

from src.powerflow import unit_actuals as ua


def test_norm_name_strips_owner_tail_and_unit_number():
    assert ua.norm_name("苫東厚真発電所") == ua.norm_name("苫東厚真火力発電所") == "苫東厚真"
    assert ua.norm_name("電源開発橘湾火力発電所") == "橘湾"
    assert ua.norm_name("東北電力原町火力発電所１号機") == "原町"
    assert ua.norm_name("玄海原子力発電所") == "玄海"
    assert ua.norm_name("発電所") == "発電所"          # 語尾だけの名前は空にしない
    # 号機・系列・軸の印と、区域の括弧書き
    assert ua.norm_name("姉崎火力発電所新２号機") == ua.norm_name("姉崎火力発電所")
    assert ua.norm_name("袖ケ浦火力発電所３号機") == ua.norm_name("袖ヶ浦火力発電所")
    assert ua.norm_name("電源開発田子倉発電所(東北)") == "田子倉"
    assert ua.norm_name("大崎発電所第１号１軸") == "大崎"
    assert ua.norm_name("牧港GT2号") == "牧港"
    assert ua.norm_name("新小野田発電所第１号機") == "新小野田"      # 名前の頭の「新」は落とさない


def _csv(tmp_path, rows):
    hdr = ["発電所コード", "エリア", "発電所名", "ユニット名", "発電方式・燃種", "対象日"]
    slots = []
    for h in range(24):
        slots += [f"{h:02d}:30[kWh]", f"{h + 1:02d}:00[kWh]"]
    hdr += slots + ["日量[kWh]"]
    lines = [",".join(hdr)]
    for area, plant, unit, fuel, day, kwh in rows:
        lines.append(",".join(["1", area, plant, unit, fuel, day] + [str(kwh)] * 48 + [str(kwh * 48)]))
    p = tmp_path / "hks_20261109_20261109.csv"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return p


def test_load_day_sums_units_and_converts_kwh_to_mw(tmp_path):
    p = _csv(tmp_path, [("東北", "原町火力発電所", "１号機", "火力（石炭）", "2026/11/09", 250000),
                        ("東北", "原町火力発電所", "２号機", "火力（石炭）", "2026/11/09", 150000),
                        ("東北", "原町火力発電所", "１号機", "火力（石炭）", "2026/11/08", 999999)])
    got = ua.load_day([p], dt.date(2026, 11, 9))
    rec = got[("tohoku", "原町火力発電所")]
    assert rec["n_units"] == 2 and rec["fuel"] == "coal"
    assert rec["mw"][0] == pytest.approx(800.0)        # 30 分で 25 万 kWh = 500 MW、15 万 kWh = 300 MW
    assert len(rec["mw"]) == 24


def _net():
    pp = pytest.importorskip("pandapower")
    net = pp.create_empty_network()
    b = [pp.create_bus(net, vn_kv=275.0, name=f"b{i}", zone="tohoku") for i in range(2)]
    pp.create_line_from_parameters(net, b[0], b[1], length_km=10, r_ohm_per_km=0.01, x_ohm_per_km=0.3,
                                   c_nf_per_km=10, max_i_ka=2)
    pp.create_load(net, b[1], p_mw=1000.0)
    g = {"原町": pp.create_gen(net, b[0], p_mw=400.0, max_p_mw=2000.0, type="coal", name="原町火力発電所"),
         "東新潟": pp.create_gen(net, b[0], p_mw=400.0, max_p_mw=4000.0, type="gas", name="東新潟火力発電所"),
         "小さい": pp.create_gen(net, b[1], p_mw=200.0, max_p_mw=500.0, type="hydro", name="どこかの水力発電所")}
    net.gen["zone_src"] = ""
    pp.create_ext_grid(net, b[1])
    return net, g


def test_match_exact_and_refuses_ambiguous_containment():
    net, g = _net()
    plants = {("tohoku", "東北電力原町火力発電所１号機"): {"fuel": "coal", "mw": [900.0] * 24, "n_units": 1},
              ("tohoku", "新潟火力発電所"): {"fuel": "gas", "mw": [100.0] * 24, "n_units": 1},
              ("tohoku", "東新潟火力発電所"): {"fuel": "gas", "mw": [3000.0] * 24, "n_units": 4},
              ("kansai", "原町火力発電所"): {"fuel": "coal", "mw": [1.0] * 24, "n_units": 1}}
    pins, led = ua.match_plants(net, plants, "east")
    assert pins[("tohoku", "東北電力原町火力発電所１号機")] == [g["原町"]]
    assert pins[("tohoku", "東新潟火力発電所")] == [g["東新潟"]]
    # 「新潟」は「東新潟」に含まれるが、東新潟は別の発電所の名前そのものなので結ばない
    assert ("tohoku", "新潟火力発電所") not in pins
    assert ("kansai", "原町火力発電所") not in pins            # 区域の島が違う
    how = {m["hks"]: m["how"] for m in led}
    assert how["東新潟火力発電所"] == "exact" and how["新潟火力発電所"] is None


def test_alias_ledger_wins():
    net, g = _net()
    plants = {("tohoku", "釧路火力発電所"): {"fuel": "coal", "mw": [50.0] * 24, "n_units": 1}}
    pins, led = ua.match_plants(net, plants, "east", {("tohoku", "釧路火力発電所"): "どこかの水力発電所"})
    assert pins[("tohoku", "釧路火力発電所")] == [g["小さい"]] and led[0]["how"] == "alias"


def test_apply_pins_and_rebalance_rest_of_zone():
    net, g = _net()
    plants = {("tohoku", "原町火力発電所"): {"fuel": "coal", "mw": [2500.0] * 24, "n_units": 2}}
    pins, _ = ua.match_plants(net, plants, "east")
    pinned = ua.pinned_at(net, pins, plants, 3)
    assert pinned == {g["原町"]: (2500.0, "coal")}
    rec = ua.apply_pins(net, pinned)
    assert net.gen.at[g["原町"], "p_mw"] == 2500.0
    assert rec["raised_cap_mw"] == pytest.approx(500.0)          # 容量 2,000 を超えた分は容量を引き上げて載せる
    rb = ua.rebalance_unpinned(net, "tohoku", pinned)
    # 観測の合計が需要(1,000)を超える区域では、残りの発電機は 0。区域は 1,500 を送る
    assert rb["rest_mw"] == 0.0
    assert net.gen.at[g["東新潟"], "p_mw"] == 0.0 and net.gen.at[g["小さい"], "p_mw"] == 0.0


def test_rebalance_shares_remaining_load_by_capacity():
    net, g = _net()
    pinned = {g["原町"]: (100.0, "coal")}
    ua.apply_pins(net, pinned)
    ua.rebalance_unpinned(net, "tohoku", pinned)
    assert net.gen.at[g["東新潟"], "p_mw"] == pytest.approx(900.0 * 4000 / 4500)
    assert net.gen.at[g["小さい"], "p_mw"] == pytest.approx(900.0 * 500 / 4500)


def test_fuel_actuals_leave_room_for_pinned_units():
    """燃料別の実績から、ユニット別の実績で置く発電機の分を引いた残りを、ほかの発電機へ配る。"""
    from scripts import export_day_flows as edf
    net, g = _net()
    pp = pytest.importorskip("pandapower")
    g["石炭2"] = pp.create_gen(net, 0, p_mw=0.0, max_p_mw=1000.0, type="coal", name="別の石炭")
    fm = {"tohoku": {"fuels": {"demand": [1000.0] * 24, "coal": [1500.0] * 24, "lng": [300.0] * 24}}}
    pinned = {g["原町"]: (1200.0, "coal")}
    led = edf.apply_fuel_actuals(net, fm, 5, island="east", pinned=pinned)
    ua.apply_pins(net, pinned)
    assert net.gen.at[g["原町"], "p_mw"] == 1200.0
    assert net.gen.at[g["石炭2"], "p_mw"] == pytest.approx(300.0)      # 石炭の実績 1,500 − 観測 1,200
    assert net.gen.at[g["東新潟"], "p_mw"] == pytest.approx(300.0)
    assert led["tohoku"]["unit_pinned_mw"] == pytest.approx(1200.0)
    assert led["tohoku"]["unit_over_fuel_mw"] == 0.0


def test_fuel_actuals_unchanged_without_pins():
    from scripts import export_day_flows as edf
    net, g = _net()
    fm = {"tohoku": {"fuels": {"demand": [1000.0] * 24, "coal": [1500.0] * 24, "lng": [300.0] * 24}}}
    led = edf.apply_fuel_actuals(net, fm, 5, island="east")
    assert net.gen.at[g["原町"], "p_mw"] == pytest.approx(1500.0)
    assert "unit_pinned_mw" not in led["tohoku"]


def test_zone_closure_skips_pinned_units_when_others_run():
    from src.powerflow import zone_closure as zc
    net, g = _net()                       # 発電 1,000・需要 1,000 → 域外へ 0
    led = zc.close_zone_balance(net, {"tohoku": 300.0}, island="east", exclude={g["原町"]})
    assert net.gen.at[g["原町"], "p_mw"] == 400.0                    # 観測で決まっている発電機は動かさない
    assert led["tohoku"]["moved_mw"] == pytest.approx(300.0)
    assert net.gen.at[g["東新潟"], "p_mw"] + net.gen.at[g["小さい"], "p_mw"] == pytest.approx(900.0)


def test_contains_needs_long_name_compatible_fuel_and_plausible_capacity():
    pp = pytest.importorskip("pandapower")
    net, g = _net()
    g["所内"] = pp.create_gen(net, 0, p_mw=1.0, max_p_mw=5.0, type="hydro", name="奥美濃所内水力発電所")
    g["太陽光"] = pp.create_gen(net, 0, p_mw=1.0, max_p_mw=2.0, type="solar", name="山川入船町指宿市発電所")
    g["酒田"] = pp.create_gen(net, 0, p_mw=1.0, max_p_mw=700.0, type="coal", name="酒田臨海火力発電所")
    plants = {("tohoku", "奥美濃発電所"): {"fuel": "hydro", "mw": [1200.0] * 24, "n_units": 6},     # 容量 5 の所内水力には結ばない
              ("tohoku", "船町発電所"): {"fuel": "gas", "mw": [10.0] * 24, "n_units": 1},            # 2 字の「含む」は使わない
              ("tohoku", "入船町発電所"): {"fuel": "gas", "mw": [1.0] * 24, "n_units": 1},           # 燃料が食い違う
              ("tohoku", "酒田臨海"): {"fuel": "coal", "mw": [600.0] * 24, "n_units": 1}}
    pins, led = ua.match_plants(net, plants, "east")
    assert set(pins) == {("tohoku", "酒田臨海")}
    assert pins[("tohoku", "酒田臨海")] == [g["酒田"]]


def test_hks_dir_follows_env(tmp_path, monkeypatch):
    """毎時の処理は本体のチェックアウトの置き場を AJG_HKS_DIR で渡す(作業ツリーの data/external には無い)。"""
    monkeypatch.delenv("AJG_HKS_DIR", raising=False)
    assert ua.hks_dir(tmp_path) == tmp_path / "data" / "external" / "occto" / "hks"
    d = tmp_path / "store" / "hks"
    d.mkdir(parents=True)
    (d / "hks_20261101_20261103.csv").write_text("x", encoding="utf-8")
    monkeypatch.setenv("AJG_HKS_DIR", str(d))
    assert [p.name for p in ua.find_files(tmp_path)] == ["hks_20261101_20261103.csv"]
