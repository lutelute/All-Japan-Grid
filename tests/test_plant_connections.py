"""介入#55: 公表の接続で電圧が分かる大型機の台帳(config/plant_connections.yaml)。

規則(#24 cap / #41 capkv)が選んだバスの代わりに、台帳の電圧のバス(構内の点 → 公表の相手 → 最寄り)へ
繋ぐこと、見つからなければ規則のままにすること、台帳を渡さなければ従来と同じことを、合成系統で固定する。
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

pp = pytest.importorskip("pandapower")
import src.powerflow.full_from_built as pf  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _net(junction=False):
    """発電所(35.00, 139.00)から 66kV 1km・154kV 6km・154kV 9km・500kV 12km。

    junction=True で、154kV の分岐点(変電所でない・sub=0)を 0.2 km に足す(構内の鉄塔に当たる)。
    """
    net = pp.create_empty_network()
    names = [("near66", 66.0, 35.009), ("mid154", 154.0, 35.054), ("other154", 154.0, 35.081),
             ("far500", 500.0, 35.108)]
    nodes, bus_of = {}, {}
    for i, (nm, kv, lat) in enumerate(names):
        b = pp.create_bus(net, vn_kv=kv, name=nm)
        t = pp.create_bus(net, vn_kv=kv, name=nm + "_tail")
        pp.create_line_from_parameters(net, b, t, length_km=5.0, r_ohm_per_km=0.02,
                                       x_ohm_per_km=0.3, c_nf_per_km=0.0,
                                       max_i_ka=4.0 if kv >= 500 else 1.0)
        nodes[f"n{i}"] = {"lat": lat, "lon": 139.0, "sub": 1}
        bus_of[f"n{i}"] = b
    if junction:
        j = pp.create_bus(net, vn_kv=154.0, name="jct154")
        pp.create_line_from_parameters(net, j, bus_of["n1"], length_km=6.0, r_ohm_per_km=0.02,
                                       x_ohm_per_km=0.3, c_nf_per_km=0.0, max_i_ka=1.0)
        nodes["j"] = {"lat": 35.0018, "lon": 139.0, "sub": 0}
        bus_of["j"] = j
    return net, nodes, bus_of


def _attach(monkeypatch, mode, ledger, name="試験火力", mw=1000.0, junction=False):
    net, nodes, bus_of = _net(junction)
    monkeypatch.setattr(pf, "ISLAND_OF", {"testregion": ("testisland", 50.0)}, raising=False)
    monkeypatch.setattr(pf.os.path, "exists", lambda p: "testregion_plants" in str(p))
    payload = json.dumps({"features": [{
        "type": "Feature", "geometry": {"type": "Point", "coordinates": [139.0, 35.0]},
        "properties": {"osm_id": 1, "name": name, "fuel_type": "gas", "capacity_mw": mw}}]})
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: io.StringIO(payload)
                        if "testregion_plants" in str(p) else real_open(p, *a, **k))
    info = pf.attach_generators(net, bus_of, nodes, "testisland", territory=False,
                                attach_mode=mode, stats=True, use_sourced=False,
                                plant_ledger=ledger)
    monkeypatch.setattr("builtins.open", real_open)
    return info, str(net.bus.at[int(net.gen.at[0, "bus"]), "name"])


@pytest.mark.parametrize("mode", ["nearest", "cap", "capkv"])
def test_ledger_puts_the_plant_on_the_published_voltage(monkeypatch, mode):
    info, bus = _attach(monkeypatch, mode, {"試験火力": {"kv": 154.0, "to": []}})
    assert bus == "mid154"                                   # 154kV のうち最寄り
    assert info["plant_ledger"]["applied"] == 1 and not info["plant_ledger"]["unresolved"]


def test_ledger_prefers_the_published_counterpart(monkeypatch):
    _, bus = _attach(monkeypatch, "capkv", {"試験火力": {"kv": 154.0, "to": ["other154"]}})
    assert bus == "other154"


def test_ledger_site_point_reaches_a_junction_bus(monkeypatch):
    """構内の点(at)は変電所でない分岐点にも届き、相手(to)より先に選ばれる。"""
    led = {"試験火力": {"kv": 154.0, "to": ["other154"], "at": (35.0018, 139.0)}}
    info, bus = _attach(monkeypatch, "capkv", led, junction=True)
    assert bus == "jct154" and info["plant_ledger"]["changed"][0]["by"] == "at"
    # 分岐点は規則の候補(変電所のバス)には入らない
    _, rule_bus = _attach(monkeypatch, "nearest", None, junction=True)
    assert rule_bus != "jct154"
    # 点の 0.5 km 以内に台帳の電圧のバスが無ければ、相手 → 最寄りに戻る
    _, bus = _attach(monkeypatch, "capkv",
                     {"試験火力": {"kv": 154.0, "to": ["other154"], "at": (35.03, 139.0)}}, junction=True)
    assert bus == "other154"


def test_ledger_falls_back_to_the_rule_when_no_bus_has_the_voltage(monkeypatch):
    _, rule_bus = _attach(monkeypatch, "capkv", None)
    info, bus = _attach(monkeypatch, "capkv", {"試験火力": {"kv": 187.0, "to": []}})
    assert bus == rule_bus and info["plant_ledger"]["unresolved"] == ["試験火力"]


def test_without_ledger_or_for_unlisted_plants_nothing_changes(monkeypatch):
    for mode in ("nearest", "capkv"):
        _, plain = _attach(monkeypatch, mode, None)
        info, other = _attach(monkeypatch, mode, {"別の火力": {"kv": 154.0, "to": []}})
        assert plain == other and info["plant_ledger"]["applied"] == 0
    info, _ = _attach(monkeypatch, "capkv", None)
    assert info["plant_ledger"] is None


def test_ledger_file_is_well_formed_and_carries_no_values():
    led = pf.load_plant_connections()
    assert len(led) >= 20
    raw = (ROOT / "config" / "plant_connections.yaml").read_text(encoding="utf-8")
    import yaml
    for r in yaml.safe_load(raw)["plants"]:
        assert float(r["kv"]) in (500.0, 275.0, 220.0, 187.0, 154.0, 110.0, 77.0, 66.0), r["name"]
        assert r.get("evidence"), r["name"]
        if r.get("at"):                                      # 構内の点は [緯度, 経度]
            assert len(r["at"]) == 2 and 20 < r["at"][0] < 46 and 122 < r["at"][1] < 154, r["name"]
        # 公表の容量・潮流の値は書かない(転載不可)。書いてよいのは線名・電圧・回線数・区間だけ
        assert not re.search(r"\d\s*MW", r["evidence"]), r["name"]


def test_model_building_paths_pass_the_ledger():
    for rel in ("scripts/uc_to_pf_built.py", "scripts/sensitivity/build_sensitivity.py",
                "scripts/sensitivity/benchmark_sensitivity.py", "scripts/sensitivity/hosting_capacity.py",
                "scripts/sensitivity/ibr_hosting_scr.py", "scripts/diagnose_pf_frontier.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "plant_ledger=model_plant_ledger()" in src, f"{rel} が台帳(#55)を渡していない"
    src = (ROOT / "scripts/export_matpower_canonical.py").read_text(encoding="utf-8")
    assert "plant_ledger=load_plant_connections() if use_ledger else None" in src
    src = (ROOT / "src/powerflow/full_from_built.py").read_text(encoding="utf-8")
    assert "if args.plant_connections else None" in src
