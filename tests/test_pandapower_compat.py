"""pandapower 3.4/3.5 のトップレベル再エクスポート差を吸収する互換層のゲート。

CI(pandapower>=3.4.0 → 3.5.x)で `pp.select_subnet` が消え、N-1 CLI が落ちた(2026-09-02)。
`pp.drop_buses` は 2026-09-01 に同じ形で落ちた。呼び出し側は必ず compat 経由で引くこと。
"""
from __future__ import annotations

import pytest


def test_select_subnet_resolves_and_matches_toolbox():
    pp = pytest.importorskip("pandapower")
    import pandapower.networks as pn
    from src.utils.pandapower_compat import select_subnet

    net = pn.case9()
    sub = select_subnet(net, [0, 3, 4], include_results=False)
    assert len(sub.bus) == 3
    assert set(sub.bus.index) == {0, 3, 4}


def test_drop_buses_resolves():
    pp = pytest.importorskip("pandapower")
    import pandapower.networks as pn
    from src.utils.pandapower_compat import drop_buses

    net = pn.case9()
    n0 = len(net.bus)
    drop_buses(net, [8])
    assert len(net.bus) == n0 - 1


def test_sensitivity_scripts_do_not_call_pp_select_subnet_directly():
    """直呼びが戻ると CI(3.5)でだけ落ちる — ソース文字列で禁止する。"""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for rel in ("scripts/sensitivity/benchmark_sensitivity.py",
                "scripts/sensitivity/build_sensitivity.py",
                "scripts/sensitivity/n1_screening.py",
                "scripts/sensitivity/ibr_hosting_scr.py",
                "src/powerflow/contingency.py",
                "src/powerflow/short_circuit.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "pp.select_subnet(" not in src, f"{rel} が pp.select_subnet を直呼びしている"
        assert "pp.drop_buses(" not in src, f"{rel} が pp.drop_buses を直呼びしている"
