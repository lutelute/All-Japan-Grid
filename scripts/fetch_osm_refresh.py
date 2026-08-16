#!/usr/bin/env python3
"""OSM再抽出(2026-08 大工事): lines+substations を osm_id+全タグ付きで再取得する。

背景(オーナー承認「大工事していい」):
  - 現行 data/{region}_{lines,substations}.geojson は **osm_id を持たず**、
    enrich結果(endpoint_matching命名等)が in-place 混入している([[project_agj_db_unification]])
  - 2025年以降のOSM新規マッピング(小倉圏の配電用変電所群・苅田変電所等)が入っていない
  - 回線数タグ(circuits/cables)はインピーダンス(2回線=半分)に直結するため全タグ保持が必須

設計:
  - Overpass直叩き(osmnx非依存)。出力は data/osm_refresh/{region}_{layer}.geojson
    (**現行dataは上書きしない** — 差分比較とenrich再走を経てから移行する)
  - 生Overpass JSONも data/osm_refresh/raw/ に保存(untracked・必要ならnas03へ退避)
  - 地域ごとにチェックポイント(出力が既にあればスキップ)=再開可能
  - タイル分割は大型地域のみ(tokyo/chubu/tohoku/hokkaido/kyushu 2x2)

実行:
  python3 scripts/fetch_osm_refresh.py            # 全10地域
  python3 scripts/fetch_osm_refresh.py --region kyushu
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/osm_refresh"
RAW = OUT / "raw"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
TILED = {"tokyo": (2, 2), "chubu": (2, 2), "tohoku": (2, 2),
         "hokkaido": (2, 2), "kyushu": (2, 2)}
PAUSE = 8          # 礼儀正しく
TIMEOUT = 300


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def overpass(query: str, label: str) -> dict | None:
    data = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(6):
        ep = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(ep, data=data,
                                         headers={"User-Agent": "AllJapanGrid-refresh/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                body = r.read()
            d = json.loads(body)
            return d
        except Exception as exc:  # noqa: BLE001
            wait = min(60, 10 * (attempt + 1))
            log(f"  ! {label}: attempt{attempt+1} {type(exc).__name__}: {str(exc)[:60]} → {wait}s待機")
            time.sleep(wait)
    return None


def tiles_of(bb: dict, region: str):
    rows, cols = TILED.get(region, (1, 1))
    la0, la1 = bb["lat_min"], bb["lat_max"]
    lo0, lo1 = bb["lon_min"], bb["lon_max"]
    dla, dlo = (la1 - la0) / rows, (lo1 - lo0) / cols
    for r in range(rows):
        for c in range(cols):
            yield (la0 + r * dla, lo0 + c * dlo, la0 + (r + 1) * dla, lo0 + (c + 1) * dlo)


def to_features(elements: list, layer: str) -> dict[tuple, dict]:
    """Overpass要素→GeoJSON feature。キー=(osm_type, osm_id)で重複排除。"""
    feats: dict[tuple, dict] = {}
    for e in elements:
        t = e.get("tags") or {}
        key = (e["type"], e["id"])
        geom = None
        if e["type"] == "node":
            geom = {"type": "Point", "coordinates": [e["lon"], e["lat"]]}
        elif e["type"] == "way" and e.get("geometry"):
            coords = [[p["lon"], p["lat"]] for p in e["geometry"]]
            if layer == "lines":
                geom = {"type": "LineString", "coordinates": coords}
            else:  # substations: 閉路ならPolygon
                if len(coords) >= 4 and coords[0] == coords[-1]:
                    geom = {"type": "Polygon", "coordinates": [coords]}
                elif e.get("bounds"):
                    b = e["bounds"]
                    geom = {"type": "Point",
                            "coordinates": [(b["minlon"] + b["maxlon"]) / 2,
                                            (b["minlat"] + b["maxlat"]) / 2]}
        elif e["type"] == "relation" and e.get("bounds"):
            b = e["bounds"]
            geom = {"type": "Point",
                    "coordinates": [(b["minlon"] + b["maxlon"]) / 2,
                                    (b["minlat"] + b["maxlat"]) / 2]}
        if geom is None:
            continue
        feats[key] = {
            "type": "Feature",
            "properties": {**t, "osm_type": e["type"], "osm_id": e["id"]},
            "geometry": geom,
        }
    return feats


QUERIES = {
    "lines": '(way["power"~"^(line|cable)$"]({s},{w},{n},{e}););out tags geom;',
    "substations": '(node["power"="substation"]({s},{w},{n},{e});'
                   'way["power"="substation"]({s},{w},{n},{e});'
                   'relation["power"="substation"]({s},{w},{n},{e}););out tags geom;',
}


def fetch_region(region: str, bb: dict) -> None:
    for layer, qtpl in QUERIES.items():
        dest = OUT / f"{region}_{layer}.geojson"
        if dest.exists():
            log(f"SKIP {region}/{layer} (既存)")
            continue
        feats: dict[tuple, dict] = {}
        tiles = list(tiles_of(bb, region))
        for i, (s, w, n, e) in enumerate(tiles):
            q = f"[out:json][timeout:{TIMEOUT}];" + qtpl.format(s=s, w=w, n=n, e=e)
            label = f"{region}/{layer} tile{i+1}/{len(tiles)}"
            d = overpass(q, label)
            if d is None:
                log(f"  !! {label} 取得失敗(6回) — この地域は不完全。destを書かず中断")
                return
            RAW.mkdir(parents=True, exist_ok=True)
            (RAW / f"{region}_{layer}_t{i}.json").write_text(
                json.dumps(d, ensure_ascii=False), encoding="utf-8")
            got = to_features(d.get("elements", []), layer)
            feats.update(got)
            log(f"  {label}: +{len(got)} (計{len(feats)})")
            time.sleep(PAUSE)
        dest.write_text(json.dumps(
            {"type": "FeatureCollection",
             "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "features": list(feats.values())}, ensure_ascii=False), encoding="utf-8")
        log(f"SAVED {dest.name}: {len(feats)} features")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region")
    args = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "config/regions.yaml").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    for region, rc in cfg["regions"].items():
        if args.region and region != args.region:
            continue
        bb = rc.get("bounding_box")
        if not bb:
            log(f"! {region}: bounding_boxなし skip")
            continue
        fetch_region(region, bb)
    log("完了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
