#!/usr/bin/env python3
"""L_DB第一歩: 変圧器(バンク)潮流実績→地点需要の正規化テーブル(2026-08-17 オーナー「両方並列で」).

出力: data/external/system_disclosure/normalized/point_demand.csv
(1,135バンク/492変電所/7社・初回実測)。kikan層(500/275)は階級間融通で需要ではない —
需要ビューは二次kV≤22で絞ること。

Source: 各社「系統情報の公表」の変圧器(バンク)潮流実績 CSV (横持ち・1時間値)。
配電用変電所の受電=地点需要の実測として、バンク列ごとに1行の統計量へ畳む。
時系列の生値は出力しない(統計量のみ)。
"""

from __future__ import annotations

import csv
import glob
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

import numpy as np

REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
BASE = os.path.join(REPO, "data/external/system_disclosure")
OUT = os.path.join(BASE, "normalized/point_demand.csv")

ENCODINGS = ("cp932", "utf-8-sig")
MIN_OBS = 100
HEADER_SCAN_ROWS = 40
# expected "no data" placeholders (post-NFKC); anything else is flagged in the log
MISSING_MARKERS = {"-", "―", "‐", "–", "—"}

COLUMNS = [
    "utility", "scope", "year", "substation", "primary_kv", "secondary_kv",
    "peak_mw", "p95_mw", "mean_mw", "min_mw", "n_obs", "source_file",
    "substation_no",
]


def norm_label(s: str) -> str:
    """Header labels carry a leading apostrophe (tohoku) and full-width spaces."""
    s = s.replace("　", " ").strip()
    if s.startswith("'"):
        s = s[1:]
    return s.replace("　", " ").strip()


def strip_name(s: str) -> str:
    """Trim outer whitespace incl. full-width space; leave the name itself intact."""
    return s.strip().strip("　").strip().lstrip("'").strip().strip("　").strip()


def read_rows(path):
    for enc in ENCODINGS:
        try:
            with open(path, encoding=enc, newline="") as fh:
                return enc, list(csv.reader(fh))
        except UnicodeDecodeError:
            continue
    return None, None


def find_header(rows):
    """Locate the 変電所No./一次電圧/二次電圧/変電所名 block; row order is stable but
    its offset is not (tohoku FY2022 prepends a 10-row 留意事項 preamble)."""
    idx = {}
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        if not row:
            continue
        lab = norm_label(row[0])
        if lab.rstrip(".") == "変電所No":
            idx.setdefault("no", i)
        elif lab.startswith("一次電圧"):
            idx.setdefault("pri", i)
        elif lab.startswith("二次電圧"):
            idx.setdefault("sec", i)
        elif lab == "変電所名":
            idx.setdefault("name", i)
    return idx


def parse_value(raw, unknown: Counter):
    s = unicodedata.normalize("NFKC", raw).strip().lstrip("'").strip()
    s = s.replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        unknown[s] += 1
        return None


def parse_kv(raw):
    # NB: do NOT strip commas here. In the kV rows a comma separates the windings
    # of a three-winding bank (shikoku "110,66"); stripping it yields 11066 kV.
    s = unicodedata.normalize("NFKC", raw).strip().lstrip("'").strip()
    if not s:
        return ""
    try:
        return float(s)
    except ValueError:
        return s  # "110,66" / "22-13.8" -> keep verbatim for downstream to split


def scope_year(fname, utility):
    m = re.match(r"jisseki_(.+?)_tr_(\d{4})", fname)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"tyoryu_(\d{4})", fname)  # okinawa
    if m:
        return "local", m.group(1)
    return "", ""


def main():
    files = sorted(glob.glob(f"{BASE}/*/flow_actual/jisseki_*_tr_*.csv"))
    files += sorted(glob.glob(f"{BASE}/okinawa/flow_actual/tyoryu_2025_2.csv"))

    out_rows = []
    unknown = Counter()
    odd_where = defaultdict(Counter)  # non-missing junk tokens -> which file
    per_util = defaultdict(lambda: {"read": 0, "skip": 0, "rows": 0, "subs": set(),
                                    "dropped_lowobs": 0, "dropped_noname": 0})
    skips = []
    enc_used = Counter()

    for path in files:
        rel = os.path.relpath(path, REPO)
        utility = os.path.relpath(path, BASE).split(os.sep)[0]
        fname = os.path.basename(path)
        st = per_util[utility]

        enc, rows = read_rows(path)
        if rows is None:
            st["skip"] += 1
            skips.append((rel, "decode failed (cp932/utf-8-sig both)"))
            continue
        enc_used[enc] += 1

        idx = find_header(rows)
        if "name" not in idx:
            st["skip"] += 1
            skips.append((rel, "no 変電所名 header row (not a bank/substation file)"))
            continue

        h_name = rows[idx["name"]]
        h_no = rows[idx["no"]] if "no" in idx else []
        h_pri = rows[idx["pri"]] if "pri" in idx else []
        h_sec = rows[idx["sec"]] if "sec" in idx else []
        data = rows[idx["name"] + 1:]

        ncol = max([len(h_name)] + [len(r) for r in data[:50]] or [0])
        scope, year = scope_year(fname, utility)

        cols = [[] for _ in range(ncol)]
        f_unknown = Counter()
        for r in data:
            if not r or not r[0].strip():
                continue
            for j in range(1, min(len(r), ncol)):
                v = parse_value(r[j], f_unknown)
                if v is not None:
                    cols[j].append(v)
        unknown.update(f_unknown)
        for tok, n in f_unknown.items():
            if tok not in MISSING_MARKERS:
                odd_where[tok][rel] += n

        for j in range(1, ncol):
            name = strip_name(h_name[j]) if j < len(h_name) else ""
            if not name:
                st["dropped_noname"] += 1
                continue
            vals = cols[j]
            if len(vals) < MIN_OBS:
                st["dropped_lowobs"] += 1
                continue
            a = np.asarray(vals, dtype=float)
            out_rows.append({
                "utility": utility,
                "scope": scope,
                "year": year,
                "substation": name,
                "primary_kv": parse_kv(h_pri[j]) if j < len(h_pri) else "",
                "secondary_kv": parse_kv(h_sec[j]) if j < len(h_sec) else "",
                "peak_mw": round(float(a.max()), 3),
                "p95_mw": round(float(np.percentile(a, 95)), 3),
                "mean_mw": round(float(a.mean()), 3),
                "min_mw": round(float(a.min()), 3),
                "n_obs": len(vals),
                "source_file": rel,
                "substation_no": strip_name(h_no[j]) if j < len(h_no) else "",
            })
            st["rows"] += 1
            st["subs"].add(name)
        st["read"] += 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(out_rows)

    # ---- report -------------------------------------------------------
    print(f"wrote {OUT}  rows={len(out_rows)}")
    print(f"encodings used: {dict(enc_used)}")
    print()
    print(f"{'utility':10s} {'read':>4s} {'skip':>4s} {'banks':>6s} {'uniq_sub':>9s} "
          f"{'drop<100':>9s} {'drop_noname':>12s}")
    for u in sorted(per_util):
        s = per_util[u]
        print(f"{u:10s} {s['read']:4d} {s['skip']:4d} {s['rows']:6d} {len(s['subs']):9d} "
              f"{s['dropped_lowobs']:9d} {s['dropped_noname']:12d}")
    tot_read = sum(s["read"] for s in per_util.values())
    tot_skip = sum(s["skip"] for s in per_util.values())
    print(f"{'TOTAL':10s} {tot_read:4d} {tot_skip:4d} {len(out_rows):6d}")
    print()
    if skips:
        print("skipped files:")
        for rel, why in skips:
            print(f"  {rel}: {why}")
        print()
    if out_rows:
        peaks = np.array([r["peak_mw"] for r in out_rows])
        q = np.percentile(peaks, [10, 50, 90])
        print(f"peak_mw quantiles: p10={q[0]:.2f} p50={q[1]:.2f} p90={q[2]:.2f} "
              f"min={peaks.min():.2f} max={peaks.max():.2f}")
        neg = int((peaks < 0).sum())
        print(f"rows with peak_mw<0 (net reverse all year): {neg}")
    print()
    print("non-numeric value tokens dropped (token: count):")
    for tok, n in unknown.most_common(20):
        flag = "" if tok in MISSING_MARKERS else "   <-- NOT a standard missing marker"
        print(f"  {tok!r}: {n}{flag}")
    if odd_where:
        print()
        print("non-standard tokens, by file:")
        for tok, where in odd_where.items():
            for rel, n in where.most_common():
                print(f"  {tok!r} x{n}  {rel}")


if __name__ == "__main__":
    main()
