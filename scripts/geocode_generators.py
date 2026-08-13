#!/usr/bin/env python3
"""発電所マスタに座標を付ける（国土地理院ジオコーディングAPI）。

    https://msearch.gsi.go.jp/address-search/AddressSearch （無償・出典明示で利用可）

FIT層は所在地（番地まで）を持つので住所ジオコーディングができる。
大規模層(OCCTO)は住所を持たないので対象外（別途住所ソースが要る）。

効率化:
  - **市区町村単位でキャッシュ**する。38万件の多くは番地違いの同一市区町村なので、
    市区町村の代表座標で足りる（発電所マップの粒度なら十分）。
    番地までジオコードしたい場合は --precise。
  - キャッシュは data/cache/geocode.jsonl（消えても再構築可能）。
  - APIに配慮して待機を入れる。

出典: 地理院APIの結果には「地理院タイル」等と同様に出典明示が要る。
出力: data/external/system_disclosure/normalized/generator_master_geo.csv（observed層）

使い方:
    python scripts/geocode_generators.py --min-mw 1     # 1MW以上だけ（推奨・現実的）
    python scripts/geocode_generators.py --precise      # 番地まで（遅い）
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NORM = ROOT / "data" / "external" / "system_disclosure" / "normalized"
CACHE = ROOT / "data" / "cache" / "geocode.jsonl"
API = "https://msearch.gsi.go.jp/address-search/AddressSearch"
UA = "All-Japan-Grid/1.0 (research; power grid mapping)"

# 市区町村までを切り出す（番地以降を落とす）
CITY_RX = re.compile(r"^(.+?[都道府県])(.+?[市区町村])")


def to_city(addr: str) -> str:
    a = re.sub(r"[\s　]", "", str(addr))
    m = CITY_RX.match(a)
    if not m:
        return a
    # 政令市の「◯◯市△△区」まで含める
    city = m.group(1) + m.group(2)
    rest = a[len(city):]
    m2 = re.match(r"^(.+?区)", rest)
    if m2 and m.group(2).endswith("市"):
        city += m2.group(1)
    return city


def load_cache() -> dict[str, list | None]:
    c: dict[str, list | None] = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                c[r["q"]] = r["coord"]
    return c


def append_cache(q: str, coord: list | None) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"q": q, "coord": coord}, ensure_ascii=False) + "\n")


def geocode(q: str) -> list | None:
    url = API + "?" + urllib.parse.urlencode({"q": q})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not data:
        return None
    c = data[0].get("geometry", {}).get("coordinates")
    return [round(c[0], 6), round(c[1], 6)] if c else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-mw", type=float, default=1.0,
                    help="この出力[MW]以上のFIT設備だけ座標化（既定1MW）")
    ap.add_argument("--precise", action="store_true", help="番地まで（遅い）")
    ap.add_argument("--sleep", type=float, default=0.15)
    args = ap.parse_args()

    master = pd.read_csv(NORM / "generator_master.csv")
    fit = master[(master.scale == "fit") & (master.get("location").notna())].copy()
    if "capacity_mw" in fit:
        fit = fit[fit.capacity_mw.fillna(0) >= args.min_mw]
    fit["query"] = fit["location"].map(lambda a: a if args.precise else to_city(a))

    cache = load_cache()
    uniq = sorted(set(fit["query"]) - set(cache))
    print(f"FIT {len(fit)} 件（{args.min_mw}MW以上）/ 未キャッシュ地名 {len(uniq)}")

    for i, q in enumerate(uniq, 1):
        coord = geocode(q)
        cache[q] = coord
        append_cache(q, coord)
        if i % 50 == 0:
            print(f"  {i}/{len(uniq)} …")
        time.sleep(args.sleep)

    fit["lon"] = fit["query"].map(lambda q: (cache.get(q) or [None, None])[0])
    fit["lat"] = fit["query"].map(lambda q: (cache.get(q) or [None, None])[1])
    got = fit["lon"].notna().sum()

    dest = NORM / "generator_master_geo.csv"
    fit.to_csv(dest, index=False, encoding="utf-8")
    print(f"座標化 {got}/{len(fit)} → {dest.relative_to(ROOT)}")
    print(f"  精度: {'番地' if args.precise else '市区町村代表点'}")
    print(f"  キャッシュ: {CACHE.relative_to(ROOT)}（{len(cache)} 地名）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
