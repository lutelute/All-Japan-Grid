"""分岐点の変圧器の一覧(docs/data/route_audit/junction_trafos.json)と、写真の判定に書き足した形の確かめ(2026-11-07)。

一覧は潮流計算の網(pandapower)を作って書くので重い。ここでは書いたものが正典と食い違っていないかだけを、正典の
all.json から軽く確かめる(正典が変わって一覧が古くなったら落ちる)。
"""
import collections
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "docs", "data")


def _load(p):
    with open(os.path.join(D, p), encoding="utf-8") as fh:
        return json.load(fh)


def _nodes_at():
    b = _load("built/all.json")
    at = collections.defaultdict(list)
    for n in b["nodes"]:
        at[(round(n["lat"], 5), round(n["lon"], 5))].append(n)
    return at


def test_counts_add_up():
    d = _load("route_audit/junction_trafos.json")
    items = d["items"]
    assert sum(v["junction_trafos"] for v in d["totals"].values()) == len(items)
    assert sum(d["by_how"].values()) == len(items)
    assert sum(d["by_class"].values()) == len(items)
    assert {r["how"] for r in items} <= {"colocated", "43a"}


def test_items_are_not_substations_in_canon():
    """一覧の座標には、正典の変電所の点(sub=1)が無い(あれば変電所の変圧器で、一覧に入れてはいけない)。"""
    at = _nodes_at()
    d = _load("route_audit/junction_trafos.json")
    for r in d["items"]:
        here = at.get((r["lat"], r["lon"]), [])
        assert here, r
        assert not any(n.get("sub") == 1 for n in here), r


def test_review_forms_match_canon():
    """写真の判定に書いた正典での形(split=電圧ごとに別の点 / one=1 つの点)が、今の正典と合う。"""
    at = _nodes_at()
    rv = _load("route_audit/mixed_kv_review.json")
    assert len(rv["items"]) == 26
    for it in rv["items"]:
        here = at.get((round(it["lat"], 5), round(it["lon"], 5)), [])
        assert it["canon"] == ("one" if len(here) == 1 else "split"), it["no"]
        assert it["powerflow"] in ("colocated", "43a", "none")
    c = collections.Counter((it["judgement"], it["powerflow"]) for it in rv["items"])
    # 誤接続 17 か所: 同じ座標の変圧器 12・#43a 4・変圧器なし 1(#24、2 つの点が別の同期系統)
    assert c[("misconnect", "colocated")] == 12
    assert c[("misconnect", "43a")] == 4
    assert c[("misconnect", "none")] == 1
