#!/usr/bin/env python3
"""つながりの点検の「正典: 変電所でない接続点で枝が 1 本(行き止まり)」が 2,268 → 2,764 に増えた内訳。

    python3 docs/reports/osm_routes_refresh_2026-11-09/deadends.py [--before-rev d0d7ca58] [--before-canon-rev c14edaf7]

前の点検 = --before-rev の docs/data/route_audit/audit.json(正典 c6c6a910 = #58 の前で作ったもの)
前の正典 = --before-canon-rev の docs/data/built/all.json(c6c6a910 と同じもの)
後の点検・正典 = 作業ツリー
点検は点を座標(小数 5 桁)でまとめ、その座標に付く枝を数える(scripts/audit_route_connectivity.py)。
新しく行き止まりになった点ごとに、前の正典でその座標に付いていた枝を見て分ける。
出力: deadends.json(この場所)
"""
import argparse
import collections
import json
import math
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def git_json(rev, path):
    return json.loads(subprocess.check_output(["git", "-C", ROOT, "show", f"{rev}:{path}"]))


def work_json(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return json.load(fh)


key = lambda ll: (round(ll[0], 5), round(ll[1], 5))


def incidence(built):
    inc = collections.defaultdict(list)
    for e in built["edges"]:
        inc[key(e["a"])].append(e)
        inc[key(e["b"])].append(e)
    return inc


def segs(e):
    p = [key(x) for x in (e.get("path") or [e["a"], e["b"]])]
    return {tuple(sorted(s)) for s in zip(p, p[1:])}


def length_km(e):
    p = e.get("path") or [e["a"], e["b"]]
    return sum(math.hypot((x2 - x1) * 111.32 * math.cos(math.radians(y1)), (y2 - y1) * 110.57)
               for (y1, x1), (y2, x2) in zip(p, p[1:]))


def far(e, c):
    return key(e["b"]) if key(e["a"]) == c else key(e["a"])


def dist_m(a, b):
    return math.hypot((b[1] - a[1]) * 111320 * math.cos(math.radians(a[0])), (b[0] - a[0]) * 110570)


def dead_ends(audit):
    k = audit["classes"].index("canon_dead_end")
    return {key((r[1] / 1e5, r[2] / 1e5)): r for r in audit["rows"] if r[0] == k}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before-rev", default="d0d7ca58")
    ap.add_argument("--before-canon-rev", default="c14edaf7")
    args = ap.parse_args()
    a0 = git_json(args.before_rev, "docs/data/route_audit/audit.json")
    a1 = work_json("docs/data/route_audit/audit.json")
    b0 = git_json(args.before_canon_rev, "docs/data/built/all.json")
    b1 = work_json("docs/data/built/all.json")
    assert a0["built_all_sha256"][:12] == "c6c6a9108212", a0["built_all_sha256"]
    inc0, inc1 = incidence(b0), incidence(b1)
    subs1 = {key((n["lat"], n["lon"])) for n in b1["nodes"] if n.get("sub")}
    d0, d1 = dead_ends(a0), dead_ends(a1)
    new = [c for c in d1 if c not in d0]
    gone = [c for c in d0 if c not in d1]
    kinds = collections.Counter()
    rows = collections.defaultdict(list)
    for c in sorted(new):
        eo = inc0.get(c, [])
        if not eo:
            t = "new_point"             # 前の正典にその座標の点が無い(#61 の帯の線・#60 の区切りなど)
        else:
            s = [segs(e) for e in eo]
            pairs = [(i, j) for i in range(len(eo)) for j in range(i + 1, len(eo))]
            if any(len(s[i] & s[j]) >= 0.5 * min(len(s[i]), len(s[j])) for i, j in pairs):
                t = "copies_overlapped"     # 前は同じ線分の写しが 2 本以上重なり、座標で見ると枝 2 本に見えた
            elif any(dist_m(far(eo[i], c), far(eo[j], c)) <= 100
                     and abs(length_km(eo[i]) - length_km(eo[j])) <= 0.3 * max(length_km(eo[i]), length_km(eo[j]))
                     for i, j in pairs):
                t = "copies_shifted"        # 写しだが頂点が少しずれている(先の端が 100 m 以内・長さが 3 割以内)
            else:
                en = inc1.get(c, [])
                if len(en) == 1 and length_km(en[0]) < 0.5 and far(en[0], c) in subs1:
                    t = "tail_from_substation"   # 変電所から出る 500 m 未満の尻尾(#60 の区切りの残り)
                else:
                    t = "other"
        kinds[t] += 1
        eo_names = sorted({e.get("name") or "" for e in eo})[:3]
        rows[t].append({"lat": c[0], "lon": c[1], "kv": d1[c][3], "names_before": eo_names,
                        "deg_before": len(eo)})
    out = {"before": {"audit_built_sha": a0["built_all_sha256"][:12], "dead_ends": len(d0)},
           "after": {"audit_built_sha": a1["built_all_sha256"][:12], "dead_ends": len(d1)},
           "new": len(new), "gone": len(gone), "new_by_kind": dict(kinds.most_common()),
           "examples": {t: v[:5] for t, v in rows.items()},
           "tails": rows.get("tail_from_substation", []) + rows.get("other", [])}
    with open(os.path.join(HERE, "deadends.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(json.dumps({k: out[k] for k in ("before", "after", "new", "gone", "new_by_kind")}, ensure_ascii=False))
    for r in out["tails"]:
        print(" tail/other", r)


if __name__ == "__main__":
    main()
