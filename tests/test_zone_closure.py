"""区域の収支を連系線の公表値に合わせる直し(介入 #62 の案)の試験。"""
from __future__ import annotations

import datetime as dt

import pytest

from src.powerflow import zone_closure as zc

# 2026-11-08 12 時ごろの公表値に近い数字(順方向が正、MW)
IC = {"hokuhon": -68.0, "soma": 4962.0, "fc": -283.0, "kansai_chugoku": -1890.0, "anan_kihoku": -973.0,
      "honshi": -643.0, "kanmon": -1480.0, "fence_chubu": -231.0, "fence_hokuriku": 102.0, "fence_kansai": -290.0}


def test_zone_net_export_signs():
    e = zc.zone_net_export(IC)
    assert e["tohoku"] == pytest.approx(4962 + 68)        # 東京へ送り、北海道へも送る
    assert e["tokyo"] == pytest.approx(-4962 - 283)       # 東北と中部から受ける
    assert e["kyushu"] == pytest.approx(1480)             # 関門で中国へ送る
    assert e["shikoku"] == pytest.approx(973 + 643)       # 阿南紀北と本四で送る
    assert e["kansai"] == pytest.approx(-1890 - 973 + 290)


def test_zone_net_export_closes_per_island():
    """島の中の区域を足すと、島の外への受け渡し(直流の連系と FC)だけが残る。"""
    e = zc.zone_net_export(IC)
    assert e["hokkaido"] == pytest.approx(IC["hokuhon"])
    assert e["tohoku"] + e["tokyo"] == pytest.approx(-IC["hokuhon"] + IC["fc"])
    west = sum(e[z] for z in ("chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu"))
    # 60 Hz の島は FC の分だけ出入りする。3 つのフェンスの食い違い(中部 − 北陸 − 関西)がそのまま残る
    ring = IC["fence_chubu"] - IC["fence_hokuriku"] - IC["fence_kansai"]
    assert west == pytest.approx(-IC["fc"] + ring)


def test_zone_net_export_needs_every_tie():
    part = {k: v for k, v in IC.items() if k != "fence_kansai"}
    assert zc.zone_net_export(part) is None


def test_kohyo04_two_kansai_chugoku_rows_are_summed():
    ic = {k: v for k, v in IC.items() if k != "kansai_chugoku"}
    ic.update(kansai_chugoku_w=-1000.0, kansai_chugoku_e=-890.0)
    assert zc.zone_net_export(ic)["chugoku"] == pytest.approx(zc.zone_net_export(IC)["chugoku"])


def test_hourly_instant_is_trapezoid():
    day = dt.date(2026, 11, 9)
    t = lambda h, m: dt.datetime(2026, 11, 9, h, m)  # noqa: E731
    stamps = {t(0, 0): 100.0, t(0, 30): 200.0, t(1, 0): 400.0, t(1, 30): 400.0}
    got = zc.hourly_instant(stamps, day)
    assert got[0] == pytest.approx((100 + 2 * 200 + 400) / 4)
    assert got[1] == pytest.approx(400.0)      # 次の時刻の頭が無いときは 2 点の平均
    assert got[2] is None


def test_spread_up_respects_capacity_and_reports_overflow():
    import numpy as np
    p = np.array([100.0, 300.0])
    cap = np.array([120.0, 1000.0])
    add, over = zc._spread(p, cap, 200.0)
    assert add.sum() == pytest.approx(200.0)
    assert add[0] == pytest.approx(20.0)       # 容量まで
    assert over == 0.0
    add, over = zc._spread(p, np.array([120.0, 320.0]), 200.0)
    assert add.sum() == pytest.approx(200.0)
    assert over == pytest.approx(160.0)        # 動いている発電機の余地は 40 だけ


def test_spread_down_is_proportional_and_keeps_stopped_units_stopped():
    import numpy as np
    add, over = zc._spread(np.array([0.0, 100.0, 300.0]), np.array([500.0, 500.0, 500.0]), -100.0)
    assert list(add) == pytest.approx([0.0, -25.0, -75.0])
    assert over == 0.0


def _two_zone_net():
    pp = pytest.importorskip("pandapower")
    net = pp.create_empty_network()
    b = [pp.create_bus(net, vn_kv=275.0, name=f"b{i}", zone=z) for i, z in enumerate(["tohoku", "tohoku", "tokyo", "tokyo"])]
    for i in range(3):
        pp.create_line_from_parameters(net, b[i], b[i + 1], length_km=10, r_ohm_per_km=0.01, x_ohm_per_km=0.3,
                                       c_nf_per_km=10, max_i_ka=2)
    iso = pp.create_bus(net, vn_kv=66.0, name="iso", zone="tokyo")       # 主系統につながらない孤立片
    pp.create_load(net, iso, p_mw=50.0)
    pp.create_load(net, b[1], p_mw=400.0)
    pp.create_load(net, b[3], p_mw=1000.0)
    g = {}
    g["th_a"] = pp.create_gen(net, b[0], p_mw=300.0, max_p_mw=900.0, type="gas")
    g["th_stop"] = pp.create_gen(net, b[0], p_mw=0.0, max_p_mw=800.0, type="nuclear")
    g["th_pv"] = pp.create_gen(net, b[1], p_mw=100.0, max_p_mw=100.0, type="solar")
    g["tk_a"] = pp.create_gen(net, b[2], p_mw=600.0, max_p_mw=700.0, type="gas")
    # 立地は東北の母線だが東京の電源(zone_src)。介入 #26 と同じ数え方をする
    g["tk_far"] = pp.create_gen(net, b[0], p_mw=200.0, max_p_mw=1000.0, type="coal")
    net.gen["zone_src"] = ""
    net.gen.at[g["tk_far"], "zone_src"] = "tokyo"
    pp.create_ext_grid(net, b[3])
    return net, g


def test_close_zone_balance_moves_only_running_dispatchable_units():
    net, g = _two_zone_net()
    # 東北: 発電 300+0+100=400、需要 400 → 0。東京: 600+200=800、需要 1000 → −200(孤立片の 50 は数えない)
    led = zc.close_zone_balance(net, {"tohoku": 500.0, "tokyo": -500.0, "kyushu": 123.0}, island="east")
    assert set(led) == {"tohoku", "tokyo"}                      # 島に居ない区域には当てない
    assert led["tohoku"]["before_mw"] == pytest.approx(0.0)
    assert led["tokyo"]["before_mw"] == pytest.approx(-200.0)
    assert net.gen.at[g["th_a"], "p_mw"] == pytest.approx(800.0)   # 動いている火力が受け持つ
    assert net.gen.at[g["th_stop"], "p_mw"] == 0.0                 # 止まっている炉は動かさない
    assert net.gen.at[g["th_pv"], "p_mw"] == pytest.approx(100.0)  # 太陽光は使わない
    assert net.gen.at[g["tk_a"], "p_mw"] + net.gen.at[g["tk_far"], "p_mw"] == pytest.approx(500.0)
    assert net.gen.at[g["tk_a"], "p_mw"] / net.gen.at[g["tk_far"], "p_mw"] == pytest.approx(3.0)   # 出力比のまま減らす
    assert led["tohoku"]["over_capacity_mw"] == 0.0


def test_close_zone_balance_records_overflow_beyond_capacity():
    net, g = _two_zone_net()
    led = zc.close_zone_balance(net, {"tohoku": 900.0}, island="east")
    # 動いている火力の余地は 600。残り 300 は容量を超えて載せ、帳簿に残す
    assert led["tohoku"]["moved_mw"] == pytest.approx(900.0)
    assert led["tohoku"]["over_capacity_mw"] == pytest.approx(300.0)
    assert net.gen.at[g["th_a"], "p_mw"] == pytest.approx(1200.0)


def test_boundary_series_matches_day_boundary_signs():
    ic = {"kind": "実績", "source": "x", "hourly": {"fc": [100.0] * 24, "hokuhon": [-50.0] * 24}}
    assert zc.boundary_series(ic, "west")[("chubu", "tokyo")][0] == 100.0     # FC の順方向は東京→中部
    assert zc.boundary_series(ic, "east")[("chubu", "tokyo")][0] == -100.0
    assert zc.boundary_series(ic, "east")[("hokkaido", "tohoku")][0] == -50.0  # 北本の順方向は北海道→東北
    assert zc.boundary_series(ic, "hokkaido")[("hokkaido", "tohoku")][0] == 50.0
    assert zc.boundary_series(ic, "okinawa") == {}


def test_load_ic_from_kohyo04(tmp_path):
    rows = ['"2026/11/01 22:58 UPDATE"',
            '"対象年月日","時刻","連系線名","順方向運用容量(MW)","逆方向運用容量(MW)","順方向マージン(MW)","逆方向マージン(MW)","順方向計画潮流(MW)","逆方向計画潮流(MW)"']
    for stamp, v in (("00:30", 100.0), ("01:00", 300.0), ("01:30", 500.0)):
        rows.append(f'"2026/11/01","{stamp}","周波数変換設備","900","900","0","0","{v}","{-v}"')
    p = tmp_path / "kohyo_04_202611.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8-sig")
    got = zc.load_ic_from_kohyo04(p, dt.date(2026, 11, 1))
    assert got["kind"] == "計画"
    assert got["hourly"]["fc"][0] == pytest.approx(200.0)     # 00:30 と 01:00 のコマ = 0 時台
    assert got["hourly"]["fc"][1] is None
