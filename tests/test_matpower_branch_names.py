"""export_net の枝の名前と行の対応 — 停止中の線があっても変圧器の名前がずれない(介入#56 で表に出た)。

書き出しの branch は動いている線・動いている変圧器の順に詰めて並ぶが、`_pd2ppc_lookups["branch"]` の
範囲は停止中の線も数える。以前はこの範囲で名前を振っていたので、停止中の線の数だけ変圧器の行がずれ、
末尾の変圧器は名前が付かなかった。
"""

import pandapower as pp
import pandas as pd

from src.converter.matpower_case import export_net, live_branch_rows


def _net():
    net = pp.create_empty_network(sn_mva=100.0)
    hv = [pp.create_bus(net, vn_kv=275.0, name=f"H{i}") for i in range(3)]
    lv = pp.create_bus(net, vn_kv=154.0, name="L")
    pp.create_ext_grid(net, hv[0])
    for k, (f, t) in enumerate(((0, 1), (1, 2), (0, 2))):
        pp.create_line_from_parameters(net, hv[f], hv[t], length_km=20.0, r_ohm_per_km=0.03, x_ohm_per_km=0.3,
                                       c_nf_per_km=10.0, max_i_ka=2.0, name=f"line{k}")
    net.line.at[1, "in_service"] = False  # 真ん中の線を開く
    pp.create_transformer(net, hv[2], lv, std_type="100 MVA 220/110 kV", name="trafoA")
    pp.create_load(net, lv, p_mw=50.0, q_mvar=10.0)
    pp.runpp(net)
    return net


def test_names_follow_rows_with_out_of_service_line(tmp_path):
    net = _net()
    export_net("t", net, True, str(tmp_path), validate=False)
    bn = pd.read_csv(tmp_path / "t_branchname.csv")
    assert list(bn.kind) == ["line", "line", "trafo"]
    assert list(bn.name) == ["line0", "line2", "trafoA"]
    rows = live_branch_rows(net, {"branch": bn[["F_BUS", "T_BUS"]].to_numpy()})
    assert [(k, i) for k, i, _ in rows] == [("line", 0), ("line", 2), ("trafo", 0)]
