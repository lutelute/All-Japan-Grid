"""正典の潮流が使う、網への足し算 2 つ(無効電力の補償・介入#37 の都心給電の仮の変圧器).

2026-10-24 に src/powerflow/pipeline.py から移した(docs/reports/project_structure_2026-10-21.md の B1)。
pipeline.py は旧系譜の build_and_solve(snapped・reconstruction)も持つので、正典の潮流
(full_from_built)と配布ケースの書き出しが、この 2 つのためだけに旧系譜を読み込んでいた。
中身は移す前と同じ。旧来の import 先(src.powerflow.pipeline)からも使える。
"""

import pandapower as pp


def add_reactive_compensation(net, factor=0.6):
    """Add capacitive shunts at load buses to counter undervoltage.

    factor = fraction of each load bus's reactive demand supplied locally by a
    shunt capacitor (q_mvar < 0 injects Q). Models the reactive compensation
    (capacitor banks / SVC) that real grids deploy but OSM omits, so solved
    voltages are not artificially depressed.
    """
    if factor <= 0 or len(net.load) == 0:
        return 0
    by_bus = net.load[net.load["in_service"]].groupby("bus")["q_mvar"].sum()
    n = 0
    for bus, q in by_bus.items():
        if q > 0:
            pp.create_shunt(net, bus=int(bus), q_mvar=-factor * float(q), p_mw=0.0)
            n += 1
    return n


def add_provisional_infeed(net, min_load_mw=100.0, max_dist_km=40.0):
    """介入#37: 都心給電の必然接続(仮) — オーナー承認 2026-08-30.

    「良い。仮が事実でないかもしれないなら、それを明記しておけば正典として
    良い」(オーナー) — 本関数が作る変圧器は名前に **(仮)・実経路未確認** を
    刻み、全件を台帳(戻り値)に出す。無効化フラグあり。

    背景: 上位系(≥275kV)への変圧器を持たない同階級線クラスタが実負荷を
    抱えるとACの解が存在しない(西の非収束の根因 — 大阪都心154kVクラスタ、
    docs/reports/west_ac_probe2_2026-08-30.md)。関西の開示系統図は実名匿名化
    (転載禁止)で出典つき回復が不可能。論法は推定母線と同じ:
    **負荷が現に供給されている以上、上位系からの給電経路の存在は電気的必然。
    存在のみを主張し、経路・パラメータは(仮)と明記する**。

    検出: 同一電圧階級(60≤kv<275)の線連結クラスタで、(a)どのバスも上位への
    変圧器を持たず (b)クラスタ負荷合計≥min_load_mw のもの。
    負荷集計(2026-08-30 第8波改良): クラスタ自階級の負荷に加え、**クラスタを
    取り除くと系統から孤立する無電源成分の純負荷**(下流変圧器配下など、
    クラスタが唯一の給電元である負荷)を算入する。動機=大阪三国型の見逃し:
    味生/西三国154クラスタ(自負荷39MW)の下に77kV 118MWがぶら下がり、旧集計
    では閾値100MW未満で不検出→大阪77網から2段直列変圧器の逆潮給電になって
    いた(vm 0.73、docs/reports/west_ac_wave7_2026-08-30.md)。
    接続: クラスタ最大負荷バス → 地理的最近傍の≥275kVバスへ変圧器1台
    (sn=負荷×1.5・vk12%=階級典型値)。**実在の経路が判明したら置換される暫定**。
    max_dist_km(2026-08-30追加): 最近傍がこれより遠い場合は縫合せず台帳のみ
    (capped=True)。動機=誤帰属ノード同士の遠距離縫合の検出面化(神保原104MWが
    誤region由来の榛名へ44km縫合された事例 — 介入#38で帰属自体は是正済みだが、
    将来の同型を電気接続でなく台帳に浮かせる)。

    Returns: ledger list(dict) — kv/load_mw/n_bus/cluster_names/to_upper/
    upper_kv/dist_km/sn_mva。呼び出し側は結果JSONへ全件保存すること。
    """
    import json as _json
    import math as _math
    import networkx as _nx
    from collections import defaultdict

    def _geo(b):
        try:
            g = _json.loads(net.bus.at[b, "geo"])
            return float(g["coordinates"][0]), float(g["coordinates"][1])
        except Exception:  # noqa: BLE001
            return None

    g = _nx.Graph()
    for _, r in net.line[net.line.in_service].iterrows():
        fb, tb = int(r.from_bus), int(r.to_bus)
        if abs(net.bus.at[fb, "vn_kv"] - net.bus.at[tb, "vn_kv"]) < 0.5:
            g.add_edge(fb, tb)
    has_up = {int(r.lv_bus) for _, r in
              net.trafo[net.trafo.in_service].iterrows()}
    # 全結線グラフ(線+変圧器) — 下流専属負荷の判定用
    g_all = _nx.Graph()
    for _, r in net.line[net.line.in_service].iterrows():
        g_all.add_edge(int(r.from_bus), int(r.to_bus))
    for _, r in net.trafo[net.trafo.in_service].iterrows():
        g_all.add_edge(int(r.hv_bus), int(r.lv_bus))
    gen_at = defaultdict(float)
    for tbl in ("gen", "sgen", "ext_grid"):
        df = getattr(net, tbl)
        if len(df) == 0:
            continue
        sel = df[df.in_service] if "in_service" in df.columns else df
        for _, r in sel.iterrows():
            gen_at[int(r.bus)] += 1.0   # 電源の存在のみ見る(出力は不問)

    def _downstream_mw(comp):
        """クラスタcompを除去したとき孤立する無電源成分の純負荷合計。"""
        if not all(b in g_all for b in comp):
            gsub = g_all.subgraph([b for b in g_all if b not in comp])
        else:
            gsub = g_all.subgraph(set(g_all.nodes) - set(comp))
        # comp に隣接していた成分だけ調べれば十分
        seen, total = set(), 0.0
        for b in comp:
            for nb in g_all.neighbors(b):
                if nb in comp or nb in seen or nb not in gsub:
                    continue
                cc = _nx.node_connected_component(gsub, nb)
                seen |= cc
                lo = sum(load_at.get(x, 0.0) for x in cc)
                ge = sum(gen_at.get(x, 0.0) for x in cc)
                # 主系統(電源つき成分)は数えない。無電源の孤立成分のみ
                if lo > 0 and ge < 1e-6:
                    total += lo
        return total
    load_at = defaultdict(float)
    for _, r in net.load[net.load.in_service].iterrows():
        load_at[int(r.bus)] += float(r.p_mw)
    clusters = []
    for comp in _nx.connected_components(g):
        kv = float(net.bus.at[next(iter(comp)), "vn_kv"])
        if kv < 60 or kv >= 275 or any(b in has_up for b in comp):
            continue
        own = sum(load_at.get(b, 0.0) for b in comp)
        down = _downstream_mw(comp)
        load = own + down
        if load < min_load_mw:
            continue
        big = max(comp, key=lambda b: load_at.get(b, 0.0))
        names = sorted({str(net.bus.at[b, "name"])[:14] for b in comp
                        if load_at.get(b, 0) > 0})[:4]
        if not names:
            names = sorted({str(net.bus.at[b, "name"])[:14]
                            for b in comp})[:2]
        clusters.append(dict(kv=kv, n_bus=len(comp),
                             load_mw=round(load, 1),
                             downstream_mw=round(down, 1),
                             anchor_bus=int(big), names=names))
    ups = [(b, _geo(b)) for b in net.bus.index
           if net.bus.at[b, "in_service"] and net.bus.at[b, "vn_kv"] >= 275]
    ups = [(b, gg) for b, gg in ups if gg]
    ledger = []
    for c in sorted(clusters, key=lambda c: -c["load_mw"]):
        ga = _geo(c["anchor_bus"])
        if not ga or not ups:
            continue
        ub, ug = min(ups, key=lambda bg: (bg[1][0]-ga[0])**2 +
                     (bg[1][1]-ga[1])**2)
        dist_km = _math.hypot((ug[0]-ga[0])*91, (ug[1]-ga[1])*111)
        if dist_km > max_dist_km:
            ledger.append(dict(
                kv=c["kv"], load_mw=c["load_mw"], n_bus=c["n_bus"],
                cluster_names=c["names"],
                to_upper=str(net.bus.at[ub, "name"])[:20],
                upper_kv=float(net.bus.at[ub, "vn_kv"]),
                dist_km=round(dist_km, 1), sn_mva=0.0, capped=True))
            continue
        sn = max(300.0, 1.5 * c["load_mw"])
        pp.create_transformer_from_parameters(
            net, hv_bus=int(ub), lv_bus=int(c["anchor_bus"]), sn_mva=sn,
            vn_hv_kv=float(net.bus.at[ub, "vn_kv"]), vn_lv_kv=c["kv"],
            vkr_percent=0.5, vk_percent=12.0, pfe_kw=0.0, i0_percent=0.0,
            name=f"(仮)都心給電#37 {c['kv']:.0f}kV 実経路未確認")
        ledger.append(dict(
            kv=c["kv"], load_mw=c["load_mw"],
            downstream_mw=c.get("downstream_mw", 0.0), n_bus=c["n_bus"],
            cluster_names=c["names"],
            to_upper=str(net.bus.at[ub, "name"])[:20],
            upper_kv=float(net.bus.at[ub, "vn_kv"]),
            dist_km=round(_math.hypot((ug[0]-ga[0])*91,
                                      (ug[1]-ga[1])*111), 1),
            sn_mva=round(sn, 0)))
    return ledger
