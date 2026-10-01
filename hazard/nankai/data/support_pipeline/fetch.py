#!/usr/bin/env python3
"""Download a source file as-is into ~/agj-hazard-data/raw and append a manifest line.

Usage (on pws-160core):
  ~/agj-hazard-data/.venv/bin/python ~/agj-hazard-data/scripts/fetch.py URL \
      --dataset D1 --license "TEPCO PG terms: all rights reserved" [--name file.pdf] [--note ...] [--force]

Prints the local path (last line). If the same URL was already fetched, the existing
file is reused unless --force. manifest.jsonl is appended under an flock.
PDFs also get a sibling .txt with "=== page N ===" markers (PyMuPDF).
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

ROOT = Path.home() / "agj-hazard-data"
RAW = ROOT / "raw"
MANIFEST = ROOT / "manifest.jsonl"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
JST = dt.timezone(dt.timedelta(hours=9))


def now():
    return dt.datetime.now(JST).isoformat(timespec="seconds")


def safe_name(url: str) -> str:
    p = urllib.parse.urlparse(url)
    name = urllib.parse.unquote(p.path.rstrip("/").split("/")[-1]) or "index"
    if p.query:
        name += "__" + re.sub(r"[^A-Za-z0-9=_.-]+", "_", p.query)[:80]
    name = re.sub(r"[\\/:*?\"<>|\s]+", "_", name)
    return name[:150]


def load_manifest():
    out = {}
    if MANIFEST.exists():
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("local_path"):
                out[rec["url"]] = rec
    return out


def pdf_to_text(path: Path):
    try:
        import pymupdf
    except ImportError:
        return None
    txt = path.with_suffix(path.suffix + ".txt")
    doc = pymupdf.open(path)
    with txt.open("w", encoding="utf-8") as f:
        for i, page in enumerate(doc, 1):
            f.write(f"\n=== page {i} ===\n")
            f.write(page.get_text())
    return txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--license", default="unknown; see source site terms")
    ap.add_argument("--name")
    ap.add_argument("--note", default="")
    ap.add_argument("--referer")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    seen = load_manifest()
    if a.url in seen and not a.force and Path(seen[a.url]["local_path"]).exists():
        print(seen[a.url]["local_path"])
        return

    headers = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}
    if a.referer:
        headers["Referer"] = a.referer
    last = None
    for attempt in range(3):
        try:
            r = requests.get(a.url, headers=headers, timeout=120, allow_redirects=True)
            break
        except requests.RequestException as e:  # retry transient errors
            last = e
            time.sleep(3 * (attempt + 1))
    else:
        print(f"ERROR fetch failed: {last}", file=sys.stderr)
        sys.exit(2)

    host = urllib.parse.urlparse(a.url).netloc
    d = RAW / a.dataset / host
    d.mkdir(parents=True, exist_ok=True)
    name = a.name or safe_name(a.url)
    ctype = r.headers.get("Content-Type", "")
    if "." not in name[-6:]:
        if "pdf" in ctype:
            name += ".pdf"
        elif "html" in ctype:
            name += ".html"
    path = d / name
    owners = {rec["url"] for rec in seen.values() if rec.get("local_path") == str(path)}
    if path.exists() and (owners - {a.url} or not owners):
        # same file name already used by a different URL: disambiguate with a URL hash
        h = hashlib.sha1(a.url.encode()).hexdigest()[:8]
        path = d / f"{path.stem}__{h}{path.suffix}"
    path.write_bytes(r.content)
    sha = hashlib.sha256(r.content).hexdigest()
    rec = {
        "url": a.url,
        "final_url": r.url,
        "http_status": r.status_code,
        "content_type": ctype,
        "bytes": len(r.content),
        "sha256": sha,
        "local_path": str(path),
        "retrieved_at": now(),
        "dataset": a.dataset,
        "license": a.license,
        "note": a.note,
    }
    with MANIFEST.open("a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)
    if r.status_code != 200:
        print(f"WARN http {r.status_code}", file=sys.stderr)
    if path.suffix.lower() == ".pdf" or "pdf" in ctype:
        try:
            t = pdf_to_text(path)
            if t:
                print(f"text: {t}", file=sys.stderr)
        except Exception as e:  # non-fatal
            print(f"WARN pdf text failed: {e}", file=sys.stderr)
    print(path)


if __name__ == "__main__":
    main()
