#!/usr/bin/env python3
"""介入#60(案)の前と後: 正典(all.json)・地域をまたぐ写し・全規模の潮流(summary.json)・N-1 を比べる。

前 = #59 の PR(#167)の先頭 cd7c90d2、後 = 作業ツリーで regenerate_all を回したもの。
地域をまたぐ写しの延長は、地域ごとの正典(docs/data/built/<地域>.json、#60 で変わらない)から #59・#58 だけを
当てたものと、#60 も当てたものを作って数える(全国の正典の枝には地域が書かれていないため)。
    PYTHONPATH=. python3 docs/reports/canon_region_dedup_splits_2026-11-08/compare.py [基準の ref(既定 cd7c90d2)]
→ docs/reports/canon_region_dedup_splits_2026-11-08/compare.json
"""
import collections
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
REF = sys.argv[1] if len(sys.argv) > 1 else "cd7c90d2"
k5 = lambda la, lo: (round(la, 5), round(lo, 5))


def git_json(path):
    out = subprocess.run(["git", "show", f"{REF}:{path}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def cur_json(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return json.load(fh)


def _m(p, q):
    c = math.cos(math.radians((p[0] + q[0]) / 2))
    return math.hypot((p[0] - q[0]) * 111320.0, (p[1] - q[1]) * 111320.0 * c)


def _pts(e):
    return [k5(*q) for q in (e.get("path") or [e["a"], e["b"]])]


def overlap_pairs(edges):
    """内側の頂点の 8 割以上が別の 1 本の枝の頂点と座標まで同じ枝の組(形が同じものは除く。#167 の報告の数え方)。"""
    E = [e for e in edges if not e.get("tie") and e.get("path") and len(e["path"]) >= 3]
    vt = collections.defaultdict(set)
    for i, e in enumerate(E):
        for q in e["path"][1:-1]:
            vt[k5(*q)].add(i)
    out = set()
    for i, e in enumerate(E):
        inner = [k5(*q) for q in e["path"][1:-1]]
        if len(inner) < 2:
            continue
        c = collections.Counter(j for q in inner for j in vt[q] if j != i)
        for j, n in c.items():
            if n >= 0.8 * len(inner):
                out.add(tuple(sorted((i, j))))
    rows = collections.Counter()
    for i, j in out:
        a, b = E[i], E[j]
        same = sorted(map(tuple, map(lambda q: k5(*q), a["path"]))) == sorted(map(tuple, map(lambda q: k5(*q), b["path"])))
        if not same and a.get("main") and b.get("main"):
            rows["main_not_same_shape"] += 1
        rows["all"] += 1
    return dict(rows)


def canon_stats(d):
    nodes, edges = d["nodes"], d["edges"]
    at = collections.defaultdict(list)
    for n in nodes:
        at[k5(n["lat"], n["lon"])].append(n)
    seg = collections.Counter()
    km = 0.0
    for e in edges:
        if e.get("tie"):
            continue
        p = _pts(e)
        for u, w in zip(p, p[1:]):
            if u != w:
                seg[(u, w) if u <= w else (w, u)] += 1
                km += _m(u, w)
    shared_km = sum(_m(*s) * (c - 1) for s, c in seg.items() if c > 1) / 1000
    ends = collections.Counter()
    for e in edges:
        ends[k5(*e["a"])] += 1
        ends[k5(*e["b"])] += 1
    return {"nodes": len(nodes), "edges": len(edges), "main_nodes": sum(1 for n in nodes if n.get("main")),
            "subs": sum(1 for n in nodes if n.get("sub") == 1),
            "split_junctions": sum(1 for n in nodes if "_jct_split_" in str(n.get("id"))),
            "coords_multi_region": sum(1 for v in at.values() if len({n.get("region") for n in v}) > 1),
            "dead_end_junction_coords": sum(1 for c, v in at.items() if ends[c] == 1 and not any(n.get("sub") for n in v)),
            "orphan_node_coords": sum(1 for c in at if ends[c] == 0),
            "km_path": round(km / 1000, 1), "km_segments_on_two_or_more_edges": round(shared_km, 1),
            "overlap_pairs": overlap_pairs(edges)}


def cross_region():
    """地域ごとの正典から、#60 を当てない場合と当てる場合の全国をまとめる前の写しを作り、地域をまたぐ写しを数える。"""
    from src.topology.region_dedup import (REGIONS, align_copy_ends, align_copy_splits, dedup_region_copies,
                                           heal_copy_splits)
    col = {}
    for r in REGIONS:
        p = os.path.join(ROOT, "docs", "data", "built", r + ".json")
        if os.path.exists(p):
            b = json.load(open(p, encoding="utf-8"))
            col[r] = {"nodes": b["nodes"], "edges": b["edges"]}

    def dup(c):
        seg = collections.defaultdict(set)
        for r, v in c.items():
            for e in v["edges"]:
                if e.get("tie"):
                    continue
                p = _pts(e)
                for u, w in zip(p, p[1:]):
                    if u != w:
                        seg[(u, w) if u <= w else (w, u)].add(r)
        by = collections.Counter()
        for s, rs in seg.items():
            if len(rs) > 1:
                by["|".join(sorted(rs))] += _m(*s) * (len(rs) - 1) / 1000
        return {"km": round(sum(by.values()), 1), "by_regions": {k: round(v, 1) for k, v in by.most_common()}}
    b, _ = dedup_region_copies(align_copy_ends(col)[0])
    s1, ls = align_copy_splits(col)
    s2, le = align_copy_ends(s1)
    s3, l8 = dedup_region_copies(s2)
    a, lh = heal_copy_splits(s3)
    return {"before": dup(b), "after": dup(a)}


KEYS = ("n_bus", "n_line", "n_trafo", "n_implicit_stepdown", "n_junction_cuts", "n_components", "n_synthetic_slack",
        "total_load_mw", "ac_converged", "ac_vm_min", "ac_vm_max", "ac_max_loading_pct", "ac_total_loss_mw", "dc_converged")


def main():
    out = {"ref": REF}
    b, a = git_json("docs/data/built/all.json"), cur_json("docs/data/built/all.json")
    out["canon"] = {"before": canon_stats(b), "after": canon_stats(a)}
    out["cross_region_copies_km"] = cross_region()
    pb, pa = git_json("docs/data/powerflow_full/summary.json")["islands"], cur_json("docs/data/powerflow_full/summary.json")["islands"]
    out["powerflow"] = {isl: {k: [pb[isl].get(k), pa[isl].get(k)] for k in KEYS} for isl in pb}
    nb, na = git_json("docs/data/n1_canon/summary.json")["islands"], cur_json("docs/data/n1_canon/summary.json")["islands"]
    out["n1"] = {x.get("island"): {k: [x.get(k), y.get(k)] for k in x if not isinstance(x.get(k), (list, dict))}
                 for x, y in zip(nb, na)}
    with open(os.path.join(HERE, "compare.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    for k, v in out["canon"]["before"].items():
        print(f"正典 {k}: {v} → {out['canon']['after'][k]}")
    print("地域をまたぐ写し", out["cross_region_copies_km"]["before"]["km"], "→", out["cross_region_copies_km"]["after"]["km"], "km")
    for isl, row in out["powerflow"].items():
        print(isl, {k: v for k, v in row.items() if v[0] != v[1]})
    for isl, row in out["n1"].items():
        print("N-1", isl, {k: v for k, v in row.items() if v[0] != v[1]})


if __name__ == "__main__":
    main()
