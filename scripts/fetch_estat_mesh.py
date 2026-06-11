"""Fetch 2020-census 1 km mesh population (e-Stat GIS, stats T001140).

    python scripts/fetch_estat_mesh.py                  # Kanto (TEPCO) codes
    python scripts/fetch_estat_mesh.py --codes 5339 5340

Drops tblT001140S<code>.txt files into data/external/estat/ (gitignored
— e-Stat terms require attribution: 「政府統計の総合窓口(e-Stat)」
国勢調査2020 1kmメッシュ人口及び世帯, https://www.e-stat.go.jp/gis).
The power-flow residual-demand allocator (spatial="population") reads
this directory; absence simply falls back to the voltage-class rule.
"""

import argparse
import io
import os
import sys
import urllib.request
import zipfile

URL = ("https://www.e-stat.go.jp/gis/statmap-search/data"
       "?statsId=T001140&code={code}&downloadType=2")

# 1st-order mesh codes covering the TEPCO service area (Kanto +
# Yamanashi + eastern Shizuoka); neighbours that 404 are skipped.
KANTO = ["5238", "5239", "5240", "5338", "5339", "5340",
         "5438", "5439", "5440", "5538", "5539", "5540"]


def fetch(code: str, out_dir: str) -> str | None:
    req = urllib.request.Request(URL.format(code=code),
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            blob = r.read()
    except Exception as e:           # noqa: BLE001 — per-code skip is fine
        print(f"  {code}: fetch failed ({e})")
        return None
    if not blob[:2] == b"PK":
        print(f"  {code}: not a zip ({len(blob)} bytes) — skipped")
        return None
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.namelist():
            if info.endswith(".txt"):
                target = os.path.join(out_dir, os.path.basename(info))
                with open(target, "wb") as f:
                    f.write(z.read(info))
                print(f"  {code}: -> {target}")
                return target
    print(f"  {code}: zip had no .txt")
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--codes", nargs="*", default=KANTO)
    ap.add_argument("--out", default="data/external/estat")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    ok = sum(1 for c in args.codes if fetch(c, args.out))
    print(f"{ok}/{len(args.codes)} mesh files in {args.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
