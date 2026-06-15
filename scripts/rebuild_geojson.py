"""geojson再生成(②): node-ref生OSMから lines geojson を作り直す。

価値の核=**電圧伝播**(オーナー目標): 共有ノードで繋がる既知電圧を無タグ線へ伝播して充填。
(node-sharing自体は座標丸めと同等=接続利得ゼロと既に判明・台帳131。よって本体は電圧推定。)
node参照を properties.osm_nodes に保持。出力は temp data_dir に置き、現行と A/B(島・ρ)する。

Usage:
    PYTHONPATH=. python scripts/rebuild_geojson.py --region kansai
"""
import argparse
import collections
import glob
import json
import os


def load_raw(region):
    """data/osm_raw_towers/tw_{region}_t*.json をマージ → ways(line系), nodes。"""
    seen = set()
    nodes = {}
    ways = []
    files = sorted(glob.glob(f"data/osm_raw_towers/tw_{region}_t*.json"))
    if not files:
        files = sorted(glob.glob(f"data/osm_raw_towers/tw_{region}.json")) \
            or sorted(glob.glob(f"data/osm_raw_towers/tw_*{region}*.json"))
    for f in files:
        for e in json.load(open(f, encoding="utf-8")).get("elements", []):
            k = (e["type"], e["id"])
            if k in seen:
                continue
            seen.add(k)
            if e["type"] == "node":
                nodes[e["id"]] = e
            elif e["type"] == "way" and (e.get("tags") or {}).get("power") in (
                    "line", "cable", "minor_line"):
                ways.append(e)
    return ways, nodes


def _vclass(v):
    import re
    digs = [int(x) for x in re.findall(r"\d+", str(v or ""))]
    return max(digs, default=0) // 1000


def infer_voltages(ways):
    """共有ノードで繋がる既知電圧を無タグ線へ伝播(反復・端点合意のみ採用)。"""
    wv = {}      # way id -> kv (tag or inferred)
    src = {}
    for w in ways:
        kv = _vclass((w.get("tags") or {}).get("voltage"))
        wv[w["id"]] = kv
        src[w["id"]] = "tag" if kv > 0 else "none"
    # node -> ways
    n2w = collections.defaultdict(list)
    for w in ways:
        for nid in w.get("nodes", []):
            n2w[nid].append(w["id"])
    for _ in range(20):
        changed = False
        for w in ways:
            if wv[w["id"]] > 0:
                continue
            seen = set()
            for nid in w.get("nodes", []):
                for ow in n2w[nid]:
                    if wv[ow] > 0:
                        seen.add(wv[ow])
            if len(seen) == 1:           # 周囲が単一クラスのみ=その継続
                wv[w["id"]] = next(iter(seen))
                src[w["id"]] = "prop"
                changed = True
        if not changed:
            break
    return wv, src


def write_lines(region, ways, nodes, wv, src, out_dir):
    feats = []
    for w in ways:
        coords = [[nodes[n]["lon"], nodes[n]["lat"]]
                  for n in w.get("nodes", []) if n in nodes]
        if len(coords) < 2:
            continue
        t = w.get("tags") or {}
        kv = wv[w["id"]]
        props = dict(t)
        if kv > 0:
            props["voltage"] = str(kv * 1000)        # 推定/既知の電圧を充填
        props["voltage_src"] = src[w["id"]]
        props["osm_nodes"] = w.get("nodes", [])       # node参照を保持(正確トポロジ)
        props["power"] = t.get("power", "line")
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": props})
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, f"{region}_lines.geojson")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh, ensure_ascii=False)
    return p, len(feats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True)
    ap.add_argument("--out", default="data/rebuild")
    args = ap.parse_args()
    ways, nodes = load_raw(args.region)
    if not ways:
        raise SystemExit(f"{args.region}: node-ref tower データ無し(tower_connectivity/build_topology を先に)")
    notag0 = sum(1 for w in ways if _vclass((w.get('tags') or {}).get('voltage')) == 0)
    wv, src = infer_voltages(ways)
    notag1 = sum(1 for w in ways if wv[w["id"]] == 0)
    p, n = write_lines(args.region, ways, nodes, wv, src, args.out)
    print(f"{args.region}: 線{len(ways)} → geojson {n}本")
    print(f"  無タグ線: {notag0} → {notag1}(電圧伝播で {notag0-notag1} 本に電圧充填)")
    print(f"  出力: {p}")


if __name__ == "__main__":
    main()
