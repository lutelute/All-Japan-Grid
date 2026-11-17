#!/usr/bin/env python3
"""潮流マップの基準を作り直したとき、過去の日別断面を、線の鍵で新しい基準の並びに並べ直す(2026-11-17).

日別断面(docs/data/flow_map/days/*.json)の値は、基準(flows_<島>.geojson)の線の並びの配列で、基準の署名
(base_sig)を持つ。基準を作り直すと、過去の日はすべて署名が合わなくなり、潮流マップに出なくなる
(flow_map.html は「線構成が古い」として当てない)。過去の日を計算し直すには各社の公表を取り直す必要があり、
古い日は取れないこともある。

ここでは**値は当時の計算のまま**、線の鍵(両端の座標・電圧・同じ組の順番、src/powerflow/line_keys.py)で
新しい基準の並びに置き直す。鍵が新しい基準に無い線(作り直しで消えた・電圧の変わった線)の値は捨て、
新しい基準にだけある線は空欄にする。並べ直した日は `rekey` に元の署名・日付・対応した数を書く。

使い方:
  PYTHONPATH=. python scripts/rekey_day_flows.py --old-ref <基準を作り直す前のコミット> [--skip 20261116 20261117] [--write]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FM = ROOT / "docs" / "data" / "flow_map"
ISLANDS = ("hokkaido", "east", "west", "okinawa")


def _git_json(ref: str, rel: str) -> dict:
    out = subprocess.run(["git", "-C", str(ROOT), "show", f"{ref}:{rel}"], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"{ref}:{rel} が読めない: {out.stderr.strip()}")
    return json.loads(out.stdout)


def remap(day_isl: dict, old_keys: list, new_keys: list, new_sig: str, today: str) -> dict:
    """1 島の日別断面を新しい基準の並びに置き直した dict を返す(元は変えない)。"""
    pos = {k: i for i, k in enumerate(new_keys)}
    n = len(new_keys)
    p = [None] * n
    ld = [None] * n
    mapped = filled = 0
    for i, k in enumerate(old_keys):
        j = pos.get(k)
        if j is None:
            continue
        mapped += 1
        p[j] = day_isl["p"][i]
        ld[j] = day_isl["ld"][i]
        if p[j] is not None and any(v is not None for v in p[j]):
            filled += 1
    out = dict(day_isl)
    out["p"], out["ld"] = p, ld
    out["rekey"] = {"from_sig": day_isl.get("base_sig"), "on": today, "n_mapped": mapped,
                    "n_old": len(old_keys), "n_new": n,
                    "note": "値は当時の正典で計算したまま、線の鍵で今の基準の並びに置き直した"}
    out["base_sig"] = new_sig
    out["coverage"] = round(filled / max(n, 1), 4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--old-ref", required=True, help="基準を作り直す前のコミット(古い flows_<島>.geojson と meta.json を読む)")
    ap.add_argument("--skip", nargs="*", default=[], help="並べ直さない日(計算し直す日)")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    old_meta = _git_json(a.old_ref, "docs/data/flow_map/meta.json")
    new_meta = json.loads((FM / "meta.json").read_text(encoding="utf-8"))
    old_keys, new_keys = {}, {}
    for isl in ISLANDS:
        old_keys[isl] = [f["properties"]["k"] for f in
                         _git_json(a.old_ref, f"docs/data/flow_map/flows_{isl}.geojson")["features"]]
        new_keys[isl] = [f["properties"]["k"] for f in
                         json.loads((FM / f"flows_{isl}.geojson").read_text(encoding="utf-8"))["features"]]
    today = date.today().isoformat()
    n_files = 0
    stats = {isl: {"rekeyed": 0, "already": 0, "other_sig": 0} for isl in ISLANDS}
    for path in sorted((FM / "days").glob("2*.json")):
        if path.stem in a.skip:
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for isl, D in (d.get("islands") or {}).items():
            if isl not in ISLANDS:
                continue
            sig = D.get("base_sig")
            if sig == new_meta[isl]["sig"]:
                stats[isl]["already"] += 1
            elif sig == old_meta[isl]["sig"] and len(D.get("p") or []) == len(old_keys[isl]):
                d["islands"][isl] = remap(D, old_keys[isl], new_keys[isl], new_meta[isl]["sig"], today)
                stats[isl]["rekeyed"] += 1
                changed = True
            else:
                stats[isl]["other_sig"] += 1
        if changed and a.write:
            path.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
            n_files += 1
    print(json.dumps({"files_written": n_files, "write": a.write, "by_island": stats}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
