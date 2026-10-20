"""アンテナ集約 — 低圧デッドエンド連鎖を親バスへ需要保存で畳む計算モデル縮約.

2026-08-20 の試験(docs/reports/trial_trafo_impedance_antenna_2026-08-20.md)で、
west島の素朴AC(フラットスタートNewton)を塞いでいたのは <100kV・次数1の
末端連鎖(バスの26%)であり、これを畳むと既定許容誤差で0.2秒収束・
vm_min 0.725→0.927 になることを実測した。

2026-10-20 に、全部畳まなくても、線路容量を超える負荷が載った木を
電圧降下の見積もりの大きい順に畳めば足りると分かった(west は 2 本・17 バス)。
配布ケースは fold_until でこの最小の縮約を使う。

これは**計算モデルの縮約**であり正典(built)は変更しない
(帳簿つき集約の原則 — feedback_reduction_reality)。負荷・sgen・shuntは
親バスへ移設して需要を保存する。発電機・スラックの載るバスは保護する。
"""
from __future__ import annotations

import copy
from collections import Counter
from typing import Callable, Dict, Iterable, List, Optional, Tuple


def aggregate_antennas(net, kv_max: float = 100.0, max_rounds: int = 60,
                       only: Optional[Iterable[int]] = None) -> Dict:
    """次数1かつ vn_kv<kv_max のバスを親へ畳む(反復・需要保存)。

    Args:
        net: pandapower net(in-place で変更される)。
        kv_max: この電圧未満のバスのみ集約対象。
        max_rounds: 連鎖を畳む最大反復数。
        only: 与えたときは、このバスの集合だけを畳む(要る木だけ畳む用)。

    Returns:
        帳簿 dict: n_removed / n_rounds / moved_load_mw / moved_sgen_mw /
        bus_before / bus_after
    """
    bus_before = len(net.bus)
    allowed = None if only is None else set(int(b) for b in only)
    # 動かした要素の番号で数える(連鎖を何段も運ばれた負荷を段ごとに足すと
    # 重複する — 2026-10-20 まで moved_load_mw はこれで過大だった)
    moved_load: set = set()
    moved_sgen: set = set()
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
                   and int(b) not in protected
                   and (allowed is None or int(b) in allowed)]
        if not victims:
            break
        rounds += 1
        vs = set(int(v) for v in victims)
        for tbl, acc in (("load", moved_load), ("sgen", moved_sgen), ("shunt", None)):
            df = getattr(net, tbl)
            for i in df.index:
                b = int(df.at[i, "bus"])
                if b in vs:
                    if acc is not None:
                        acc.add(i)
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
            "moved_load_mw": round(float(net.load.loc[list(moved_load), "p_mw"].sum()), 1),
            "moved_sgen_mw": round(float(net.sgen.loc[list(moved_sgen), "p_mw"].sum()), 1),
            "bus_before": bus_before, "bus_after": len(net.bus),
            "kv_max": kv_max}


def antenna_trees(net, kv_max: float = 100.0) -> List[Dict]:
    """aggregate_antennas が畳むバスを、親バスごとの木に分けて電圧降下を見積もる。

    降下は木の根(親バス)を 1.0 pu として、下流の負荷 P,Q と枝の R,X から
    ΔV ≈ (R·P + X·Q)/V² を末端まで足したもの(DistFlow の近似。損失は無視)。
    線路容量を超える負荷が載った放射状の木ほど大きくなり、厳しい許容誤差の
    AC を妨げる。降下の大きい順に返す。
    """
    import networkx as nx

    probe = copy.deepcopy(net)
    aggregate_antennas(probe, kv_max=kv_max)
    ant = set(int(b) for b in net.bus.index) - set(int(b) for b in probe.bus.index)

    g = nx.MultiGraph()
    for i, r in net.line[net.line.in_service].iterrows():
        g.add_edge(int(r.from_bus), int(r.to_bus), kind="line", idx=i)
    for i, r in net.trafo[net.trafo.in_service].iterrows():
        g.add_edge(int(r.hv_bus), int(r.lv_bus), kind="trafo", idx=i)

    pq: Dict[int, List[float]] = {}
    for tbl, sign in (("load", 1.0), ("sgen", -1.0)):
        df = getattr(net, tbl)
        for _, r in df[df.in_service].iterrows():
            v = pq.setdefault(int(r.bus), [0.0, 0.0])
            v[0] += sign * float(r.p_mw)
            v[1] += sign * float(r.get("q_mvar", 0.0) or 0.0)
    for _, r in net.shunt[net.shunt.in_service].iterrows():
        pq.setdefault(int(r.bus), [0.0, 0.0])[1] += float(r.q_mvar)

    def z_ohm(u, v):
        ys = []
        for d in g.get_edge_data(u, v).values():
            if d["kind"] == "line":
                ln = net.line.loc[d["idx"]]
                z = complex(ln.r_ohm_per_km, ln.x_ohm_per_km) * float(ln.length_km)
                par = float(ln.get("parallel", 1) or 1)
            else:
                t = net.trafo.loc[d["idx"]]
                zb = float(t.vn_lv_kv) ** 2 / float(t.sn_mva)
                vk, vkr = float(t.vk_percent) / 100, float(t.vkr_percent) / 100
                z = complex(vkr, max(vk * vk - vkr * vkr, 0.0) ** 0.5) * zb
                par = float(t.get("parallel", 1) or 1)
            ys.append(par / z if abs(z) > 1e-9 else 1e9)
        return 1 / sum(ys)

    trees = []
    for comp in nx.connected_components(g.subgraph(ant)):
        roots = {n for b in comp for n in g.neighbors(b) if n not in ant}
        root = next(iter(roots))
        t = nx.bfs_tree(g.subgraph(comp | {root}), root)
        order = list(nx.topological_sort(t))
        down: Dict[int, complex] = {}
        for b in reversed(order):
            p, q = pq.get(b, (0.0, 0.0)) if b in comp else (0.0, 0.0)
            s = complex(p, q) + sum((down[c] for c in t.successors(b)), 0j)
            down[b] = s
        drop = {root: 0.0}
        for b in order:
            for c in t.successors(b):
                z = z_ohm(b, c)
                vn = float(net.bus.at[c, "vn_kv"])
                drop[c] = drop[b] + (z.real * down[c].real + z.imag * down[c].imag) / (vn * vn)
        trees.append({
            "root": root, "root_name": str(net.bus.at[root, "name"]),
            "buses": sorted(comp),
            "names": [str(net.bus.at[b, "name"]) for b in sorted(comp)],
            "kv": sorted({float(net.bus.at[b, "vn_kv"]) for b in comp}),
            "load_mw": round(sum(pq.get(b, (0.0, 0.0))[0] for b in comp), 1),
            "drop_pu": round(max(drop.values()), 4)})
    trees.sort(key=lambda d: -d["drop_pu"])
    return trees


def fold_until(net, converges: Callable, kv_max: float = 100.0,
               max_trees: Optional[int] = None) -> Tuple[object, Optional[Dict]]:
    """降下の大きいアンテナの木から順に畳み、converges(net) が真になった最小の写しを返す。

    全部畳む(aggregate_antennas)と west では 26% のバスが消える。収束を妨げて
    いるのは線路容量を超える負荷が載った少数の木なので、要る分だけ畳む
    (2026-10-20: west は 2 本・17 バスで足りた)。畳んでも収束しなければ
    (None, 帳簿) を返す。帳簿には畳んだ木ごとの根・バス名・負荷・降下を残す。
    """
    trees = antenna_trees(net, kv_max=kv_max)
    limit = len(trees) if max_trees is None else min(max_trees, len(trees))
    k = 0
    while k < limit:
        k = k + 1 if k < 8 else min(k * 2, limit)
        trial = copy.deepcopy(net)
        led = aggregate_antennas(trial, kv_max=kv_max,
                                 only={b for t in trees[:k] for b in t["buses"]})
        if converges(trial):
            led.update(method="fold_until", n_trees=k, n_trees_total=len(trees),
                       trees=trees[:k])
            return trial, led
    return None, {"method": "fold_until", "n_trees": k,
                  "n_trees_total": len(trees), "converged": False}
