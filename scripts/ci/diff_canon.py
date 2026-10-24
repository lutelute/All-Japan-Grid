#!/usr/bin/env python3
"""2 つの正典(all.json)の違いを、何がどう違うかで出す(2026-10-24)。

CI の reproduce-canon が落ちたときに、コミットしてある正典と作り直した正典の違いを読むのに使う。

    python3 scripts/ci/diff_canon.py <a/all.json> <b/all.json> [--max 20]
    python3 scripts/ci/diff_canon.py --git HEAD docs/data/built/all.json     # コミットと作業ツリー
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter


def _load(spec: str, git_rev: str | None) -> dict:
    if git_rev:
        out = subprocess.run(["git", "show", f"{git_rev}:{spec}"], capture_output=True, text=True, check=True).stdout
        return json.loads(out)
    with open(spec, encoding="utf-8") as f:
        return json.load(f)


def _num_close(x, y) -> float | None:
    if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool):
        return abs(float(x) - float(y))
    return None


def diff_items(a: list, b: list, label: str, mx: int) -> None:
    print(f"{label}: {len(a)} / {len(b)}")
    fields, shown, maxnum = Counter(), 0, {}
    for i, (x, y) in enumerate(zip(a, b)):
        if x == y:
            continue
        for k in sorted(set(x) | set(y)):
            if x.get(k) != y.get(k):
                fields[k] += 1
                d = _num_close(x.get(k), y.get(k))
                if d is not None:
                    maxnum[k] = max(maxnum.get(k, 0.0), d)
                if shown < mx:
                    print(f"  [{i}] {x.get('id') or x.get('name') or ''} .{k}: {str(x.get(k))[:120]!s} -> {str(y.get(k))[:120]!s}")
                    shown += 1
    if len(a) != len(b):
        print(f"  件数が違う: {len(a)} -> {len(b)}")
    print(f"  違う欄: {dict(fields)}" + (f"  数値の最大差: {maxnum}" if maxnum else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--git", metavar="REV", help="a を git のこの版のパスとして読む")
    ap.add_argument("--max", type=int, default=20)
    args = ap.parse_args()
    if args.git:
        a, b = _load(args.a, args.git), _load(args.b, None)
    else:
        a, b = _load(args.a, None), _load(args.b, None)
    for key in ("nodes", "edges"):
        if key in a or key in b:
            diff_items(a.get(key, []), b.get(key, []), key, args.max)
    top_a = {k: v for k, v in a.items() if k not in ("nodes", "edges")}
    top_b = {k: v for k, v in b.items() if k not in ("nodes", "edges")}
    for k in sorted(set(top_a) | set(top_b)):
        if top_a.get(k) != top_b.get(k):
            print(f"上の欄 {k}: {str(top_a.get(k))[:200]} -> {str(top_b.get(k))[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
