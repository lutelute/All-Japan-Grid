"""アンテナ集約 — 低圧デッドエンド連鎖を親バスへ需要保存で畳む計算モデル縮約.

2026-08-20 の試験(docs/reports/trial_trafo_impedance_antenna_2026-08-20.md)で、
west島の素朴AC(フラットスタートNewton)を塞いでいたのは <100kV・次数1の
末端連鎖(バスの26%)であり、これを畳むと既定許容誤差で0.2秒収束・
vm_min 0.725→0.927 になることを実測した。

これは**計算モデルの縮約**であり正典(built)は変更しない
(帳簿つき集約の原則 — feedback_reduction_reality)。負荷・sgen・shuntは
親バスへ移設して需要を保存する。発電機・スラックの載るバスは保護する。
"""
from __future__ import annotations

from collections import Counter
from typing import Dict


def aggregate_antennas(net, kv_max: float = 100.0, max_rounds: int = 60) -> Dict:
    """次数1かつ vn_kv<kv_max のバスを親へ畳む(反復・需要保存)。

    Args:
        net: pandapower net(in-place で変更される)。
        kv_max: この電圧未満のバスのみ集約対象。
        max_rounds: 連鎖を畳む最大反復数。

    Returns:
        帳簿 dict: n_removed / n_rounds / moved_load_mw / moved_sgen_mw /
        bus_before / bus_after
    """
    bus_before = len(net.bus)
    moved_load = moved_sgen = 0.0
    removed_total = 0
    rounds = 0
    for _round in range(max_rounds):
        deg: Counter = Counter()
        nbr: dict = {}
        for _, r in net.line.iterrows():
            if not r.in_service:
                continue
            a, b = int(r.from_bus), int(r.to_bus)
            deg[a] += 1
            deg[b] += 1
            nbr.setdefault(a, b)
            nbr.setdefault(b, a)
        for _, r in net.trafo.iterrows():
            if not r.in_service:
                continue
            a, b = int(r.hv_bus), int(r.lv_bus)
            deg[a] += 1
            deg[b] += 1
            nbr.setdefault(a, b)
            nbr.setdefault(b, a)
        protected = set(int(b) for b in net.ext_grid.bus) | \
            set(int(b) for b in net.gen.bus)
        victims = [b for b in net.bus.index
                   if deg.get(int(b), 0) == 1
                   and float(net.bus.at[b, "vn_kv"]) < kv_max
                   and int(b) not in protected]
        if not victims:
            break
        rounds += 1
        vs = set(int(v) for v in victims)
        for tbl, acc in (("load", "load"), ("sgen", "sgen"), ("shunt", None)):
            df = getattr(net, tbl)
            for i in df.index:
                b = int(df.at[i, "bus"])
                if b in vs:
                    if acc == "load":
                        moved_load += float(df.at[i, "p_mw"])
                    elif acc == "sgen":
                        moved_sgen += float(df.at[i, "p_mw"])
                    df.at[i, "bus"] = nbr[b]
        drop_l = [i for i in net.line.index
                  if int(net.line.at[i, "from_bus"]) in vs
                  or int(net.line.at[i, "to_bus"]) in vs]
        net.line.drop(drop_l, inplace=True)
        drop_t = [i for i in net.trafo.index
                  if int(net.trafo.at[i, "hv_bus"]) in vs
                  or int(net.trafo.at[i, "lv_bus"]) in vs]
        net.trafo.drop(drop_t, inplace=True)
        net.bus.drop(list(vs), inplace=True)
        removed_total += len(vs)
    return {"n_removed": removed_total, "n_rounds": rounds,
            "moved_load_mw": round(moved_load, 1),
            "moved_sgen_mw": round(moved_sgen, 1),
            "bus_before": bus_before, "bus_after": len(net.bus),
            "kv_max": kv_max}
