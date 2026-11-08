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

介入#59(案、2026-11-07): 形は同じで端を結ぶ点だけが違う写し(67 組)は、#58 の前に align_copy_ends で端の点を
1 つにまとめる(点を寄せる)。同じ way の同じ端が、地域 X の取り出しでは点 p、地域 Y では点 q に結ばれていた
(数 m〜500 m)。p と q は同じ場所の 2 つの表し方なので、p を q に寄せると、写しの両端の点がそろい、#58 が
ふつうの写しとしてまとめる。寄せ先は、変電所の点 > ほかの線が付く点 > その座標の領土の地域の点。
無効化: 環境変数 AJG_REGION_DEDUP_ENDS=0 か build_editor_data.py --no-region-dedup-ends。

介入#60(案、2026-11-08): 区切りの違う写し(同じ way を地域ごとに違う点で区切ったので、形が同じにならない写し)は、
#59 の前に align_copy_splits で区切りをそろえ、#58 のあとに heal_copy_splits で要らなくなった区切りを戻す。
地域の取り出しは外接矩形に掛かる way を丸ごと拾うので、その先の way が取り出しに無い地域では線が途中で止まり、
分岐や変電所が取り出しに無い地域では線が区切られずに通り抜ける。どこかの地域で区切られている点(写しの線分で
終わる枝の形の端)と、写しが分かれる点で、すべての地域の写しを区切ると、区切りの間の枝は地域をまたいで形が同じに
なり、#59 が端をそろえ、#58 が 1 つにまとめる。#58 のあとに、区切りで作った点に同じ枝の 2 つの切れ端しか
付かなくなったら、つなぎ直す(区切る前の枝に戻る)。
無効化: 環境変数 AJG_REGION_DEDUP_SPLITS=0 か build_editor_data.py --no-region-dedup-splits。
"""
from __future__ import annotations

import collections
import json
import math
import os
from typing import Dict, List, Tuple

REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
REGION_DEDUP_DEFAULT = (os.environ.get("AJG_REGION_DEDUP", "1") == "1")
END_ALIGN_DEFAULT = (os.environ.get("AJG_REGION_DEDUP_ENDS", "1") == "1")
SPLIT_ALIGN_DEFAULT = (os.environ.get("AJG_REGION_DEDUP_SPLITS", "1") == "1")
# 寄せる 2 点の間の上限。67 組の実測の最大は 507 m(線の端を変電所の点に結ぶ距離)。これを超える組は寄せない
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


def align_copy_ends(collected: Dict[str, dict], owner_of=None, island_of=None) -> Tuple[Dict[str, dict], dict]:
    """介入#59(案): 形が同じで端を結ぶ点だけが違う地域の写しの、端の点を 1 つに寄せる(#58 の前に呼ぶ)。

    根拠: 頂点の並びが同じ枝は同じ OSM の way。その同じ端を、地域ごとの取り出しが別の点に結んでいた
    (変電所が片方の取り出しにしか無い・同じ変電所の点が地域ごとに数十 m ずれて 2 つある・片方は線の端の分岐点)。
    同じ端の 2 つの表し方なので、点を寄せる(その座標に付くすべての地域の枝の端を寄せ先の座標に書き換える)。
    寄せ先(各組・各端): 変電所の点 > ほかの線が付く点 > 付く線の数 > 座標の領土の地域の写しの点 > 座標の順。
      変電所の点を先にする(2026-11-08): 寄せても枝はすべて寄せ先に付け替わるのでつながりは変わらないが、行き止まりの
      変電所の点(写しだけが付く)を、ほかの線が付く別の地域の分岐点に寄せると、変電所の点が消えた(#60 の試算で
      那須湯本・豊原・中郷区坂本・美波町の 4 か所。#59 だけの 49 か所には、変電所の点を分岐点に寄せたものは無い)。
    点: 寄せた先に同じ電圧の点があれば消し、無ければ寄せ先の座標へ動かす(変電所の点は、寄せ先に同じ電圧の
      変電所の点が無ければ残して動かす)。写しだけが付く行き止まりの点は動かさずに消す(寄せ先に変電所の点が
      無いときの変電所の点だけは動かして残す)。寄せて両端が同じ点になった枝は消す(帳簿に書く)。
    周波数の境: 消すのは、寄せ先に「潮流計算で同じ島(同期系統)に入る」点があるときだけ。島の違う点しか無ければ
      動かして残す(富士市変電所: 東京の点を中部の点にまとめると、東京の線の先が東の島から消えた。2026-11-07 の試算)。
    island_of: (lat, lon, 地域) → 島。既定は潮流計算と同じ領土の再属性(#5・#38)のあとの島。検査で差し替える。
    Returns: (書き換えた collected, 帳簿)
    """
    if owner_of is None:
        from src.powerflow.region_attribution import area_of_coord as owner_of
    if island_of is None:
        island_of = _island_of
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
                return (c in sub_at, other > 0, other, own in regs, -min(order.get(r, 99) for r in regs), c)
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
    targets = set(alias.values())
    at_target = collections.defaultdict(list)          # 寄せ先 → [(島, kv, sub)](今ある点)
    for reg, v in collected.items():
        for n in v["nodes"]:
            c = _k5(n["lat"], n["lon"])
            if c in targets:
                at_target[c].append((island_of(c[0], c[1], reg), float(n.get("kv") or 0), bool(n.get("sub"))))
    n_kept_island = 0
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
                isl = island_of(t[0], t[1], reg)
                here = [(k, s) for i2, k, s in at_target[t] if i2 == isl]   # 寄せ先の点のうち、同じ島に入るもの
                if any(k == kv and (s or not sub) for k, s in here):
                    n_merged += 1                        # 寄せ先に同じ電圧の点(変電所なら変電所の点)がある
                    continue
                if here and ends_at[c] - gown[c] == 0 and not (sub and not any(s for _, s in here)):
                    n_merged += 1                        # 写しだけが付く行き止まりの点: 寄せ先が表す(変電所の点は寄せ先に変電所が無ければ残す)
                    continue
                if not here and at_target[t]:
                    n_kept_island += 1                   # 寄せ先には島の違う点しか無い → 動かして残す
                n = dict(n, lat=t[0], lon=t[1])
                at_target[t].append((isl, kv, sub))
                n_moved += 1
            nodes.append(n)
        out[reg] = dict(v, nodes=nodes, edges=edges)
    ledger = {
        "what": "形が同じで端を結ぶ点だけが違う地域の写しの、端の点を 1 つに寄せた帳簿(介入#59 案、#58 の前)",
        "n_points_aliased": len(alias), "n_edge_ends_repointed": n_repoint, "n_edges_collapsed": n_collapsed,
        "n_nodes_moved": n_moved, "n_nodes_merged": n_merged, "n_nodes_kept_other_island": n_kept_island,
        "gap_max_m": END_GAP_MAX_M,
        "kinds": dict(collections.Counter(r["kind"] for r in rows)),
        "rows": rows, "collapsed": collapsed, "too_far": far,
    }
    return out, ledger


LEDGER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "docs", "data", "fragments", "region_dedup_ledger.json")


def load_point_aliases(node_keys, path: str = LEDGER_PATH) -> Dict[tuple, tuple]:
    """#59 の帳簿から「寄せた点 → 寄せ先」を読む。帳簿の座標を最寄りの点に吸着する後段(apply_disclosure_v2)が使う。

    寄せた点は正典から消えているので、吸着すると近くの別の変電所に付くことがあった(扇町五丁目変電所の同一敷地タイが
    約 250 m 離れた多古変電所に付いた。2026-11-07 の試算)。帳簿が古くても誤らないよう、寄せた点が今の正典に無く、
    寄せ先が今の正典にあるものだけを返す。node_keys: 今の正典の点の座標(小数 5 桁)の集まり。"""
    try:
        with open(path, encoding="utf-8") as fh:
            rows = (json.load(fh).get("ends") or {}).get("rows") or []
    except (OSError, ValueError):
        return {}
    out = {}
    for r in rows:
        a, b = _k5(*r["from"]), _k5(*r["to"])
        if a not in node_keys and b in node_keys:
            out[a] = b
    return out


ISLANDS = {"hokkaido": "hokkaido", "tohoku": "east", "tokyo": "east", "chubu": "west", "hokuriku": "west",
           "kansai": "west", "chugoku": "west", "shikoku": "west", "kyushu": "west", "okinawa": "okinawa"}


def _island_of(lat: float, lon: float, region: str) -> str:
    """点が潮流計算で入る島(src.powerflow.full_from_built.ISLAND_OF と同じ分け方)。潮流計算の網と同じく、領土で
    地域を再属性してから(#5。周波数を跨ぐ移動は、県の周波数が一意のときだけ = #38)島を決める。"""
    from src.powerflow.region_attribution import reattribute_node_regions
    n = {"lat": lat, "lon": lon, "region": region}
    reattribute_node_regions([n], freq_fix=True)
    return ISLANDS.get(n["region"], n["region"])


def _site(name: str) -> str:
    """変電所の点の名前から、電圧・(untyped)・_N を除いた名前(同じ変電所かの目安)。"""
    import re
    s = re.sub(r"\s*\(untyped\)$|\s*\d+(\.\d+)?kV$", "", name or "").strip()
    return re.sub(r"_\d+$", "", s)


def _pts(e) -> list:
    return [_k5(q[0], q[1]) for q in (e.get("path") or [e["a"], e["b"]])]


def _seg(u, w) -> tuple:
    return (u, w) if u <= w else (w, u)


def align_copy_splits(collected: Dict[str, dict], island_of=None) -> Tuple[Dict[str, dict], dict]:
    """介入#60(案): 区切りの違う地域の写しを、区切りをそろえて形が同じ写しにする(#59・#58 の前に呼ぶ)。

    根拠: 地域をまたいで同じ線分(隣り合う 2 つの頂点。小数 5 桁で同じ)を持つ枝は、同じ OSM の way の同じ径間。
    写しの線分のうち、ある地域の枝の形がそこで終わる頂点(その地域ではそこに変電所・分岐・way の端がある)と、
    写しが分かれる頂点(片側の線分だけをほかの地域と共有する)で、その頂点を途中に持つ枝を区切る。
    区切りの点: 区切った地域に、枝の電圧の分岐点を作る(id は <地域>_jct_split_…)。
    区切らない頂点:
      - その頂点を通る枝・そこにある点の、分かる電圧が 2 つ以上(電圧の違う併架。同じ座標に電圧の違う点ができると
        潮流計算の網が変電所の無い所の変圧器を作る)
      - 区切る地域と、区切りの理由になった地域とで、潮流計算の島が違う(周波数の境。#59 の富士市と同じ。
        区切ると、島の違う写しが #58 で落ち、島の中の線が切れる)
      - 区切る地域に、もうそこを通る枝のものでない点がある(区切るとその点につながってしまう)
    island_of: (lat, lon, 地域) → 島。既定は #59 と同じ。検査で差し替える。
    Returns: (区切った collected, 帳簿)
    """
    if island_of is None:
        island_of = _island_of
    seg_regs = collections.defaultdict(set)
    kv_at = collections.defaultdict(set)              # 頂点 → そこを通る枝・そこにある点の分かる電圧(すべての地域)
    for reg, v in collected.items():
        for e in v["edges"]:
            if e.get("tie") or not e.get("a") or not e.get("b"):
                continue
            p = _pts(e)
            k = float(e.get("kv") or 0)
            if k > 0:
                for q in p:
                    kv_at[q].add(k)
            for u, w in zip(p, p[1:]):
                if u != w:
                    seg_regs[_seg(u, w)].add(reg)
    shared = {s: rs for s, rs in seg_regs.items() if len(rs) >= 2}
    anchor = collections.defaultdict(set)             # 頂点 → {(地域, 端の線分)}: 枝の形が写しの線分で終わる所
    for reg, v in collected.items():
        for e in v["edges"]:
            if e.get("tie") or not e.get("a") or not e.get("b"):
                continue
            p = _pts(e)
            if len(p) < 2:
                continue
            for v0, v1 in ((p[0], p[1]), (p[-1], p[-2])):
                if _seg(v0, v1) in shared:
                    anchor[v0].add((reg, _seg(v0, v1)))
    node_at = set()                                   # (地域, 座標)
    for reg, v in collected.items():
        for n in v["nodes"]:
            c = _k5(n["lat"], n["lon"])
            node_at.add((reg, c))
            if float(n.get("kv") or 0) > 0:
                kv_at[c].add(float(n["kv"]))
    cand = collections.defaultdict(set)               # 頂点 → 理由
    by_of = collections.defaultdict(set)              # (地域, 頂点) → 理由になった地域
    for reg, v in collected.items():
        for e in v["edges"]:
            if e.get("tie") or not e.get("a") or not e.get("b"):
                continue
            p = _pts(e)
            for k in range(1, len(p) - 1):
                q = p[k]
                s0, s1 = _seg(p[k - 1], q), _seg(q, p[k + 1])
                if s0 not in shared and s1 not in shared:
                    continue
                by = {r2 for r2, s in anchor.get(q, ()) if r2 != reg and s in (s0, s1)}
                why = "end"
                if not by:
                    by = (shared.get(s0, set()) - {reg}) ^ (shared.get(s1, set()) - {reg})
                    why = "diverge"
                if by:
                    cand[q].add(why)
                    by_of[(reg, q)] |= by
    kv_skip = {q for q in cand if len(kv_at[q]) >= 2}
    isl_cache = {}

    def isl(q, r):
        if (q, r) not in isl_cache:
            isl_cache[(q, r)] = island_of(q[0], q[1], r)
        return isl_cache[(q, r)]
    out = {}
    n_split = n_pieces = 0
    island_skip, own_skip = set(), set()
    rows = []
    for reg, v in collected.items():
        edges, nodes = [], list(v["nodes"])
        made = set()
        for i, e in enumerate(v["edges"]):
            if e.get("tie") or not e.get("path") or not e.get("a") or not e.get("b"):
                edges.append(e)
                continue
            p = _pts(e)
            cuts = []
            for k in range(1, len(p) - 1):
                q = p[k]
                if (reg, q) not in by_of or q in kv_skip:
                    continue
                if q not in made and (reg, q) in node_at:
                    own_skip.add((reg, q))
                    continue
                if any(isl(q, r2) != isl(q, reg) for r2 in by_of[(reg, q)]):
                    island_skip.add((reg, q))
                    continue
                cuts.append(k)
            if not cuts:
                edges.append(e)
                continue
            n_split += 1
            a, b = _k5(*e["a"]), _k5(*e["b"])
            if _m(a, p[0]) + _m(b, p[-1]) > _m(a, p[-1]) + _m(b, p[0]):
                a, b = b, a                           # a を形の最初の頂点の側にそろえる
            ks = [0] + cuts + [len(p) - 1]
            m = len(ks) - 1
            for j in range(m):
                lo, hi = ks[j], ks[j + 1]
                pa = a if j == 0 else p[lo]
                pb = b if j == m - 1 else p[hi]
                edges.append(dict(e, a=[pa[0], pa[1]], b=[pb[0], pb[1]],
                                  path=[list(x) for x in e["path"][lo:hi + 1]], _split=(reg, i, j, m)))
                n_pieces += 1
            kv = float(e.get("kv") or 0)
            for k in cuts:
                q = p[k]
                if q in made:
                    continue
                made.add(q)
                nodes.append({"id": f"{reg}_jct_split_{q[0]:.5f}:{q[1]:.5f}:{kv:g}", "lat": q[0], "lon": q[1],
                              "kv": kv, "main": 1 if e.get("main") else 0, "deg": 2, "sub": 0,
                              "name": f"{reg} junction {q[0]:.4f}:{q[1]:.4f}:{kv:g}", "_split_node": 1})
                rows.append({"region": reg, "at": [q[0], q[1]], "why": sorted(cand[q]), "kv": kv,
                             "by": sorted(by_of[(reg, q)]), "name": e.get("name") or ""})
        out[reg] = dict(v, nodes=nodes, edges=edges)
    ledger = {
        "what": "区切りの違う地域の写しの区切りをそろえた帳簿(介入#60 案、#59・#58 の前。heal は #58 のあと)",
        "n_shared_segments": len(shared), "n_candidate_points": len(cand),
        "n_points_skipped_kv": len(kv_skip), "n_skipped_island": len(island_skip), "n_skipped_own_node": len(own_skip),
        "n_edges_split": n_split, "n_pieces": n_pieces, "n_nodes_made": len(rows),
        "why": dict(collections.Counter(w for ws in cand.values() for w in ws)),
        "skipped_island": sorted([r, list(q)] for r, q in island_skip),
        "rows": rows,
    }
    return out, ledger


def heal_copy_splits(collected: Dict[str, dict]) -> Tuple[Dict[str, dict], dict]:
    """介入#60(案): #58 のあと、区切りで作った点のうち要らなくなったものを戻す。

    同じ枝の隣り合う 2 つの切れ端が残り、その継ぎ目の座標に付く枝の端がその 2 本だけで、区切りで作った点のほかに
    点が無い(変電所の点などを #59 が寄せていない)なら、2 本をつなぎ直す(区切る前の枝に戻る)。どの枝も付かなく
    なった区切りの点は消す。帳簿に使う印(_split 等)はここで外す。
    """
    ends = collections.Counter()
    others_at = set()
    for v in collected.values():
        for e in v["edges"]:
            ends[_k5(*e["a"])] += 1
            ends[_k5(*e["b"])] += 1
        for n in v["nodes"]:
            if not n.get("_split_node"):
                others_at.add(_k5(n["lat"], n["lon"]))
    n_heal = n_left = 0
    out = {}
    for reg, v in collected.items():
        keep, groups = [], collections.defaultdict(list)
        for e in v["edges"]:
            (groups[e["_split"][:2]] if e.get("_split") else keep).append(e)
        for ps in groups.values():
            ps.sort(key=lambda e: e["_split"][2])
            run = [ps[0]]
            for nx in ps[1:]:
                cur = run[-1]
                q = _k5(*cur["b"])
                if (nx["_split"][2] == cur.get("_hi", cur["_split"][2]) + 1 and q == _k5(*nx["a"]) and ends[q] == 2
                        and q not in others_at and cur.get("kv") == nx.get("kv") and cur.get("par") == nx.get("par")):
                    run[-1] = dict(cur, b=nx["b"], path=cur["path"] + nx["path"][1:], _hi=nx["_split"][2])
                    n_heal += 1
                else:
                    run.append(nx)
            for e in run:
                if not (e["_split"][2] == 0 and e.get("_hi", 0) == e["_split"][3] - 1):
                    n_left += 1
                keep.append({k: x for k, x in e.items() if k not in ("_split", "_hi")})
        live = set()
        for e in keep:
            live.add(_k5(*e["a"]))
            live.add(_k5(*e["b"]))
        nodes = []
        for n in v["nodes"]:
            if n.get("_split_node"):
                if _k5(n["lat"], n["lon"]) not in live:
                    continue
                n = {k: x for k, x in n.items() if k != "_split_node"}
            nodes.append(n)
        out[reg] = dict(v, nodes=nodes, edges=keep)
    n_nodes_left = sum(1 for v in out.values() for n in v["nodes"] if "_jct_split_" in str(n.get("id")))
    return out, {"n_joints_healed": n_heal, "n_pieces_left": n_left, "n_split_nodes_left": n_nodes_left}
