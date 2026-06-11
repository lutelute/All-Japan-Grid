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

Probed 2026-06-12 (ledger 57): jhSybt=01/03 are daily-granularity and
05/06 intra-day FORECAST variants (予想潮流) of the same two datasets —
no additional actuals in this API family. Renewable output actuals
live in each TSO's own 需給実績 CSVs (a separate source family,
recorded as a future fetcher). Every run now writes
``meta_<type>_<window>.json`` next to the CSVs (fetched_at, URL,
window, retention note) so the provenance survives the ~14-month API
retention.

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


def write_meta(types, d0: dt.date, d1: dt.date, files, out_dir: str) -> str:
    """Provenance sidecar: the API retains ~14 months, the meta makes a
    fetched snapshot citable after the source window has rolled away."""
    import json

    meta = {
        "source": "OCCTO 系統情報公表 (web-kohyo.occto.or.jp, 登録不要CSV)",
        "url_template": BASE,
        "types": list(types),
        "window": f"{d0:%Y-%m-%d}..{d1:%Y-%m-%d}",
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"),
        "n_files": len(files),
        "retention_note": "API retains roughly 14 months; this snapshot "
                          "is the citable record after the window rolls",
    }
    path = os.path.join(out_dir,
                        f"meta_{'-'.join(types)}_{d0:%Y%m}_{d1:%Y%m}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1, ensure_ascii=False)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", nargs="*", default=["02", "04"],
                    help="02=area actuals, 04=IC planned flow; 01/03/05/06 "
                         "are forecast variants (see docstring)")
    ap.add_argument("--from", dest="d0", default="2024-04-01")
    ap.add_argument("--to", dest="d1", default="2025-03-31")
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    d0 = dt.date.fromisoformat(args.d0)
    d1 = dt.date.fromisoformat(args.d1)
    fetched = []
    for t in args.types:
        for f, to in month_chunks(d0, d1):
            try:
                p = fetch(t, f, to, args.out_dir)
                fetched.append(p)
                print(f"  {t} {f:%Y-%m}: {os.path.getsize(p):>9,d} B")
            except Exception as e:  # noqa: BLE001 — keep fetching other months
                print(f"  {t} {f:%Y-%m}: FAILED {e}", file=sys.stderr)
            time.sleep(1.0)        # polite
    if fetched:
        print(f"meta -> {write_meta(args.types, d0, d1, fetched, args.out_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
