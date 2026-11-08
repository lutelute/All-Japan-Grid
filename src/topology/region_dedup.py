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
"""
from __future__ import annotations

import collections
import os
from typing import Dict, List, Tuple

REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
REGION_DEDUP_DEFAULT = (os.environ.get("AJG_REGION_DEDUP", "1") == "1")


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
