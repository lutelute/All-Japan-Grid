"""B路線 夜間ドライバ: 全国を node参照つきで取得 → node-topology連結性を測定 → 現モデルと比較。

オーナー指示(2026-06-15「サーバー等を使い一晩かけてよい」)。Bの根本(生OSMノード参照で正確接続)を
全国規模で実行する第一歩=データ取得(キャッシュ)＋連結性測定。低リスク(取得・分析のみ・本番モデル不変)。

設計:
- 地域bboxをタイル分割→各タイルを Overpass `out body`(node参照)で取得し data/osm_raw/ にキャッシュ
- Overpassエチケット: 新規取得時のみ sleep(キャッシュ済はskip)・複数EPフォールバック・一巡失敗で再挑戦
- 各地域: node-topology(共有ノード=接続)で line連結性、現モデル(snapped)の連結性を併記
- 再開可能: data/osm_raw/b_summary.json に逐次保存・完了地域/タイルはskip

Usage:
    PYTHONPATH=. python scripts/b_overnight.py            # 全地域(小→大)
    PYTHONPATH=. python scripts/b_overnight.py --only shikoku
出力: data/osm_raw/b_summary.json
"""
import argparse
import collections
import json
import os
import time

import yaml

from scripts.osm_node_topology import fetch_power_ways, build_node_topology, RAW_DIR

_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "regions.yaml")


def load_region_bbox(region):
    cfg = yaml.safe_load(open(_CONFIG, encoding="utf-8"))
    return cfg["regions"][region]["bounding_box"]


def subdivide_bbox(bb, rows, cols):
    """bbox dict(lat/lon_min/max) → (lon_min,lat_min,lon_max,lat_max) tiles。"""
    la0, la1, lo0, lo1 = bb["lat_min"], bb["lat_max"], bb["lon_min"], bb["lon_max"]
    dla, dlo = (la1 - la0) / rows, (lo1 - lo0) / cols
    return [(lo0 + c * dlo, la0 + r * dla, lo0 + (c + 1) * dlo, la0 + (r + 1) * dla)
            for r in range(rows) for c in range(cols)]

SLEEP = 22  # Overpassエチケット(新規取得時のみ)
GRID = {"okinawa": (2, 2), "shikoku": (2, 2), "hokuriku": (2, 2),
        "chugoku": (3, 3), "kansai": (3, 3), "kyushu": (3, 3),
        "chubu": (3, 3), "tohoku": (3, 3), "hokkaido": (3, 3), "tokyo": (3, 3)}
ORDER = ["okinawa", "shikoku", "hokuriku", "chugoku", "kansai",
         "kyushu", "chubu", "tohoku", "hokkaido", "tokyo"]


def fetch_region(region):
    bb = load_region_bbox(region)
    rows, cols = GRID.get(region, (3, 3))
    tiles = subdivide_bbox(bb, rows, cols)   # (lon_min,lat_min,lon_max,lat_max)
    seen = set()
    merged = []
    failed = 0
    for i, t in enumerate(tiles):
        s, w, n, e = t[1], t[0], t[3], t[2]
        key = f"{region}_t{i}"
        cpath = os.path.join(RAW_DIR, f"power_nodes_{key}.json")
        cached = os.path.exists(cpath)
        try:
            data = fetch_power_ways((s, w, n, e), cache_key=key)
        except Exception as exc:   # noqa: BLE001 — 1タイル失敗で地域を止めない(再実行で補完)
            print(f"  tile {key} FAIL: {str(exc)[:80]}", flush=True)
            failed += 1
            continue
        for el in data.get("elements", []):
            k = (el["type"], el["id"])
            if k not in seen:
                seen.add(k)
                merged.append(el)
        if not cached:
            time.sleep(SLEEP)
    return {"elements": merged}, failed, len(tiles)


def current_model(region):
    try:
        import networkx as nx
        from src.powerflow.snapped_topology import build_network_snapped
        net = build_network_snapped(region)
        g = nx.Graph()
        g.add_nodes_from(s.id for s in net.substations)
        for ln in net.transmission_lines:
            g.add_edge(ln.from_substation_id, ln.to_substation_id)
        comps = sorted(nx.connected_components(g), key=len, reverse=True)
        big = len(comps[0]) if comps else 0
        return {"subs": len(net.substations), "lines": len(net.transmission_lines),
                "components": len(comps), "largest": big,
                "island_nodes": len(net.substations) - big}
    except Exception as exc:   # noqa: BLE001
        return {"error": str(exc)[:120]}


def measure(region):
    data, failed, ntiles = fetch_region(region)
    topo = build_node_topology(data)
    comps = sorted(topo["comps"], key=len, reverse=True)
    kinds = collections.Counter((w.get("tags") or {}).get("power") for w in topo["ways"])
    return {"region": region, "tiles": ntiles, "tiles_failed": failed,
            "osm_ways": len(topo["ways"]), "osm_nodes": len(topo["nodes"]),
            "connection_points": len(topo["shared"]),
            "line_components": len(comps),
            "largest_component": len(comps[0]) if comps else 0,
            "way_kinds": dict(kinds), "current_model": current_model(region)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="特定地域のみ")
    args = ap.parse_args()
    os.makedirs(RAW_DIR, exist_ok=True)
    out = os.path.join(RAW_DIR, "b_summary.json")
    results = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    done = {r["region"] for r in results if "region" in r and "error" not in r
            and r.get("tiles_failed", 1) == 0}
    order = [args.only] if args.only else ORDER
    for region in order:
        if region in done:
            print("skip(done)", region, flush=True)
            continue
        print(f"=== measure {region} ===", flush=True)
        try:
            res = measure(region)
        except Exception as exc:   # noqa: BLE001
            res = {"region": region, "error": str(exc)[:200]}
        results = [r for r in results if r.get("region") != region] + [res]
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
        cm = res.get("current_model", {})
        print(f"done {region}: node-topo成分{res.get('line_components')} "
              f"接続点{res.get('connection_points')} / 現モデル成分{cm.get('components')} "
              f"島{cm.get('island_nodes')} (tile失敗{res.get('tiles_failed')})", flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
