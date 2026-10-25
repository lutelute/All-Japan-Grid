"""解いた島のネットから電力会社エリア(bus.zone)を切り出す.

エリアの最大連結成分だけ残し、成分の外へ出る枝(線路・変圧器)を境界として返す。
切り出したネットでは、境界の枝 1 本ごとに内側のバスへ固定出力の発電機
(``type="boundary"``、出力 = 島の AC で枝が運んでいた潮流、電圧 = 島の解)を置く。
これで切り出したネット単体の AC が島の解をそのまま再現する。

境界の潮流は「正典モデルが示す値」で、実測ではない。境界をどう与えるか
(固定・容量内の変数・別の値)は呼び出し側が決める。発電機として置くのは、
MATPOWER の gen 行の PMIN/PMAX を差し替えるだけで変えられるようにするため。
"""
from __future__ import annotations

import math

import networkx as nx
import pandas as pd
import pandapower as pp
import pandapower.topology as top

BOUNDARY_COLS = ["name", "kind", "index", "branch_name", "inner_bus", "outer_bus",
                 "neighbor_zone", "vn_kv", "rate_mva", "p_out_mw", "q_out_mvar"]


def branch_rate_mva(net, kind: str, i) -> float:
    """枝の容量 [MVA]。線路 = √3·V·I·並列数(理論値。運用容量ではない)、変圧器 = sn_mva·並列数。"""
    t = net[kind]
    par = int(t.at[i, "parallel"])
    if kind == "line":
        return float(math.sqrt(3) * net.bus.at[t.at[i, "from_bus"], "vn_kv"] * t.at[i, "max_i_ka"] * par)
    return float(t.at[i, "sn_mva"] * par)


def extract_zone(net, zone: str):
    """AC で解いた pandapower ネット → (切り出したネット, 境界 DataFrame, 情報 dict).

    境界の p_out_mw / q_out_mvar は内側の端で測った、エリアから出る向きを正とする潮流。
    """
    if net.res_bus.empty:
        raise ValueError("net に潮流の解がない(先に AC を解く)")
    zb = net.bus.index[(net.bus["zone"] == zone) & net.bus["in_service"]]
    if len(zb) == 0:
        raise ValueError(f"zone={zone!r} のバスが無い")
    g = top.create_nxgraph(pp.select_subnet(net, set(zb)))
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    main = comps[0]

    rows = []
    for kind, fb, tb, pf, qf, pt, qt in (
            ("line", "from_bus", "to_bus", "p_from_mw", "q_from_mvar", "p_to_mw", "q_to_mvar"),
            ("trafo", "hv_bus", "lv_bus", "p_hv_mw", "q_hv_mvar", "p_lv_mw", "q_lv_mvar")):
        t, r = net[kind], net["res_" + kind]
        for i in t.index[t["in_service"]]:
            a, b = int(t.at[i, fb]), int(t.at[i, tb])
            if (a in main) == (b in main):
                continue
            inner, outer = (a, b) if a in main else (b, a)
            if not net.bus.at[outer, "in_service"]:
                continue
            p, q = (r.at[i, pf], r.at[i, qf]) if a in main else (r.at[i, pt], r.at[i, qt])
            rate = branch_rate_mva(net, kind, i)
            rows.append((f"boundary:{kind}{i}", kind, i, str(t.at[i, "name"]), inner, outer,
                         net.bus.at[outer, "zone"], float(net.bus.at[inner, "vn_kv"]),
                         float(rate), float(p), float(q)))
    # 境界が 0 本(エリア = 島全体。北海道・沖縄)でも数の列は数にしておく(空だと object になり集計で落ちる)
    bd = pd.DataFrame(rows, columns=BOUNDARY_COLS).astype(
        {"index": int, "inner_bus": int, "outer_bus": int, "vn_kv": float, "rate_mva": float,
         "p_out_mw": float, "q_out_mvar": float})

    sub = pp.select_subnet(net, main, include_results=True)
    vm, va = net.res_bus["vm_pu"], net.res_bus["va_degree"]
    for x in bd.itertuples():
        pp.create_gen(sub, x.inner_bus, p_mw=-x.p_out_mw, vm_pu=float(vm[x.inner_bus]),
                      min_p_mw=-x.p_out_mw, max_p_mw=-x.p_out_mw,
                      name=x.name, type="boundary")
    added_slack = None
    if not sub.ext_grid["in_service"].any():
        # エリアに島のスラックが無い → 最大の発電機のバスに島の解の電圧・位相で立てる
        real = sub.gen[sub.gen["in_service"] & (sub.gen["type"] != "boundary")]
        if real.empty:
            raise ValueError(f"zone={zone!r} の主成分に発電機もスラックも無い")
        added_slack = int(real.at[real["max_p_mw"].fillna(real["p_mw"]).idxmax(), "bus"])
        pp.create_ext_grid(sub, added_slack, vm_pu=float(vm[added_slack]),
                           va_degree=float(va[added_slack]), name=f"zone_slack_{added_slack}")
    info = {"zone": zone, "n_zone_bus": len(zb), "n_bus": len(main),
            "n_fragments": len(comps) - 1, "fragment_buses": len(zb) - len(main),
            "n_boundary": len(bd), "boundary_net_out_mw": round(float(bd["p_out_mw"].sum()), 1),
            "added_slack_bus": added_slack}
    return sub, bd, info
