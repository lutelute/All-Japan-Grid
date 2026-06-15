"""E10: 系統モデル(build後)の接続状態を返す — エディタでOSMと並列表示し接続を確認する。

`build_network_snapped` の結果(snapped topology)を、節点(島/本系統で色分け)+接続線として返す。
これにより「OSMでは線が見えるのにモデルでは島(=未接続)」がエディタ上で一目で分かる。
"""
import networkx as nx


def built_view(region, data_dir=None, join_untagged_tips=False):
    """系統モデルの節点・接続線・連結性を返す(エディタの『系統』レイヤ用)。

    join_untagged_tips: 無タグの行き止まり鉄塔tipを近接既知ノードに吸着(台帳132・検証済)。
    """
    from src.powerflow.snapped_topology import build_network_snapped
    net = build_network_snapped(region, data_dir=data_dir,
                                join_untagged_tips=join_untagged_tips)
    if net is None:
        return None
    pos = {s.id: (s.latitude, s.longitude) for s in net.substations}
    kv = {s.id: float(s.voltage_kv) for s in net.substations}
    g = nx.Graph()
    g.add_nodes_from(s.id for s in net.substations)
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    main = set(comps[0]) if comps else set()
    comp_of = {}
    for i, c in enumerate(comps):
        for n in c:
            comp_of[n] = i

    nodes = []
    for n, (la, lo) in pos.items():
        nodes.append({
            "id": n, "lat": round(la, 5), "lon": round(lo, 5),
            "kv": kv.get(n, 0.0), "comp": comp_of.get(n, -1),
            "main": n in main, "deg": g.degree(n),
        })
    edges = []
    for ln in net.transmission_lines:
        a, b = ln.from_substation_id, ln.to_substation_id
        # 実OSM幾何(鉄塔を通る折れ線)を保持 → エディタでOSM線と重ねて描ける。
        # 鉄塔は次数2なら畳まれ bus にはならないが、線形(path)は失われない。
        coords = getattr(ln, "coordinates", None) or []
        path = [[round(la, 5), round(lo, 5)] for (la, lo) in coords
                if la is not None and lo is not None]
        if len(path) < 2:  # 幾何が無ければ bus 端点で直線フォールバック
            if a in pos and b in pos:
                path = [[round(pos[a][0], 5), round(pos[a][1], 5)],
                        [round(pos[b][0], 5), round(pos[b][1], 5)]]
            else:
                continue
        edges.append({"path": path, "main": (a in main and b in main)})
    return {
        "region": region, "n_nodes": len(nodes), "n_edges": len(edges),
        "n_components": len(comps), "main_size": len(main),
        "n_island_nodes": len(nodes) - len(main),
        "nodes": nodes, "edges": edges,
    }
