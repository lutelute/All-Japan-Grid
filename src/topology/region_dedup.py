"""介入#58(案): 地域をまたぐ写しを 1 つにまとめる(全国の正典をまとめる前に、2026-11-07)。

正典は地域ごとに OSM を取り出して作り(data/<地域>_lines.geojson)、全国でつなげる(build_editor_data.build_national)。
地域の外接矩形は重なっているので、境の線は 2 つの地域の取り出しに丸ごと入り、全国の正典に 2 回入る
(頂点まで同じ形の枝が地域をまたいで 2,513 組)。電圧の推し量りは地域ごとなので、写しの電圧が食い違うこともあり
(片方だけ電圧不明 51 組・分かる電圧が違う 49 組)、潮流計算の網ではそれが変電所の無い所の変圧器になっていた。

写しの見つけ方(根拠): 枝の両端の点と形(頂点の並び。小数 5 桁に丸め、向きをそろえたもの)が同じで、2 つ以上の
  地域から出ている(形が同じでも端の結び方が違うものは写しとしない。path_sig の説明)。
残す写し: 線の中ほどの頂点の座標の領土(都道府県→エリア、src.powerflow.region_attribution.area_of_coord。正典の
  #5 と同じ)の地域。その地域が写しの中に無ければ REGIONS の順の最初。
電圧: 残す写しの枝が電圧不明(kv=0)で、ほかの地域の写しの電圧が 1 つに決まるなら、その電圧を採る(帳簿に書く)。
  分かる電圧どうしが違うときは、残す写し(領土の地域の推し量り)のまま。
併架(同じ形で電圧の違う回線): 地域ごとにひとまとまりで扱い、残す地域の回線をそのまま残す。
点: 写しを落として枝が 1 本も付かなくなった点は消す。ただし変電所の点は、残す地域に同じ座標の点があるときだけ消す。
  まだ枝の付く点は残す(電圧の違う別の線の点。潮流計算の B 案が同じ座標・同じ電圧の点を 1 つのバスにする)。

形が同じでない写し(地域で区切りの点が違い、枝の分け方が違う)は見つけない(控えめな側)。
無効化: 環境変数 AJG_REGION_DEDUP=0 か build_editor_data.py --no-region-dedup。

介入#59(案、2026-11-07): 形は同じで端を結ぶ点だけが違う写し(64 組)は、#58 の前に align_copy_ends で端の点を
1 つにまとめる(点を寄せる)。同じ way の同じ端が、地域 X の取り出しでは点 p、地域 Y では点 q に結ばれていた
(数 m〜500 m)。p と q は同じ場所の 2 つの表し方なので、p を q に寄せると、写しの両端の点がそろい、#58 が
ふつうの写しとしてまとめる。寄せ先は、ほかの線が付く点 > 変電所の点 > その座標の領土の地域の点。
無効化: 環境変数 AJG_REGION_DEDUP_ENDS=0 か build_editor_data.py --no-region-dedup-ends。
"""
from __future__ import annotations

import collections
import math
import os
from typing import Dict, List, Tuple

REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
REGION_DEDUP_DEFAULT = (os.environ.get("AJG_REGION_DEDUP", "1") == "1")
END_ALIGN_DEFAULT = (os.environ.get("AJG_REGION_DEDUP_ENDS", "1") == "1")
# 寄せる 2 点の間の上限。64 組の実測の最大は 507 m(線の端を変電所の点に結ぶ距離)。これを超える組は寄せない
END_GAP_MAX_M = 600.0


def _k5(la, lo):
    return (round(float(la), 5), round(float(lo), 5))


def path_sig(e) -> tuple:
    """枝の署名: 両端の点(a・b)と形(頂点の並び)を小数 5 桁に丸め、向きをそろえたもの。

    形だけでは足りない(2026-11-07 の試算): 同じ形でも、端をどの点に結ぶかは地域の取り出しで違うことがある
    (阿波変電所~鉢変電所線 500 kV: 中国の写しは線の端の分岐点、四国の写しは阿南周波数変換所の点)。
    境の網はそれぞれの結び方を混ぜてつながっているので、片方を落とすと潮流計算の網(座標がぴったり同じ点だけを
    つなぐ)が切れ、徳島の 469 バス・4,025 MW が西の主系統から外れた。端まで同じものだけを写しとする。"""
    p = tuple(_k5(q[0], q[1]) for q in (e.get("path") or [e["a"], e["b"]]))
    a, b = _k5(*e["a"]), _k5(*e["b"])
    return min((a, b, p), (b, a, p[::-1]))


def dedup_region_copies(collected: Dict[str, dict], owner_of=None) -> Tuple[Dict[str, dict], dict]:
    """地域ごとの正典 {地域: {"nodes": [...], "edges": [...]}} から地域をまたぐ写しを落とした写しを返す。

    owner_of: (lat, lon) → 地域。既定は area_of_coord(領土)。検査で差し替える。
    Returns: (落としたあとの collected, 帳簿)
    """
    if owner_of is None:
        from src.powerflow.region_attribution import area_of_coord as owner_of
    order = {r: k for k, r in enumerate(REGIONS)}
    groups: Dict[tuple, Dict[str, List[int]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    for reg, v in collected.items():
        for i, e in enumerate(v["edges"]):
            if e.get("tie"):
                continue
            groups[path_sig(e)][reg].append(i)
    drop: Dict[str, set] = collections.defaultdict(set)
    kv_set: Dict[Tuple[str, int], float] = {}
    rows = []
    pair = collections.Counter()
    kinds = collections.Counter()
    for sig, by in groups.items():
        if len(by) < 2:
            continue
        shape = sig[2]
        mid = shape[len(shape) // 2]
        own = owner_of(mid[0], mid[1])
        regs = sorted(by, key=lambda r: (order.get(r, 99), r))
        keep = own if own in by else regs[0]
        kv_of = {r: sorted({float(collected[r]["edges"][i].get("kv") or 0) for i in ix}) for r, ix in by.items()}
        keep_kv = kv_of[keep]
        others_known = sorted({k for r in by if r != keep for k in kv_of[r] if k > 0})
        kind = ("same_kv" if all(kv_of[r] == keep_kv for r in by) else
                "kv0_filled" if keep_kv == [0.0] and len(others_known) == 1 else
                "keep_kv0" if keep_kv == [0.0] else
                "kv_differs")
        kinds[kind] += 1
        pair[tuple(sorted(by))] += 1
        if kind == "kv0_filled":
            for i in by[keep]:
                kv_set[(keep, i)] = others_known[0]
        for r, ix in by.items():
            if r != keep:
                drop[r].update(ix)
        if kind != "same_kv":
            e0 = collected[keep]["edges"][by[keep][0]]
            rows.append({"kind": kind, "keep": keep, "owner": own, "regions": regs,
                         "kv": {r: kv_of[r] for r in regs}, "name": e0.get("name") or "",
                         "mid": [mid[0], mid[1]]})
    out = {}
    n_drop_nodes = 0
    coords_of = {r: {_k5(m["lat"], m["lon"]) for m in v["nodes"]} for r, v in collected.items()}
    for reg, v in collected.items():
        edges = []
        for i, e in enumerate(v["edges"]):
            if i in drop.get(reg, ()):
                continue
            if (reg, i) in kv_set:
                e = dict(e, kv=kv_set[(reg, i)], kv_from_copy=1)
            edges.append(e)
        touched = set()
        for i in drop.get(reg, ()):
            e = v["edges"][i]
            touched.add(_k5(*e["a"]))
            touched.add(_k5(*e["b"]))
        live = set()
        for e in edges:
            live.add(_k5(*e["a"]))
            live.add(_k5(*e["b"]))
        nodes = []
        for n in v["nodes"]:
            c = _k5(n["lat"], n["lon"])
            if c in touched and c not in live:
                if n.get("sub"):
                    # 変電所の点は、残す地域に同じ座標の点があるときだけ消す
                    if not any(c in coords_of[r2] for r2 in collected if r2 != reg):
                        nodes.append(n)
                        continue
                n_drop_nodes += 1
                continue
            nodes.append(n)
        out[reg] = dict(v, nodes=nodes, edges=edges)
    ledger = {
        "what": "地域をまたぐ写し(頂点まで同じ形の枝が 2 つ以上の地域から出る)を 1 つにまとめた帳簿(介入#58 案)",
        "n_groups": sum(kinds.values()), "kinds": dict(kinds),
        "n_edges_dropped": sum(len(s) for s in drop.values()), "n_nodes_dropped": n_drop_nodes,
        "n_kv_filled": len(kv_set),
        "pairs": {"|".join(k): v for k, v in sorted(pair.items(), key=lambda kv: -kv[1])},
        "kv_rows": rows,
    }
    return out, ledger


def _m(p, q) -> float:
    """2 点の間の距離(m、平面近似)。"""
    c = math.cos(math.radians((p[0] + q[0]) / 2))
    return math.hypot((p[0] - q[0]) * 111320.0, (p[1] - q[1]) * 111320.0 * c)


def _shape(e) -> tuple:
    """枝の形(頂点の並び、小数 5 桁、向きをそろえたもの)。両端の点は含めない。"""
    p = tuple(_k5(q[0], q[1]) for q in (e.get("path") or [e["a"], e["b"]]))
    return min(p, p[::-1])


def _ends_by_side(e, shape) -> Tuple[tuple, tuple]:
    """枝の両端の点を、形の最初の頂点の側・最後の頂点の側の順に返す(端と頂点の距離の和が小さい組み合わせ)。"""
    a, b = _k5(*e["a"]), _k5(*e["b"])
    s0, s1 = shape[0], shape[-1]
    if _m(a, s0) + _m(b, s1) <= _m(a, s1) + _m(b, s0):
        return a, b
    return b, a


def align_copy_ends(collected: Dict[str, dict], owner_of=None) -> Tuple[Dict[str, dict], dict]:
    """介入#59(案): 形が同じで端を結ぶ点だけが違う地域の写しの、端の点を 1 つに寄せる(#58 の前に呼ぶ)。

    根拠: 頂点の並びが同じ枝は同じ OSM の way。その同じ端を、地域ごとの取り出しが別の点に結んでいた
    (変電所が片方の取り出しにしか無い・同じ変電所の点が地域ごとに数十 m ずれて 2 つある・片方は線の端の分岐点)。
    同じ端の 2 つの表し方なので、点を寄せる(その座標に付くすべての地域の枝の端を寄せ先の座標に書き換える)。
    寄せ先(各組・各端): ほかの線が付く点 > 変電所の点 > 付く線の数 > 座標の領土の地域の写しの点 > 座標の順。
    点: 寄せた先に同じ電圧の点があれば消し、無ければ寄せ先の座標へ動かす(変電所の点は、寄せ先に同じ電圧の
      変電所の点が無ければ残して動かす)。写しだけが付く行き止まりの点は動かさずに消す(寄せ先に変電所の点が
      無いときの変電所の点だけは動かして残す)。寄せて両端が同じ点になった枝は消す(帳簿に書く)。
    Returns: (書き換えた collected, 帳簿)
    """
    if owner_of is None:
        from src.powerflow.region_attribution import area_of_coord as owner_of
    order = {r: k for k, r in enumerate(REGIONS)}
    groups: Dict[tuple, Dict[str, List[int]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    ends_at = collections.Counter()
    for reg, v in collected.items():
        for i, e in enumerate(v["edges"]):
            ends_at[_k5(*e["a"])] += 1
            ends_at[_k5(*e["b"])] += 1
            if e.get("tie"):
                continue
            groups[_shape(e)][reg].append(i)
    sub_at = set()
    regs_at = collections.defaultdict(set)
    names_at = collections.defaultdict(set)
    for reg, v in collected.items():
        for n in v["nodes"]:
            c = _k5(n["lat"], n["lon"])
            regs_at[c].add(reg)
            if n.get("sub"):
                sub_at.add(c)
                names_at[c].add(n.get("name") or "")
    votes = collections.Counter()
    pairs = []          # (寄せる点, 寄せ先, 組の線名, この組の写しの端の数)
    far = []
    for shape, by in sorted(groups.items()):
        if len(by) < 2 or len(shape) < 2:
            continue
        sides = [collections.defaultdict(list), collections.defaultdict(list)]   # 点 → [(地域, 枝)]
        for reg, ix in by.items():
            for i in ix:
                e = collected[reg]["edges"][i]
                for k, c in enumerate(_ends_by_side(e, shape)):
                    sides[k][c].append((reg, i))
        if all(len(sd) == 1 for sd in sides):
            continue                                     # 両端が同じ = #58 がそのまま扱う
        mid = shape[len(shape) // 2]
        own = owner_of(mid[0], mid[1])
        names = sorted({str(collected[r]["edges"][i].get("name") or "") for r, ix in by.items() for i in ix})
        plan = []
        for sd in sides:
            if len(sd) < 2:
                continue
            def key(c):
                other = ends_at[c] - len(sd[c])          # この組の写し以外に、その点に付く枝の端の数
                regs = {r for r, _ in sd[c]}
                return (other > 0, c in sub_at, other, own in regs, -min(order.get(r, 99) for r in regs), c)
            ref = max(sd, key=key)
            for c in sd:
                if c != ref:
                    plan.append((c, ref, len(sd[c])))
        if any(_m(c, ref) > END_GAP_MAX_M for c, ref, _ in plan):
            far.append({"names": names, "gaps_m": [round(_m(c, ref), 1) for c, ref, _ in plan]})
            continue
        for c, ref, nown in plan:
            votes[ref] += 1
            pairs.append((c, ref, names, nown))
    # 寄せる点のつながり(連鎖)ごとに寄せ先を 1 つに決める
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for c, ref, _, _ in pairs:
        ra, rb = find(c), find(ref)
        if ra != rb:
            parent[ra] = rb
    comps = collections.defaultdict(set)
    for x in list(parent):
        comps[find(x)].add(x)
    alias = {}
    for comp in comps.values():
        rep = max(comp, key=lambda c: (votes[c], c in sub_at, ends_at[c], c))
        for c in comp:
            if c != rep:
                alias[c] = rep
    gown = collections.Counter()
    lines_of = collections.defaultdict(set)
    for c, ref, names, nown in pairs:
        gown[c] += nown
        lines_of[c].update(names)
        lines_of[ref].update(names)
    rows = []
    for c, to in sorted(alias.items()):
        other = ends_at[c] - gown[c]
        kind = ("dangling" if other == 0 else
                "same_substation" if (c in sub_at and to in sub_at and
                                      {_site(x) for x in names_at[c]} & {_site(x) for x in names_at[to]}) else
                "substation_pair" if (c in sub_at and to in sub_at) else
                "junction_to_substation" if (to in sub_at) else "other")
        rows.append({"from": list(c), "to": list(to), "gap_m": round(_m(c, to), 1), "kind": kind,
                     "from_regions": sorted(regs_at[c]), "to_regions": sorted(regs_at[to]),
                     "from_subs": sorted(names_at[c]), "to_subs": sorted(names_at[to]),
                     "other_ends_at_from": other, "lines": sorted(lines_of[c])})
    # 枝の端を書き換え、点を寄せる
    out = {}
    n_repoint = n_collapsed = n_moved = n_merged = 0
    collapsed = []
    at_target = collections.defaultdict(list)          # 寄せ先 → [(kv, sub)](今ある点)
    for reg, v in collected.items():
        for n in v["nodes"]:
            c = _k5(n["lat"], n["lon"])
            if c not in alias:
                at_target[c].append((float(n.get("kv") or 0), bool(n.get("sub"))))
    for reg in collected:
        v = collected[reg]
        edges = []
        for e in v["edges"]:
            a, b = _k5(*e["a"]), _k5(*e["b"])
            na, nb = alias.get(a, a), alias.get(b, b)
            if (na, nb) != (a, b):
                n_repoint += 1
                if na == nb:
                    n_collapsed += 1
                    collapsed.append({"region": reg, "name": e.get("name") or "", "kv": e.get("kv"), "at": list(na)})
                    continue
                e = dict(e, a=[na[0], na[1]], b=[nb[0], nb[1]])
            edges.append(e)
        nodes = []
        for n in v["nodes"]:
            c = _k5(n["lat"], n["lon"])
            if c in alias:
                t = alias[c]
                kv, sub = float(n.get("kv") or 0), bool(n.get("sub"))
                here = at_target[t]
                if any(k == kv and (s or not sub) for k, s in here):
                    n_merged += 1                        # 寄せ先に同じ電圧の点(変電所なら変電所の点)がある
                    continue
                if ends_at[c] - gown[c] == 0 and not (sub and not any(s for _, s in here)):
                    n_merged += 1                        # 写しだけが付く行き止まりの点: 寄せ先が表す(変電所の点は寄せ先に変電所が無ければ残す)
                    continue
                n = dict(n, lat=t[0], lon=t[1])
                here.append((kv, sub))
                n_moved += 1
            nodes.append(n)
        out[reg] = dict(v, nodes=nodes, edges=edges)
    ledger = {
        "what": "形が同じで端を結ぶ点だけが違う地域の写しの、端の点を 1 つに寄せた帳簿(介入#59 案、#58 の前)",
        "n_points_aliased": len(alias), "n_edge_ends_repointed": n_repoint, "n_edges_collapsed": n_collapsed,
        "n_nodes_moved": n_moved, "n_nodes_merged": n_merged, "gap_max_m": END_GAP_MAX_M,
        "kinds": dict(collections.Counter(r["kind"] for r in rows)),
        "rows": rows, "collapsed": collapsed, "too_far": far,
    }
    return out, ledger


def _site(name: str) -> str:
    """変電所の点の名前から、電圧・(untyped)・_N を除いた名前(同じ変電所かの目安)。"""
    import re
    s = re.sub(r"\s*\(untyped\)$|\s*\d+(\.\d+)?kV$", "", name or "").strip()
    return re.sub(r"_\d+$", "", s)
