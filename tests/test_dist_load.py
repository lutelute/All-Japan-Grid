"""介入#65: ajg-dist の配電の需要で県内の配り方を決める(既定 OFF)。dist の置き場が無くても回る試験。"""
from __future__ import annotations

import pandapower as pp
import pytest

from src.powerflow import dist_load


CAT = [
    {"osm_key": "w1", "lat": "43.00", "lon": "141.00"},
    {"osm_key": "w2", "lat": "43.02", "lon": "141.00"},
    {"osm_key": "w3", "lat": "44.00", "lon": "142.00"},
]
LS = (
    "f_area,region,agj_bus,p_mw,q_mvar,osm_keys\n"
    "50hz,hokkaido,hokkaido_sub_1,30.0,10.0,w1;w2\n"      # 2 つの起点をまとめた行 → 座標は平均
    "50hz,hokkaido,hokkaido_sub_9,5.0,1.0,w3\n"
    "50hz,hokkaido,,7.0,2.0,w404\n"                         # 一覧に無い起点 → 使わない
    "50hz,hokkaido,hokkaido_sub_2,0.0,0.0,w3\n"              # 需要 0 → 使わない
)


def test_parse_points_averages_roots_and_skips_unknown():
    pts = dist_load.parse_points(LS, CAT)
    assert len(pts) == 2
    assert pts[0]["lat"] == pytest.approx(43.01) and pts[0]["p_mw"] == 30.0
    assert pts[0]["region"] == "hokkaido"


def _net():
    net = pp.create_empty_network()
    xy = {}
    for name, kv, lat, lon, zone in [
        ("a66", 66.0, 43.00, 141.00, "hokkaido"),
        ("b66", 66.0, 43.05, 141.00, "hokkaido"),
        ("c22", 22.0, 43.00, 141.02, "hokkaido"),
        ("d187", 187.0, 43.00, 141.00, "hokkaido"),   # 77 kV より上 → 配る先にしない
        ("e66", 66.0, 45.00, 142.00, "hokkaido"),     # 起点から遠い
    ]:
        b = pp.create_bus(net, vn_kv=kv, name=name, type="b", zone=zone)
        xy[b] = (lon, lat)
    return net, xy


def _vw(net):
    return lambda b: {66.0: 0.5, 22.0: 0.066, 187.0: 0.25}[float(net.bus.at[b, "vn_kv"])]


def test_bus_weights_spread_by_voltage_and_distance_and_skip_others():
    net, xy = _net()
    pts = [
        {"lat": 43.00, "lon": 141.00, "p_mw": 10.0, "region": "hokkaido"},
        {"lat": 35.0, "lon": 139.0, "p_mw": 99.0, "region": "tokyo"},      # ほかの島
        {"lat": 41.0, "lon": 140.0, "p_mw": 50.0, "region": "hokkaido"},   # 半径の中に点が無い
    ]
    w, led = dist_load.bus_weights(net, pts, radius_km=20.0, vweight=_vw(net), lonlat=lambda n, b: xy[b])
    names = {net.bus.at[b, "name"]: v for b, v in w.items()}
    assert "d187" not in names and "e66" not in names
    assert sum(w.values()) == pytest.approx(10.0)                 # 使った起点の需要だけ
    assert names["a66"] > names["b66"] > 0                          # 近いほど重い
    assert names["a66"] > names["c22"]                              # 電圧の重み
    assert led["n_points"] == 2 and led["n_points_used"] == 1 and led["n_points_outside_radius"] == 1


def test_points_near_observed_bus_are_not_used():
    net, xy = _net()
    a = int(net.bus.index[net.bus.name == "a66"][0])
    pts = [{"lat": 43.001, "lon": 141.0, "p_mw": 10.0, "region": "hokkaido"}]
    w, led = dist_load.bus_weights(net, pts, radius_km=20.0, pinned={a}, vweight=_vw(net),
                                   lonlat=lambda n, b: xy[b])
    assert w == {} and led["n_points_near_pinned"] == 1


def test_allocate_loads_keeps_zone_total_and_follows_dist(monkeypatch):
    import src.powerflow.full_from_built as ff
    net, xy = _net()
    monkeypatch.setattr(ff, "_bus_lonlat", lambda n, b: xy[b])
    pts = (tuple(sorted({"lat": 43.05, "lon": 141.0, "p_mw": 10.0, "region": "hokkaido"}.items())),)
    monkeypatch.setattr(dist_load, "load_points", lambda: (pts, {"store": "x", "n_points": 1}))
    cfg = {"regional_peak_demand_mw": {"hokkaido": 100.0}, "load_factor": 1.0, "power_factor": 0.95,
           "voltage_weights": {66: 0.5, 22: 0.066, 187: 0.25}}
    net_off, _ = _net()
    tot_off = ff.allocate_loads(net_off, cfg)
    tot_on = ff.allocate_loads(net, cfg, dist_share={"radius_km": 20.0})
    assert tot_on == pytest.approx(tot_off) == pytest.approx(100.0)   # 区域の合計は同じ
    by = net.load.groupby("bus").p_mw.sum()
    name = lambda b: net.bus.at[b, "name"]
    loads = {name(b): p for b, p in by.items()}
    assert loads.get("b66", 0) > loads.get("a66", 0)                   # 起点に近い b66 が重い
    assert loads.get("d187", 0) == 0 and loads.get("e66", 0) == 0      # 配る先でない・遠い
    assert net._dist_share_ledger["n_points_used"] == 1


def test_falls_back_to_voltage_weights_when_no_dist_point_reaches(monkeypatch):
    import src.powerflow.full_from_built as ff
    net, xy = _net()
    monkeypatch.setattr(ff, "_bus_lonlat", lambda n, b: xy[b])
    monkeypatch.setattr(dist_load, "load_points", lambda: ((), {"store": "x", "n_points": 0}))
    cfg = {"regional_peak_demand_mw": {"hokkaido": 100.0}, "load_factor": 1.0, "power_factor": 0.95,
           "voltage_weights": {66: 0.5, 22: 0.066, 187: 0.25}}
    ff.allocate_loads(net, cfg, dist_share={"radius_km": 20.0})
    assert net.load.p_mw.sum() == pytest.approx(100.0)
    assert len(net._dist_share_ledger["fallback_groups"]) == 1


def test_switch_is_off_by_default(monkeypatch):
    """既定は OFF。環境変数 AJG_DIST_LOAD_SHARE=1 か --dist-load-share でだけ入る。"""
    import inspect
    import src.powerflow.full_from_built as ff
    monkeypatch.delenv("AJG_DIST_LOAD_SHARE", raising=False)
    assert inspect.signature(ff.allocate_loads).parameters["dist_share"].default is None
    src = inspect.getsource(ff.main)
    assert 'os.environ.get("AJG_DIST_LOAD_SHARE", "0") == "1"' in src


def test_store_location_comes_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AJG_DIST_ROOT", str(tmp_path / "dist"))
    monkeypatch.delenv("AJG_DIST_STORE", raising=False)
    assert dist_load.dist_store() == tmp_path / "dist" / "data" / "std"
    monkeypatch.setenv("AJG_DIST_STORE", str(tmp_path / "s"))
    assert dist_load.dist_store() == tmp_path / "s"
