#!/usr/bin/env python3
"""地域の外接矩形を広げた分の OSM を、日付の決まった抽出(.osm.pbf)から足す(2026-11-09)。

地域の外接矩形(config/regions.yaml)のすき間に入っていた所の、送電線・変電所・発電所を地域のファイルに足す。
2026-11-09 に見つけたすき間: 東北 lon_min 139.0・東京と中部 lat_max 37.0・北陸 lon_max 137.9 の間で、
新潟県の西(上越・柏崎・長岡・十日町・魚沼)と佐渡が、どの地域にも入っていなかった(柏崎刈羽が無い issue #37)。
東北の lon_min を 137.8 に広げ、広げた帯(東経 137.8〜139.0 度・北緯 36.8〜41.5 度)だけをここで足す。

ほかの所は 2026-08 の取り込み(scripts/fetch_osm_refresh.py・migrate_osm_refresh.py)のまま変えない
(地域全体を取り直すと、帯の外の 3 か月分の OSM の編集まで混ざるため)。

2 段に分ける:
  1. 取り出し(OSM の抽出のある計算機で):
       python3 scripts/osm_bbox_supplement.py extract <japan-YYMMDD.osm.pbf> <出力フォルダ>
     osmium tags-filter で way の power=line/cable と、node/way/relation の power=substation・power=plant を残し、
     帯に点が 1 つでもある地物を、Overpass の JSON と同じ形の要素から、fetch_osm_refresh.to_features と
     fetch_plants.elements_to_geojson と同じ形の地物にして書く(gap_{lines,substations,plants}.geojson)。
  2. 足し込み(リポジトリで):
       python3 scripts/osm_bbox_supplement.py merge <出力フォルダ> [--write]
     足すのは、領土(代表の点の座標 → 県 → エリア、region_attribution.area_of_coord。線は中ほどの頂点、
     変電所は重心、発電所は点)が東北で、新潟県の 60 Hz の飛び地(妙高・糸魚川、data/reference/freq_boundary_mixed.geojson
     の protected_enclave。介入#42 と同じ台帳)の外にある地物だけ。領土がほかの地域のもの(長野・群馬・富山の分)と
     飛び地のものは、その地域のファイルのままにする(発電所は島ごとに osm_id で 1 回だけ採るので、
     東と西の両方のファイルに入ると 50 Hz と 60 Hz の両方で数えてしまう)。
     そのうえで地物の鍵(osm_type, osm_id)で、
       - 東北のファイルにもうある → 足さない
       - ほかの地域のファイルにある → その地物を写す(同じ版の形にそろえ、介入#58 が写しとして 1 つにまとめる。
         地域の重なりのほかの所と同じ扱い。発電所は osm_id で 1 回だけ採る: full_from_built の plants dedup)
       - どこにも無い → 抽出の地物を足す
     ファイルの末尾に足す(前からの地物の並びと番号を変えない。UC の発電機 id は番号で引く)。

帯は config/regions.yaml の東北の外接矩形のうち、旧 lon_min(139.0)より西。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

REGION = "tohoku"
#: 足す帯(南・北・西・東)。東北の外接矩形を lon_min 139.0 → 137.8 に広げた分
BAND = {"lat_min": 36.8, "lat_max": 41.5, "lon_min": 137.8, "lon_max": 139.0}
REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
           "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
LAYERS = ("lines", "substations", "plants")


def _in_band(lat: float, lon: float) -> bool:
    return BAND["lat_min"] <= lat <= BAND["lat_max"] and BAND["lon_min"] <= lon <= BAND["lon_max"]


def _bounds(pts):
    las = [p["lat"] for p in pts]
    los = [p["lon"] for p in pts]
    return {"minlat": min(las), "maxlat": max(las), "minlon": min(los), "maxlon": max(los)}


def extract(pbf: str, out_dir: str) -> None:
    from osm_pbf_to_power_json import parse_tags, unesc   # 同じ OPL の読み方
    from fetch_osm_refresh import to_features
    from fetch_plants import elements_to_geojson

    os.makedirs(out_dir, exist_ok=True)
    filt = os.path.join(out_dir, "power_lsp.osm.pbf")
    opl = os.path.join(out_dir, "power_lsp.opl")
    subprocess.run(["osmium", "tags-filter", pbf, "w/power=line,cable", "nwr/power=substation", "nwr/power=plant",
                    "-o", filt, "--overwrite"], check=True)
    subprocess.run(["osmium", "cat", filt, "-f", "opl", "-o", opl, "--overwrite"], check=True)
    stamp = subprocess.run(["osmium", "fileinfo", "-g", "header.option.osmosis_replication_timestamp", pbf],
                           capture_output=True, text=True).stdout.strip() or None

    nodes, ways, rels = {}, {}, {}
    with open(opl, encoding="utf-8") as fh:
        for line in fh:
            f = {p[0]: p[1:] for p in line.rstrip("\n").split(" ") if p}
            kind, oid = line[0], int(line[1:line.index(" ")])
            tags = parse_tags(f.get("T", ""))
            if kind == "n":
                if not f.get("x") or not f.get("y"):
                    continue
                nodes[oid] = {"type": "node", "id": oid, "lat": float(f["y"]), "lon": float(f["x"]), "tags": tags}
            elif kind == "w":
                ways[oid] = {"type": "way", "id": oid, "tags": tags,
                             "nodes": [int(x[1:]) for x in f.get("N", "").split(",") if x]}
            elif kind == "r":
                mem = []
                for m in f.get("M", "").split(","):
                    if not m:
                        continue
                    ref, _, role = m.partition("@")
                    mem.append((ref[0], int(ref[1:]), unesc(role)))
                rels[oid] = {"type": "relation", "id": oid, "tags": tags, "members": mem}

    def way_pts(w):
        return [{"lat": nodes[n]["lat"], "lon": nodes[n]["lon"]} for n in w["nodes"] if n in nodes]

    def rel_pts(r, depth=0):
        pts = []
        for t, ref, _role in r["members"]:
            if t == "n" and ref in nodes:
                pts.append({"lat": nodes[ref]["lat"], "lon": nodes[ref]["lon"]})
            elif t == "w" and ref in ways:
                pts += way_pts(ways[ref])
            elif t == "r" and ref in rels and depth < 2:
                pts += rel_pts(rels[ref], depth + 1)
        return pts

    def element(kind, obj):
        """Overpass の out tags geom / out center tags と同じ形の要素(帯に点が無ければ None)。"""
        if kind == "node":
            if not _in_band(obj["lat"], obj["lon"]):
                return None
            return {"type": "node", "id": obj["id"], "lat": obj["lat"], "lon": obj["lon"], "tags": obj["tags"]}
        pts = way_pts(obj) if kind == "way" else rel_pts(obj)
        if not pts or not any(_in_band(p["lat"], p["lon"]) for p in pts):
            return None
        b = _bounds(pts)
        e = {"type": kind, "id": obj["id"], "tags": obj["tags"], "bounds": b,
             "center": {"lat": (b["minlat"] + b["maxlat"]) / 2, "lon": (b["minlon"] + b["maxlon"]) / 2}}
        if kind == "way":
            e["geometry"] = pts
        return e

    def pick(power_values, kinds):
        out = []
        for kind, pool in (("node", nodes), ("way", ways), ("relation", rels)):
            if kind not in kinds:
                continue
            for oid in sorted(pool):
                obj = pool[oid]
                if (obj.get("tags") or {}).get("power") not in power_values:
                    continue
                e = element(kind, obj)
                if e:
                    out.append(e)
        return out

    el = {
        "lines": pick({"line", "cable"}, {"way"}),
        "substations": pick({"substation"}, {"node", "way", "relation"}),
        "plants": pick({"plant"}, {"node", "way", "relation"}),
    }
    meta = {"source": os.path.basename(pbf), "osm_timestamp": stamp, "band": BAND,
            "copyright": "The data included in this document is from www.openstreetmap.org. "
                         "The data is made available under ODbL."}
    for layer in ("lines", "substations"):
        feats = list(to_features(el[layer], layer).values())
        _dump(os.path.join(out_dir, f"gap_{layer}.geojson"), {"type": "FeatureCollection", **meta, "features": feats})
    fc = elements_to_geojson(el["plants"], REGION)
    _dump(os.path.join(out_dir, "gap_plants.geojson"), {**fc, **meta})
    print(f"{os.path.basename(pbf)}({stamp}) 帯 {BAND}: "
          + " ".join(f"{k} {len(v):,}" for k, v in el.items()))


def _dump(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))


def _key(feat):
    p = feat.get("properties") or {}
    return (p.get("osm_type"), p.get("osm_id"))


def _rep_point(feat):
    g = feat.get("geometry") or {}
    t, c = g.get("type"), g.get("coordinates")
    if t == "Point":
        return c[1], c[0]
    if t == "LineString" and c:
        m = c[len(c) // 2]
        return m[1], m[0]
    if t == "Polygon" and c and c[0]:
        ring = c[0][:-1] or c[0]
        return sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring)
    return None


def _belongs():
    """地物 → "ok" か足さない理由("enclave" / "territory:<地域>")。"""
    sys.path.insert(0, ROOT)
    from shapely.geometry import Point, shape
    from src.powerflow.region_attribution import area_of_coord
    bd = json.load(open(os.path.join(ROOT, "data", "reference", "freq_boundary_mixed.geojson"), encoding="utf-8"))
    enclave = [shape(f["geometry"]) for f in bd["features"]
               if (f.get("properties") or {}).get("role") == "protected_enclave"]

    def judge(feat):
        rp = _rep_point(feat)
        if rp is None:
            return "no_geometry"
        lat, lon = rp
        if any(poly.contains(Point(lon, lat)) for poly in enclave):
            return "enclave"
        a = area_of_coord(lat, lon)
        return "ok" if a == REGION else f"territory:{a}"
    return judge


def merge(gap_dir: str, write: bool) -> dict:
    rep = {"band": BAND, "region": REGION, "layers": {}}
    judge = _belongs()
    for layer in LAYERS:
        gap = json.load(open(os.path.join(gap_dir, f"gap_{layer}.geojson"), encoding="utf-8"))
        rep.setdefault("source", gap.get("source"))
        rep.setdefault("osm_timestamp", gap.get("osm_timestamp"))
        files = {}
        for r in REGIONS:
            p = os.path.join(ROOT, "data", f"{r}_{layer}.geojson")
            if os.path.exists(p):
                files[r] = json.load(open(p, encoding="utf-8"))
        index = {r: {_key(f): f for f in fc["features"] if _key(f)[1] is not None} for r, fc in files.items()}
        mine = files[REGION]
        n_have = n_copy = n_new = 0
        copied_from = {}
        skipped = {}
        added_names = []
        for f in sorted(gap["features"], key=lambda x: (str(_key(x)[0]), _key(x)[1])):
            k = _key(f)
            why = judge(f)
            if why != "ok":
                skipped[why] = skipped.get(why, 0) + 1
                continue
            if k in index[REGION]:
                n_have += 1
                continue
            src = next((r for r in REGIONS if r != REGION and k in index.get(r, {})), None)
            if src:
                g = copy.deepcopy(index[src][k])
                if layer == "plants":
                    g["properties"]["_region"] = REGION
                n_copy += 1
                copied_from[src] = copied_from.get(src, 0) + 1
            else:
                g = f
                n_new += 1
                nm = (g.get("properties") or {}).get("name")
                if nm:
                    added_names.append(nm)
            mine["features"].append(g)
            index[REGION][k] = g
        mine.setdefault("supplements", []).append(
            {"date": "2026-11-09", "band": BAND, "source": gap.get("source"),
             "osm_timestamp": gap.get("osm_timestamp"), "script": "scripts/osm_bbox_supplement.py",
             "added_new": n_new, "added_copies": n_copy})
        rep["layers"][layer] = {"in_band": len(gap["features"]), "skipped": skipped, "already": n_have, "copied": n_copy,
                                "copied_from": copied_from, "new": n_new,
                                "new_named_sample": sorted(set(added_names))[:40]}
        if layer == "plants":
            big = sorted(((g["properties"].get("capacity_mw") or 0, g["properties"].get("name"))
                          for g in mine["features"][-(n_copy + n_new):] if (g["properties"].get("capacity_mw") or 0) >= 100),
                         reverse=True) if (n_copy + n_new) else []
            rep["layers"][layer]["added_ge_100mw"] = [{"name": n, "capacity_mw": c} for c, n in big]
        if write:
            _dump(os.path.join(ROOT, "data", f"{REGION}_{layer}.geojson"), mine)
        print(f"{layer:11}: 帯 {len(gap['features']):5} = 足さない {sum(skipped.values()):4} {skipped} + "
              f"東北にある {n_have:5} + 写す {n_copy:4} {copied_from} + 新しく {n_new:5}")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("extract")
    a.add_argument("pbf")
    a.add_argument("out_dir")
    b = sub.add_parser("merge")
    b.add_argument("gap_dir")
    b.add_argument("--write", action="store_true")
    b.add_argument("--report")
    args = ap.parse_args()
    if args.cmd == "extract":
        extract(args.pbf, args.out_dir)
        return 0
    rep = merge(args.gap_dir, args.write)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
