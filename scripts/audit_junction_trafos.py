#!/usr/bin/env python3
"""潮流計算の網で、変電所でない点(分岐点・鉄塔)に張られた変圧器を数えて一覧にする(2026-11-07)。

正典(docs/data/built/all.json)の分岐点は電圧ごとに別の点(id の末尾が電圧)なので、交差する線や併架の線が
同じ座標を通っても、正典の中ではつながっていない。ところが潮流計算の網(src/powerflow/full_from_built.py の
build_island_net)は、
  (a) 同じ座標に電圧の違う点があると、変電所かどうかを見ずに変圧器でつなぐ(「同じ座標の変圧器」)
  (b) 線の電圧と違う電圧の点に線がつながっていると、介入#43a がそこに変圧器を足す(「#43a」)
ので、変電所の無い所に変圧器ができる。この一覧はその変圧器(両側のバスが変電所でない = bus type 'n')を全部出し、
docs/data/route_audit/mixed_kv_review.json(航空写真で確かめた 26 か所)に、正典での形と潮流計算での形を書き足す。

    PYTHONPATH=. python3 scripts/audit_junction_trafos.py          # 一覧を書き、写真の判定に形を書き足す

出力: docs/data/route_audit/junction_trafos.json
"""
from __future__ import annotations

import collections
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BUILT = os.path.join(ROOT, "docs", "data", "built", "all.json")
OUT = os.path.join(ROOT, "docs", "data", "route_audit", "junction_trafos.json")
REVIEW = os.path.join(ROOT, "docs", "data", "route_audit", "mixed_kv_review.json")


# 作った枝(OSM の線そのものでなく、公表・回収・接続の規則などで足した枝)の印。all.json の枝のキー
MADE_KEYS = ("disclosure", "recovery", "conn_class", "same_site", "tie", "dc_tie", "stub", "routed_line", "hygiene")
MADE_NAMES = ("leadin", "namebind")   # ビルダーが足す引込み・名前での結び付けの枝(名前がそのまま入る)


def k5(la, lo):
    return (round(float(la), 5), round(float(lo), 5))


def dist_m(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = p2 - p1, math.radians(d - b)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def canon_form(nodes_here):
    """正典での形: 'one' = 1 つの点に電圧の違う枝 / 'split' = 電圧ごとに別の点(同じ座標)。"""
    return "one" if len(nodes_here) == 1 else "split"


def main():
    import src.powerflow.full_from_built as F

    db = json.load(open(BUILT, encoding="utf-8"))
    at = collections.defaultdict(list)
    for n in db["nodes"]:
        at[k5(n["lat"], n["lon"])].append(n)
    inc = collections.defaultdict(list)
    for e in db["edges"]:
        inc[k5(*e["a"])].append(e)
        inc[k5(*e["b"])].append(e)
    subs = [(n["lat"], n["lon"], n.get("name") or "") for n in db["nodes"] if n.get("sub") == 1]

    def nearest_sub(la, lo):
        best = min(subs, key=lambda s: (s[0] - la) ** 2 + ((s[1] - lo) * math.cos(math.radians(la))) ** 2)
        return round(dist_m(la, lo, best[0], best[1])), best[2]

    rows = []
    totals = {}
    for island in ("hokkaido", "east", "west", "okinawa"):
        nodes = json.loads(json.dumps(db["nodes"]))   # build_island_net は region を書き換えるので写しを渡す
        net, _bus_of, _st = F.build_island_net(island, nodes, db["edges"], F.ISLAND_FREQ[island], {})
        bt = net.bus["type"]
        n_all = len(net.trafo)
        n_nn = 0
        for ti, r in net.trafo.iterrows():
            h, lo_b = int(r.hv_bus), int(r.lv_bus)
            if not (bt[h] == "n" and bt[lo_b] == "n"):
                continue
            n_nn += 1
            g = net.bus.at[h, "geo"]
            lon, lat = (json.loads(g) if isinstance(g, str) else g)["coordinates"]
            c = k5(lat, lon)
            here = at.get(c, [])
            es = inc.get(c, [])
            sm, sname = nearest_sub(lat, lon)
            rows.append({
                "island": island, "lat": c[0], "lon": c[1],
                "hv_kv": float(r.vn_hv_kv), "lv_kv": float(r.vn_lv_kv),
                "how": "43a" if "#43a" in str(r["name"]) else "colocated",
                "canon": canon_form(here) if here else "none",
                "canon_nodes": [[x["id"], float(x.get("kv") or 0), x.get("deg")] for x in here],
                "regions": sorted({x.get("region") for x in here if x.get("region")}),
                "edges": sorted([[float(e.get("kv") or 0), e.get("name") or ""] for e in es]),
                "made_edge": sorted({k for e in es for k in MADE_KEYS if e.get(k)}
                                    | {e["name"] for e in es if e.get("name") in MADE_NAMES}),
                "nearest_sub_m": sm, "nearest_sub": sname,
            })
        totals[island] = {"trafos": n_all, "junction_trafos": n_nn}
        print(f"{island}: 変圧器 {n_all}・両側とも変電所でない {n_nn}")

    rows.sort(key=lambda r: (r["island"], r["lat"], r["lon"]))
    reviewed = set()
    if os.path.exists(REVIEW):
        reviewed = {k5(it["lat"], it["lon"]) for it in json.load(open(REVIEW, encoding="utf-8"))["items"]}
    for r in rows:
        if (r["lat"], r["lon"]) in reviewed:
            r["class"] = "photo"          # 航空写真で確かめた 26 か所
        elif any(n[1] == 0 for n in r["canon_nodes"]):
            r["class"] = "unknown_kv"     # 同じ座標に電圧不明の点(隣の地域の取り出しの写しが多い)。仮置きの 66 kV と変圧器でつながる
        elif r["made_edge"]:
            r["class"] = "made_edge"      # 作った枝(公表・回収・引込み・名前での結び付け)が関わる
        elif r["nearest_sub_m"] <= 300:
            r["class"] = "near_sub"       # 変電所から 300 m 以内
        else:
            r["class"] = "other"
    by_how = collections.Counter(r["how"] for r in rows)
    by_class = collections.Counter(r["class"] for r in rows)
    doc = {
        "what": "潮流計算の網(build_island_net の既定)で、両側のバスが変電所でない(分岐点・鉄塔)変圧器の一覧",
        "how": {"colocated": "同じ座標にある電圧の違う点を変圧器でつないだ(full_from_built の『同じ座標の変圧器』)",
                "43a": "線の電圧と違う電圧の点に線がつながっていて、介入#43a が変圧器を足した"},
        "canon": {"split": "正典では電圧ごとに別の点(同じ座標)", "one": "正典で 1 つの点に電圧の違う枝がつながる"},
        "class": {"photo": "航空写真で確かめた 26 か所(mixed_kv_review.json)",
                  "unknown_kv": "同じ座標に電圧不明の点がある(隣の地域の取り出しの写しが多い)。潮流計算は仮に 66 kV と置いて変圧器でつなぐ",
                  "made_edge": "作った枝(公表・回収・引込み・名前での結び付け)が関わる",
                  "near_sub": "変電所から 300 m 以内", "other": "そのほか"},
        "source": "docs/data/built/all.json", "totals": totals, "by_how": dict(by_how), "by_class": dict(by_class),
        "items": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print(f"合計 {len(rows)}(同じ座標 {by_how.get('colocated', 0)}・#43a {by_how.get('43a', 0)}) {dict(by_class)} → {OUT}")

    # 写真で確かめた 26 か所に、正典での形と潮流計算での形を書き足す
    if os.path.exists(REVIEW):
        rv = json.load(open(REVIEW, encoding="utf-8"))
        idx = {(r["lat"], r["lon"]): r for r in rows}
        for it in rv["items"]:
            c = k5(it["lat"], it["lon"])
            here = at.get(c, [])
            it["canon"] = canon_form(here) if here else "none"
            it["canon_nodes"] = [[x["id"], float(x.get("kv") or 0), x.get("deg")] for x in here]
            r = idx.get(c)
            it["powerflow"] = r["how"] if r else "none"
        rv["what"] = ("正典で変電所でない点の座標に電圧の違う枝が集まる所(作った枝の関わらない 26 か所)を、"
                      "国土地理院の航空写真(全国最新写真、ズーム 17)で確かめた判定")
        rv["fields"] = {
            "canon": "正典での形(split=電圧ごとに別の点で、正典の中ではつながっていない / one=1 つの点に電圧の違う枝)",
            "powerflow": "潮流計算の網でのつながり(colocated=同じ座標の変圧器 / 43a=介入#43a の変圧器 / none=変圧器なし)",
        }
        with open(REVIEW, "w", encoding="utf-8") as fh:
            json.dump(rv, fh, ensure_ascii=False, indent=1)
        c1 = collections.Counter((it["judgement"], it["canon"], it["powerflow"]) for it in rv["items"])
        for k, v in sorted(c1.items()):
            print("  ", k, v)


if __name__ == "__main__":
    main()
