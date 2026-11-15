"""介入#64: 22・33 kV を正典の級として持つ(2026-11-15)。前は 66 kV に丸めていた。"""
from __future__ import annotations

import importlib

import pytest


def test_classes_include_22_and_33():
    from src.utils.voltage import KV_CLASSES, LOW_KV_CLASSES
    assert LOW_KV_CLASSES is True
    assert KV_CLASSES[:3] == (22, 33, 66)


def test_clean_voltage_keeps_low_classes():
    from src.powerflow.snapped_topology import _clean_voltage
    assert _clean_voltage(33.0) == 33.0
    assert _clean_voltage(22.0) == 22.0
    assert _clean_voltage(30.0) == 33.0 and _clean_voltage(44.0) == 33.0
    assert _clean_voltage(25.0) == 22.0
    assert _clean_voltage(60.0) == 66.0 and _clean_voltage(50.0) == 66.0
    assert _clean_voltage(0.0) == 0.0


def test_all_tables_share_one_class_list():
    from src.powerflow import line_capacity, snapped_topology, full_from_built
    from src.utils.voltage import KV_CLASSES
    assert tuple(snapped_topology.VALID_VOLTAGES) == KV_CLASSES
    assert tuple(full_from_built.VALID_KV) == KV_CLASSES
    assert tuple(line_capacity.KV_CLASSES) == KV_CLASSES
    assert line_capacity.nearest_class(33) == 33


def test_low_classes_have_line_and_trafo_parameters():
    from src.converter.line_parameters import get_line_parameters
    from src.powerflow.transforms import _get_trafo_params
    for kv in (22, 33):
        p = get_line_parameters(kv, 50)
        assert p["max_i_ka"] > 0 and p["x_ohm_per_km"] > 0
    assert _get_trafo_params(66, 33)["sn_mva"] == 30
    assert _get_trafo_params(77, 22)["sn_mva"] == 40


def test_switch_restores_old_rounding(monkeypatch):
    import src.utils.voltage as v
    import src.powerflow.snapped_topology as st
    monkeypatch.setenv("AJG_LOW_KV_CLASSES", "0")
    try:
        importlib.reload(v)
        importlib.reload(st)
        assert v.KV_CLASSES[0] == 66
        assert st._clean_voltage(33.0) == 66.0
    finally:
        monkeypatch.delenv("AJG_LOW_KV_CLASSES")
        importlib.reload(v)
        importlib.reload(st)


def test_mixed_tag_splits_into_low_class_circuit():
    """併架のタグ 77;22 は 77 kV と 22 kV の 2 回線になる(前は 22 kV を丸めた架空の 66 kV の回線になった)。"""
    from src.powerflow.snapped_topology import _parse_voltage_classes
    assert _parse_voltage_classes("77000;22000") == {77.0, 22.0}
    assert _parse_voltage_classes("66000;22000") == {66.0, 22.0}


def test_overview_takes_line_voltage_not_endpoint_coordinate():
    """全国の概観は線の電圧を潮流の出力の kv から取る(2026-11-15)。

    同じ敷地に電圧の違う母線が重なるので、端の座標から引くと後に書いた母線の電圧になり、500 kV の幹線 158 本が
    下の帯に入っていた。帯のファイルの線の kv が帯の範囲にあることと、知られた 500 kV の幹線が 500 kV の帯にあることを見る。
    """
    import json
    from pathlib import Path
    full = Path(__file__).resolve().parents[1] / "docs" / "data" / "powerflow_full"
    lines = json.loads((full / "hokkaido_ac_lines.geojson").read_text(encoding="utf-8"))["features"]
    assert all("kv" in f["properties"] for f in lines if not f["properties"].get("trafo"))
    from scripts.gen_national_overview_from_full import TIER_BANDS
    for b, lo, hi in TIER_BANDS:
        feats = json.loads((full / f"national_overview_{b}kv.geojson").read_text(encoding="utf-8"))["features"]
        assert all(lo <= f["properties"]["kv"] and (hi is None or f["properties"]["kv"] < hi) for f in feats), b
        if b == 500:
            names = {f["properties"]["name"] for f in feats}
            assert {"新三河幹線", "駿遠幹線", "信濃幹線"} <= names
