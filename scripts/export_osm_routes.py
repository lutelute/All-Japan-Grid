#!/usr/bin/env python3
"""系統図ビューアーの「路線」「鉄塔」「横断検索」の層を書き出す(2026-11-07)。

    PYTHONPATH=. python scripts/export_osm_routes.py [--raw <tw_*_t*.json のある場所>]

入力(読むだけ)
  - tw_*_t*.json                      OSM の送電線 way・鉄塔・route=power(Overpass の JSON と同じ形、git の外)。
                                      既定は nas03 の osm_jp_power/20261105_agj_transmission/json(osm_routes.default_raw_dir)
  - docs/data/built/all.json          正典(地域の割り当て・変電所の名前・枝と路線の対応)
  - docs/data/map/lines_all.geojson   地図に出している正典の線(枝と同じ順。枝を引く鍵を作る)
  - data/{region}_substations.geojson・data/{region}_plants.geojson  路線の端の敷地の名前(基底 OSM)
  - docs/data/plants_all.geojson      検索に入れる発電所

出力(docs/data/osm_routes/、上書き。出力は入力が同じなら毎回同じバイトになる。実行日は書かない)
  - meta.json              入力の SHA256・OSM の取得時刻・件数・規則の説明・ライセンス
  - routes_{region}.json   路線(属性+way の形。形は Google polyline・小数 5 桁)
  - towers_{region}.json   鉄塔(番号・名前・載っている路線・形や高さのタグ)
  - edge_routes.json       地図の正典の線(鍵)→ 路線
  - search.json            横断検索の一覧(路線・変電所・発電所・番号か名前のある鉄塔)

路線のまとめ方は src/topology/osm_routes.py。正典(docs/data/built)は変えない。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

import numpy as np
from shapely import points as shp_points
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.topology import osm_routes as R  # noqa: E402

REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
OUT = os.path.join(ROOT, "docs", "data", "osm_routes")
TOWER_TAGS = ("design", "structure", "height", "material", "operator", "line_attachment",
              "line_management", "colour", "start_date", "name:en", "note")
ROUTE_COLS = ["id(最小の way id)", "名前(0=無し)", "名前の無い way の本数", "kV", "長さ km", "bbox[w,s,e,n]",
              "鉄塔の数", "番号のある鉄塔の数", "つなぎ方[同じ名前,名前なしの続き,片方だけ名前]",
              "端[[種類,名前]](sub=変電所 plant=発電所 line=ほかの路線へ portal/terminal/transition none=何もない)",
              "OSM タグ(name・voltage 以外、多い順に 4 つまで)",
              "way[[way id, kV, 描き分け(''=架空 c=ケーブル u=地中 s=海底), polyline(小数5桁)]]",
              "回線数の推定 [回線数, 根拠(cables=導体数÷3 / cables_dc=直流の導体数÷2 / relations=route=power の数)] か 0(OSM に回線数がある・推定できない)",
              "一筆書きの路線か(1 なら way を端から順にたどれる。鉄塔の「n 基目」はこのときだけ数える)"]
ROUTE_TAG_KEYS = ("name", "ref", "voltage", "circuits", "cables", "wires", "frequency", "operator",
                  "operator:wikidata", "wikidata", "wikipedia", "location", "line", "start_date", "name:en")


def lat5(x):
    return int(round(x * 1e5))


def dump(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        fh.write("\n")


def load_sites():
    """路線の端の敷地(変電所・発電所の輪郭)。点しか無いものは小さな円で代える。"""
    geoms, names, kinds = [], [], []
    for reg in REGIONS:
        for kind, fname in (("sub", f"{reg}_substations.geojson"), ("sub", f"{reg}_substations_supplement.geojson"),
                            ("plant", f"{reg}_plants.geojson")):
            p = os.path.join(ROOT, "data", fname)
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
            for ft in d.get("features", []):
                try:
                    g = shape(ft["geometry"])
                except Exception:   # noqa: BLE001 壊れた形は飛ばす
                    continue
                if g.is_empty:
                    continue
                if g.geom_type == "Point":
                    g = g.buffer(0.0008 if kind == "sub" else 0.0015)   # 約 80 m / 150 m
                geoms.append(g.buffer(0.0004))                          # 輪郭の外 約 40 m まで敷地とみなす
                names.append((ft.get("properties") or {}).get("name") or "")
                kinds.append(kind)
    return geoms, names, kinds


class Sites:
    def __init__(self):
        self.geoms, self.names, self.kinds = load_sites()
        self.tree = STRtree(self.geoms)

    def at(self, lat, lon):
        """(kind, name) か None。変電所を発電所より先に見る。"""
        p = Point(lon, lat)
        hits = [i for i in self.tree.query(p) if self.geoms[i].contains(p)]
        if not hits:
            return None
        hits.sort(key=lambda i: (self.kinds[i] != "sub", self.geoms[i].area))
        i = hits[0]
        return self.kinds[i], self.names[i]


def region_lookup(built_nodes):
    """座標 → 地域。いちばん近い正典の点の地域。

    地域をまたぐ写し(同じ線が 2 つの地域の取り出しに入る)では、同じ座標に地域の違う点が並ぶ。2026-11-07 まで
    STRtree.nearest がそのどちらかを返していて、どちらになるかが OS で変わった(Mac と Linux で鉄塔の地域が
    数百基単位で食い違った)。同じ距離の候補を全部取り、鉄塔の座標の領土(都道府県→エリア、正典の #5 と同じ
    area_of_coord)の地域があればそれ、無ければ REGIONS の順の最初、で決める。"""
    from src.powerflow.region_attribution import area_of_coord
    pts = shp_points([[n["lon"], n["lat"]] for n in built_nodes])
    tree = STRtree(pts)
    regs = [n.get("region") or "" for n in built_nodes]
    order = {r: k for k, r in enumerate(REGIONS)}

    def f(lonlats):
        if not len(lonlats):
            return []
        q_idx, t_idx = tree.query_nearest(shp_points(lonlats), all_matches=True)
        cand = collections.defaultdict(set)
        for i, j in zip(np.atleast_1d(q_idx), np.atleast_1d(t_idx)):
            cand[int(i)].add(regs[int(j)])
        out = []
        for i, (lo, la) in enumerate(lonlats):
            rs = cand.get(i) or {""}
            if len(rs) == 1:
                out.append(next(iter(rs)))
                continue
            a = area_of_coord(la, lo)
            out.append(a if a in rs else min(rs, key=lambda r: (order.get(r, 99), r)))
        return out
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=None,
                    help="tw_*_t*.json のあるフォルダ(既定: 環境変数 AJG_OSM_RAW_TOWERS か nas03 の 20261105 の抽出)")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    args.raw = args.raw or R.default_raw_dir()
    if not R.raw_files(args.raw):
        sys.exit(R.missing_raw_message(args.raw))
    os.makedirs(args.out, exist_ok=True)

    nodes, ways, info = R.load_raw(args.raw)
    route_of, joins = R.assemble(ways)
    mem = R.members(route_of)
    nidx = R.node_index(ways)
    print(f"way {len(ways):,} → 路線 {len(mem):,}(OSM {info['osm_base_min']}〜{info['osm_base_max']})")

    with open(os.path.join(ROOT, "docs", "data", "built", "all.json"), encoding="utf-8") as fh:
        built = json.load(fh)
    region_of = region_lookup(built["nodes"])
    sites = Sites()

    towers = {i: n for i, n in nodes.items() if (n.get("tags") or {}).get("power") == "tower"}
    tower_routes = collections.defaultdict(set)
    for wid, w in ways.items():
        for nid in w["nodes"]:
            if nid in towers:
                tower_routes[nid].add(route_of[wid])

    # ── 補完(番号の推定・線の折れ点・回線数の推定)。推定は必ず推定と分かる形で書く ──
    rel_count = collections.Counter()
    for rel in (info.get("relations") or {}).values():
        for m in rel.get("members", []):
            if m.get("type") == "way" and m.get("ref") in ways:
                rel_count[m["ref"]] += 1
    num_of = lambda n: R.ref_number((towers[n].get("tags") or {}).get("ref")) if n in towers else None
    est_num, est_rid, est_conflict = {}, {}, set()
    ext, ext_conflict = {}, set()      # 端まで延ばした番号 {鉄塔: (番号, 路線, 元の鉄塔, 何基先)}
    route_linear = {}
    for rid in sorted(mem):
        seqs, linear = R.chains(mem[rid], ways)
        route_linear[rid] = linear
        for seq in seqs:
            for node, num in R.infer_numbers(seq, lambda n: n in towers, num_of).items():
                if (towers[node].get("tags") or {}).get("ref"):
                    continue
                if node in est_num and est_num[node] != num:
                    est_conflict.add(node)
                est_num.setdefault(node, num)
                est_rid.setdefault(node, rid)
            # 端まで延ばす(番号のある鉄塔が 2 基以上で、向きと間隔がそろう並びだけ。R.extend_numbers)
            for node, (num, src, k) in R.extend_numbers(seq, lambda n: n in towers, num_of).items():
                if (towers[node].get("tags") or {}).get("ref"):
                    continue
                if node in ext and ext[node][0] != num:
                    ext_conflict.add(node)
                ext.setdefault(node, (num, rid, src, k))
    for node in est_conflict:          # 路線によって違う番号になる鉄塔(併架など)は埋めない
        est_num.pop(node, None)
        est_rid.pop(node, None)
    for node in list(ext):
        # 路線によって違う番号になる鉄塔、前後の番号から埋めた推定とぶつかる鉄塔は延ばさない(あいだを埋めた方が根拠が強い)
        if node in ext_conflict or node in est_conflict or (node in est_num and est_num[node] != ext[node][0]):
            ext.pop(node)
        elif node in est_num:
            ext.pop(node)              # 同じ番号なら、前後の番号から埋めた方として出す
    # 線の折れ点: 架空線(power=line)の途中の点で、鉄塔などのタグが無いもの(鉄塔が描かれていないが、折れ点は鉄塔の位置であることが多い)
    bends = {}
    for wid in sorted(ways):
        w = ways[wid]
        if (w.get("tags") or {}).get("power") != "line":
            continue
        for nid in w["nodes"][1:-1]:
            n = nodes.get(nid)
            if n and not (n.get("tags") or {}).get("power") and nid not in bends:
                bends[nid] = route_of[wid]

    # ── 路線の属性 ──
    rids = sorted(mem)
    mids = []
    for rid in rids:
        longest = max(mem[rid], key=lambda w: (len(ways[w]["nodes"]), -w))
        c = R.way_coords(ways[longest], nodes)
        mids.append([c[len(c) // 2][1], c[len(c) // 2][0]] if c else [137.0, 36.0])
    rregion = dict(zip(rids, region_of(mids)))

    routes_by_region = collections.defaultdict(list)
    route_meta = {}
    for rid, mid in zip(rids, mids):
        wids = mem[rid]
        name, unnamed = R.route_name(wids, ways, nodes)
        kvs = set()
        tagvals = collections.defaultdict(collections.Counter)
        styles = collections.Counter()
        length = 0.0
        geom = []
        lats, lons = [], []
        for w in wids:
            t = ways[w].get("tags") or {}
            kvs |= R.kv_set(t)
            for k in ROUTE_TAG_KEYS:
                if t.get(k):
                    tagvals[k][str(t[k])] += 1
            st = R.way_style(t)
            styles[st or "air"] += 1
            c = R.way_coords(ways[w], nodes)
            if len(c) < 2:
                continue
            length += R.way_length_km(ways[w], nodes)
            lats += [p[0] for p in c]
            lons += [p[1] for p in c]
            wkv = max(R.kv_set(t), default=0)
            geom.append([w, wkv, st, R.encode_polyline(c)])
        # 路線の端: 路線の中で 1 本の way にしか出てこない端点
        cnt = collections.Counter()
        for w in wids:
            for nid in (ways[w]["nodes"][0], ways[w]["nodes"][-1]):
                cnt[nid] += 1
        own = set(wids)
        ends = []
        for nid in sorted(n for n, k in cnt.items() if k == 1):
            if nid not in nodes:
                continue
            s = sites.at(nodes[nid]["lat"], nodes[nid]["lon"])
            other = [x for x in nidx.get(nid, []) if x not in own]
            if s:
                ends.append([s[0], s[1] or None])
            elif other:
                ends.append(["line", None])          # ほかの路線へ続く
            else:
                pw = (nodes[nid].get("tags") or {}).get("power")
                ends.append([pw if pw in ("portal", "terminal", "transition") else "none", None])
        tw = [n for w in wids for n in ways[w]["nodes"] if n in towers]
        tw = list(dict.fromkeys(tw))
        n_ref = sum(1 for n in tw if (towers[n].get("tags") or {}).get("ref"))
        jn = joins.get(rid, {})
        # 列の並びは ROUTE_COLS(meta.json にも書く)。null の代わりに 0 を使って短くする
        tg = {k: [v for v, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:4]]
              for k, c in sorted(tagvals.items()) if k not in ("name", "voltage")}
        # 回線数の推定: OSM に回線数のある way が 1 本も無い路線だけ。way ごとの推定の多い方
        cir_est = 0
        if not tagvals.get("circuits"):
            ests = collections.Counter()
            for w in wids:
                e_ = R.circuits_estimate(ways[w].get("tags") or {}, rel_count.get(w, 0))
                if e_:
                    ests[e_] += 1
            if ests:
                (v_, src_), _ = sorted(ests.items(), key=lambda kv: (-kv[1], kv[0]))[0]
                cir_est = [v_, src_]
        rec = [rid, name or 0, unnamed, sorted(kvs), round(length, 2),
               [round(min(lons), 5), round(min(lats), 5), round(max(lons), 5), round(max(lats), 5)] if lats else 0,
               len(tw), n_ref, [jn.get("same_name", 0), jn.get("continuation", 0), jn.get("half_named", 0)],
               [[e[0], e[1] or 0] for e in ends], tg or 0, geom, cir_est, 1 if route_linear.get(rid) else 0]
        routes_by_region[rregion[rid]].append(rec)
        route_meta[rid] = (rregion[rid], name, max(kvs, default=0), mid)

    reg_index = {r: i for i, r in enumerate(REGIONS)}
    region_bbox = {}
    for reg in REGIONS:
        rs = routes_by_region.get(reg, [])
        bb = [r[5] for r in rs if r[5]]
        region_bbox[reg] = [min(b[0] for b in bb), min(b[1] for b in bb), max(b[2] for b in bb), max(b[3] for b in bb)] if bb else None
        dump(os.path.join(args.out, f"routes_{reg}.json"), {"region": reg, "cols": ROUTE_COLS, "routes": rs})

    # ── 鉄塔(地域ごと) ──
    # 列ごとに持ち、id と座標は 1 つ前との差で書く(id の順に並べると近い鉄塔が続くので差が小さい)。
    # 路線は各ファイルの路線一覧 rl への番号で持つ(併架は番号の配列)。番号・名前は持つ鉄塔だけ {位置: 値}
    towers_by_region = collections.defaultdict(list)
    tids = sorted(towers)
    treg = region_of([[towers[i]["lon"], towers[i]["lat"]] for i in tids])
    reg_of_tower = dict(zip(tids, treg))
    for tid, reg in zip(tids, treg):
        towers_by_region[reg].append(tid)
    bends_by_region = {}
    bids = sorted(bends)
    breg = region_of([[nodes[b]["lon"], nodes[b]["lat"]] for b in bids]) if bids else []
    _bb = collections.defaultdict(list)
    for b, reg in zip(bids, breg):
        _bb[reg].append(b)
    for reg, lst in _bb.items():
        lst.sort(key=lambda b: (bends[b], b))
        brl = sorted({bends[b] for b in lst})
        bri = {r: i for i, r in enumerate(brl)}
        pla = plo = 0
        dla_, dlo_, rr_ = [], [], []
        for b in lst:
            la, lo = lat5(nodes[b]["lat"]), lat5(nodes[b]["lon"])
            dla_.append(la - pla); dlo_.append(lo - plo); pla, plo = la, lo
            rr_.append(bri[bends[b]])
        bends_by_region[reg] = {"n": len(lst), "lat": dla_, "lon": dlo_, "r": rr_, "rl": brl}
    # 地域ごとの補完の数(前後の比べに使う)
    comp = {reg: collections.Counter() for reg in REGIONS}
    for tid, reg in zip(tids, treg):
        t = towers[tid].get("tags") or {}
        c = comp[reg]
        c["towers"] += 1
        c["ref_osm"] += bool(t.get("ref"))
        c["name_osm"] += bool(t.get("name"))
        c["ref_or_name_osm"] += bool(t.get("ref") or t.get("name"))
        if not (t.get("ref") or t.get("name")):
            if tid in est_num:
                c["ref_est"] += 1
            elif tid in ext:
                c["ref_ext"] += 1
            elif any(route_linear.get(r) for r in tower_routes.get(tid, ())):
                c["ordinal_only"] += 1
            else:
                c["nothing"] += 1
    for reg, lst in _bb.items():
        comp[reg]["bends"] = len(lst)
    wmid = []
    wsorted = sorted(ways)
    for wid in wsorted:
        c_ = R.way_coords(ways[wid], nodes)
        wmid.append([c_[len(c_) // 2][1], c_[len(c_) // 2][0]] if c_ else [137.0, 36.0])
    for wid, reg in zip(wsorted, region_of(wmid)):
        t = ways[wid].get("tags") or {}
        if t.get("power") not in ("line", "cable"):
            continue
        c = comp[reg]
        c["lines"] += 1
        if t.get("circuits"):
            c["cir_osm"] += 1
        else:
            e_ = R.circuits_estimate(t, rel_count.get(wid, 0))
            c["cir_est_" + e_[1] if e_ else "cir_none"] += 1

    for reg in REGIONS:
        ids = towers_by_region.get(reg, [])
        rl = sorted({r for t in ids for r in tower_routes.get(t, ())})
        ri_of = {r: i for i, r in enumerate(rl)}
        did, dla, dlo, rr = [], [], [], []
        refs, names, extra, ests = {}, {}, {}, {}
        pid = pla = plo = 0
        for k, tid in enumerate(ids):
            n = towers[tid]
            la, lo = lat5(n["lat"]), lat5(n["lon"])
            did.append(tid - pid); dla.append(la - pla); dlo.append(lo - plo)
            pid, pla, plo = tid, la, lo
            rs = [ri_of[r] for r in sorted(tower_routes.get(tid, ()))]
            rr.append(-1 if not rs else rs[0] if len(rs) == 1 else rs)
            t = n.get("tags") or {}
            if t.get("ref"):
                refs[str(k)] = t["ref"]
            if t.get("name"):
                names[str(k)] = t["name"]
            if tid in est_num:
                ests[str(k)] = [est_num[tid], ri_of.get(est_rid[tid], -1)]
            elif tid in ext:
                num, rid_, src, steps = ext[tid]
                ests[str(k)] = [num, ri_of.get(rid_, -1), REGIONS.index(reg_of_tower[src]) if src in reg_of_tower else -1,
                                src, num_of(src), steps]
            ex = {kk: t[kk] for kk in TOWER_TAGS if t.get(kk) and kk != "operator"}
            if ex:
                extra[str(k)] = ex
        dump(os.path.join(args.out, f"towers_{reg}.json"), {
            "region": reg, "n": len(ids),
            "how": "id・lat・lon は 1 つ前との差(lat・lon は ×1e5 の整数)。r は rl の番号(-1 は線に載っていない、配列は併架)",
            "rl": rl, "id": did, "lat": dla, "lon": dlo, "r": rr, "ref": refs, "name": names, "tags": extra,
            "est": ests, "est_how": ("番号の推定 {位置: [番号, rl の番号(その番号を埋めた路線)]}。前後の番号のある鉄塔の間の基数が"
                                     "番号の差と合うときだけ。6 つの要素のものは線の端まで延ばした推定 [番号, rl の番号, 延ばした元の鉄塔の地域"
                                     "(regions の番号), 元の鉄塔の node id, 元の番号, 元から何基先]。番号のある鉄塔が 2 基以上あり、どの 2 基の"
                                     "あいだも 1 基ごとに番号が 1 つずつ増える(減る)並びだけ"),
            "bends": bends_by_region.get(reg, {"n": 0, "lat": [], "lon": [], "r": [], "rl": []}),
            "bends_how": "線の折れ点(鉄塔のタグの無い架空線の途中の点)。lat・lon は 1 つ前との差、r は bends.rl の番号"})
        towers_by_region[reg] = [(tid, lat5(towers[tid]["lat"]), lat5(towers[tid]["lon"]),
                                  (towers[tid].get("tags") or {}).get("ref"), (towers[tid].get("tags") or {}).get("name"),
                                  sorted(tower_routes.get(tid, ()))) for tid in ids]

    # ── 地図の正典の線 → 路線 ──
    idx5 = collections.defaultdict(set)
    for wid, w in ways.items():
        for nid in w["nodes"]:
            n = nodes.get(nid)
            if n:
                idx5[(round(n["lat"], 5), round(n["lon"], 5))].add(route_of[wid])
    with open(os.path.join(ROOT, "docs", "data", "map", "lines_all.geojson"), encoding="utf-8") as fh:
        feats = json.load(fh)["features"]
    if len(feats) != len(built["edges"]):
        sys.exit("lines_all.geojson と built/all.json の枝の数が違う(先に export_map_tiers_from_built.py を走らせる)")
    edge_routes = {}
    n_mapped = 0
    for e, f in zip(built["edges"], feats):
        path = e.get("path")
        if not path:
            continue
        hits = collections.Counter()
        for lat, lon in path:
            for rid in idx5.get((round(lat, 5), round(lon, 5)), ()):
                hits[rid] += 1
        if not hits:
            continue
        ekv = float(e.get("kv") or 0)
        need = 2 if len(path) >= 3 else 1

        def score(item):
            rid, h = item
            rkv = route_meta[rid][2]
            kv_ok = (not ekv) or (not rkv) or abs(rkv - ekv) < 0.6
            return (not kv_ok, -h, rid)
        picked = [rid for rid, h in sorted(hits.items(), key=score) if h >= need][:4]
        if not picked:
            continue
        key = R.edge_key(f["geometry"]["coordinates"])
        cur = edge_routes.setdefault(key, [])
        for rid in picked:
            if rid not in cur[::2]:
                cur += [rid, reg_index.get(route_meta[rid][0], -1)]
        n_mapped += 1
    dump(os.path.join(args.out, "edge_routes.json"), {"key": "x1e4,y1e4,x1e4,y1e4,頂点数(地図の線の始点・終点・頂点数)",
                                                      "value": "[route_id, 地域番号, ...] 地域番号は meta.regions の順",
                                                      "map": dict(sorted(edge_routes.items()))})

    # ── 横断検索の一覧 ──
    s_routes = []
    for rid in rids:
        reg, name, kv, mid = route_meta[rid]
        if not name:
            continue
        s_routes.append([rid, reg_index.get(reg, -1), name, kv, lat5(mid[1]), lat5(mid[0]),
                         sorted(R.name_set({"name": name}))])
    s_subs = []
    seen = set()
    for n in built["nodes"]:
        if not n.get("sub") or not n.get("name"):
            continue
        k = (n["name"], round(n["lat"], 3), round(n["lon"], 3))
        if k in seen:
            continue
        seen.add(k)
        s_subs.append([n["name"], float(n.get("kv") or 0), lat5(n["lat"]), lat5(n["lon"]), reg_index.get(n.get("region"), -1)])
    s_subs.sort(key=lambda x: (x[0], x[2], x[3]))
    s_plants = []
    with open(os.path.join(ROOT, "docs", "data", "plants_all.geojson"), encoding="utf-8") as fh:
        for f in json.load(fh)["features"]:
            p = f["properties"]
            nm = (p.get("_display_name") or "").strip()
            if not nm or f["geometry"]["type"] != "Point":
                continue
            lon, lat = f["geometry"]["coordinates"][:2]
            s_plants.append([nm, p.get("fuel_type") or "unknown", p.get("capacity_mw") or 0, lat5(lat), lat5(lon),
                             reg_index.get(p.get("_region"), -1)])
    s_plants.sort(key=lambda x: (x[0], x[3], x[4]))
    s_towers = []
    for reg in REGIONS:
        ri = reg_index[reg]
        for tid, la, lo, ref, nm, rs in towers_by_region.get(reg, []):
            if not (ref or nm):
                continue
            s_towers.append([tid, ri, ref or 0, nm or 0, la, lo, rs[:3]])
    dump(os.path.join(args.out, "search.json"), {
        "regions": REGIONS,
        "routes": s_routes, "routes_cols": ["route_id", "地域", "名前", "kV", "lat×1e5", "lon×1e5", "名前の部分(比べる形)"],
        "subs": s_subs, "subs_cols": ["名前", "kV", "lat×1e5", "lon×1e5", "地域"],
        "plants": s_plants, "plants_cols": ["名前", "燃料", "MW(OSM)", "lat×1e5", "lon×1e5", "地域"],
    })
    dump(os.path.join(args.out, "search_towers.json"), {
        "regions": REGIONS,
        "towers": s_towers, "towers_cols": ["node_id", "地域", "番号(ref)", "名前", "lat×1e5", "lon×1e5", "路線"],
    })

    # ── meta ──
    join_tot = collections.Counter()
    for c in joins.values():
        join_tot.update(c)
    sizes = collections.Counter()
    for rid in rids:
        k = len(mem[rid])
        sizes["1" if k == 1 else "2-5" if k <= 5 else "6-20" if k <= 20 else ">20"] += 1
    meta = {
        "what": "OSM の送電線を路線にまとめた層と鉄塔(観測から作った derived。正典は変えない)",
        "source": {"files": info["files"], "sha256": info["sha256"],
                   "osm_base_min": info["osm_base_min"], "osm_base_max": info["osm_base_max"],
                   "built_all_sha256": _sha(os.path.join(ROOT, "docs", "data", "built", "all.json"))},
        "license": "© OpenStreetMap contributors, ODbL 1.0(https://www.openstreetmap.org/copyright)",
        "rules": {"same_name": "同じ名前・電圧が矛盾しない・点を共有",
                  "continuation": "名前の無い way どうしが端点で 2 本だけ会い、電圧が同じ",
                  "half_named": "片方だけ名前のある way が同じ条件で会い、電圧が分かっている(名前は隣から=推定)",
                  "never": "併架(別の線が同じ鉄塔に載る)・電圧の食い違い・名前の違うまとまりの橋渡しはつながない"},
        "regions": REGIONS,
        "route_cols": ROUTE_COLS,
        "region_bbox": region_bbox,
        "counts": {"ways": len(ways), "routes": len(mem), "route_sizes": dict(sorted(sizes.items())),
                   "joins": dict(sorted(join_tot.items())),
                   "routes_named": len(s_routes), "towers": len(towers),
                   "towers_on_line": sum(1 for t in towers if t in tower_routes),
                   "towers_ref": sum(1 for t in towers.values() if (t.get("tags") or {}).get("ref")),
                   "towers_name": sum(1 for t in towers.values() if (t.get("tags") or {}).get("name")),
                   "map_edges": len(feats), "map_edges_with_path": sum(1 for e in built["edges"] if e.get("path")),
                   "map_edges_mapped": n_mapped, "edge_keys": len(edge_routes)},
        "completion": {reg: dict(sorted(c.items())) for reg, c in comp.items()},
        "relations": len(info.get("relations") or {}),
        "script": "scripts/export_osm_routes.py",
    }
    dump(os.path.join(args.out, "meta.json"), meta)
    tot = sum(os.path.getsize(os.path.join(args.out, f)) for f in os.listdir(args.out))
    print(json.dumps(meta["counts"], ensure_ascii=False))
    print(f"書き出し {args.out}: {tot / 1e6:.1f} MB")


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


if __name__ == "__main__":
    main()
