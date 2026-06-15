"""全鉄塔(power=tower)をプロットし、接続されていない鉄塔を検証する(geojson再生成の第一歩)。

オーナー方針(2026-06-16)「まず全鉄塔をプロット→未接続がどれだけあるか検証」。
Overpass `out body`(node参照+nodeタグ)で power=tower ノードと power=line/cable/minor_line ways を取得し:
  - 各鉄塔が線(way)に参照されているか(=線が通っているか)
  - 鉄塔が乗る線が主連結成分か断片か
を判定して色分けプロット・未接続数を出す。共有ノード=正確接続(座標推測なし)。

Usage:
    PYTHONPATH=. python scripts/tower_connectivity.py --region kansai
    PYTHONPATH=. python scripts/tower_connectivity.py --bbox 35.3,135.5,36.2,136.6 --key fukui
"""
import argparse
import collections
import json
import os
import time

import requests

ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
UA = "AllJapanGrid/GridStitch tower-connectivity (lutebass@gmail.com)"
RAW = "data/osm_raw_towers"
_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "regions.yaml")


def _fetch(bbox, key, timeout=120):
    os.makedirs(RAW, exist_ok=True)
    cp = os.path.join(RAW, f"tw_{key}.json")
    if os.path.exists(cp):
        return json.load(open(cp, encoding="utf-8"))
    s, w, n, e = bbox
    q = (f"[out:json][timeout:{timeout-20}];("
         f'way["power"~"^(line|cable|minor_line)$"]({s},{w},{n},{e});'
         f'node["power"="tower"]({s},{w},{n},{e});'
         f"); out body; >; out body;")
    last = None
    for attempt in range(3):
        for ep in ENDPOINTS:
            try:
                r = requests.post(ep, data={"data": q}, headers={"User-Agent": UA}, timeout=timeout)
                if r.status_code == 200:
                    d = r.json()
                    with open(cp, "w", encoding="utf-8") as fh:
                        json.dump(d, fh, ensure_ascii=False)
                    return d
                last = f"{ep.split('/')[2]} {r.status_code}"
            except Exception as exc:   # noqa: BLE001
                last = f"{ep.split('/')[2]} {str(exc)[:50]}"
            time.sleep(3)
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"Overpass到達不可: {last}")


def _bbox_tiles(region, rows=3, cols=3):
    import yaml
    bb = yaml.safe_load(open(_CONFIG, encoding="utf-8"))["regions"][region]["bounding_box"]
    la0, la1, lo0, lo1 = bb["lat_min"], bb["lat_max"], bb["lon_min"], bb["lon_max"]
    dla, dlo = (la1 - la0) / rows, (lo1 - lo0) / cols
    return [(la0 + r * dla, lo0 + c * dlo, la0 + (r + 1) * dla, lo0 + (c + 1) * dlo)
            for r in range(rows) for c in range(cols)]


def gather(region=None, bbox=None, key=None):
    seen = set()
    nodes = {}
    ways = []
    if bbox:
        tiles = [(tuple(bbox), key or "bbox")]
    else:
        tiles = [(t, f"{region}_t{i}") for i, t in enumerate(_bbox_tiles(region))]
    for tb, tk in tiles:
        d = _fetch(tb, tk)
        for el in d.get("elements", []):
            k = (el["type"], el["id"])
            if k in seen:
                continue
            seen.add(k)
            if el["type"] == "node":
                nodes[el["id"]] = el
            elif el["type"] == "way":
                ways.append(el)
        if not os.path.exists(os.path.join(RAW, f"tw_{tk}.json")):
            time.sleep(22)
    return nodes, ways


def classify(nodes, ways):
    import networkx as nx
    lines = [w for w in ways if (w.get("tags") or {}).get("power")
             in ("line", "cable", "minor_line")]
    towers = {nid: n for nid, n in nodes.items()
              if (n.get("tags") or {}).get("power") == "tower"}
    # 線の連結(共有ノード)→ 各wayの成分
    g = nx.Graph()
    n2w = collections.defaultdict(list)
    for w in lines:
        g.add_node(("w", w["id"]))
        for nid in w.get("nodes", []):
            n2w[nid].append(w["id"])
    for ws in n2w.values():
        ws = list(dict.fromkeys(ws))
        for a in range(len(ws)):
            for b in range(a + 1, len(ws)):
                g.add_edge(("w", ws[a]), ("w", ws[b]))
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    main = comps[0] if comps else set()
    wcomp = {}
    for i, c in enumerate(comps):
        for x in c:
            wcomp[x] = i
    # 鉄塔分類: 線に参照されている? その線は主成分?
    res = {"on_main": [], "on_fragment": [], "orphan": []}
    for nid, n in towers.items():
        ws = n2w.get(nid, [])
        if not ws:
            res["orphan"].append(n)
        elif any(("w", wid) in main for wid in ws):
            res["on_main"].append(n)
        else:
            res["on_fragment"].append(n)
    return res, len(lines), len(comps), len(main)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region")
    ap.add_argument("--bbox", help="s,w,n,e")
    ap.add_argument("--key")
    ap.add_argument("--out", default="/tmp")
    args = ap.parse_args()
    bbox = tuple(float(x) for x in args.bbox.split(",")) if args.bbox else None
    nodes, ways = gather(region=args.region, bbox=bbox, key=args.key)
    res, nlines, ncomp, nmain = classify(nodes, ways)
    nt = sum(len(v) for v in res.values())
    label = args.region or args.key or "area"
    print(f"=== {label} 鉄塔接続検証 ===")
    print(f"全鉄塔 {nt} / 線(way) {nlines} / 線成分 {ncomp}(最大{nmain})")
    print(f"  主系統の線上: {len(res['on_main'])} ({100*len(res['on_main'])//max(nt,1)}%)")
    print(f"  断片の線上  : {len(res['on_fragment'])}")
    print(f"  孤立(線が通っていない鉄塔): {len(res['orphan'])}")
    # プロット
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    for c in ("Hiragino Sans", "YuGothic", "Arial Unicode MS"):
        try:
            if fm.findfont(c, fallback_to_default=False):
                plt.rcParams["font.family"] = c
                break
        except Exception:   # noqa: BLE001
            continue
    fig, ax = plt.subplots(figsize=(13, 12), dpi=120)
    for w in ways:
        if (w.get("tags") or {}).get("power") not in ("line", "cable", "minor_line"):
            continue
        co = [(nodes[n]["lon"], nodes[n]["lat"]) for n in w.get("nodes", []) if n in nodes]
        if len(co) >= 2:
            ax.plot([c[0] for c in co], [c[1] for c in co], color="#cccccc", lw=0.5, zorder=1)
    for key2, col, z in (("on_main", "#1f6feb", 2), ("on_fragment", "#f0a000", 3), ("orphan", "#e8410a", 4)):
        xs = [n["lon"] for n in res[key2]]
        ys = [n["lat"] for n in res[key2]]
        ax.plot(xs, ys, "o", ms=1.5, color=col, zorder=z)
    ax.set_title(f"{label} 全鉄塔{nt}  青=主系統線上 / 橙=断片線上 / 赤=孤立(線なし){len(res['orphan'])}", fontsize=11)
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    ax.grid(True, alpha=0.2)
    path = os.path.join(args.out, f"towers_{label}.png")
    plt.savefig(path, bbox_inches="tight")
    print("saved", path)


if __name__ == "__main__":
    main()
