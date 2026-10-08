#!/usr/bin/env python3
"""Fill lat/lon of utility_offices records with the GSI address geocoder.

  geocode.py IN.jsonl OUT.jsonl

GSI AddressSearch returns candidates; we keep the first one and record its title so
the match can be audited (geocode_title vs address). 1 request per second, cached.
Raw responses are appended to ~/agj-hazard-data/raw/D5/gsi_geocode_cache.jsonl.
"""
import datetime as dt
import json
import re
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path

import requests

UA = "Mozilla/5.0 (agj-hazard-data research; contact via lab)"
CACHE = Path.home() / "agj-hazard-data" / "raw" / "D5" / "gsi_geocode_cache.jsonl"
API = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="


def load_cache():
    c = {}
    if CACHE.exists():
        for ln in CACHE.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            c[r["q"]] = r
    return c


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    out = []
    for ln in src.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        rec = json.loads(ln)
        addr = (rec.get("address") or "").strip()
        if addr and rec.get("lat") is None:
            q = re.sub(r"〒\s*\d{3}\s*[-－ー‐]\s*\d{4}", "", addr).strip()
            q = re.split(r"[ 　]", q)[0] if re.search(r"\d", re.split(r"[ 　]", q)[0]) else q.replace(" ", "")
            if q not in cache:
                url = API + urllib.parse.quote(q)
                r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
                res = r.json() if r.status_code == 200 else []
                entry = {"q": q, "url": url, "status": r.status_code, "result": res,
                         "retrieved_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")}
                with CACHE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                cache[q] = entry
                time.sleep(1.0)
            e = cache[q]
            if e["result"]:
                top = e["result"][0]
                lon, lat = top["geometry"]["coordinates"]
                rec["lat"], rec["lon"] = lat, lon
                rec["geocode_title"] = top["properties"].get("title")
                rec["geocode_source"] = "GSI AddressSearch " + e["url"]
                rec["geocode_n_candidates"] = len(e["result"])
                m = re.match(r"^(?:北海道|東京都|京都府|大阪府|.{2,3}県)?(?:[^市区町村]{1,5}郡)?(.+?[市区町村])", q)
                city = m.group(1) if m else None
                fold = lambda x: unicodedata.normalize("NFKC", x or "").replace("ヶ", "ケ").replace("ヵ", "カ").replace("龍", "竜")
                title = rec["geocode_title"] or ""
                rec["geocode_check"] = ("city_in_title" if city and fold(city) in fold(title) else f"CHECK: '{city}' not in title")
            else:
                rec["geocode_source"] = "GSI AddressSearch: no result for " + q
        out.append(rec)
    dst.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    print(f"{len(out)} records -> {dst}")


if __name__ == "__main__":
    main()
