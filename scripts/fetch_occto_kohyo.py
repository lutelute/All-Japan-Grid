#!/usr/bin/env python3
"""Fetch OCCTO's public wide-area CSV API (no registration required).

Discovered 2026-06-11: ``web-kohyo.occto.or.jp`` serves registration-free
CSV downloads. Two datasets matter for model calibration:

- ``jhSybt=02`` — per-AREA demand/supply/reserve, 30-min steps
  (columns incl. エリア需要(MW)): measured area demand to replace the
  static "2023 peak x load factor" guess.
- ``jhSybt=04`` — per-INTERCONNECTOR operating capacity / margin /
  PLANNED flow (順方向計画潮流(MW)), 30-min steps: data-driven signed
  utilisations to replace the hand-set TYPICAL_UTILISATION in
  src/powerflow/boundary.py (validation roadmap item 5).

Raw CSVs land under ``data/external/occto/`` (NOT redistributable —
gitignored); commit only derived aggregates with citation.

Usage::

    python scripts/fetch_occto_kohyo.py --from 2024-04-01 --to 2025-03-31
    python scripts/fetch_occto_kohyo.py --types 04 --from 2024-04-01 --to 2024-04-30
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
import urllib.request

BASE = ("https://web-kohyo.occto.or.jp/kks-web-public/download/"
        "downloadCsv?jhSybt={t}&tgtYmdFrom={f}&tgtYmdTo={to}")
OUT_DIR = os.path.join("data", "external", "occto")
UA = {"User-Agent": "Mozilla/5.0 (All-Japan-Grid research fetch)"}


def month_chunks(d0: dt.date, d1: dt.date):
    cur = d0
    while cur <= d1:
        nxt = (cur.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        end = min(nxt - dt.timedelta(days=1), d1)
        yield cur, end
        cur = nxt


def fetch(t: str, f: dt.date, to: dt.date, out_dir: str) -> str:
    url = BASE.format(t=t, f=f.strftime("%Y/%m/%d"), to=to.strftime("%Y/%m/%d"))
    path = os.path.join(out_dir, f"kohyo_{t}_{f:%Y%m}.csv")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as fh:
        fh.write(r.read())
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", nargs="*", default=["02", "04"])
    ap.add_argument("--from", dest="d0", default="2024-04-01")
    ap.add_argument("--to", dest="d1", default="2025-03-31")
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    d0 = dt.date.fromisoformat(args.d0)
    d1 = dt.date.fromisoformat(args.d1)
    for t in args.types:
        for f, to in month_chunks(d0, d1):
            try:
                p = fetch(t, f, to, args.out_dir)
                print(f"  {t} {f:%Y-%m}: {os.path.getsize(p):>9,d} B")
            except Exception as e:  # noqa: BLE001 — keep fetching other months
                print(f"  {t} {f:%Y-%m}: FAILED {e}", file=sys.stderr)
            time.sleep(1.0)        # polite
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
