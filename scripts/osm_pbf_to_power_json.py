#!/usr/bin/env python3
"""OSM の抽出(.osm.pbf)から、送電線・鉄塔・route=power を Overpass の JSON と同じ形で書き出す(2026-11-07)。

    python scripts/osm_pbf_to_power_json.py <japan-YYMMDD.osm.pbf> <出力フォルダ>

Overpass での取り直し(scripts/fetch_osm_power.py)は 1 区画に 1〜2 分かかり全国で 2 時間を超えるので、
Geofabrik の日本の抽出を osmium(コマンド)で絞り込む方を既定にした。全国が同じ時点(抽出の時刻)にそろう。
  1. osmium tags-filter: way の power=line/cable/minor_line、node の power=tower、relation の route=power
     (way の点と relation のメンバーも一緒に残る)
  2. osmium cat -f opl で文字にして読み、地域の外接矩形(config/regions.yaml)の中だけを残す
  3. tw_japan_t0.json(Overpass の JSON と同じ形。osm_routes.load_raw がそのまま読める)
タグは全部残す。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ESC = re.compile(r"%([0-9a-fA-F]+)%")


def unesc(s: str) -> str:
    return _ESC.sub(lambda m: chr(int(m.group(1), 16)), s)


def parse_tags(t: str) -> dict:
    out = {}
    if not t:
        return out
    for kv in t.split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        out[unesc(k)] = unesc(v)
    return out


def main():
    pbf, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    filt = os.path.join(out_dir, "power.osm.pbf")
    opl = os.path.join(out_dir, "power.opl")
    subprocess.run(["osmium", "tags-filter", pbf, "w/power=line,cable,minor_line", "n/power=tower", "r/route=power",
                    "-o", filt, "--overwrite"], check=True)
    subprocess.run(["osmium", "cat", filt, "-f", "opl", "-o", opl, "--overwrite"], check=True)
    stamp = subprocess.run(["osmium", "fileinfo", "-g", "header.option.osmosis_replication_timestamp", pbf],
                           capture_output=True, text=True).stdout.strip() or None

    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "regions.yaml"), encoding="utf-8"))["regions"]
    boxes = [(r["bounding_box"]["lat_min"], r["bounding_box"]["lat_max"], r["bounding_box"]["lon_min"], r["bounding_box"]["lon_max"])
             for k, r in cfg.items() if "bounding_box" in r and k != "national_backbone"]

    def inside(lat, lon):
        return any(a <= lat <= b and c <= lon <= d for a, b, c, d in boxes)

    nodes, ways, rels = {}, [], []
    with open(opl, encoding="utf-8") as fh:
        for line in fh:
            f = {p[0]: p[1:] for p in line.rstrip("\n").split(" ") if p}
            kind, oid = line[0], int(line[1:line.index(" ")])
            tags = parse_tags(f.get("T", ""))
            if kind == "n":
                if not f.get("x") or not f.get("y"):
                    continue
                e = {"type": "node", "id": oid, "lat": float(f["y"]), "lon": float(f["x"])}
                if tags:
                    e["tags"] = tags
                nodes[oid] = e
            elif kind == "w":
                nd = [int(x[1:]) for x in f.get("N", "").split(",") if x]
                ways.append({"type": "way", "id": oid, "nodes": nd, "tags": tags})
            elif kind == "r":
                mem = []
                for m in f.get("M", "").split(","):
                    if not m:
                        continue
                    ref, _, role = m.partition("@")
                    mem.append({"type": {"n": "node", "w": "way", "r": "relation"}[ref[0]], "ref": int(ref[1:]), "role": unesc(role)})
                rels.append({"type": "relation", "id": oid, "members": mem, "tags": tags})
    # 地域の外接矩形の中だけ: 鉄塔は点の位置、way は点が 1 つでも中にあれば、relation はメンバーの way が残れば
    keep_w = [w for w in ways if any(n in nodes and inside(nodes[n]["lat"], nodes[n]["lon"]) for n in w["nodes"])]
    need_n = {n for w in keep_w for n in w["nodes"]}
    keep_n = [e for i, e in nodes.items() if i in need_n or ((e.get("tags") or {}).get("power") == "tower" and inside(e["lat"], e["lon"]))]
    wids = {w["id"] for w in keep_w}
    keep_r = [r for r in rels if any(m["type"] == "way" and m["ref"] in wids for m in r["members"])]
    d = {"version": 0.6, "generator": "osmium tags-filter + scripts/osm_pbf_to_power_json.py",
         "osm3s": {"timestamp_osm_base": stamp, "source": os.path.basename(pbf),
                   "copyright": "The data included in this document is from www.openstreetmap.org. The data is made available under ODbL."},
         "elements": sorted(keep_n, key=lambda e: e["id"]) + sorted(keep_w, key=lambda e: e["id"]) + sorted(keep_r, key=lambda e: e["id"])}
    path = os.path.join(out_dir, "tw_japan_t0.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    n_tw = sum(1 for e in keep_n if (e.get("tags") or {}).get("power") == "tower")
    print(f"{os.path.basename(pbf)}({stamp}): 鉄塔 {n_tw:,}・点 {len(keep_n):,}・way {len(keep_w):,}・route=power {len(keep_r):,} → {path}")


if __name__ == "__main__":
    main()
