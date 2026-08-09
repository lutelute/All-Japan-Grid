"""発電機の接続規則（介入#24 `--gen-attach`）のゲート。

2026-08-09 の組み合わせ探索で、接続規則が過負荷を最も強く動かす軸だと分かった
（east cap で過負荷 603→551、太陽光の是正と併せて 303）。規則を本番へ移したので、

  1. 既定 `nearest` が**従来と完全に同じ**であること（無効化手段が本当に効くこと）
  2. 各規則が意図どおりバスを選ぶこと
  3. what-if が本番へ**委譲**していること（実装の二重化＝過去2回誤った原因を禁じる）

を固定する。実データを使わない合成系統なので速い。
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PF = ROOT / "scripts" / "run_full_powerflow_from_db.py"
WGV = ROOT / "scripts" / "capacity" / "whatif_gen_voltage.py"

pytestmark = pytest.mark.skipif(not PF.exists(), reason="潮流本体が無い")


def _pf():
    spec = importlib.util.spec_from_file_location("pf_under_test", PF)
    m = importlib.util.module_from_spec(spec)
    sys.modules["pf_under_test"] = m
    spec.loader.exec_module(m)
    return m


def _net():
    """66kV が近く・500kV が遠い、実系統の縮図。

    bus0 66kV（発電所から 1km）／bus1 500kV（12km）を幹線で支える。
    最寄り規則ならどんな大型機も bus0 に載る。
    """
    import pandapower as pp
    net = pp.create_empty_network()
    b0 = pp.create_bus(net, vn_kv=66.0, name="near66")
    b1 = pp.create_bus(net, vn_kv=500.0, name="far500")
    b2 = pp.create_bus(net, vn_kv=66.0, name="tail66")
    b3 = pp.create_bus(net, vn_kv=500.0, name="tail500")
    pp.create_line_from_parameters(net, b0, b2, length_km=5.0, r_ohm_per_km=0.1,
                                   x_ohm_per_km=0.3, c_nf_per_km=0.0, max_i_ka=0.6)
    pp.create_line_from_parameters(net, b1, b3, length_km=5.0, r_ohm_per_km=0.02,
                                   x_ohm_per_km=0.25, c_nf_per_km=0.0, max_i_ka=4.0)
    return net, b0, b1


def _nodes_bus_of(b0, b1):
    """発電所(35.00, 139.00) から bus0 は約 1km、bus1 は約 12km。"""
    nodes = {"n0": {"lat": 35.009, "lon": 139.0, "sub": 1},
             "n1": {"lat": 35.108, "lon": 139.0, "sub": 1}}
    return nodes, {"n0": b0, "n1": b1}


def _plant(mw):
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [139.0, 35.0]},
            "properties": {"osm_id": 1, "name": "試験火力", "fuel_type": "gas",
                           "capacity_mw": mw}}


def _attach(pf, monkeypatch, mode, mw):
    """島の発電所リストを差し替えて 1 機だけ繋ぐ。"""
    import json as _json
    net, b0, b1 = _net()
    nodes, bus_of = _nodes_bus_of(b0, b1)
    monkeypatch.setattr(pf, "ISLAND_OF", {"testregion": ("testisland", 50.0)},
                        raising=False)
    monkeypatch.setattr(pf.os.path, "exists", lambda p: "testregion_plants" in str(p))
    payload = _json.dumps({"features": [_plant(mw)]})

    import io
    real_open = open

    def fake_open(path, *a, **k):
        if "testregion_plants" in str(path):
            return io.StringIO(payload)
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)
    info = pf.attach_generators(net, bus_of, nodes, "testisland", territory=False,
                                attach_mode=mode, stats=True)
    monkeypatch.setattr("builtins.open", real_open)
    kv = float(net.bus.at[int(net.gen.at[0, "bus"]), "vn_kv"]) if len(net.gen) else None
    return info, kv


def test_nearest_is_the_default_and_picks_the_close_66kv(monkeypatch):
    """既定は従来どおり最寄り — 3,600MW でも 1km 先の 66kV に載る（これが真因A）。"""
    pytest.importorskip("pandapower")
    pf = _pf()
    info, kv = _attach(pf, monkeypatch, "nearest", 3600.0)
    assert info["n_gen"] == 1 and kv == 66.0
    assert info["n_moved"] == 0, "既定モードで繋ぎ替えが起きてはいけない"


def test_cap_moves_a_large_unit_to_the_bus_that_can_receive_it(monkeypatch):
    """cap: 受電容量が出力に足りない 66kV を避け、12km 先の 500kV を選ぶ。"""
    pytest.importorskip("pandapower")
    pf = _pf()
    info, kv = _attach(pf, monkeypatch, "cap", 3600.0)
    assert kv == 500.0, "受電容量で選べば大型機は 66kV に載らない"
    assert info["n_moved"] == 1 and info["moved_mw"] == pytest.approx(3600.0)


def test_cap_leaves_a_small_unit_where_it_was(monkeypatch):
    """cap: 66kV が受けきれる小型機は動かさない（外科的であること）。"""
    pytest.importorskip("pandapower")
    pf = _pf()
    info, kv = _attach(pf, monkeypatch, "cap", 5.0)
    assert kv == 66.0 and info["n_moved"] == 0


def test_kvfit_uses_the_ladder_measured_from_the_model(monkeypatch):
    """kvfit: 階級の梯子はモデル自身の導体定数から測る（外部の表を持ち込まない）。"""
    pytest.importorskip("pandapower")
    pf = _pf()
    info, kv = _attach(pf, monkeypatch, "kvfit", 3600.0)
    assert kv == 500.0
    assert "66kV" in (info["ladder_note"] or ""), "梯子がモデル実測から作られていない"


def test_unknown_mode_is_rejected(monkeypatch):
    pytest.importorskip("pandapower")
    pf = _pf()
    with pytest.raises(ValueError):
        _attach(pf, monkeypatch, "somethingelse", 100.0)


# ── 単位系のゲート ────────────────────────────────────────────────────────
def test_bus_incident_mva_counts_parallel_circuits():
    """並列回線を数え落とすと受電容量が半分に出る — この系列で 5 回踏んだ罠。"""
    pytest.importorskip("pandapower")
    import pandapower as pp
    pf = _pf()
    net = pp.create_empty_network()
    a = pp.create_bus(net, vn_kv=110.0)
    b = pp.create_bus(net, vn_kv=110.0)
    pp.create_line_from_parameters(net, a, b, length_km=1.0, r_ohm_per_km=0.1,
                                   x_ohm_per_km=0.3, c_nf_per_km=0.0, max_i_ka=0.5,
                                   parallel=3)
    got = pf.bus_incident_mva(net)[a]
    assert got == pytest.approx(0.5 * 110.0 * math.sqrt(3.0) * 3, rel=1e-6)


def test_required_kv_picks_the_lowest_class_that_can_carry_it():
    pf = _pf()
    ladder = [(66.0, 137.0), (154.0, 533.0), (275.0, 1905.0), (500.0, 6928.0)]
    assert pf.required_kv(100.0, ladder) == 66.0
    assert pf.required_kv(600.0, ladder) == 275.0
    assert pf.required_kv(99999.0, ladder) == 500.0, "運べない出力は最上位へ"
    assert pf.required_kv(100.0, []) == 0.0


# ── 実装の一本化 ──────────────────────────────────────────────────────────
def test_whatif_delegates_to_production():
    """what-if は本番を呼ぶだけであること。写しを戻したらここで落ちる。"""
    src = WGV.read_text(encoding="utf-8")
    assert "pf.attach_generators(" in src, "本番へ委譲していない"
    for leaked in ("def bus_incident_mva", "def class_branch_mva", "def required_kv"):
        assert leaked not in src, f"規則の写しが what-if に戻っている: {leaked}"


def test_disable_switch_is_documented_in_the_ledger():
    """介入#24/#25 が台帳に登録され、無効化手段が書かれていること。"""
    led = (ROOT / "docs" / "MODEL_INTERVENTIONS.md").read_text(encoding="utf-8")
    assert "--gen-attach" in led, "介入#24 が台帳に無い"
    assert "--default-cap" in led, "介入#25 が台帳に無い"
