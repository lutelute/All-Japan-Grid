"""全国連結性の単一権威(全面改修 Phase 3)。

`national.py`(潮流アセンブリ)と `built_view_all`(表示)で食い違っていた連結性計算を
**一本化**する。物理的に正しいモデルを node/edge リストだけで(pandapower 非依存・表示にも
潮流前段にも使える軽量版)再現する:

  - **4周波数同期島**(`ISLANDS`): hokkaido(50) / east=tohoku+tokyo(50) /
    west=chubu+hokuriku+kansai+chugoku+shikoku+kyushu(60) / okinawa(60)。
    連結性は**島内のみ**で計算(東50Hz と 西60Hz を AC で繋がない=非同期)。
  - **越境stitch**: 県境スライス重複を **同一電圧階級・~110m**(`STITCH_CELL`)で連結
    (national.stitch_slice_boundaries と同一規則)。
  - **OCCTO AC タイ**(`interconnections.yaml` type=AC): 島内の region 対を明示連結
    (例 ic_002 東北-東京 / ic_004-009 西内)。**非同期(HVDC/FC)は AC 連結に含めない**。

正(島grouping・タイ定義)は `national.ISLANDS` / `national.load_interconnections` に一本化
(本モジュールはそれを import = 単一の正)。
"""
from __future__ import annotations

from collections import defaultdict

import networkx as nx

from src.powerflow.national import ISLANDS, load_interconnections
from src.powerflow.snapped_topology import _haversine_km

STITCH_CELL = 0.001  # ~110m, national.stitch_slice_boundaries(cell=0.001) と同一

# region -> island_id(ISLANDS を反転 = 単一の正)
REGION_ISLAND = {r: isl for isl, (regs, _f) in ISLANDS.items() for r in regs}


def _k5(la, lo):
    return (round(la, 5), round(lo, 5))


def _centroid(nodes):
    pts = [(n["lat"], n["lon"]) for n in nodes if n.get("lat") is not None]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _find_tie_node(region_nodes, sub_name, target_centroid, voltage_kv):
    """タイ端点を終端する node を選ぶ(national._find_tie_bus の node-list 版)。

    1) OCCTO 名称の先頭一致 → 2) 相手region centroid に最も近い高圧 bus。
    """
    if not region_nodes:
        return None
    key = (sub_name or "").replace("変電所", "").replace("変換所", "").strip()
    if len(key) >= 2:
        for n in region_nodes:
            if n.get("name") and key[:3] in n["name"]:
                return n
    hv = [n for n in region_nodes if (n.get("kv") or 0) >= max(voltage_kv * 0.8, 150)]
    cands = hv or region_nodes
    if target_centroid is None:
        return cands[0]
    return min(cands, key=lambda n: _haversine_km(
        n["lat"], n["lon"], target_centroid[0], target_centroid[1]))


def compute_connectivity(nodes, edges, stitch_cell=STITCH_CELL):
    """物理的に正しい全国連結性を計算(周波数島ごと)。

    Args:
        nodes: [{id, lat, lon, kv, region, name}] (built_view / build_editor_data の node)
        edges: [{a:[lat,lon], b:[lat,lon]}] (モデル枝の端点)

    Returns dict:
        main_keys: set[k5]            各島の最大成分(=本系統)に属する座標キー
        island_of: {k5: island_id}    座標キー→所属周波数島
        tie_edges: [(k5_a, k5_b, name)]  追加した AC タイ枝(表示用)
        meta: {n_stitch, n_tie, components:{island: n}, main_size:{island: n}}
    """
    ac_ties, _async = load_interconnections()

    # 島ごとに node を仕分け + 座標→島 索引
    by_island = defaultdict(list)
    island_of = {}
    island_keys = defaultdict(set)   # island -> その島に属する座標キー集合
    for n in nodes:
        isl = REGION_ISLAND.get(n.get("region"))
        if not isl:
            continue
        by_island[isl].append(n)
        k = _k5(n["lat"], n["lon"])
        island_of.setdefault(k, isl)
        island_keys[isl].add(k)

    main_keys = set()
    tie_edges = []
    n_stitch = n_tie = 0
    components = {}
    main_size = {}

    for isl, (regs, _freq) in ISLANDS.items():
        isl_nodes = by_island.get(isl, [])
        if not isl_nodes:
            continue
        g = nx.Graph()
        for n in isl_nodes:
            g.add_node(_k5(n["lat"], n["lon"]))
        # intra: 両端がこの島の枝。
        # 判定は「先勝ちの island_of」でなく **島ごとのキー集合**で行う。
        # 境界スライスの重複で同一座標に別島ラベルのコピーが載ると（東西境界203キー・
        # 北海道/東北17キーを実測）、先勝ち判定では片島がキーを奪い、もう片島の枝が
        # 黙って捨てられて境界が断片化する（下北半島が本系統に合流できなかった実害）。
        keys = island_keys[isl]
        for e in edges:
            a, b = e.get("a"), e.get("b")
            if not a or not b:
                continue
            ka, kb = tuple(a), tuple(b)
            if ka in keys and kb in keys:
                g.add_edge(ka, kb)
        # 越境stitch: 同一電圧階級・~cell・異なる region(national と同一規則)
        cellmap = defaultdict(list)
        for n in isl_nodes:
            cellmap[(round(n["lat"] / stitch_cell), round(n["lon"] / stitch_cell),
                     round(float(n.get("kv") or 0), 1))].append(n)
        for grp in cellmap.values():
            if len(grp) < 2 or len({n.get("region") for n in grp}) < 2:
                continue
            base = _k5(grp[0]["lat"], grp[0]["lon"])
            for n in grp[1:]:
                kk = _k5(n["lat"], n["lon"])
                if kk != base:
                    g.add_edge(base, kk)
                    n_stitch += 1
        # AC タイ: 島内 region 対を明示連結
        reg_nodes = defaultdict(list)
        for n in isl_nodes:
            reg_nodes[n.get("region")].append(n)
        cents = {r: _centroid(reg_nodes.get(r, [])) for r in regs}
        for tie in ac_ties:
            fr, to = tie["from_region"], tie["to_region"]
            if fr in regs and to in regs:
                fn = _find_tie_node(reg_nodes.get(fr, []), tie["from_sub"],
                                    cents.get(to), tie["voltage_kv"])
                tn = _find_tie_node(reg_nodes.get(to, []), tie["to_sub"],
                                    cents.get(fr), tie["voltage_kv"])
                if fn and tn:
                    ka, kb = _k5(fn["lat"], fn["lon"]), _k5(tn["lat"], tn["lon"])
                    if ka != kb:
                        g.add_edge(ka, kb)
                        tie_edges.append((ka, kb, tie["name"]))
                        n_tie += 1
        comps = sorted(nx.connected_components(g), key=len, reverse=True)
        components[isl] = len(comps)
        if comps:
            main_keys |= set(comps[0])
            main_size[isl] = len(comps[0])

    return {
        "main_keys": main_keys, "island_of": island_of, "tie_edges": tie_edges,
        "meta": {"n_stitch": n_stitch, "n_tie": n_tie,
                 "components": components, "main_size": main_size},
    }
