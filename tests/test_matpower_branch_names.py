"""export_net の枝の名前と行の対応 — 停止中の枝があっても名前・容量がずれない(介入#56 で表に出た)。

書き出しの branch は動いている線・動いている変圧器の順に詰めて並ぶが、`_pd2ppc_lookups["branch"]` の
範囲は停止中の線も数える。以前はこの範囲で名前を振っていたので、停止中の線の数だけ変圧器の行がずれ、
末尾の変圧器は名前が付かなかった。ゾーンの書き出し(scripts/export_zone_case.py)は同じ範囲で容量を振って
いたので、停止中の線がゾーンの中にあると IndexError で止まった。
"""

import numpy as np
import pandas as pd
import pytest

pp = pytest.importorskip("pandapower")

from src.converter.matpower_case import export_net, live_branch_rows  # noqa: E402
from src.powerflow.zone_extract import branch_rate_mva, extract_zone  # noqa: E402

LN = dict(length_km=20.0, r_ohm_per_km=0.03, x_ohm_per_km=0.3, c_nf_per_km=10.0, max_i_ka=2.0)


def _net(zone=False):
    """275 kV の 3 バスの輪(真ん中の線は停止)と、154 kV へ降ろす変圧器 2 台(1 台目は停止)。
    zone=True なら全体をゾーン A にし、外に B の 1 バスを線 1 本でつなぐ。"""
    net = pp.create_empty_network(sn_mva=100.0)
    z = {"zone": "A"} if zone else {}
    hv = [pp.create_bus(net, vn_kv=275.0, name=f"H{i}", **z) for i in range(3)]
    lv = pp.create_bus(net, vn_kv=154.0, name="L", **z)
    pp.create_ext_grid(net, hv[0])
    for k, (f, t) in enumerate(((0, 1), (1, 2), (0, 2))):
        pp.create_line_from_parameters(net, hv[f], hv[t], name=f"line{k}", **LN)
    net.line.at[1, "in_service"] = False
    pp.create_transformer(net, hv[1], lv, std_type="100 MVA 220/110 kV", name="trafoX", in_service=False)
    pp.create_transformer(net, hv[2], lv, std_type="100 MVA 220/110 kV", name="trafoA")
    pp.create_load(net, lv, p_mw=50.0, q_mvar=10.0)
    if zone:
        out = pp.create_bus(net, vn_kv=275.0, name="B0", zone="B")
        pp.create_line_from_parameters(net, hv[2], out, name="tie", **LN)
        pp.create_load(net, out, p_mw=20.0, q_mvar=4.0)
    pp.runpp(net, calculate_voltage_angles=True)
    return net


def test_names_follow_rows_with_out_of_service_branches(tmp_path):
    net = _net()
    export_net("t", net, True, str(tmp_path), validate=False)
    bn = pd.read_csv(tmp_path / "t_branchname.csv")
    assert list(bn.kind) == ["line", "line", "trafo"]
    assert list(bn.name) == ["line0", "line2", "trafoA"]
    rows = live_branch_rows(net, bn[["F_BUS", "T_BUS"]].to_numpy())
    assert [(k, i) for k, i, _ in rows] == [("line", 0), ("line", 2), ("trafo", 1)]


def test_mismatch_raises(tmp_path):
    net = _net()
    export_net("t", net, True, str(tmp_path), validate=False)
    br = pd.read_csv(tmp_path / "t_branchname.csv")[["F_BUS", "T_BUS"]].to_numpy()
    with pytest.raises(ValueError):
        live_branch_rows(net, br[::-1])   # 並びが違う
    with pytest.raises(ValueError):
        live_branch_rows(net, br[:2])     # 行が足りない
    with pytest.raises(ValueError):
        live_branch_rows(net, np.vstack([br, br[:1]]))  # 行が余る


def test_zone_path_rates_follow_rows(tmp_path):
    """export_zone_case.py と同じ順(切り出し → AC → export_net → 容量を振る)。"""
    sub, _bd, _info = extract_zone(_net(zone=True), "A")
    assert not sub.line.in_service.all() and not sub.trafo.in_service.all()
    pp.runpp(sub, calculate_voltage_angles=True)
    export_net("A", sub, True, str(tmp_path), validate=False)
    bn = pd.read_csv(tmp_path / "A_branchname.csv")
    rate = [0.0] * len(bn)
    for kind, i, row in live_branch_rows(sub, bn[["F_BUS", "T_BUS"]].to_numpy()):
        rate[row] = branch_rate_mva(sub, kind, i)
    assert list(bn.name) == ["line0", "line2", "trafoA"]
    assert rate[0] == pytest.approx(branch_rate_mva(sub, "line", 0))
    assert rate[2] == pytest.approx(branch_rate_mva(sub, "trafo", 1))
