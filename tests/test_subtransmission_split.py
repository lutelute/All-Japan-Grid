"""介入#56: 154 kV 網の分割運用の推定(src/powerflow/subtransmission_split.py)。

降圧点(275 kV 以上→154 kV 級の変圧器の二次側)ごとに受け持ちを決め、境の線だけを開くこと、
降圧点から届かない 154 kV の網と 154 kV 級の外の線は触らないこと、分けても網が切れないこと、
既定 OFF であることを合成系統で固定する。
"""
from __future__ import annotations

from pathlib import Path

import pytest

pp = pytest.importorskip("pandapower")
import pandapower.topology as top  # noqa: E402

import src.powerflow.full_from_built as pf  # noqa: E402
from src.powerflow.subtransmission_split import split_subtransmission  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _line(net, a, b, km, name):
    return pp.create_line_from_parameters(net, a, b, length_km=km, r_ohm_per_km=0.03,
                                          x_ohm_per_km=0.3, c_nf_per_km=0.0, max_i_ka=1.0, name=name)


def _net():
    """275 kV の母線から 154 kV の降圧点 A・B。A0-a1-m-b1-B0 の鎖で、m は A に近い(2 km 対 6 km)。"""
    net = pp.create_empty_network()
    h = pp.create_bus(net, 275.0, name="H275")
    a0, a1, m, b1, b0 = (pp.create_bus(net, 154.0, name=n) for n in ("A0", "a1", "m", "b1", "B0"))
    u1, u2 = (pp.create_bus(net, 154.0, name=n) for n in ("u1", "u2"))   # 降圧点の無い 154 kV
    l1, l2 = (pp.create_bus(net, 66.0, name=n) for n in ("l1", "l2"))
    for lv, nm in ((a0, "T_A"), (b0, "T_B")):
        pp.create_transformer_from_parameters(net, h, lv, sn_mva=300, vn_hv_kv=275, vn_lv_kv=154,
                                              vk_percent=12, vkr_percent=0.3, pfe_kw=0, i0_percent=0,
                                              name=nm)
    pp.create_transformer_from_parameters(net, a1, l1, sn_mva=100, vn_hv_kv=154, vn_lv_kv=66,
                                          vk_percent=12, vkr_percent=0.3, pfe_kw=0, i0_percent=0)
    lines = {"A0-a1": _line(net, a0, a1, 1, "A0-a1"), "a1-m": _line(net, a1, m, 1, "a1-m"),
             "m-b1": _line(net, m, b1, 5, "m-b1"), "b1-B0": _line(net, b1, b0, 1, "b1-B0"),
             "u1-u2": _line(net, u1, u2, 3, "u1-u2"), "l1-l2": _line(net, l1, l2, 3, "l1-l2")}
    pp.create_ext_grid(net, h)
    return net, lines


def _n_components(net):
    return len(list(top.connected_components(top.create_nxgraph(net, respect_switches=False))))


def test_opens_only_the_line_between_two_step_downs():
    net, lines = _net()
    n_comp = _n_components(net)
    led = split_subtransmission(net)
    assert led["n_sources"] == 2 and led["n_opened"] == 1
    assert led["opened"][0]["name"] == "m-b1"
    assert {led["opened"][0]["from_source"], led["opened"][0]["to_source"]} == {"A0", "B0"}
    off = {nm for nm, li in lines.items() if not net.line.at[li, "in_service"]}
    assert off == {"m-b1"}
    # 降圧点の無い 154 kV(u1-u2)と 66 kV の線は触らない。分けても網は切れない
    assert led["n_unowned"] == 2
    assert _n_components(net) == n_comp


def test_apply_false_only_counts():
    net, _ = _net()
    led = split_subtransmission(net, apply=False)
    assert led["n_opened"] == 1 and bool(net.line["in_service"].all())


def test_no_step_down_means_nothing_to_split():
    net, _ = _net()
    net.trafo.loc[net.trafo["name"].isin(["T_A", "T_B"]), "in_service"] = False
    led = split_subtransmission(net)
    assert led["n_sources"] == 0 and led["n_opened"] == 0 and bool(net.line["in_service"].all())


def test_model_hook_follows_the_switch(monkeypatch):
    net, _ = _net()
    monkeypatch.setattr(pf, "SPLIT_154_DEFAULT", False)
    assert pf.model_split_154(net) is None and bool(net.line["in_service"].all())
    assert pf.model_split_154(net, enabled=True)["n_opened"] == 1


def test_model_default_is_off_unless_env_set():
    src = (ROOT / "src/powerflow/full_from_built.py").read_text(encoding="utf-8")
    assert 'SPLIT_154_DEFAULT = (os.environ.get("AJG_SPLIT_154", "0") == "1")' in src, \
        "介入#56 の既定が動いた — 台帳(#56)を先に更新すること"


def test_model_building_paths_call_the_split_hook():
    for rel in ("scripts/sensitivity/build_sensitivity.py", "scripts/sensitivity/benchmark_sensitivity.py",
                "scripts/sensitivity/hosting_capacity.py", "scripts/sensitivity/ibr_hosting_scr.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "model_split_154(net)" in src, f"{rel} が介入#56 の口を通っていない"
    src = (ROOT / "src/powerflow/full_from_built.py").read_text(encoding="utf-8")
    assert "model_split_154(net, enabled=args.split_154)" in src
