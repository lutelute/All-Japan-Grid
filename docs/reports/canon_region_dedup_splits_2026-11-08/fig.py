#!/usr/bin/env python3
"""介入#60(案)の図。地域ごとの正典(docs/data/built/<地域>.json)に #59・#58 だけを当てたもの(前)と、#60 も当てた
もの(後)を、地域をまたいで二重になっている線分(赤)で比べる。

    PYTHONPATH=. python3 docs/reports/canon_region_dedup_splits_2026-11-08/fig.py
→ fig_dup.png(全国)・fig_cases.png(4 か所の前と後)
"""
import collections
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
from src.topology.region_dedup import (REGIONS, align_copy_ends, align_copy_splits, dedup_region_copies,  # noqa: E402
                                       heal_copy_splits)

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
k5 = lambda la, lo: (round(la, 5), round(lo, 5))
REG_C = {"hokkaido": "#8c564b", "tohoku": "#2ca02c", "tokyo": "#d62728", "chubu": "#1f77b4", "hokuriku": "#17becf",
         "kansai": "#ff7f0e", "chugoku": "#9467bd", "shikoku": "#bcbd22", "kyushu": "#e377c2", "okinawa": "#7f7f7f"}
REG_JA = {"hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京", "chubu": "中部", "hokuriku": "北陸", "kansai": "関西",
          "chugoku": "中国", "shikoku": "四国", "kyushu": "九州", "okinawa": "沖縄"}
# 4 か所: (中心, 半径 m, 見出し)
CASES = [((37.0060, 137.7700), 2600, "大字青海変電所（66 kV）: 中部の写しは北陸の変電所を通り抜ける"),
         ((37.0700, 140.0112), 900, "那須湯本変電所（那須線）: 東京の写しは変電所の点が無く通り抜ける"),
         ((33.6082, 131.0154), 1300, "豊前変電所（豊前北幹線など）: 中国の写しは変電所を通り抜ける"),
         ((36.7127, 139.8330), 700, "新今市開閉所（新いわき幹線 500 kV）: 最後の径間が地域で違う")]


def load():
    col = {}
    for r in REGIONS:
        p = os.path.join(ROOT, "docs", "data", "built", r + ".json")
        if os.path.exists(p):
            b = json.load(open(p, encoding="utf-8"))
            col[r] = {"nodes": b["nodes"], "edges": b["edges"]}
    before, _ = dedup_region_copies(align_copy_ends(col)[0])
    s1, _ = align_copy_splits(col)
    s3, _ = dedup_region_copies(align_copy_ends(s1)[0])
    after, _ = heal_copy_splits(s3)
    return before, after


def pts(e):
    return [k5(*q) for q in (e.get("path") or [e["a"], e["b"]])]


def dup_segs(c, weighted=False):
    seg = collections.defaultdict(set)
    for r, v in c.items():
        for e in v["edges"]:
            if e.get("tie"):
                continue
            p = pts(e)
            for u, w in zip(p, p[1:]):
                if u != w:
                    seg[(u, w) if u <= w else (w, u)].add(r)
    if weighted:
        return {s: len(rs) - 1 for s, rs in seg.items() if len(rs) > 1}
    return {s for s, rs in seg.items() if len(rs) > 1}


def km(segs):
    def m(p, q):
        c = math.cos(math.radians((p[0] + q[0]) / 2))
        return math.hypot((p[0] - q[0]) * 111320.0, (p[1] - q[1]) * 111320.0 * c)
    return sum(m(*s) * n for s, n in segs.items()) / 1000


def fig_dup(before, after):
    fig, axs = plt.subplots(1, 2, figsize=(14, 8.4))
    for ax, c, tag in ((axs[0], before, "前（#59・#58 まで）"), (axs[1], after, "後（#60 も当てる）")):
        segs = [[(q[1], q[0]) for q in pts(e)] for v in c.values() for e in v["edges"] if not e.get("tie")]
        ax.add_collection(LineCollection(segs, colors="#c8c8c8", linewidths=0.3))
        d = dup_segs(c, weighted=True)
        ax.add_collection(LineCollection([[(u[1], u[0]), (w[1], w[0])] for u, w in d], colors="#d62728", linewidths=1.6))
        ax.set_xlim(128.5, 146.0)
        ax.set_ylim(30.8, 45.7)
        ax.set_aspect(1 / math.cos(math.radians(38)))
        ax.set_title(f"{tag}: 地域をまたいで二重に数えた延長 {km(d):,.0f} km", fontsize=12)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle("区切りの違う地域の写し（赤 = 2 つ以上の地域の正典に同じ線分がある）", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_dup.png"), dpi=110)


def draw(ax, c, center, r_m, title):
    lat0, lon0 = center
    dla = r_m / 111320.0
    dlo = r_m / (111320.0 * math.cos(math.radians(lat0)))
    box = (lat0 - dla, lat0 + dla, lon0 - dlo, lon0 + dlo)
    inb = lambda q: box[0] <= q[0] <= box[1] and box[2] <= q[1] <= box[3]
    d = dup_segs(c)
    ax.add_collection(LineCollection([[(u[1], u[0]), (w[1], w[0])] for u, w in d if inb(u) or inb(w)],
                                     colors="#ff000033", linewidths=9))
    off = {r: k for k, r in enumerate(REGIONS)}
    seen = set()
    labeled = set()
    for r, v in c.items():
        for e in v["edges"]:
            p = pts(e)
            full = [k5(*e["a"])] + p + [k5(*e["b"])]
            if not any(inb(q) for q in full):
                continue
            # 地域ごとに少しずらして描く(重なる写しが見えるように)
            sh = (off[r] - 4) * dlo * 0.006
            xs = [q[1] + sh for q in full]
            ys = [q[0] + sh for q in full]
            ax.plot(xs, ys, "-", color=REG_C[r], lw=1.4, alpha=0.9, label=REG_JA[r] if r not in seen else None)
            seen.add(r)
        for n in v["nodes"]:
            q = k5(n["lat"], n["lon"])
            if not inb(q):
                continue
            if n.get("sub"):
                ax.plot(q[1], q[0], "s", ms=8, mfc="none", mec="k", mew=1.2)
                if q not in labeled:
                    labeled.add(q)
                    ax.annotate(str(n.get("name") or "").split(" ")[0][:10], (q[1], q[0]), fontsize=7, xytext=(4, 4),
                                textcoords="offset points")
            elif "_jct_split_" in str(n.get("id")):
                ax.plot(q[1], q[0], "x", ms=8, color=REG_C[r], mew=2)
            else:
                ax.plot(q[1], q[0], "o", ms=3.5, color=REG_C[r])
    ax.set_xlim(box[2], box[3])
    ax.set_ylim(box[0], box[1])
    ax.set_aspect(1 / math.cos(math.radians(lat0)))
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=7, loc="lower right")


def fig_cases(before, after):
    fig, axs = plt.subplots(len(CASES), 2, figsize=(12, 5.6 * len(CASES)))
    for k, (center, r_m, title) in enumerate(CASES):
        draw(axs[k][0], before, center, r_m, "前: " + title)
        draw(axs[k][1], after, center, r_m, "後: 区切りをそろえてまとめた")
    fig.suptitle("前と後（赤い帯 = 地域をまたいで二重の線分・□ = 変電所の点・× = #60 が区切った点・地域ごとに少しずらして描く）",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    fig.savefig(os.path.join(HERE, "fig_cases.png"), dpi=100)


if __name__ == "__main__":
    b, a = load()
    fig_dup(b, a)
    fig_cases(b, a)
    print("ok")
