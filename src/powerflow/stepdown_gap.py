"""介入#43: 降圧点欠損の是正 — (a) 異階級直結線の暗黙降圧 / (b) 降圧点無し低圧網の帳簿付き縮約.

背景(docs/reports/stepdown_sourcing_negative_2026-08-10.md・whatif_stepdown_2026-08-09.md):
east は 66/77kV バス 4,727 に対し変圧器 630 台しかなく、66/77kV 需要の 10% は
どの降圧点からも到達できない。出典(基幹系統図・OSM名)ではこの層の降圧点は埋まらない
=負の結果。推奨は「66/77kV 層を網として解かず、帳簿付きで親変電所へ集約する」。

本モジュールは 2 つの介入を **PF ビルダー側(計算モデル)** で行う。正典 built は変更しない。

#43a 異階級直結線の暗黙降圧(implicit step-down)
    正典の線(kv_L)の端点座標に kv_L のノードが無く、ビルダーが同座標の別階級バス
    (kv_H≠kv_L)へ線を繋いでいる箇所(例: 新淀線 66kV → 新宿変電所 275kV 母線)。
    66kV 線が 275kV 母線に直結することは電気的にあり得ないので、**同サイトに kv_L 母線が
    存在し、kv_H/kv_L 変圧器で結ばれていることは電気的必然**(#37 と同じ論法:
    存在のみ主張・容量は出典があれば銘板、無ければ推定と明記)。
    → 同座標に kv_L バスを新設し線を付け替え、変圧器を挿入する。

#43b 降圧点無し 66/77kV 網の帳簿付き縮約(lv aggregation)
    同階級の線だけで連結し、変圧器も(仮)給電(#37)も電源も持たない 66/77kV 成分は、
    現状「合成無限大母線(synthetic slack)」が給電する=網としては解けていない。
    その負荷を最近傍(≤R km)の上位電圧(≥110kV)バスへ移し、当該成分は非通電化する。
    需要は保存(縮約であって捏造ではない)。R 超のものは集約せず「未給電網」として開示。

どちらも全件を帳簿(戻り値)に出す。無効化=フラグ OFF(既定は台帳参照)。
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections import defaultdict
from typing import Callable, Dict, List, Optional

LV_MAX_KV = 100.0       # 66/77kV 層(これ未満を低圧網とみなす)
HV_MIN_KV = 110.0       # 縮約先の上位電圧
STD_VK, STD_VKR = 12.0, 0.5   # 既存ヒューリスティック変圧器と同じ定数
SN_STEP = 100.0
# #43a の容量規則(2026-09-03): "line"=取付線の熱容量を 100MVA 刻みで切上げ(従来・既定)。
# "prior"=出典つき銘板の電圧対別中央値(線の熱容量を上限)。既定は従来のまま — 切替は
# 環境変数 AJG_STEPDOWN_CAPACITY=prior か apply_implicit_stepdown(capacity_rule=)。
CAPACITY_RULE_DEFAULT = os.environ.get("AJG_STEPDOWN_CAPACITY", "line")


def _k5(la, lo):
    return (round(la, 5), round(lo, 5))


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _path_len_km(path):
    if not path or len(path) < 2:
        return 0.0
    return sum(_haversine_km(path[i][0], path[i][1], path[i + 1][0], path[i + 1][1])
               for i in range(len(path) - 1))


def bus_lonlat(net, b):
    """(lon, lat)。pandapower 3.x の geo 列(GeoJSON 文字列)から。無ければ (None, None)。"""
    g = net.bus.at[b, "geo"] if "geo" in net.bus.columns else None
    if not g:
        return None, None
    try:
        c = json.loads(g)["coordinates"]
        return float(c[0]), float(c[1])
    except (ValueError, KeyError, IndexError, TypeError):
        return None, None


def site_name_of_bus(name: str) -> str:
    """'信貴変電所 500kV' → '信貴変電所'(NFKC・空白除去)。run_full_powerflow_from_db と同旨。"""
    s = re.sub(r"\s*\d+(?:\.\d+)?\s*kV$", "", str(name))
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


# ── 線の電圧階級(元エッジの kv)を線テーブルへ付ける ────────────────────────
def assign_line_classes(net, bus_of, nodes, edges, coord_nodes) -> Dict:
    """各 pandapower 線に `kv_class`(元エッジの kv・不明は 0)を付ける。

    ビルダーはエッジ→線の対応を返さないので、端点バス対+経路長で引き戻す
    (同一バス対・同一長さの重複は先勝ち。B案 dedup 後の線は一意に近い)。
    """
    if "kv_class" not in net.line.columns:
        net.line["kv_class"] = 0.0
    by_pair: Dict[tuple, List[int]] = defaultdict(list)
    for li in net.line.index:
        a, b = int(net.line.at[li, "from_bus"]), int(net.line.at[li, "to_bus"])
        by_pair[(min(a, b), max(a, b))].append(int(li))
    used = set()
    n_assigned = n_unmatched = 0

    def pick(cands, ekv):
        if ekv > 0:
            for j in cands:
                if abs(float(nodes[j].get("kv") or 0) - ekv) < 0.5:
                    return j
        return cands[0]

    for e in edges:
        ca = coord_nodes.get(_k5(*e["a"]))
        cb = coord_nodes.get(_k5(*e["b"]))
        if not ca or not cb:
            continue
        ekv = float(e.get("kv") or 0.0)
        ja, jb = pick(ca, ekv), pick(cb, ekv)
        if ja == jb or ja not in bus_of or jb not in bus_of:
            continue
        fa, ta = int(bus_of[ja]), int(bus_of[jb])
        cands = [li for li in by_pair.get((min(fa, ta), max(fa, ta)), []) if li not in used]
        if not cands:
            n_unmatched += 1
            continue
        L = _path_len_km(e.get("path") or [e["a"], e["b"]])
        li = min(cands, key=lambda k: abs(float(net.line.at[k, "length_km"]) - L))
        used.add(li)
        net.line.at[li, "kv_class"] = ekv
        n_assigned += 1
    return {"n_assigned": n_assigned, "n_unmatched": n_unmatched}


# ── (a) 異階級直結の検出と暗黙降圧 ────────────────────────────────────────
def find_class_mismatch(net) -> List[Dict]:
    """線の kv_class と端点バスの vn_kv が食い違う箇所(線ごと・端ごと)。"""
    if "kv_class" not in net.line.columns:
        return []
    out = []
    for li in net.line.index:
        kvl = float(net.line.at[li, "kv_class"] or 0.0)
        if kvl <= 0 or not bool(net.line.at[li, "in_service"]):
            continue
        for end in ("from_bus", "to_bus"):
            b = int(net.line.at[li, end])
            kvb = float(net.bus.at[b, "vn_kv"])
            if abs(kvb - kvl) > 0.5:
                out.append({"line": int(li), "end": end, "bus": b,
                            "bus_kv": kvb, "line_kv": kvl,
                            "name": str(net.line.at[li, "name"]),
                            "bus_name": str(net.bus.at[b, "name"])})
    return out


def _line_mva(net, li):
    """線の熱容量 [MVA]。**理論定格**（介入#45 の較正前）で測る。

    #43a が挿入する変圧器の推定容量は「この線を1回線で運べる設備」の代理なので、
    運用容量への較正（#45・`max_i_ka` を 0.27〜0.95 倍する）が乗った値で測ると
    設備そのものが小さくなってしまう。較正 ON でも同じ変圧器が入るよう、
    `max_i_ka_theo`（較正前を保持する列・#45 で追加）があればそちらを読む。
    """
    kv = float(net.bus.at[int(net.line.at[li, "from_bus"]), "vn_kv"])
    col = "max_i_ka_theo" if "max_i_ka_theo" in net.line.columns else "max_i_ka"
    ika = net.line.at[li, col]
    if ika is None or (isinstance(ika, float) and math.isnan(ika)):
        ika = net.line.at[li, "max_i_ka"]
    return (math.sqrt(3) * kv * float(ika)
            * max(int(net.line.at[li, "parallel"]), 1))


def reclass_unknown_kv_buses(net, unknown_kv_buses) -> List[Dict]:
    """電圧不明ノード(built kv=0 → ビルダーが 66kV を仮置き)のバスを、接続線の階級で正す.

    不明ノードの 66kV は「値」ではなく仮置きなので、そこへ 187kV 幹線が繋がっていても
    降圧点ではない(道南幹線の junction 等)。接続線の kv_class が一種類ならその階級に
    置き直す(変圧器は作らない)。複数階級が集まる不明ノードは最上位階級に置き直し、
    下位階級の線は #43a の暗黙降圧に回す。変圧器が既に付くバスは触らない。
    """
    if not unknown_kv_buses or "kv_class" not in net.line.columns:
        return []
    touched = set()
    for t in net.trafo.index:
        touched.add(int(net.trafo.at[t, "hv_bus"]))
        touched.add(int(net.trafo.at[t, "lv_bus"]))
    classes: Dict[int, set] = defaultdict(set)
    for li in net.line.index:
        kvl = float(net.line.at[li, "kv_class"] or 0.0)
        if kvl <= 0 or not bool(net.line.at[li, "in_service"]):
            continue
        for end in ("from_bus", "to_bus"):
            b = int(net.line.at[li, end])
            if b in unknown_kv_buses:
                classes[b].add(round(kvl, 1))
    ledger = []
    for b, ks in classes.items():
        if b in touched or not ks:
            continue
        cur = round(float(net.bus.at[b, "vn_kv"]), 1)
        target = max(ks)
        if abs(target - cur) <= 0.5:
            continue
        net.bus.at[b, "vn_kv"] = target
        ledger.append({"bus": int(b), "name": str(net.bus.at[b, "name"]), "from_kv": cur,
                       "to_kv": target, "line_classes": sorted(ks),
                       "mixed": len(ks) > 1})
    return ledger


# ── 出典つき銘板の分布(電圧対ごと) — 推定容量の事前分布 ──────────────────
TRAFO_SOURCES = os.path.join(os.path.dirname(__file__), "..", "..",
                             "data", "transformer_sources.jsonl")
_PRIOR_CACHE = None


def sourced_capacity_prior(path: str = None) -> Dict:
    """{(hv_kv, lv_kv): {"median","max","n"}} — `status=existing` の銘板の分布。

    2026-09-03 の検証で、#43a の推定(取付線の熱容量を 100MVA 刻みで切上げ)が
    **出典のある銘板の帯を電圧対ごとに 2〜5 倍上回る**ことが分かった
    (275/66 で推定 1,000MVA vs 出典最大 300MVA=東川崎・取付線 1 本、
     275/154 で推定 2,200 vs 出典最大 450)。原因は「線の熱容量」と
    「バンク容量」の取り違えで、線は通過潮流ぶん太く、降圧バンクは
    その地点の需要ぶんしか無い。この関数は是正のための実測事前分布を返す。

    site 単位で hv_kv・lv_kv・sn_mva が揃っている existing レコードのみ使う
    (sn_total_mva は変電所全体の総出力でバンク容量ではないため使わない)。
    """
    global _PRIOR_CACHE
    if path is None and _PRIOR_CACHE is not None:
        return _PRIOR_CACHE
    import collections
    import statistics
    src = os.path.abspath(path or TRAFO_SOURCES)
    site = collections.defaultdict(lambda: collections.defaultdict(list))
    try:
        with open(src, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("status") == "existing" and r.get("field") and "site_key" in r:
                    site[r["site_key"]][r["field"]].append(r["value"])
    except OSError:
        return {}
    by_pair = collections.defaultdict(list)
    for v in site.values():
        if "sn_mva" in v and "hv_kv" in v and "lv_kv" in v:
            by_pair[(float(max(v["hv_kv"])), float(min(v["lv_kv"])))] += [
                float(x) for x in v["sn_mva"]]
    out = {p: {"median": statistics.median(vals), "max": max(vals), "n": len(vals)}
           for p, vals in by_pair.items()}
    if path is None:
        _PRIOR_CACHE = out
    return out


def apply_implicit_stepdown(net, nameplates: Optional[Dict] = None,
                            region_of_bus: Optional[Callable] = None,
                            unknown_kv_buses=None,
                            capacity_rule: str = CAPACITY_RULE_DEFAULT) -> List[Dict]:
    """#43a: 異階級直結の端点に kv_L バス+kv_H/kv_L 変圧器を挿入し線を付け替える。

    nameplates: {(region, 正規化サイト名): [{hv_kv, lv_kv, sn_mva, n_parallel}]}
      (run_full_powerflow_from_db.load_nameplates と同形)。一致すれば銘板容量。
    region_of_bus: bus -> region 文字列。省略時は net.bus.zone。
    容量(推定): 新バスに付く線の熱容量合計を 100MVA 刻みで切り上げ(≥100)。
      変圧器を線より細くして偽の隘路を作らないための保守側の推定であり、実在の
      銘板ではない(名前に @推定 を刻む)。
    unknown_kv_buses: 電圧不明ノード由来のバス集合。先に reclass_unknown_kv_buses で
      接続線の階級へ置き直す(仮置き 66kV への幹線直結は降圧点ではない)。
    Returns: 帳簿(1 変圧器 1 行)。reclass の帳簿は net._stepdown_reclass に置く。
    """
    import pandapower as pp

    net._stepdown_reclass = reclass_unknown_kv_buses(net, set(unknown_kv_buses or ()))
    mism = find_class_mismatch(net)
    if not mism:
        return []
    groups: Dict[tuple, List[Dict]] = defaultdict(list)
    for m in mism:
        groups[(m["bus"], round(m["line_kv"], 1))].append(m)
    ledger = []
    for (b, kvl), items in sorted(groups.items()):
        kvb = float(net.bus.at[b, "vn_kv"])
        lon, lat = bus_lonlat(net, b)
        geodata = (lon, lat) if lon is not None else None
        nb = pp.create_bus(net, vn_kv=kvl, name=f"{net.bus.at[b, 'name']}@{kvl:.0f}kV(#43a)",
                           type=str(net.bus.at[b, "type"]), geodata=geodata)
        if "zone" in net.bus.columns:
            net.bus.at[nb, "zone"] = net.bus.at[b, "zone"]
        names = []
        for m in items:
            net.line.at[m["line"], m["end"]] = nb
            names.append(m["name"])
        hv_kv, lv_kv = max(kvb, kvl), min(kvb, kvl)
        hb, lb = (b, nb) if kvb > kvl else (nb, b)
        # 銘板(出典) → 無ければ推定
        sn, par, tag = None, 1, "@推定"
        if nameplates:
            region = (region_of_bus(b) if region_of_bus
                      else (net.bus.at[b, "zone"] if "zone" in net.bus.columns else None))
            for p in nameplates.get((region, site_name_of_bus(net.bus.at[b, "name"])), ()):
                if p.get("hv_kv") is None or p.get("lv_kv") is None:
                    continue
                if abs(p["hv_kv"] - hv_kv) <= 0.5 and abs(p["lv_kv"] - lv_kv) <= 0.5:
                    sn, par, tag = float(p["sn_mva"]), max(int(p.get("n_parallel") or 1), 1), "@nameplate"
                    break
        if sn is None:
            mva = sum(_line_mva(net, m["line"]) for m in items)
            line_sn = max(SN_STEP, math.ceil(mva / SN_STEP) * SN_STEP)
            pri = (sourced_capacity_prior().get((hv_kv, lv_kv))
                   if capacity_rule == "prior" else None)
            if pri:
                # 出典帯の中央値。ただし線の熱容量を超えない(過大な事前分布で
                # 線より太い変圧器を作らない)。100MVA 刻みは踏襲
                sn = max(SN_STEP, min(line_sn,
                                      math.ceil(pri["median"] / SN_STEP) * SN_STEP))
                tag = "@出典帯"
            else:
                sn = line_sn
        pp.create_transformer_from_parameters(
            net, hv_bus=hb, lv_bus=lb, sn_mva=sn, vn_hv_kv=hv_kv, vn_lv_kv=lv_kv,
            vkr_percent=STD_VKR, vk_percent=STD_VK, pfe_kw=0.0, i0_percent=0.0,
            parallel=par, name=f"trafo_{hv_kv:.0f}/{lv_kv:.0f}kV#43a{tag}")
        ledger.append({"site": str(net.bus.at[b, "name"]), "bus": int(b), "new_bus": int(nb),
                       "hv_kv": hv_kv, "lv_kv": lv_kv, "n_lines": len(items),
                       "lines": names[:6], "sn_mva": sn, "parallel": par,
                       "capacity": {"@nameplate": "nameplate",
                                    "@出典帯": "prior"}.get(tag, "estimated"),
                       "lat": lat, "lon": lon})
    return ledger


# ── (b) 降圧点無し低圧網の検出・縮約 ─────────────────────────────────────
def lv_islands(net, kv_max: float = LV_MAX_KV, hv_min: float = HV_MIN_KV) -> List[Dict]:
    """変圧器・電源を持たない同階級(<kv_max)線成分と、最近傍の上位電圧バスまでの距離。"""
    import networkx as nx
    import numpy as np

    g = nx.Graph()
    for li in net.line.index:
        if not bool(net.line.at[li, "in_service"]):
            continue
        a, b = int(net.line.at[li, "from_bus"]), int(net.line.at[li, "to_bus"])
        if abs(float(net.bus.at[a, "vn_kv"]) - float(net.bus.at[b, "vn_kv"])) > 0.5:
            continue
        if float(net.bus.at[a, "vn_kv"]) >= kv_max:
            continue
        g.add_edge(a, b)
    for b in net.bus.index:
        if bool(net.bus.at[b, "in_service"]) and float(net.bus.at[b, "vn_kv"]) < kv_max:
            g.add_node(int(b))
    touched = set()
    for t in net.trafo.index:
        if bool(net.trafo.at[t, "in_service"]):
            touched.add(int(net.trafo.at[t, "hv_bus"]))
            touched.add(int(net.trafo.at[t, "lv_bus"]))
    sourced = set()
    for tbl in ("gen", "sgen", "ext_grid"):
        df = getattr(net, tbl)
        if len(df):
            sourced |= {int(x) for x in df.loc[df.in_service, "bus"]} if "in_service" in df.columns \
                else {int(x) for x in df.bus}
    load_at = defaultdict(float)
    for i in net.load.index:
        if bool(net.load.at[i, "in_service"]):
            load_at[int(net.load.at[i, "bus"])] += float(net.load.at[i, "p_mw"])
    hv = []
    for b in net.bus.index:
        if bool(net.bus.at[b, "in_service"]) and float(net.bus.at[b, "vn_kv"]) >= hv_min:
            lon, lat = bus_lonlat(net, b)
            if lon is not None:
                hv.append((int(b), lat, lon))
    hv_lat = np.array([h[1] for h in hv]) if hv else np.zeros(0)
    hv_lon = np.array([h[2] for h in hv]) if hv else np.zeros(0)
    out = []
    for comp in nx.connected_components(g):
        comp = {int(b) for b in comp}
        if comp & touched or comp & sourced:
            continue
        load = sum(load_at.get(b, 0.0) for b in comp)
        pts = [(bus_lonlat(net, b), load_at.get(b, 0.0)) for b in comp]
        pts = [((lo, la), w) for (lo, la), w in pts if lo is not None]
        if not pts:
            continue
        wsum = sum(w for _, w in pts)
        if wsum > 0:
            clat = sum(la * w for (lo, la), w in pts) / wsum
            clon = sum(lo * w for (lo, la), w in pts) / wsum
        else:
            clat = sum(la for (lo, la), _ in pts) / len(pts)
            clon = sum(lo for (lo, la), _ in pts) / len(pts)
        anchor, dist = None, None
        if len(hv):
            d = np.hypot((hv_lat - clat) * 111.0, (hv_lon - clon) * 91.0)
            k = int(np.argmin(d))
            anchor, dist = hv[k][0], float(d[k])
        kv = float(net.bus.at[next(iter(comp)), "vn_kv"])
        names = sorted({str(net.bus.at[b, "name"])[:14] for b in comp if load_at.get(b, 0) > 0})[:3]
        out.append({"buses": sorted(comp), "n_bus": len(comp), "kv": kv,
                    "load_mw": round(load, 2), "anchor_bus": anchor,
                    "anchor_name": (str(net.bus.at[anchor, "name"]) if anchor is not None else None),
                    "anchor_kv": (float(net.bus.at[anchor, "vn_kv"]) if anchor is not None else None),
                    "dist_km": (round(dist, 2) if dist is not None else None),
                    "names": names, "lat": round(clat, 5), "lon": round(clon, 5)})
    out.sort(key=lambda c: -c["load_mw"])
    return out


def aggregate_lv_islands(net, r_max_km: float = 5.0, kv_max: float = LV_MAX_KV,
                         hv_min: float = HV_MIN_KV) -> Dict:
    """#43b: lv_islands のうち最近傍上位バスが r_max_km 以内の成分の負荷/sgen/shunt を
    そのバスへ移し、成分のバス・線を非通電化する(需要保存)。R 超は未給電網として開示。"""
    comps = lv_islands(net, kv_max=kv_max, hv_min=hv_min)
    moved, unserved = [], []
    moved_mw = 0.0
    for c in comps:
        if c["anchor_bus"] is None or c["dist_km"] is None or c["dist_km"] > r_max_km:
            unserved.append({k: c[k] for k in ("n_bus", "kv", "load_mw", "dist_km", "names", "lat", "lon")})
            continue
        bs = set(c["buses"])
        for tbl in ("load", "sgen", "shunt"):
            df = getattr(net, tbl)
            for i in df.index:
                if int(df.at[i, "bus"]) in bs:
                    df.at[i, "bus"] = c["anchor_bus"]
        for li in net.line.index:
            if int(net.line.at[li, "from_bus"]) in bs or int(net.line.at[li, "to_bus"]) in bs:
                net.line.at[li, "in_service"] = False
        for b in bs:
            net.bus.at[b, "in_service"] = False
        moved_mw += c["load_mw"]
        moved.append({k: c[k] for k in ("n_bus", "kv", "load_mw", "anchor_bus", "anchor_name",
                                        "anchor_kv", "dist_km", "names", "lat", "lon")})
    return {"r_max_km": r_max_km, "n_islands": len(comps), "n_aggregated": len(moved),
            "aggregated_mw": round(moved_mw, 1), "n_unserved": len(unserved),
            "unserved_mw": round(sum(u["load_mw"] for u in unserved), 1),
            "aggregated": moved, "unserved": unserved,
            "note": "縮約(需要保存・成分は非通電化)。移設先は最近傍の≥110kVバス=経路の推定。"
                    "実在の給電経路ではない"}


# ── census(ドライラン用の集計) ────────────────────────────────────────────
def census(net) -> Dict:
    mism = find_class_mismatch(net)
    unknown = getattr(net, "_unknown_kv_buses", set())
    pairs = defaultdict(int)
    sites = defaultdict(int)
    n_unknown = 0
    for m in mism:
        if m["bus"] in unknown:
            n_unknown += 1
            continue
        pairs[f"{m['line_kv']:.0f}->{m['bus_kv']:.0f}"] += 1
        sites[(m["bus"], round(m["line_kv"], 1))] += 1
    isl = lv_islands(net)
    buckets = [(1, "≤1km"), (2, "≤2km"), (5, "≤5km"), (10, "≤10km"), (1e9, ">10km")]
    dist = {lab: {"n": 0, "load_mw": 0.0, "n_bus": 0} for _, lab in buckets}
    for c in isl:
        d = c["dist_km"] if c["dist_km"] is not None else 1e9
        for lim, lab in buckets:
            if d <= lim:
                dist[lab]["n"] += 1
                dist[lab]["load_mw"] += c["load_mw"]
                dist[lab]["n_bus"] += c["n_bus"]
                break
    for lab in dist:
        dist[lab]["load_mw"] = round(dist[lab]["load_mw"], 1)
    return {"mismatch": {"n_line_ends": len(mism) - n_unknown, "n_sites": len(sites),
                         "n_line_ends_at_unknown_kv_bus": n_unknown,
                         "by_pair": dict(sorted(pairs.items(), key=lambda kv: -kv[1])),
                         "examples": [{"line": m["name"], "line_kv": m["line_kv"],
                                       "bus": m["bus_name"], "bus_kv": m["bus_kv"]}
                                      for m in mism if m["bus"] not in unknown][:12]},
            "lv_islands": {"n": len(isl), "n_bus": sum(c["n_bus"] for c in isl),
                           "load_mw": round(sum(c["load_mw"] for c in isl), 1),
                           "n_with_load": sum(1 for c in isl if c["load_mw"] > 0),
                           "n_ge_100mw": sum(1 for c in isl if c["load_mw"] >= 100),
                           "by_distance": dist,
                           "top": [{k: c[k] for k in ("n_bus", "kv", "load_mw", "anchor_name",
                                                      "anchor_kv", "dist_km", "names")}
                                   for c in isl[:12]]}}


def builder_hook(net, bus_of, nodes, edges, coord_nodes, nameplates, freq,
                 implicit_stepdown: bool) -> Dict:
    """build_island_net から 1 箇所で呼ばれる入口。kv_class を常に付け、#43a はフラグ時のみ。"""
    stats = assign_line_classes(net, bus_of, nodes, edges, coord_nodes)
    unknown = {int(b) for i, b in bus_of.items() if not float(nodes[i].get("kv") or 0)}
    net._unknown_kv_buses = unknown
    ledger, reclass = [], []
    if implicit_stepdown:
        def _region(b):
            return net.bus.at[b, "zone"] if "zone" in net.bus.columns else None
        ledger = apply_implicit_stepdown(net, nameplates=nameplates or None,
                                         region_of_bus=_region, unknown_kv_buses=unknown,
                                         capacity_rule=CAPACITY_RULE_DEFAULT)
        reclass = getattr(net, "_stepdown_reclass", [])
    return {"line_class": stats, "implicit_stepdown": ledger, "reclass": reclass}
