#!/usr/bin/env python3
"""介入#58(案)の前と後: 正典(all.json)・全規模の潮流(summary.json)・N-1(n1_canon/summary.json)を比べる。

前 = main(git の origin/main)に入っているもの、後 = 作業ツリーで regenerate_all を回したもの。
    PYTHONPATH=. python3 docs/reports/canon_region_dedup_2026-11-07/compare.py [基準の ref(既定 origin/main)]
→ docs/reports/canon_region_dedup_2026-11-07/compare.json
"""
import collections
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REF = sys.argv[1] if len(sys.argv) > 1 else "origin/main"


def git_json(path):
    out = subprocess.run(["git", "show", f"{REF}:{path}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def cur_json(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return json.load(fh)


def canon_stats(d):
    nodes, edges = d["nodes"], d["edges"]
    k5 = lambda la, lo: (round(la, 5), round(lo, 5))
    at = collections.defaultdict(list)
    for n in nodes:
        at[k5(n["lat"], n["lon"])].append(n)
    multi_reg = sum(1 for v in at.values() if len({n.get("region") for n in v}) > 1)
    def sig(e):
        p = tuple(k5(*q) for q in (e.get("path") or [e["a"], e["b"]]))
        return min(p, p[::-1])
    sigs = collections.Counter(sig(e) for e in edges if not e.get("tie"))
    return {"nodes": len(nodes), "edges": len(edges), "main_nodes": sum(1 for n in nodes if n.get("main")),
            "subs": sum(1 for n in nodes if n.get("sub") == 1),
            "coords_multi_region": multi_reg, "edges_same_shape_extra": sum(c - 1 for c in sigs.values() if c > 1),
            "km_lines": round(sum(_len(e) for e in edges if not e.get("tie")), 1)}


def _len(e):
    import math
    p = e.get("path") or [e["a"], e["b"]]
    s = 0.0
    for (a, b), (c, d) in zip(p, p[1:]):
        s += math.hypot(c - a, (d - b) * math.cos(math.radians(a))) * 111.195
    return s


KEYS = ("n_bus", "n_line", "n_trafo", "n_implicit_stepdown", "n_junction_cuts", "n_components", "n_synthetic_slack",
        "total_load_mw", "ac_converged", "ac_vm_min", "ac_vm_max", "ac_max_loading_pct", "ac_total_loss_mw", "dc_converged")


def main():
    out = {"ref": REF}
    b, a = git_json("docs/data/built/all.json"), cur_json("docs/data/built/all.json")
    out["canon"] = {"before": canon_stats(b), "after": canon_stats(a)}
    pb, pa = git_json("docs/data/powerflow_full/summary.json")["islands"], cur_json("docs/data/powerflow_full/summary.json")["islands"]
    out["powerflow"] = {isl: {k: [pb[isl].get(k), pa[isl].get(k)] for k in KEYS} for isl in pb}
    nb, na = git_json("docs/data/n1_canon/summary.json")["islands"], cur_json("docs/data/n1_canon/summary.json")["islands"]
    out["n1"] = {x.get("island"): {k: [x.get(k), y.get(k)] for k in x if not isinstance(x.get(k), (list, dict))}
                 for x, y in zip(nb, na)}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compare.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    for k, v in out["canon"]["before"].items():
        print(f"正典 {k}: {v:,} → {out['canon']['after'][k]:,}")
    for isl, row in out["powerflow"].items():
        print(isl, {k: v for k, v in row.items() if v[0] != v[1]})
    for isl, row in out["n1"].items():
        print("N-1", isl, {k: v for k, v in row.items() if v[0] != v[1]})


if __name__ == "__main__":
    main()
