"""様式5(系統情報公表)の線路インピーダンス実測をモデル線へ適用する.

正規化正本 `data/external/system_disclosure/normalized/
crosswalk_impedance_to_model.csv`(1,009線・R%/X%/B/2%・基底MVA・両端の
モデル照合と座標)のうち both_resolved=True の行を、モデル線(pandapower
net.line)へ端点座標の近接で照合し、実測 R/X/B に置換する。

置換の意味: OSM由来のヒューリスティック線定数(電圧階級の代表値×線長)を、
事業者公表の実測%インピーダンスで上書きする = 「物理を足す」側の第一歩
(2026-08-20 未解決課題#1)。

v1の適用範囲(正直な限定):
- 両端が座標解決済み(411行)のうち、**モデル上で両端バスを直結する線がある**
  ものだけ。公表1線がモデル上で複数区間(junction経由)の場合は未適用
  (経路配分は将来課題 — 総量を区間へ按分する実装が必要)
- %値は1回線あたり。モデル線の parallel は pandapower が内部で処理する
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict

CSV_PATH = ("data/external/system_disclosure/normalized/"
            "crosswalk_impedance_to_model.csv")


def _bus_lonlat(net, b):
    g = net.bus.at[b, "geo"] if "geo" in net.bus.columns else None
    if not g:
        return None, None
    try:
        coords = json.loads(g)["coordinates"]
        return float(coords[0]), float(coords[1])
    except Exception:  # noqa: BLE001
        return None, None


def _key(lat, lon, prec=2):
    # 0.01°セル(≈1.1km) — ±1セル近傍で snap_km=1.2km を確実に覆う
    return (round(lat, prec), round(lon, prec))


def apply_disclosed_line_impedance(net, csv_path: str = CSV_PATH,
                                   snap_km: float = 1.2,
                                   freq_hz: float = 50.0) -> Dict:
    """実測線路インピーダンスをモデル線へ適用(in-place)。帳簿を返す。"""
    rows = [r for r in csv.DictReader(open(csv_path))
            if r.get("both_resolved") == "True"]

    # バス座標索引(粗グリッド)
    grid = defaultdict(list)
    bll = {}
    for b in net.bus.index:
        lon, lat = _bus_lonlat(net, b)
        if lon is None:
            continue
        bll[int(b)] = (lat, lon)
        grid[_key(lat, lon)].append(int(b))

    def nearest_bus(lat, lon, kv):
        best, bd = None, snap_km
        k0 = _key(lat, lon)
        for dlat in (-1, 0, 1):
            for dlon in (-1, 0, 1):
                for b in grid.get((round(k0[0] + dlat / 100.0, 2),
                                   round(k0[1] + dlon / 100.0, 2)), []):
                    bla, blo = bll[b]
                    d = math.hypot((bla - lat) * 111.0,
                                   (blo - lon) * 111.0 * math.cos(math.radians(lat)))
                    # 電圧一致を優先(±20%)、次点で任意電圧
                    vmatch = abs(float(net.bus.at[b, "vn_kv"]) - kv) < kv * 0.2
                    score = d - (0.5 if vmatch else 0.0)
                    if score < bd:
                        best, bd = b, score
        return best

    # (busペア) -> [line idx] 索引
    pair_lines = defaultdict(list)
    for li in net.line.index:
        a, b = int(net.line.at[li, "from_bus"]), int(net.line.at[li, "to_bus"])
        pair_lines[frozenset((a, b))].append(li)

    n_applied = n_no_bus = n_no_direct = 0
    applied_rows = []
    seen_line = set()
    for r in rows:
        kv = float(r["voltage_kv"])
        fb = nearest_bus(float(r["from_lat"]), float(r["from_lon"]), kv)
        tb = nearest_bus(float(r["to_lat"]), float(r["to_lon"]), kv)
        if fb is None or tb is None or fb == tb:
            n_no_bus += 1
            continue
        lis = pair_lines.get(frozenset((fb, tb)))
        if not lis:
            n_no_direct += 1
            continue
        base_mva = float(r["base_mva"] or 1000.0)
        z_base = kv * kv / base_mva            # ohm
        r_tot = float(r["R_pct"]) / 100.0 * z_base
        x_tot = float(r["X_pct"]) / 100.0 * z_base
        b_tot_s = 2.0 * float(r["B_half_pct"] or 0) / 100.0 / z_base  # S(全体)
        for li in lis:
            if li in seen_line:
                continue           # 1モデル線に複数公表行(並行回線)は最初の1行
            seen_line.add(li)
            length = max(float(net.line.at[li, "length_km"]), 0.05)
            net.line.at[li, "r_ohm_per_km"] = r_tot / length
            net.line.at[li, "x_ohm_per_km"] = x_tot / length
            c_nf = b_tot_s / (2 * math.pi * freq_hz) / length * 1e9
            net.line.at[li, "c_nf_per_km"] = c_nf
            n_applied += 1
            applied_rows.append({"line": r["line_name"], "kv": kv,
                                 "R_pct": r["R_pct"], "X_pct": r["X_pct"]})
            break
    return {"n_rows_resolved": len(rows), "n_applied": n_applied,
            "n_no_bus_match": n_no_bus, "n_no_direct_line": n_no_direct,
            "sample": applied_rows[:8]}
