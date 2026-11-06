#!/usr/bin/env python3
"""地図の線の形(直線の区間)を数え、直す前と比べる報告を書く(2026-11-07)。

    PYTHONPATH=. python scripts/report_line_geometry.py --before <直す前の lines_all.geojson> --out docs/reports/map_line_geometry_2026-11-07.md

数えるもの: 隣り合う頂点の間が 1 km を超える区間(直線の区間)の本数と延長。
直したあとの区間は、次の 2 つに分ける。
  - OSM の線の形どおり: OSM の線そのものが、隣り合う点の間を 1 km 超で結んでいる(山や川を越える長い径間など)。
    鉄塔をたどった形で、直線にしたのではない
  - 経路未取得(直線は仮): OSM の線をたどる経路が見つからず、直線のまま残した区間。地図では破線
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def hav(a, b):
    p = math.pi / 180
    x = math.sin((b[1] - a[1]) * p / 2) ** 2 + math.cos(a[1] * p) * math.cos(b[1] * p) * math.sin((b[0] - a[0]) * p / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x))


def segs(features):
    out = []
    for i, ft in enumerate(features):
        c = ft["geometry"]["coordinates"]
        for j in range(len(c) - 1):
            out.append((i, j, hav(c[j], c[j + 1])))
    return out


def summary(features):
    s = segs(features)
    tot = sum(d for _, _, d in s)
    s1 = [x for x in s if x[2] > 1]
    s10 = [x for x in s if x[2] > 10]
    return tot, len(s1), sum(d for *_, d in s1), len(s10), sum(d for *_, d in s10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", default=os.path.join(ROOT, "docs", "data", "map", "lines_all.geojson"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    before = json.load(open(args.before, encoding="utf-8"))["features"]
    after = json.load(open(args.after, encoding="utf-8"))["features"]

    osm_long = set()
    n_osm = km_osm = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "*_lines.geojson"))):
        for ft in json.load(open(f, encoding="utf-8"))["features"]:
            if not ft["properties"].get("osm_id"):
                continue
            g = ft["geometry"]
            for c in ([g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]):
                for j in range(len(c) - 1):
                    d = hav(c[j], c[j + 1])
                    if d > 1:
                        n_osm += 1
                        km_osm += d
                        a = (round(c[j][0], 6), round(c[j][1], 6))
                        b = (round(c[j + 1][0], 6), round(c[j + 1][1], 6))
                        osm_long.add((a, b))
                        osm_long.add((b, a))

    cat = {"osm": [0, 0.0], "unr": [0, 0.0], "other": [0, 0.0]}
    unr_list = []
    for i, ft in enumerate(after):
        c = ft["geometry"]["coordinates"]
        p = ft["properties"]
        unr = set(p.get("_unr") or [])
        for j in range(len(c) - 1):
            d = hav(c[j], c[j + 1])
            if j in unr:
                unr_list.append((d, p, c[j], c[j + 1]))
            if d <= 1:
                continue
            a = (round(c[j][0], 6), round(c[j][1], 6))
            b = (round(c[j + 1][0], 6), round(c[j + 1][1], 6))
            k = "osm" if (a, b) in osm_long else "unr" if j in unr else "other"
            cat[k][0] += 1
            cat[k][1] += d

    # 経路未取得の区間(1 km 超)に沿って OSM の線があるか(区間の 5 か所で、300 m 以内に OSM の点があるか)
    import sys as _sys
    _sys.path.insert(0, ROOT)
    from src.topology import line_geometry as LG
    net = LG.load_net(os.path.join(ROOT, "data"), ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai",
                                                  "chugoku", "shikoku", "kyushu", "okinawa"])
    along = {"none": [0, 0.0], "part": [0, 0.0], "full": [0, 0.0]}
    for d, p, a, b in unr_list:
        if d <= 1:
            continue
        hits = 0
        for t in (0.2, 0.35, 0.5, 0.65, 0.8):
            if net.nearest(a[1] + (b[1] - a[1]) * t, a[0] + (b[0] - a[0]) * t, 300) is not None:
                hits += 1
        k = "none" if hits == 0 else "part" if hits <= 3 else "full"
        along[k][0] += 1
        along[k][1] += d

    b_tot, b_n1, b_k1, b_n10, b_k10 = summary(before)
    a_tot, a_n1, a_k1, a_n10, a_k10 = summary(after)
    geom = {}
    for ft in after:
        g = ft["properties"].get("_geom") or "osm"
        geom[g] = geom.get(g, 0) + 1
    L = []
    L.append("# 地図の線の形（直線の区間）— 直す前と後（2026-11-07）\n")
    L.append("系統図マップ（map.html）の線を、OSM の実際の経路（鉄塔をたどる形）で描くように直した"
             "（scripts/export_map_tiers_from_built.py・src/topology/line_geometry.py）。"
             "正典（docs/data/built）の枝とつながりは変えていない。変えたのは地図に描く形だけ。\n")
    L.append("## 直し方\n")
    L.append("1. 座標を小数 4 桁（約 11 m）に丸めていたのをやめ、6 桁で出す。")
    L.append("2. 正典の枝の形の頂点を、座標が一致する OSM の点（基底 OSM の線 `data/{地域}_lines.geojson`）に置き換える。")
    L.append("3. 隣り合う頂点が 300 m を超えて離れている所は、電圧の合う OSM の線をたどる最短の経路で埋める"
             "（長さが直線の 1.6 倍 + 1 km まで → 2.2 倍 + 3 km まで → 電圧を問わず 1.6 倍 + 1 km まで、の順に試す）。"
             "OSM の線の端が別の線と 80 m 以内で離れているだけの所（つなぎ忘れ）は、経路を探すときだけつなぐ。")
    L.append("4. 形を持たない枝（引込み・連系線など）は、両端の 800 m 以内の OSM の点から 3 と同じように探す。")
    L.append("5. 見つからない区間だけ直線のまま残し、地図では破線で「経路未取得（直線は仮）」と描く。下に一覧。\n")
    L.append("## 数\n")
    L.append("| | 直す前（main） | 直した後 | 増減 |")
    L.append("|---|---:|---:|---:|")
    L.append(f"| 1 km を超える直線の区間 | {b_n1:,} 本 | {a_n1:,} 本 | {a_n1 - b_n1:+,} 本 |")
    L.append(f"| その延長 | {b_k1:,.0f} km | {a_k1:,.0f} km | {a_k1 - b_k1:+,.0f} km |")
    L.append(f"| 10 km を超える直線の区間 | {b_n10} 本・{b_k10:,.0f} km | {a_n10} 本・{a_k10:,.0f} km | {a_n10 - b_n10:+} 本 |")
    L.append(f"| 線の総延長 | {b_tot:,.0f} km | {a_tot:,.0f} km | |")
    L.append("")
    L.append(f"直した後の 1 km を超える区間 {a_n1:,} 本の内訳:\n")
    L.append(f"- **OSM の線の形どおり**（OSM の線そのものが 1 km 超の間隔で点を結んでいる。山や川を越える長い径間など。"
             f"鉄塔をたどった形で、直線にしたのではない）: {cat['osm'][0]:,} 本・{cat['osm'][1]:,.0f} km"
             f"（参考: OSM の線全体にある 1 km 超の区間は {n_osm:,} 本・{km_osm:,.0f} km）")
    L.append(f"- **経路未取得（直線は仮・地図では破線）**: {cat['unr'][0]:,} 本・{cat['unr'][1]:,.0f} km")
    L.append(f"  - うち、区間に沿う OSM の線が無い（区間の 5 か所のどこにも 300 m 以内に OSM の線が無い）: "
             f"{along['none'][0]:,} 本・{along['none'][1]:,.0f} km。OSM に線が描かれていないので、実際の経路は今の OSM からは引けない")
    L.append(f"  - 一部だけ沿う: {along['part'][0]:,} 本・{along['part'][1]:,.0f} km、ほぼ沿う: {along['full'][0]:,} 本・"
             f"{along['full'][1]:,.0f} km。OSM の線の切れ目が 80 m より広い・電圧のタグが違う・遠回りが長すぎる、のいずれか。次に直す候補")
    L.append(f"- そのほか（OSM の点と一致しない頂点どうし）: {cat['other'][0]:,} 本・{cat['other'][1]:,.0f} km\n")
    L.append("地図の線（19,909 本）の形の内訳: " + "・".join(
        f"{ {'osm': 'OSM の経路', 'found': '形の無い枝に経路を探して当てた', 'partial': '一部が経路未取得', 'straight': '全部が経路未取得'}.get(k, k)} {v:,} 本"
        for k, v in sorted(geom.items())) + "\n")
    L.append("## 経路未取得（直線は仮）の区間の一覧（長い順。1 km 以下も含む）\n")
    L.append("連系線のように OSM で経路を探しても見つからなかったもの。理由の多くは、OSM の線に切れ目がある・"
             "正典の端の位置が OSM の線から離れている・台帳の端の変電所が違う（例: 中国四国間連系線は台帳の中国側の端が"
             "山口の東山口変電所になっていて、讃岐まで 195.7 km の直線になる。台帳の確認が要る）。\n")
    L.append(f"全 {len(unr_list):,} 区間・{sum(x[0] for x in unr_list):,.0f} km。\n")
    L.append("| 長さ | 線の名前 | 電圧 | 区間の両端 |")
    L.append("|---:|---|---|---|")
    for d, p, a, b in sorted(unr_list, key=lambda x: (-x[0], x[1].get("_display_name") or "")):
        kv = p.get("_voltage_kv")
        L.append(f"| {d:,.1f} km | {p.get('_display_name') or '名前なし'} | {kv:g} kV | " if kv else
                 f"| {d:,.1f} km | {p.get('_display_name') or '名前なし'} | 不明 | ")
        L[-1] += (f"[{a[1]:.5f}, {a[0]:.5f}](https://www.openstreetmap.org/#map=15/{a[1]:.5f}/{a[0]:.5f}) → "
                  f"[{b[1]:.5f}, {b[0]:.5f}](https://www.openstreetmap.org/#map=15/{b[1]:.5f}/{b[0]:.5f}) |")
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"前 {b_n1:,} 本 {b_k1:,.0f} km → 後 {a_n1:,} 本 {a_k1:,.0f} km(OSM の形どおり {cat['osm'][0]} 本 {cat['osm'][1]:,.0f} km・"
          f"経路未取得 {cat['unr'][0]} 本 {cat['unr'][1]:,.0f} km・そのほか {cat['other'][0]} 本)。経路未取得の区間 全 {len(unr_list)}")


if __name__ == "__main__":
    main()
