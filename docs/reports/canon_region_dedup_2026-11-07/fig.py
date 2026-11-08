#!/usr/bin/env python3
"""介入#58(案)の前と後の図: 全国の正典で、地域をまたぐ写し(同じ形の枝が 2 つ以上の地域の点に付く)を赤で示す。

    PYTHONPATH=. python3 docs/reports/canon_region_dedup_2026-11-07/fig.py [基準の ref(既定 origin/main)]
"""
import collections
import json
import math
import os
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
REF = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
k5 = lambda la, lo: (round(la, 5), round(lo, 5))


def copies(d):
    """両端の点と形が同じ枝が 2 本以上あり、その端の点に 2 つ以上の地域の点がある組の枝。"""
    reg_at = collections.defaultdict(set)
    for n in d["nodes"]:
        reg_at[k5(n["lat"], n["lon"])].add(n.get("region"))
    by = collections.defaultdict(list)
    for e in d["edges"]:
        if e.get("tie"):
            continue
        p = tuple(k5(*q) for q in (e.get("path") or [e["a"], e["b"]]))
        a, b = k5(*e["a"]), k5(*e["b"])
        by[min((a, b, p), (b, a, p[::-1]))].append(e)
    out = []
    for sig, es in by.items():
        if len(es) >= 2 and len(reg_at[sig[0]] | reg_at[sig[1]]) >= 2:
            out += es[1:]
    return out


def main():
    b = json.loads(subprocess.run(["git", "show", f"{REF}:docs/data/built/all.json"], cwd=ROOT,
                                  capture_output=True, text=True, check=True).stdout)
    a = json.load(open(os.path.join(ROOT, "docs/data/built/all.json"), encoding="utf-8"))
    fig, axs = plt.subplots(1, 2, figsize=(16, 9.5))
    for ax, d, title in ((axs[0], b, "前"), (axs[1], a, "後（介入#58 案）")):
        segs = [[(q[1], q[0]) for q in (e.get("path") or [e["a"], e["b"]])] for e in d["edges"]]
        ax.add_collection(LineCollection(segs, colors="#c8c8c8", linewidths=0.3, zorder=1))
        cp = copies(d)
        km = sum(sum(math.hypot(q2[0] - q1[0], (q2[1] - q1[1]) * math.cos(math.radians(q1[0]))) * 111.195
                     for q1, q2 in zip(e.get("path") or [e["a"], e["b"]], (e.get("path") or [e["a"], e["b"]])[1:])) for e in cp)
        ax.add_collection(LineCollection([[(q[1], q[0]) for q in (e.get("path") or [e["a"], e["b"]])] for e in cp],
                                         colors="#d62728", linewidths=1.2, zorder=2))
        ax.set_xlim(127.5, 146.0)
        ax.set_ylim(26.0, 45.6)
        ax.set_aspect(1 / math.cos(math.radians(36)))
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(f"{title}: 点 {len(d['nodes']):,}・枝 {len(d['edges']):,}\n"
                     f"地域をまたいで二重に入っている枝（赤）{len(cp):,} 本・{km:,.0f} km", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_copies.png"), dpi=100)
    print("ok")


if __name__ == "__main__":
    main()
