#!/usr/bin/env python3
"""送電線のつながりの点検(2026-11-07)。観測(OSM)と正典(built)の候補を分けて書き出す。

    PYTHONPATH=. python scripts/audit_route_connectivity.py --raw <data/osm_raw_towers のある場所>

何を見るか
  観測(OSM の線を路線にまとめたもの、src/topology/osm_routes.py)
    - obs_near_line : 線の端がどこにも続かず、60 m 以内に別の線がある(つなぎ忘れの候補。並走する別の線のこともある)
    - obs_near_sub  : 線の端がどこにも続かず、300 m 以内に変電所がある(引込みの描き残し)
    - obs_nothing   : 線の端がどこにも続かず、近くに何もない
    - obs_outside   : 線の端が取得した範囲(地域の外接矩形)の外。取り直せば続く可能性がある
    - obs_split     : 同じ名前・同じ電圧の路線が 2 km 以内の隙間で分かれている
    (変電所・発電所の敷地の中、引留め鉄構・終端・架空と地中の切替で終わる端は数えない。
     電圧の違う線が鉄塔の点を共有する所は、ほとんどが併架で OSM の誤りではないので候補にしない)
  正典(docs/data/built/all.json)
    - canon_mixed_kv : 変電所でない接続点で、電圧の違う枝がつながっている(変圧器なしで電圧は変わらない)
    - canon_dead_end : 変電所でない接続点で、枝が 1 本しかない(変電所に届かずに終わる)

これは**候補の一覧**で、誤りの判定ではない。直すのは航空写真・OSM・公表値の根拠があるものだけで、
直しは別の手順(介入台帳 docs/MODEL_INTERVENTIONS.md)で行う。

出力(上書き。入力が同じなら同じバイト)
  docs/data/route_audit/audit.json                         地図の「つながりの点検」の層が読む
  docs/reports/route_connectivity_audit_<OSM 取得日>.md     地域別の表と 154 kV 以上の一覧
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sys

import yaml
from shapely import points as shp_points
from shapely.geometry import Point
from shapely.strtree import STRtree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.export_osm_routes import REGIONS, Sites, region_lookup, lat5  # noqa: E402
from src.topology import osm_routes as R  # noqa: E402

M_PER_DEG = 111_000.0
NEAR_LINE_M = 60
NEAR_SUB_M = 300
SPLIT_GAP_M = 2000
REGION_JA = {"hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京", "chubu": "中部", "hokuriku": "北陸",
             "kansai": "関西", "chugoku": "中国", "shikoku": "四国", "kyushu": "九州", "okinawa": "沖縄"}
CLASS_JA = {
    "obs_near_line": "線の端の 60 m 以内に別の線(つなぎ忘れの候補)",
    "obs_near_sub": "線の端の 300 m 以内に変電所(引込みの描き残し)",
    "obs_nothing": "線の端が何もない所で終わる",
    "obs_outside": "線の端が取得範囲の外",
    "obs_split": "同じ名前・電圧の路線が 2 km 以内の隙間で途切れる(両側とも線の端がどこにも続かない)",
    "canon_mixed_kv": "正典: 変電所でない接続点で電圧の違う枝がつながる",
    "canon_dead_end": "正典: 変電所でない接続点で枝が 1 本(行き止まり)",
}


def kv_band(kv):
    return "154+" if kv >= 154 else "66-153" if kv >= 66 else "<66" if kv > 0 else "不明"


def dist_m(a_lat, a_lon, b_lat, b_lon):
    dx = (a_lon - b_lon) * M_PER_DEG * math.cos(math.radians((a_lat + b_lat) / 2))
    dy = (a_lat - b_lat) * M_PER_DEG
    return math.hypot(dx, dy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=os.environ.get("AGJ_OSM_RAW_TOWERS", os.path.join(ROOT, "data", "osm_raw_towers")))
    args = ap.parse_args()
    if not R.raw_files(args.raw):
        sys.exit(f"鉄塔の生データが見つからない: {args.raw}")

    nodes, ways, info = R.load_raw(args.raw)
    route_of, _ = R.assemble(ways)
    mem = R.members(route_of)
    nidx = R.node_index(ways)
    with open(os.path.join(ROOT, "docs", "data", "built", "all.json"), encoding="utf-8") as fh:
        built = json.load(fh)
    region_of = region_lookup(built["nodes"])
    sites = Sites()
    with open(os.path.join(ROOT, "config", "regions.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)["regions"]
    boxes = [(r["bounding_box"]["lat_min"], r["bounding_box"]["lat_max"], r["bounding_box"]["lon_min"], r["bounding_box"]["lon_max"])
             for k, r in cfg.items() if k in REGIONS]

    def inside_fetch(lat, lon, margin=0.01):
        return any(a + margin <= lat <= b - margin and c + margin <= lon <= d - margin for a, b, c, d in boxes)

    # 変電所の輪郭そのもの(敷地とみなす余白を付けない)と名前
    sub_geoms = [g.buffer(-0.0004) for g, k in zip(sites.geoms, sites.kinds) if k == "sub"]
    sub_names = [n for n, k in zip(sites.names, sites.kinds) if k == "sub"]
    sub_tree = STRtree(sub_geoms)

    # 全 way の頂点(どの路線の点か)
    v_route, v_pts = [], []
    for wid in sorted(ways):
        for nid in ways[wid]["nodes"]:
            n = nodes.get(nid)
            if n:
                v_route.append(route_of[wid])
                v_pts.append(Point(n["lon"], n["lat"]))
    v_tree = STRtree(v_pts)

    # 正典: 節点と枝の形の頂点
    bn = built["nodes"]
    bn_tree = STRtree(shp_points([[n["lon"], n["lat"]] for n in bn]))
    bpath_pts = []
    for e in built["edges"]:
        for lat, lon in (e.get("path") or [e["a"], e["b"]]):
            bpath_pts.append((lon, lat))
    bpath_tree = STRtree(shp_points(bpath_pts))

    def canon_near(lat, lon):
        p = Point(lon, lat)
        i = int(bn_tree.nearest(p))
        dn = dist_m(lat, lon, bn[i]["lat"], bn[i]["lon"])
        j = int(bpath_tree.nearest(p))
        dp = dist_m(lat, lon, bpath_pts[j][1], bpath_pts[j][0])
        return round(dn), round(dp), bool(bn[i].get("main")), bn[i].get("name") or ""

    rinfo = {}
    for rid, wids in mem.items():
        name, _ = R.route_name(wids, ways, nodes)
        kvs = set()
        for w in wids:
            kvs |= R.kv_set(ways[w].get("tags") or {})
        rinfo[rid] = (name, max(kvs, default=0.0))

    # ── 観測: 路線の端 ──
    obs = []
    for rid in sorted(mem):
        name, kv = rinfo[rid]
        cnt = collections.Counter()
        for w in mem[rid]:
            for nid in (ways[w]["nodes"][0], ways[w]["nodes"][-1]):
                cnt[nid] += 1
        for nid in sorted(n for n, k in cnt.items() if k == 1):
            if len(nidx.get(nid, [])) > 1 or nid not in nodes:
                continue                       # ほかの way へ続く
            n = nodes[nid]
            lat, lon = n["lat"], n["lon"]
            if sites.at(lat, lon):
                continue                       # 変電所・発電所の敷地で終わる
            pw = (n.get("tags") or {}).get("power")
            if pw in ("portal", "terminal", "transition") or (n.get("tags") or {}).get("location:transition"):
                continue                       # 引留め鉄構・終端・架空と地中の切替
            wid = next(w for w in nidx[nid])
            p = Point(lon, lat)
            near_line = None
            for j in v_tree.query(p.buffer(NEAR_LINE_M / M_PER_DEG * 1.5)):
                if v_route[j] == rid:
                    continue
                d = dist_m(lat, lon, v_pts[j].y, v_pts[j].x)
                if near_line is None or d < near_line[0]:
                    near_line = (d, v_route[j])
            i = int(sub_tree.nearest(p))
            dsub = sub_geoms[i].distance(p) * M_PER_DEG
            if not inside_fetch(lat, lon):
                cls = "obs_outside"
            elif near_line and near_line[0] <= NEAR_LINE_M:
                cls = "obs_near_line"
            elif dsub <= NEAR_SUB_M:
                cls = "obs_near_sub"
            else:
                cls = "obs_nothing"
            cn = canon_near(lat, lon)
            obs.append({"cls": cls, "lat": lat, "lon": lon, "kv": kv, "rid": rid, "way": wid, "node": nid, "name": name,
                        "near_line_m": round(near_line[0]) if near_line else None,
                        "near_line_rid": near_line[1] if near_line else None,
                        "near_line_name": rinfo[near_line[1]][0] if near_line else None,
                        "sub_m": round(dsub), "sub_name": sub_names[i] or None,
                        "canon_node_m": cn[0], "canon_line_m": cn[1], "canon_main": cn[2], "canon_node_name": cn[3]})

    # ── 観測: 同じ名前・電圧で分かれた路線 ──
    groups = collections.defaultdict(list)
    for rid, (name, kv) in rinfo.items():
        if not name:
            continue
        for part in R.name_set({"name": name}):
            groups[(part, kv)].append(rid)

    def route_ends(rid):
        cnt = collections.Counter()
        for w in mem[rid]:
            for nid in (ways[w]["nodes"][0], ways[w]["nodes"][-1]):
                cnt[nid] += 1
        # どこにも続かず(ほかの way と点を共有しない)、変電所・発電所の敷地の外にある端だけ。
        # 端で別の way(「A線;B線」のような 2 つの名前の区間など)に続いているなら、隙間ではない
        return [nodes[n] for n, k in sorted(cnt.items())
                if k == 1 and n in nodes and len(nidx.get(n, [])) == 1
                and not sites.at(nodes[n]["lat"], nodes[n]["lon"])]

    split = []
    seen_pairs = set()
    for (part, kv), rids in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if len(rids) < 2:
            continue
        rids = sorted(set(rids))
        ends = {r: route_ends(r) for r in rids}
        for a_i in range(len(rids)):
            for b_i in range(a_i + 1, len(rids)):
                a, b = rids[a_i], rids[b_i]
                if (a, b) in seen_pairs:
                    continue
                best = None
                for ea in ends[a]:
                    for eb in ends[b]:
                        d = dist_m(ea["lat"], ea["lon"], eb["lat"], eb["lon"])
                        if best is None or d < best[0]:
                            best = (d, ea, eb)
                if best and 0 < best[0] <= SPLIT_GAP_M:
                    seen_pairs.add((a, b))
                    d, ea, eb = best
                    lat, lon = (ea["lat"] + eb["lat"]) / 2, (ea["lon"] + eb["lon"]) / 2
                    cn = canon_near(lat, lon)
                    split.append({"cls": "obs_split", "lat": lat, "lon": lon, "kv": kv, "rid": a, "rid2": b, "name": part,
                                  "gap_m": round(d), "a": [ea["lat"], ea["lon"]], "b": [eb["lat"], eb["lon"]],
                                  "canon_node_m": cn[0], "canon_line_m": cn[1], "canon_main": cn[2]})

    # ── 正典 ──
    key = lambda ll: (round(ll[0], 5), round(ll[1], 5))
    bnode = {key((n["lat"], n["lon"])): n for n in bn}
    inc = collections.defaultdict(list)
    for e in built["edges"]:
        inc[key(e["a"])].append(e)
        inc[key(e["b"])].append(e)
    canon = []
    sub_nodes = [n for n in bn if n.get("sub")]
    sub_tree2 = STRtree(shp_points([[n["lon"], n["lat"]] for n in sub_nodes]))
    for k in sorted(bnode):
        n = bnode[k]
        if n.get("sub"):
            continue
        es = inc.get(k, [])
        kvs = sorted({float(e.get("kv") or 0) for e in es} - {0.0})
        cls = None
        if len(kvs) > 1:
            cls = "canon_mixed_kv"
        elif len(es) == 1:
            cls = "canon_dead_end"
        if not cls:
            continue
        j = int(sub_tree2.nearest(Point(n["lon"], n["lat"])))
        s = sub_nodes[j]
        canon.append({"cls": cls, "lat": n["lat"], "lon": n["lon"], "kv": max(kvs, default=0.0), "kvs": kvs,
                      "names": sorted({e.get("name") or "" for e in es})[:6], "deg": len(es), "main": bool(n.get("main")),
                      "sub_m": round(dist_m(n["lat"], n["lon"], s["lat"], s["lon"])), "sub_name": s.get("name") or None})

    allc = obs + split + canon
    regs = region_of([[c["lon"], c["lat"]] for c in allc]) if allc else []
    for c, r in zip(allc, regs):
        c["region"] = r

    # ── 書き出し ──
    out_dir = os.path.join(ROOT, "docs", "data", "route_audit")
    os.makedirs(out_dir, exist_ok=True)
    ri = {r: i for i, r in enumerate(REGIONS)}
    cls_list = list(CLASS_JA)
    cols = ["種類(classes の番号)", "lat×1e5", "lon×1e5", "kV", "地域(regions の番号)", "路線(route_id, 0=正典)",
            "詳しく(種類ごと)"]

    def detail(c):
        if c["cls"].startswith("obs_split"):
            return {"name": c["name"], "gap_m": c["gap_m"], "rid2": c["rid2"], "a": [lat5(c["a"][0]), lat5(c["a"][1])],
                    "b": [lat5(c["b"][0]), lat5(c["b"][1])], "canon_line_m": c["canon_line_m"]}
        if c["cls"].startswith("obs_"):
            d = {"name": c["name"], "way": c["way"], "node": c["node"], "sub_m": c["sub_m"], "sub_name": c["sub_name"],
                 "canon_node_m": c["canon_node_m"], "canon_line_m": c["canon_line_m"], "canon_main": c["canon_main"],
                 "canon_node_name": c["canon_node_name"]}
            if c["near_line_m"] is not None:
                d.update({"near_line_m": c["near_line_m"], "near_line_rid": c["near_line_rid"], "near_line_name": c["near_line_name"]})
            return d
        return {"kvs": c["kvs"], "names": c["names"], "deg": c["deg"], "main": c["main"], "sub_m": c["sub_m"], "sub_name": c["sub_name"]}

    rows = [[cls_list.index(c["cls"]), lat5(c["lat"]), lat5(c["lon"]), c["kv"], ri.get(c.get("region"), -1),
             c.get("rid", 0), detail(c)] for c in allc]
    rows.sort(key=lambda r: (r[0], -r[3], r[1], r[2]))
    stamp = (info["osm_base_max"] or "")[:10]
    audit = {"what": "送電線のつながりの点検の候補(誤りの判定ではない)。観測(OSM)と正典(built)を分けている",
             "osm_base": info["osm_base_max"], "osm_sha256": info["sha256"],
             "built_all_sha256": __import__("scripts.export_osm_routes", fromlist=["_sha"])._sha(
                 os.path.join(ROOT, "docs", "data", "built", "all.json")),
             "thresholds_m": {"near_line": NEAR_LINE_M, "near_sub": NEAR_SUB_M, "split_gap": SPLIT_GAP_M},
             "classes": cls_list, "classes_ja": [CLASS_JA[c] for c in cls_list], "regions": REGIONS,
             "cols": cols, "rows": rows,
             "license": "観測の候補は © OpenStreetMap contributors(ODbL)から作った",
             "script": "scripts/audit_route_connectivity.py"}
    with open(os.path.join(out_dir, "audit.json"), "w", encoding="utf-8") as fh:
        json.dump(audit, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")

    # ── 報告 ──
    tab = collections.defaultdict(lambda: collections.Counter())
    for c in allc:
        tab[c["cls"]][(c.get("region"), kv_band(c["kv"]))] += 1
    lines = []
    lines.append(f"# 送電線のつながりの点検（OSM {stamp} 取得・正典 {audit['built_all_sha256'][:12]}）\n")
    lines.append("`scripts/audit_route_connectivity.py` が書いた。**候補の一覧で、誤りの判定ではない。**"
                 "観測（OSM の線を路線にまとめたもの、docs/OSM_ROUTES.md）と正典（docs/data/built）を分けて数える。"
                 "直すのは航空写真・OSM・公表値の根拠があるものだけで、直しは介入台帳（docs/MODEL_INTERVENTIONS.md）で行う。"
                 "地図では map.html の「つながりの点検」で印を出せる。\n")
    lines.append("数えないもの: 変電所・発電所の敷地の中、引留め鉄構・終端・架空と地中の切替で終わる線の端。"
                 "電圧の違う線が鉄塔の点を共有する所（ほとんどが併架で OSM の誤りではない）。\n")
    lines.append("## 種類ごと・地域ごとの数（かっこ内は 154 kV 以上）\n")
    head = "| 種類 | " + " | ".join(REGION_JA[r] for r in REGIONS) + " | 計 |"
    lines.append(head)
    lines.append("|" + "---|" * (len(REGIONS) + 2))
    for cls in cls_list:
        cells, tot, tot154 = [], 0, 0
        for r in REGIONS:
            a = sum(v for (rr, b), v in tab[cls].items() if rr == r)
            h = tab[cls][(r, "154+")]
            tot += a
            tot154 += h
            cells.append(f"{a:,}" + (f"（{h}）" if h else ""))
        lines.append(f"| {CLASS_JA[cls]} | " + " | ".join(cells) + f" | **{tot:,}**（{tot154}） |")
    lines.append("")
    # 観測の候補が正典でどう扱われているか(154 kV 以上)
    o154 = [c for c in obs if c["kv"] >= 154 and c["cls"] != "obs_outside"]
    covered = sum(1 for c in o154 if c["canon_line_m"] <= 60)
    lines.append("## 観測の候補（154 kV 以上）は正典でどうなっているか\n")
    lines.append(f"154 kV 以上の観測の候補 {len(o154)} か所のうち、正典の枝の形が 60 m 以内を通るのは {covered} か所"
                 f"（正典では線がその先へ続いている＝OSM の描き方の問題で、正典は直さなくてよい候補）。"
                 f"残り {len(o154) - covered} か所は正典でも線がその場所を通っていない。\n")
    lines.append("## 154 kV 以上の観測の候補\n")
    lines.append("| 種類 | 地域 | 路線 | kV | 位置 | 手がかり | 正典の枝まで |")
    lines.append("|---|---|---|---:|---|---|---:|")
    for c in sorted(o154, key=lambda c: (c["cls"], c.get("region") or "", -c["kv"], c["lat"])):
        hint = (f"{c['near_line_m']} m 先に {c['near_line_name'] or '名前なしの線'}" if c["cls"] == "obs_near_line"
                else f"{c['sub_m']} m 先に {c['sub_name'] or '名前なしの変電所'}" if c["cls"] == "obs_near_sub" else "—")
        lines.append(f"| {CLASS_JA[c['cls']].split('(')[0]} | {REGION_JA.get(c.get('region'), '?')} | {c['name'] or '名前なし'}"
                     f"（[way {c['way']}](https://www.openstreetmap.org/way/{c['way']})） | {c['kv']:g} | "
                     f"[{c['lat']:.5f}, {c['lon']:.5f}](https://www.openstreetmap.org/#map=18/{c['lat']:.5f}/{c['lon']:.5f}) | "
                     f"{hint} | {c['canon_line_m']} m |")
    lines.append("")
    lines.append("## 正典: 変電所でない接続点で電圧の違う枝がつながる所（全件）\n")
    lines.append("変圧器なしで電圧は変わらないので、モデルの誤接続の有力な候補。併架の鉄塔で別の電圧の線どうしを"
                 "つないでしまった可能性が高い。\n")
    lines.append("| 地域 | 電圧 | 枝の名前 | 位置 | 本系統 | 最寄りの変電所 |")
    lines.append("|---|---|---|---|---|---|")
    for c in sorted([c for c in canon if c["cls"] == "canon_mixed_kv"], key=lambda c: (c.get("region") or "", c["lat"])):
        lines.append(f"| {REGION_JA.get(c.get('region'), '?')} | {' / '.join(f'{k:g}' for k in c['kvs'])} kV | "
                     f"{'・'.join(n for n in c['names'] if n)[:80]} | "
                     f"[{c['lat']:.5f}, {c['lon']:.5f}](https://www.openstreetmap.org/#map=18/{c['lat']:.5f}/{c['lon']:.5f}) | "
                     f"{'はい' if c['main'] else 'いいえ'} | {c['sub_name'] or '—'}（{c['sub_m']:,} m） |")
    lines.append("")
    lines.append("## 作り直し方\n")
    lines.append("```bash\nPYTHONPATH=. python scripts/audit_route_connectivity.py --raw <data/osm_raw_towers のある場所>\n```\n")
    lines.append(f"閾値: 別の線まで {NEAR_LINE_M} m・変電所まで {NEAR_SUB_M} m・同じ名前の隙間 {SPLIT_GAP_M:,} m。"
                 f"入力の SHA256 は docs/data/route_audit/audit.json に書いている。\n")
    rep = os.path.join(ROOT, "docs", "reports", f"route_connectivity_audit_{stamp}.md")
    with open(rep, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(json.dumps({c: sum(tab[c].values()) for c in cls_list}, ensure_ascii=False))
    print(f"154 kV 以上の観測の候補 {len(o154)}・うち正典の枝が 60 m 以内 {covered}")
    print(f"書き出し {os.path.relpath(rep, ROOT)}・docs/data/route_audit/audit.json "
          f"({os.path.getsize(os.path.join(out_dir, 'audit.json')) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
