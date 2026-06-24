"""島の分類器 — 島変電所を「なぜ繋がらないか」で仕分け、編集ツール/OSM還元に渡す。

GridStitch P1bの再評価(台帳125)の結論を運用化する:
自動束縛では大半が捏造になるため、島を分類して**人間が編集ツールで判断**する材料を出す。
方針 A/B/C(GRIDSTITCH_PLAN §8)+ 実到達判定で次のバケツに仕分ける:

  railway  : 届く線がJR/鉄道/別事業者 → 別網=正当な島(繋がない)
  phantom  : 近傍にOSM変電所が無い → 抽出/合成の幽霊(要除去・bug)
  vsplit   : 同名の別電圧ヤードが離れて存在(変圧器未連結)→ 人間が変圧器連結を判断
  osm_gap  : 届く線が構内で完結し主系統に届かない → 連系線がOSM未整備(人間/OSM貢献)
  reachable: 届く線が主系統の別変電所へ実到達なのに島 → 真の束縛バグ候補(精査)
  isolated : 届く線が無い(degree0・線なし) → OSM上そもそも孤立(方針A)

出力: 標準出力サマリ + data/db/island_classify_{region}_{stamp}.json(committedスコアカードに非接触)。

Usage:
    PYTHONPATH=. python scripts/island_classify.py --region tokyo
    PYTHONPATH=. python scripts/island_classify.py --region tokyo --stamp 2026-06-15 --out data/db
"""
import argparse
import collections
import json
import os

import networkx as nx


def _allpts(g):
    pts = []

    def w(a):
        if isinstance(a, (int, float)):
            return
        if len(a) >= 2 and isinstance(a[0], (int, float)):
            pts.append(a)
            return
        for x in a:
            w(x)
    w(g["coordinates"])
    return pts


def _d_km(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 * 111.0


def _is_rail(props_list):
    s = " ".join(str(p.get("name", "")) + str(p.get("operator", ""))
                 + str(p.get("operator:en", "")) for p in props_list)
    return ("JR" in s or "鉄道" in s or "ailway" in s or "Railway" in s)


def classify(region, data_dir="data", reach_km=0.25):
    from src.powerflow.snapped_topology import build_network_snapped, _freq_excluded
    from src.regions import REGION_FREQUENCY_HZ as REGION_FREQ
    net = build_network_snapped(region, data_dir=data_dir)
    if net is None:
        return None
    g = nx.Graph()
    g.add_nodes_from(s.id for s in net.substations)
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    main = set(comps[0]) if comps else set()
    main_subs = [(s.latitude, s.longitude, s.name)
                 for s in net.substations if s.id in main]

    lines = json.load(open(os.path.join(data_dir, f"{region}_lines.geojson"),
                           encoding="utf-8"))
    # 本線(母線/ベイ等を除く)のみ。builder と同じ周波数フィルタを適用し、
    # 別同期島(例: 60Hz地域に混入した50Hz TEPCO資産)の線を「届く」と誤検知しない。
    freq = REGION_FREQ.get(region, 50)
    main_lines = [f for f in lines["features"]
                  if (f.get("properties") or {}).get("line")
                  not in ("busbar", "bay", "substation", "internal")
                  and not _freq_excluded(f.get("properties") or {}, freq)]

    # 同名グループ(電圧分離検出用)
    byname = collections.defaultdict(list)
    for s in net.substations:
        byname[s.name].append(s)

    def reaching(la, lo):
        out = []
        for f in main_lines:
            if any(_d_km((x[1], x[0]), (la, lo)) < reach_km
                   for x in _allpts(f["geometry"])):
                out.append(f)
        return out

    def reaches_other_main(la, lo, fs):
        for f in fs:
            for x in _allpts(f["geometry"]):
                for mla, mlo, _ in main_subs:
                    if _d_km((x[1], x[0]), (mla, mlo)) < 0.3 and \
                            _d_km((la, lo), (mla, mlo)) > 0.5:
                        return True
        return False

    buckets = collections.OrderedDict(
        (k, []) for k in ("railway", "phantom", "vsplit", "osm_gap",
                          "reachable", "isolated"))
    for s in net.substations:
        if s.id in main or "sub" not in s.id:
            continue
        fs = reaching(s.latitude, s.longitude)
        props = [f.get("properties") or {} for f in fs]
        rec = {"id": s.id, "name": s.name, "kv": s.voltage_kv,
               "deg": g.degree(s.id), "lat": round(s.latitude, 5),
               "lon": round(s.longitude, 5), "n_reaching": len(fs)}
        # 同名の別バスが本系統にいる&離れている=電圧分離
        sibs = [x for x in byname[s.name] if x.id != s.id]
        sib_main_far = any(
            x.id in main and _d_km((s.latitude, s.longitude),
                                   (x.latitude, x.longitude)) > 0.2
            for x in sibs)
        if not fs:
            buckets["isolated"].append(rec)
        elif _is_rail(props):
            buckets["railway"].append(rec)
        elif sib_main_far:
            rec["note"] = "同名バスが本系統に別在(電圧ヤード分離・変圧器未連結)"
            buckets["vsplit"].append(rec)
        elif reaches_other_main(s.latitude, s.longitude, fs):
            buckets["reachable"].append(rec)
        else:
            buckets["osm_gap"].append(rec)

    # phantom(OSM変電所が無いモデル節点)は jct を見る — 簡易に「sub だが OSM名なし」は別途。
    # ここでは sub 節点のみ対象(phantomは別経路で。空でも構造維持)
    summary = {k: len(v) for k, v in buckets.items()}
    return {"region": region, "n_islands_sub": sum(summary.values()),
            "summary": summary, "buckets": buckets,
            "n_components": len(comps), "main_size": len(main)}


def main():
    ap = argparse.ArgumentParser(description="島変電所の分類(railway/osm_gap/vsplit/reachable/isolated)")
    ap.add_argument("--region", required=True)
    ap.add_argument("--out", default=None, help="JSON出力先ディレクトリ(省略時は書かない)")
    ap.add_argument("--stamp", default=None, help="出力ファイル名の日付(YYYY-MM-DD)")
    args = ap.parse_args()
    res = classify(args.region)
    if res is None:
        raise SystemExit(f"{args.region}: モデル構築失敗")
    print(f"=== {args.region} 島変電所分類 (成分{res['n_components']}/本系統{res['main_size']}) ===")
    labels = {"railway": "鉄道/別事業者(繋がない)", "phantom": "幽霊(要除去)",
              "vsplit": "電圧ヤード分離(人間が変圧器連結)",
              "osm_gap": "OSM連系線欠落(人間/OSM貢献)",
              "reachable": "主系統に実到達なのに島(精査)",
              "isolated": "線なし孤立(方針A)"}
    for k, n in res["summary"].items():
        ex = [b["name"] for b in res["buckets"][k][:5]]
        print(f"  {k:10} {n:4}  {labels[k]}  例={ex}")
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        stamp = args.stamp or "nostamp"
        path = os.path.join(args.out, f"island_classify_{args.region}_{stamp}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        print("JSON:", path)


if __name__ == "__main__":
    main()
