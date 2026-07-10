"""E10: 系統モデル(build後)の接続状態を返す — エディタでOSMと並列表示し接続を確認する。

`build_network_snapped` の結果(snapped topology)を、節点(島/本系統で色分け)+接続線として返す。
これにより「OSMでは線が見えるのにモデルでは島(=未接続)」がエディタ上で一目で分かる。
"""
from collections import defaultdict

import networkx as nx

REGIONS_ALL = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
               "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]


def built_view_all(join_untagged_tips=False, regions=None, stitch_km=0.15):
    """全国ビュー = 全地域の built モデルを合成(設計R1: 単一の正=全国も地域も同じ build を描く)。

    Phase1: 全国も生OSMでなく build を描く(編集が全国に反映)。
    Phase2(越境stitch): 地域別buildは県境で線を切り島化させる。**地域をまたいで同一物理点
    (同座標~stitch_km以内の越境変電所/鉄塔)を繋ぎ**、全国でグローバルに連結性を計算する。
    同座標重複は座標キーで自動統合・近接(~100m)は明示stitch。証拠=同一座標(捏造でない)。
    """
    regions = regions or REGIONS_ALL
    nodes, edges, by_region = [], [], {}
    for r in regions:
        try:
            v = built_view(r, join_untagged_tips=join_untagged_tips)
        except Exception:   # noqa: BLE001 — 1地域の失敗で全国を止めない
            v = None
        if not v:
            by_region[r] = {"error": True}
            continue
        for n in v["nodes"]:
            n["region"] = r
        nodes.extend(v["nodes"])
        edges.extend(v["edges"])
        by_region[r] = {"n_nodes": v["n_nodes"], "n_edges": v["n_edges"],
                        "n_components": v["n_components"],
                        "main_size": v["main_size"], "island_nodes": v["n_island_nodes"]}

    def k5(la, lo):
        return (round(la, 5), round(lo, 5))

    # Phase3: 連結性は単一権威(src.powerflow.connectivity)で計算 = national.py(潮流)と統一。
    # 4周波数同期島ごとに(東50Hz/西60Hzを別に)・越境は同電圧階級stitch(~110m)・OCCTO ACタイを連結。
    # 旧「全国一枚グラフ・任意階級stitch・タイ無し」だと東西を誤連結し島判定が潮流と食い違っていた。
    from src.powerflow.connectivity import compute_connectivity
    conn = compute_connectivity(nodes, edges)
    main = conn["main_keys"]
    for n in nodes:
        n["main"] = k5(n["lat"], n["lon"]) in main      # 所属周波数島の最大成分=本系統
    for e in edges:
        if e.get("a") and e.get("b"):
            e["main"] = tuple(e["a"]) in main and tuple(e["b"]) in main
    # ACタイを表示枝に追加(島内 region 対を繋ぐ物理連系=本系統連結の一部)
    for ka, kb, tname in conn["tie_edges"]:
        edges.append({"path": [list(ka), list(kb)], "a": list(ka), "b": list(kb),
                      "main": (ka in main and kb in main), "par": 1, "kv": 0,
                      "name": tname, "tie": True})
    meta = conn["meta"]
    island = sum(1 for n in nodes if not n["main"])
    return {"region": "all", "n_nodes": len(nodes), "n_edges": len(edges),
            "nodes": nodes, "edges": edges, "by_region": by_region,
            "main_size": len(main), "n_components": sum(meta["components"].values()),
            "n_island_nodes": island, "n_stitch": meta["n_stitch"], "n_tie": meta["n_tie"],
            "islands": meta["components"],
            "note": "周波数島(east/west/hokkaido/okinawa)別に連結性計算+OCCTO ACタイ"
                    "(Phase3: national.pyと単一権威で統一)"}


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
    nm = {s.id: (s.name or "") for s in net.substations}
    # 出典透過(Phase 1-B): GeoJSONマーカー由来の {field: {src, url}}。
    # ここで落とすと出典は正典(docs/data/built)に永遠に届かない。
    pv = {s.id: getattr(s, "provenance", None) for s in net.substations}
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
        # sub=実変電所 / junction=鉄塔の分岐点(モデルが作る節点)。オーナー指摘:
        # 島として描かれる点の多くは「変電所でなくただの鉄塔」=junction。両者を区別する。
        node = {
            "id": n, "lat": round(la, 5), "lon": round(lo, 5),
            "kv": kv.get(n, 0.0), "comp": comp_of.get(n, -1),
            "main": n in main, "deg": g.degree(n),
            "sub": "_jct_" not in n, "name": nm.get(n, ""),
        }
        if pv.get(n):
            node["src"] = pv[n]
        nodes.append(node)
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
        # 端点(変電所/junction)座標を round5 で添える。エディタの✂切断は a/b を
        # disconnect 編集に載せ、builder の cut機構(端点座標一致)が同じ精度で照合する。
        ea = [round(pos[a][0], 5), round(pos[a][1], 5)] if a in pos else None
        eb = [round(pos[b][0], 5), round(pos[b][1], 5)] if b in pos else None
        # 回線数(num_parallel): 並行2回線等は1枝にまとめ parallel=2 として容量保持される。
        # 「片方に吸収された」のは描画が1本なだけで、電気的には2回線(容量2倍)を保持している。
        par = int(getattr(ln, "num_parallel", 1) or 1)
        edges.append({"path": path, "main": (a in main and b in main),
                      "a": ea, "b": eb, "par": par,
                      "kv": float(getattr(ln, "voltage_kv", 0) or 0),
                      "name": getattr(ln, "name", "") or ""})
    return {
        "region": region, "n_nodes": len(nodes), "n_edges": len(edges),
        "n_components": len(comps), "main_size": len(main),
        "n_island_nodes": len(nodes) - len(main),
        "nodes": nodes, "edges": edges,
    }
