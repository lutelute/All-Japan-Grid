#!/usr/bin/env python3
"""Print the visible text of a fetched raw file (HTML via BeautifulSoup, PDF via its .txt
sidecar or PyMuPDF), optionally only lines matching a regex with context.

  textof.py RAWPATH [-g REGEX] [-C 2]
"""
import argparse
import re
import sys
from pathlib import Path


def text_of(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".pdf":
        side = path.with_suffix(path.suffix + ".txt")
        if side.exists():
            return side.read_text(encoding="utf-8")
        import pymupdf
        doc = pymupdf.open(path)
        return "".join(f"\n=== page {i} ===\n" + p.get_text() for i, p in enumerate(doc, 1))
    raw = path.read_bytes()
    if suf in (".html", ".htm") or raw[:2000].lower().find(b"<html") >= 0:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, "lxml")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        txt = soup.get_text("\n")
        return re.sub(r"\n\s*\n+", "\n", txt)
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("-g", "--grep")
    ap.add_argument("-C", type=int, default=1)
    a = ap.parse_args()
    txt = text_of(Path(a.path))
    if not a.grep:
        sys.stdout.write(txt)
        return
    lines = txt.splitlines()
    pat = re.compile(a.grep)
    page = None
    shown = set()
    for i, ln in enumerate(lines):
        if ln.startswith("=== page "):
            page = ln
        if pat.search(ln):
            lo, hi = max(0, i - a.C), min(len(lines), i + a.C + 1)
            if i in shown:
                continue
            print(f"--- {page or ''} line {i}")
            for j in range(lo, hi):
                shown.add(j)
                print(lines[j])


if __name__ == "__main__":
    main()
