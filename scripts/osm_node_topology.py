"""B路線プロトタイプ: 生OSM(ノード参照)から**正確な**接続トポロジを得る。

問題(オーナー指摘): 現GeoJSONはOSMの「ノード参照(どのwayがどのノードで繋がるか)」を
落としており、ビルダーは座標一致で接続を**推測**している→時々ショートカット/取りこぼし。
人間がOSMで見る接続は、way同士が共有するノードで**正確に**決まっている。

本スクリプト: Overpass `out body;`(way→node参照を保持)で取得し、
**共有ノード=接続**として正確なトポロジ(連結成分・接続点)を出す。座標スナップ不要。

Usage:
    PYTHONPATH=. python scripts/osm_node_topology.py --bbox 35.545,135.958,35.572,135.988   # 嶺南
    PYTHONPATH=. python scripts/osm_node_topology.py --region kansai   # 地域bbox(data/region_bbox)
    # 取得した生レスポンスは data/osm_raw/ にキャッシュ(再取得回避)

これはBの基盤(正確トポロジの取得+グラフ化)。フル実装は全国取得+ビルダー統合(段階的)。
"""
import argparse
import collections
import json
import os
import time

import requests

# 過負荷時のフォールバック(maps.mail.ru が比較的安定。private.coffee は本番主経路)
ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
UA = "AllJapanGrid/GridStitch node-topology (lutebass@gmail.com)"
RAW_DIR = os.path.join("data", "osm_raw")


def fetch_power_ways(bbox, cache_key=None, timeout=110):
    """bbox=(s,w,n,e) の power way を node参照つきで取得。生JSONを返す(キャッシュ可)。"""
    if cache_key:
        os.makedirs(RAW_DIR, exist_ok=True)
        cpath = os.path.join(RAW_DIR, f"power_nodes_{cache_key}.json")
        if os.path.exists(cpath):
            return json.load(open(cpath, encoding="utf-8"))
    s, w, n, e = bbox
    q = (f"[out:json][timeout:90];("
         f'way["power"="line"]({s},{w},{n},{e});'
         f'way["power"="cable"]({s},{w},{n},{e});'
         f'way["power"="minor_line"]({s},{w},{n},{e});'
         f'way["power"="substation"]({s},{w},{n},{e});'
         f"); out body; >; out skel qt;")
    last = None
    for attempt in range(3):              # エンドポイント一巡を最大3回(夜間の過負荷耐性)
        for ep in ENDPOINTS:
            try:
                r = requests.post(ep, data={"data": q}, headers={"User-Agent": UA}, timeout=timeout)
                if r.status_code == 200:
                    data = r.json()
                    if cache_key:
                        with open(cpath, "w", encoding="utf-8") as fh:
                            json.dump(data, fh, ensure_ascii=False)
                    return data
                last = f"{ep.split('/')[2]} HTTP {r.status_code}"
            except Exception as exc:   # noqa: BLE001
                last = f"{ep.split('/')[2]} {str(exc)[:60]}"
            time.sleep(3)
        time.sleep(20 * (attempt + 1))    # 一巡失敗→バックオフして再挑戦
    raise RuntimeError(f"Overpass到達不可(最後: {last})")


def build_node_topology(data):
    """共有ノード=接続でトポロジを構築。ways/連結成分/接続点を返す(座標スナップ不要)。"""
    els = data["elements"]
    ways = [e for e in els if e["type"] == "way"]
    nodes = {e["id"]: e for e in els if e["type"] == "node"}
    # ノード→そのノードを含むway
    node2ways = collections.defaultdict(list)
    for wy in ways:
        for nid in wy.get("nodes", []):
            node2ways[nid].append(wy["id"])
    # way隣接(共有ノードで接続)
    adj = collections.defaultdict(set)
    for nid, ws in node2ways.items():
        uws = list(dict.fromkeys(ws))
        for i in range(len(uws)):
            for j in range(i + 1, len(uws)):
                adj[uws[i]].add(uws[j])
                adj[uws[j]].add(uws[i])
    # 連結成分(way単位・union-find風BFS)
    seen = set()
    comps = []
    for wy in ways:
        wid = wy["id"]
        if wid in seen:
            continue
        stack = [wid]
        comp = []
        seen.add(wid)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in adj.get(x, ()):
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        comps.append(comp)
    shared = {nid: list(dict.fromkeys(ws)) for nid, ws in node2ways.items()
              if len(set(ws)) >= 2}
    return {"ways": ways, "nodes": nodes, "adj": adj, "comps": comps, "shared": shared}


def main():
    ap = argparse.ArgumentParser(description="生OSM(ノード参照)から正確接続トポロジ(Bプロトタイプ)")
    ap.add_argument("--bbox", help="s,w,n,e")
    ap.add_argument("--region", help="data の region bbox を使う")
    ap.add_argument("--key", help="キャッシュキー(省略時bbox/region)")
    args = ap.parse_args()
    if args.bbox:
        bbox = tuple(float(x) for x in args.bbox.split(","))
        key = args.key or "bbox_" + "_".join(args.bbox.split(","))
    elif args.region:
        from scripts.fetch_subdivided import load_region_bbox
        bb = load_region_bbox(args.region)
        bbox = (bb["south"], bb["west"], bb["north"], bb["east"])
        key = args.key or args.region
    else:
        raise SystemExit("--bbox か --region を指定")
    data = fetch_power_ways(bbox, cache_key=key)
    topo = build_node_topology(data)
    nway = len(topo["ways"])
    comps = sorted(topo["comps"], key=len, reverse=True)
    print(f"=== 生OSMノードトポロジ ({key}) ===")
    print(f"power way: {nway} / node: {len(topo['nodes'])}")
    print(f"共有ノード(正確な接続点): {len(topo['shared'])}")
    print(f"連結成分(way単位): {len(comps)} / 最大成分 {len(comps[0]) if comps else 0} way")
    kinds = collections.Counter((w.get('tags') or {}).get('power') for w in topo["ways"])
    print(f"power種別: {dict(kinds)}")
    # 最も多くのwayが集まる接続点(=母線/分岐)
    top = sorted(topo["shared"].items(), key=lambda kv: -len(kv[1]))[:5]
    print("接続点の例(集まるway数):")
    for nid, ws in top:
        print(f"  node{nid}: {len(ws)} ways")


if __name__ == "__main__":
    main()
