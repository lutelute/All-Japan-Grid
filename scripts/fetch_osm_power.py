#!/usr/bin/env python3
"""OSM から送電線・鉄塔・route=power の relation を取り直す(2026-11-07)。

    python scripts/fetch_osm_power.py --out data/osm_raw_towers/2026-11-07 [--workers 3]

data/osm_raw_towers(2026-06-15 取得)は、関東の区域で今の OSM より鉄塔が約 19% 少なかった(オーナー側の確認)。
取り直す。区切りは scripts/tower_connectivity.py と同じ(地域の外接矩形を 3x3 に割る)。タグは全部取る。
取った結果は tw_{地域}_t{番号}.json(Overpass の JSON のまま)。すでにあるファイルは取り直さない(途中から再開できる)。
同時に投げるのはサーバーごとに 2 本まで(overpass-api.de は 1 つの IP から 2 本まで。--per-server で変える)。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import time

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENDPOINTS = [   # 2026-11-07 に応答を確かめたもの(private.coffee・kumi は応答しなかった)
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
UA = "AllJapanGrid/1.0 (+https://github.com/lutelute/All-Japan-Grid)"
REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]


def tiles():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "regions.yaml"), encoding="utf-8"))["regions"]
    out = []
    for reg in REGIONS:
        bb = cfg[reg]["bounding_box"]
        la0, la1, lo0, lo1 = bb["lat_min"], bb["lat_max"], bb["lon_min"], bb["lon_max"]
        dla, dlo = (la1 - la0) / 3, (lo1 - lo0) / 3
        for r in range(3):
            for c in range(3):
                out.append((f"{reg}_t{r * 3 + c}", (la0 + r * dla, lo0 + c * dlo, la0 + (r + 1) * dla, lo0 + (c + 1) * dlo)))
    return out


def query(bbox, timeout=300):
    s, w, n, e = bbox
    b = f"{s},{w},{n},{e}"
    return (f"[out:json][timeout:{timeout}];("
            f'way["power"~"^(line|cable|minor_line)$"]({b});'
            f'node["power"="tower"]({b});'
            f'relation["route"="power"]({b});'
            f"); out body; >; out body;")


def fetch_one(key, bbox, out_dir, ep):
    path = os.path.join(out_dir, f"tw_{key}.json")
    if os.path.exists(path):
        return key, "cached"
    last = None
    for attempt in range(4):
        try:
            r = requests.post(ep, data={"data": query(bbox)}, headers={"User-Agent": UA}, timeout=360)
            if r.status_code == 200:
                d = r.json()
                if (d.get("remark") or "").lower().find("timed out") >= 0 or "runtime error" in (d.get("remark") or ""):
                    last = "remark: " + d["remark"][:80]
                else:
                    tmp = path + ".part"
                    with open(tmp, "w", encoding="utf-8") as fh:
                        json.dump(d, fh, ensure_ascii=False)
                    os.replace(tmp, path)
                    return key, f"ok {len(d.get('elements', []))}"
            else:
                last = f"http {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:80]
        time.sleep(30 * (attempt + 1))
    return key, f"FAILED {last}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=2, help="使うサーバーの数")
    ap.add_argument("--per-server", type=int, default=2, help="1 つのサーバーに同時に投げる本数(2 まで)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    todo = tiles()
    eps = ENDPOINTS[: max(1, min(args.workers, len(ENDPOINTS)))] * max(1, min(args.per_server, 2))
    lanes = [todo[i::len(eps)] for i in range(len(eps))]

    def run(lane, ep):
        res = []
        for key, bbox in lane:
            k, st = fetch_one(key, bbox, args.out, ep)
            print(f"{k}: {st} ({ep.split('/')[2]})", flush=True)
            res.append((k, st))
            if st != "cached":
                time.sleep(8)
        return res

    with cf.ThreadPoolExecutor(len(eps)) as ex:
        results = [r for f in [ex.submit(run, lane, ep) for lane, ep in zip(lanes, eps)] for r in f.result()]
    bad = [k for k, s in results if s.startswith("FAILED")]
    print(f"done: {len(results) - len(bad)} / {len(results)}" + (f"・失敗 {bad}" if bad else ""))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
