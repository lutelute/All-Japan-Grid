#!/usr/bin/env python3
"""正典 all.json(A) と再生成 all.json(B) を比べる。

ノード: id で突き合わせ(kv/region/name/lat/lon/sub)。id が片側にしか無いものは
座標(k5)+kv でも突き合わせる(採番ずれの検出)。
枝: 端点(k5, 無向)+kv+name の多重集合で段階的に突き合わせる。
  1) 端点+kv+name 一致 → par/長さ/経路の差を見る
  2) 残りを 端点+name で → kv の差
  3) 残りを 端点のみ で → name の差
  4) 残り = 片側だけの枝
結果を JSON(--out)に書き、要約を表示する。
"""
from __future__ import annotations

import argparse
import collections
import json
import math


def k5(p):
    return (round(float(p[0]), 5), round(float(p[1]), 5))


def hav(p, q):
    R = 6371.0088
    la1, lo1, la2, lo2 = map(math.radians, (p[0], p[1], q[0], q[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def length_km(e):
    pts = e.get("path") or [e["a"], e["b"]]
    return sum(hav(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def ekey_ends(e):
    a, b = k5(e["a"]), k5(e["b"])
    return (a, b) if a <= b else (b, a)


FLAG_KEYS = ["disclosure", "recovery", "conn_class", "same_site", "dc_tie", "stub",
             "routed_line", "tie", "hygiene", "kv_corrected", "par_src", "satellite",
             "sat_conn"]


def flags(e):
    out = {}
    for k in e:
        if k in ("a", "b", "main", "kv", "par", "path", "name"):
            continue
        v = e[k]
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)[:80]
        out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--out", default="")
    ap.add_argument("--show", type=int, default=8)
    args = ap.parse_args()
    A = json.load(open(args.a, encoding="utf-8"))
    B = json.load(open(args.b, encoding="utf-8"))
    res = {"A": args.a, "B": args.b}

    # ---------------- nodes ----------------
    na = {n["id"]: n for n in A["nodes"]}
    nb = {n["id"]: n for n in B["nodes"]}
    res["n_nodes"] = [len(A["nodes"]), len(B["nodes"])]
    res["dup_node_ids"] = [len(A["nodes"]) - len(na), len(B["nodes"]) - len(nb)]
    common = na.keys() & nb.keys()
    only_a = sorted(na.keys() - nb.keys())
    only_b = sorted(nb.keys() - na.keys())
    diffs = collections.defaultdict(list)
    for i in sorted(common):
        x, y = na[i], nb[i]
        for f in ("kv", "region", "name", "sub"):
            if (x.get(f) or 0 if f in ("kv", "sub") else x.get(f)) != (y.get(f) or 0 if f in ("kv", "sub") else y.get(f)):
                diffs[f].append({"id": i, "A": x.get(f), "B": y.get(f),
                                 "A_flags": {k: x[k] for k in x if k in ("freq_fix", "mixed_pref", "region_src", "hygiene", "kv_corrected", "supplement")},
                                 "B_flags": {k: y[k] for k in y if k in ("freq_fix", "mixed_pref", "region_src", "hygiene", "kv_corrected", "supplement")}})
        if k5((x["lat"], x["lon"])) != k5((y["lat"], y["lon"])):
            diffs["coord"].append({"id": i, "A": [x["lat"], x["lon"]], "B": [y["lat"], y["lon"]]})
        for f in ("sub_props",):
            if json.dumps(x.get(f), sort_keys=True) != json.dumps(y.get(f), sort_keys=True):
                diffs[f].append({"id": i})
        fa = {k for k in x if k not in ("id", "lat", "lon", "kv", "main", "deg", "sub", "name", "region", "src", "sub_props")}
        fb = {k for k in y if k not in ("id", "lat", "lon", "kv", "main", "deg", "sub", "name", "region", "src", "sub_props")}
        if fa != fb:
            diffs["node_flagset"].append({"id": i, "A": sorted(fa), "B": sorted(fb)})
    # id-only-one-side: try coordinate+kv match
    ca = collections.defaultdict(list)
    for i in only_a:
        n = na[i]
        ca[(k5((n["lat"], n["lon"])), float(n.get("kv") or 0))].append(i)
    renum = []
    only_b_left = []
    for i in only_b:
        n = nb[i]
        key = (k5((n["lat"], n["lon"])), float(n.get("kv") or 0))
        if ca.get(key):
            renum.append((ca[key].pop(), i))
        else:
            only_b_left.append(i)
    only_a_left = [i for lst in ca.values() for i in lst]
    res["nodes"] = {
        "common_ids": len(common),
        "only_A_ids": len(only_a), "only_B_ids": len(only_b),
        "renumbered_same_coord_kv": len(renum),
        "only_A_after_coord": len(only_a_left), "only_B_after_coord": len(only_b_left),
        "diff_counts": {k: len(v) for k, v in diffs.items()},
    }
    res["node_only_A"] = [{**{k: na[i][k] for k in ("id", "lat", "lon", "kv", "region", "name", "sub")},
                           "flags": {k: na[i][k] for k in na[i] if k in ("freq_fix", "mixed_pref", "region_src", "hygiene", "kv_corrected", "supplement", "suppl_src")}}
                          for i in sorted(only_a_left)]
    res["node_only_B"] = [{**{k: nb[i][k] for k in ("id", "lat", "lon", "kv", "region", "name", "sub")},
                           "flags": {k: nb[i][k] for k in nb[i] if k in ("freq_fix", "mixed_pref", "region_src", "hygiene", "kv_corrected", "supplement", "suppl_src")}}
                          for i in sorted(only_b_left)]
    res["node_renum"] = renum
    res["node_diffs"] = diffs

    # ---------------- edges ----------------
    EA, EB = A["edges"], B["edges"]
    res["n_edges"] = [len(EA), len(EB)]
    remA = set(range(len(EA)))
    remB = set(range(len(EB)))
    pairs = []

    def match(keyf, stage):
        ga = collections.defaultdict(list)
        gb = collections.defaultdict(list)
        for i in remA:
            ga[keyf(EA[i])].append(i)
        for j in remB:
            gb[keyf(EB[j])].append(j)
        n = 0
        for k, la in ga.items():
            lb = gb.get(k)
            if not lb:
                continue
            # pair by closest (par, length)
            la = sorted(la, key=lambda i: (EA[i]["par"], round(length_km(EA[i]), 3), i))
            lb = sorted(lb, key=lambda j: (EB[j]["par"], round(length_km(EB[j]), 3), j))
            for i, j in zip(la, lb):
                pairs.append((i, j, stage))
                remA.discard(i)
                remB.discard(j)
                n += 1
        return n

    s1 = match(lambda e: (ekey_ends(e), float(e["kv"]), e.get("name") or ""), "ends+kv+name")
    s2 = match(lambda e: (ekey_ends(e), e.get("name") or ""), "ends+name")
    s3 = match(lambda e: (ekey_ends(e), float(e["kv"])), "ends+kv")
    s4 = match(lambda e: ekey_ends(e), "ends")
    res["edge_match_stages"] = {"ends+kv+name": s1, "ends+name": s2, "ends+kv": s3, "ends": s4}

    ediff = collections.defaultdict(list)
    for i, j, stage in pairs:
        x, y = EA[i], EB[j]
        rec = {"iA": i, "iB": j, "name": x.get("name"), "nameB": y.get("name"), "kvA": x["kv"], "kvB": y["kv"],
               "parA": x["par"], "parB": y["par"], "lenA": round(length_km(x), 4), "lenB": round(length_km(y), 4),
               "flagsA": flags(x), "flagsB": flags(y)}
        if float(x["kv"]) != float(y["kv"]):
            ediff["kv"].append(rec)
        if (x.get("name") or "") != (y.get("name") or ""):
            ediff["name"].append(rec)
        if int(x["par"]) != int(y["par"]):
            ediff["par"].append(rec)
        if abs(rec["lenA"] - rec["lenB"]) > 0.001:
            ediff["length"].append(rec)
        pa = [k5(p) for p in (x.get("path") or [x["a"], x["b"]])]
        pb = [k5(p) for p in (y.get("path") or [y["a"], y["b"]])]
        if pa != pb and pa != pb[::-1]:
            ediff["path"].append(rec)
        if set(flags(x)) != set(flags(y)):
            ediff["flagset"].append(rec)
    res["edges"] = {
        "matched": len(pairs), "only_A": len(remA), "only_B": len(remB),
        "diff_counts": {k: len(v) for k, v in ediff.items()},
    }
    res["edge_only_A"] = [{"iA": i, "a": EA[i]["a"], "b": EA[i]["b"], "kv": EA[i]["kv"], "par": EA[i]["par"],
                           "name": EA[i].get("name"), "len": round(length_km(EA[i]), 4), "flags": flags(EA[i])}
                          for i in sorted(remA)]
    res["edge_only_B"] = [{"iB": j, "a": EB[j]["a"], "b": EB[j]["b"], "kv": EB[j]["kv"], "par": EB[j]["par"],
                           "name": EB[j].get("name"), "len": round(length_km(EB[j]), 4), "flags": flags(EB[j])}
                          for j in sorted(remB)]
    res["edge_diffs"] = ediff
    res["edge_pairs_iA_to_iB"] = {i: j for i, j, _ in pairs}

    # summary print
    print(f"A={args.a}\nB={args.b}")
    print(f"nodes A/B = {res['n_nodes']}  dup ids={res['dup_node_ids']}")
    print("  ", res["nodes"])
    print(f"edges A/B = {res['n_edges']}")
    print("  stages", res["edge_match_stages"])
    print("  ", res["edges"])
    # flag breakdown of only-A / only-B edges
    def fb(lst):
        c = collections.Counter()
        for r in lst:
            f = r["flags"]
            tag = ",".join(sorted(k for k in f if k in FLAG_KEYS or k in ("par_prev",))) or "(none)"
            c[tag] += 1
        return c.most_common(15)
    print("  only_A edge flag-tags:", fb(res["edge_only_A"]))
    print("  only_B edge flag-tags:", fb(res["edge_only_B"]))
    print("  only_A node region/flags:", collections.Counter((r["region"], ",".join(sorted(r["flags"]))) for r in res["node_only_A"]).most_common(10))
    print("  only_B node region/flags:", collections.Counter((r["region"], ",".join(sorted(r["flags"]))) for r in res["node_only_B"]).most_common(10))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
        print("written", args.out)


if __name__ == "__main__":
    main()
