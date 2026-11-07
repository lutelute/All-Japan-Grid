"""介入#57: 航空写真で誤接続と分かった分岐点で、潮流計算の網に変圧器を張らない(2026-11-07)。

正典(docs/data/built/all.json)の分岐点は電圧ごとに別の点(id の末尾が電圧)だが、枝は座標でしか点を指さない。
潮流計算の網(full_from_built.build_island_net)は、
  (a) 同じ座標に電圧の違う点があると、変電所かどうかを見ずに変圧器でつなぐ
  (b) 線の電圧と違う電圧の点に線がつながっていると、介入#43a が変圧器を足す
ので、交差や併架の鉄塔の座標にも変圧器ができる。docs/reports/route_audit_mixed_kv_review_2026-11-07.md で
写真を見て「変電所の無い所で電圧の違う線が交差するか同じ鉄塔に載る」と判定した点(台帳
data/reference/junction_misconnects.json の adopt=true)だけ、次のようにする。

  1. その座標の線の端を、線と同じ電圧のバスへ付け替える(無ければその座標に作る)。
     電圧の分からない線(kv=0)は、台帳の点ごとの指定(unknown_kv: {線の名前: kV}。写真で決めたもの)、
     同じ名前の電圧の分かる線、一番高い電圧(正典を作るときの「電圧不明の線はその座標の一番高い階級に
     つなぐ」と同じ)の順で決める。
  2. その座標には変圧器を張らない(同じ座標の変圧器を飛ばし、線とバスの電圧がそろうので #43a も足さない)。

変圧器を消すだけで、線は消さない。台帳に無い点は何も変えない。
無効化: build_island_net(junction_cuts=False)・両ドライバ --no-junction-cuts・環境変数 AJG_JUNCTION_CUTS=0。
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER_PATH = os.path.join(ROOT, "data", "reference", "junction_misconnects.json")
JUNCTION_CUTS_DEFAULT = (os.environ.get("AJG_JUNCTION_CUTS", "1") == "1")

Coord = Tuple[float, float]


def _k5(la, lo) -> Coord:
    return (round(float(la), 5), round(float(lo), 5))


def load_cut_points(path: Optional[str] = None) -> Dict[Coord, dict]:
    """台帳の adopt=true の点を {(lat5, lon5): 行} で返す。台帳が無ければ空。"""
    p = path or LEDGER_PATH
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        d = json.load(fh)
    return {_k5(it["lat"], it["lon"]): it for it in d.get("items", []) if it.get("adopt")}


def _norm_name(s) -> str:
    return "".join(str(s or "").split())


def apply_junction_cuts(net, cut_points: Dict[Coord, dict],
                        coord_buses: Dict[Coord, Iterable[int]],
                        line_ends: Dict[int, Tuple[Coord, Coord, float, str]]) -> Tuple[List[dict], set]:
    """台帳の点で線の端を自分の電圧のバスへ付け替える。

    coord_buses: この島の {座標: その座標の点のバス}(build_island_net の coord_nodes と bus_of から)
    line_ends: {線の番号: (from 側の座標, to 側の座標, 枝の kV(不明は 0), 枝の名前)}
    Returns: (帳簿 1 点 1 行, 当てた座標の集合)。当てた座標には呼び出し側が変圧器を張らない。
    付け替えた線には kv_class(枝の kV)を付ける(#43a の assign_line_classes はこの線を引き直さない)。
    """
    import pandapower as pp

    if not cut_points:
        return [], set()
    if "kv_class" not in net.line.columns:
        net.line["kv_class"] = 0.0
    fixed = set(getattr(net, "_kv_class_fixed", set()))
    ends_at: Dict[Coord, List[Tuple[int, str, float, str]]] = defaultdict(list)
    for li, (ca, cb, ekv, name) in line_ends.items():
        if ca in cut_points:
            ends_at[ca].append((li, "from_bus", ekv, name))
        if cb in cut_points and cb != ca:
            ends_at[cb].append((li, "to_bus", ekv, name))
    ledger, applied = [], set()
    for c in sorted(cut_points):
        buses = sorted({int(b) for b in coord_buses.get(c, ())})
        if not buses:
            continue          # この島に無い点
        ends = [x for x in ends_at.get(c, []) if int(net.line.at[x[0], x[1]]) in buses]
        by_kv: Dict[float, int] = {}
        for b in buses:
            by_kv.setdefault(round(float(net.bus.at[b, "vn_kv"]), 1), b)
        kv_of_name = {}
        for li, end, ekv, name in ends:
            if ekv > 0:
                kv_of_name.setdefault(_norm_name(name), round(ekv, 1))
        top = max(by_kv)
        base = buses[0]
        it = cut_points[c]
        override = {_norm_name(k): round(float(v), 1) for k, v in (it.get("unknown_kv") or {}).items()}
        moved, created = [], []
        for li, end, ekv, name in ends:
            if ekv > 0:
                want = round(ekv, 1)
            else:
                nm = _norm_name(name)
                want = override.get(nm) or kv_of_name.get(nm) or top
            if want not in by_kv:
                g = net.bus.at[base, "geo"] if "geo" in net.bus.columns else None
                try:
                    lon, lat = (json.loads(g) if isinstance(g, str) else g)["coordinates"]
                    geodata = (lon, lat)
                except (TypeError, KeyError, ValueError):
                    geodata = (c[1], c[0])
                nb = pp.create_bus(net, vn_kv=want, name=f"{net.bus.at[base, 'name']}@{want:.0f}kV(#57)",
                                   type="n", geodata=geodata)
                if "zone" in net.bus.columns:
                    net.bus.at[nb, "zone"] = net.bus.at[base, "zone"]
                by_kv[want] = int(nb)
                created.append({"bus": int(nb), "kv": want})
            tb = by_kv[want]
            if ekv > 0:
                net.line.at[li, "kv_class"] = float(ekv)
                fixed.add(int(li))
            if int(net.line.at[li, end]) != tb:
                moved.append({"line": int(li), "name": str(name), "kv": float(ekv), "from_kv":
                              float(net.bus.at[int(net.line.at[li, end]), "vn_kv"]), "to_kv": want})
                net.line.at[li, end] = tb
        applied.add(c)
        ledger.append({"no": it.get("no"), "lat": c[0], "lon": c[1], "kvs": sorted(by_kv),
                       "n_line_ends": len(ends), "moved": moved, "created": created})
    net._kv_class_fixed = fixed
    return ledger, applied
