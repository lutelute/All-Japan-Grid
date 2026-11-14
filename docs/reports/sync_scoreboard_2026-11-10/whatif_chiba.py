#!/usr/bin/env python3
"""試し(正典は変えない): 東京湾の東岸の発電所の繋ぎ先を、地図で見た形に直したら、線路の潮流は観測に近づくか。

  - 姉崎火力(と、同じ発電所の英語名の写し)を、中袖 500 kV → 房総変電所の 275 kV へ(姉崎線 275 kV の行き先)
  - モデルに無い五井火力(2,340 MW)を、五井海岸変電所の 275 kV に足す(五井火力線の起点の近く)
scripts/export_day_flows.py をそのまま呼び、発電機を付ける関数だけ差し替える。
"""
import sys

import src.powerflow.full_from_built as impl

MOVES = {"姉崎火力発電所": "房総変電所 275kV", "Shin Anegasaki Power Plant": "房総変電所 275kV"}
ADD = [("五井火力発電所", "五井海岸変電所 275kV", 2340.0, "gas", "tokyo")]
_orig = impl.attach_generators


def patched(net, bus_of, nodes, island, *a, **k):
    out = _orig(net, bus_of, nodes, island, *a, **k)
    if island != "east":
        return out
    import pandapower as pp
    name2bus = {str(n): int(b) for b, n in net.bus["name"].items()}
    for gname, bname in MOVES.items():
        m = net.gen["name"].astype(str) == gname
        if m.any() and bname in name2bus:
            net.gen.loc[m, "bus"] = name2bus[bname]
            print(f"  [試し] {gname} → {bname}({int(m.sum())} 台)")
    for gname, bname, cap, typ, zone in ADD:
        if bname in name2bus:
            gi = pp.create_gen(net, name2bus[bname], p_mw=0.0, max_p_mw=cap, min_p_mw=0.0, vm_pu=1.0, name=gname, type=typ)
            for c in net.gen.columns:
                if c in ("zone_src",):
                    net.gen.at[gi, c] = zone
            print(f"  [試し] {gname} {cap:.0f} MW を {bname} に足した")
    return out


impl.attach_generators = patched
import scripts.export_day_flows as edf  # noqa: E402

sys.exit(edf.main())
