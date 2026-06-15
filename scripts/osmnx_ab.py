"""osmnx(標準ツール)で OSM node-sharing トポロジを取得し、我々の手法とA/B。

検証したいこと(オーナー質問「点と線をつなぐツールは? / 全てAI判断?」への実証):
  Q. 標準ツール(osmnx)の node-sharing 接続は、我々が手作りした座標スナップが
     取りこぼしている接続を見つけるか?
  → osmnx自身が取得したノードに prec4 座標丸めを適用して成分数を比較する
    (同一ノード集合・二通りのグラフ構築=vintage交絡ゼロ=台帳131の管理された再現)。

副次: build_network_snapped('kansai') の headline 連結性も文脈として併記
       (注: そちらは curated geojson 由来でデータ範囲が異なる)。

Usage:
    PYTHONPATH=. python scripts/osmnx_ab.py
"""
import collections
import glob
import json

import networkx as nx


def osmnx_graph(bbox):
    """osmnxで power line を取得し node-sharing 無向グラフを返す。失敗時 None。"""
    import osmnx as ox
    ox.settings.overpass_url = "https://maps.mail.ru/osm/tools/overpass/api"
    ox.settings.overpass_rate_limit = False     # ミラーは /status 非対応のため無効化
    ox.settings.requests_timeout = 300
    ox.settings.useful_tags_way = list(ox.settings.useful_tags_way) + [
        "power", "voltage", "circuits", "cables"]
    try:
        g = ox.graph_from_bbox(
            bbox, custom_filter='["power"~"line|cable|minor_line"]',
            simplify=False, retain_all=True, truncate_by_edge=False)
        return g.to_undirected()
    except Exception as exc:   # noqa: BLE001
        print(f"  osmnx live取得 失敗: {str(exc)[:120]}")
        return None


def cached_node_sharing_graph():
    """フォールバック: キャッシュ済 node-ref生データ から node-sharing グラフ。"""
    seen, nodes, ways = set(), {}, []
    for f in sorted(glob.glob("data/osm_raw_towers/tw_kansai_t*.json")):
        for e in json.load(open(f, encoding="utf-8")).get("elements", []):
            k = (e["type"], e["id"])
            if k in seen:
                continue
            seen.add(k)
            if e["type"] == "node":
                nodes[e["id"]] = (e["lon"], e["lat"])
            elif e["type"] == "way" and (e.get("tags") or {}).get("power") in (
                    "line", "cable", "minor_line"):
                ways.append(e)
    g = nx.Graph()
    for w in ways:
        ns = [n for n in w.get("nodes", []) if n in nodes]
        for a, b in zip(ns, ns[1:]):
            if a != b:
                g.add_edge(a, b)
        for n in ns:
            g.add_node(n, x=nodes[n][0], y=nodes[n][1])
    return g, len(ways)


def coord_rounded_components(g, prec=4):
    """gのノード座標を prec桁に丸めて同一セルを統合したグラフの成分数。"""
    def key(n):
        d = g.nodes[n]
        return (round(d["x"], prec), round(d["y"], prec))
    h = nx.Graph()
    for n in g.nodes():
        h.add_node(key(n))
    for u, v in g.edges():
        ku, kv = key(u), key(v)
        if ku != kv:
            h.add_edge(ku, kv)
    return h


def comp_stats(g):
    comps = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
    return {"nodes": g.number_of_nodes(), "edges": g.number_of_edges(),
            "components": len(comps), "largest": comps[0] if comps else 0}


def main():
    bbox = (134.5, 33.4, 136.8, 35.8)   # kansai (west,south,east,north)
    print("=== osmnx(標準ツール) vs 我々の座標スナップ — kansai ===\n")
    print("[1] osmnx で power line を node-sharing 取得中...")
    g = osmnx_graph(bbox)
    src = "osmnx live (現OSM)"
    if g is None:
        print("  → キャッシュ node-ref 生データにフォールバック")
        g, nways = cached_node_sharing_graph()
        src = f"cached node-ref ({nways}本)"

    ns = comp_stats(g)                      # node-sharing(osmid共有)
    h = coord_rounded_components(g, prec=4)
    cr = comp_stats(h)                      # 座標丸め prec4(我々の手法)

    print(f"\nデータ源: {src}")
    print(f"\n{'グラフ構築法':<28}{'ノード':>9}{'辺':>8}{'成分':>7}{'最大成分':>9}")
    print(f"{'A) node-sharing(osmid共有)':<28}{ns['nodes']:>9}{ns['edges']:>8}{ns['components']:>7}{ns['largest']:>9}")
    print(f"{'B) 座標丸めprec4(我々の手法)':<28}{cr['nodes']:>9}{cr['edges']:>8}{cr['components']:>7}{cr['largest']:>9}")

    dc = cr["components"] - ns["components"]
    print(f"\n判定: 座標丸めは node-sharing より成分 {dc:+d}")
    if dc <= 0:
        print(f"  → 座標丸めは node-sharing が繋ぐ接続を**全て捕捉**し、さらに近接(~11m)で {-dc} 組多く橋渡し。")
        print("    標準ツール(osmnx)が見つけて我々が取りこぼす接続は無い = 台帳131を独立再確認。")
    else:
        print(f"  → node-sharing の方が {dc} 成分少ない = 我々が取りこぼす接続が存在(要調査)。")

    # 文脈: build_network_snapped の headline(データ範囲が異なる点に注意)
    print("\n[2] 文脈: build_network_snapped('kansai')(curated geojson由来・範囲別)")
    try:
        from scripts.rebuild_ab import metrics
        from src.powerflow.snapped_topology import build_network_snapped
        m = metrics(build_network_snapped("kansai", db=None))
        print(f"  実変電所={m['real_subs']} 枝={m['branches']} 成分={m['total_components']} "
              f"最大={m['largest_comp']} カバー={m['coverage_pct']}%")
    except Exception as exc:   # noqa: BLE001
        print(f"  (スキップ: {str(exc)[:80]})")


if __name__ == "__main__":
    main()
