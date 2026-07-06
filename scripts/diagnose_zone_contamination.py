#!/usr/bin/env python3
"""zone汚染診断 — 幻tie「kyushu↔shikoku」の解剖と、bbox重なり汚染の全量計測.

背景(docs/reports/slack_tie_diagnosis_2026-07-05.md):
  PFのzone跨ぎ集計に実在しない連系線「kyushu↔shikoku 445MW」が現れた。
  本診断器はその正体を機械的に特定する(特定=機械・修正判断=人間)。

計測すること(島単位):
  1. zone跨ぎ線の全ペア別本数と座標つき詳細(=tie_flows_by_pairの集計対象の実態)
  2. 幻ペア(実在連系のないペア)の線の座標・端点名 → 領土誤属性の証拠
  3. 同一座標(k5)で複数zoneのバスが並存する箇所数(重複バスの規模)
  4. 発電所geojsonの地域間重複(同名発電所の二重計上候補)

使い方:
    PYTHONPATH=. .venv/bin/python scripts/diagnose_zone_contamination.py --island west
    PYTHONPATH=. .venv/bin/python scripts/diagnose_zone_contamination.py --island east

出力: docs/reports/zone_contamination_<island>_<date>.json
"""
import argparse
import datetime as _dt
import json
import os
import sys
import warnings
from collections import Counter, defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from scripts.run_full_powerflow_from_db import (  # noqa: E402
    BUILT,
    ISLAND_OF,
    build_island_net,
)

ROOT = os.getcwd()

# OCCTO実連系のある地域ペア(westの地域間・ACベース。阿南紀北はDCなのでAC線ゼロが正)
REAL_TIE_PAIRS = {
    ("chugoku", "kyushu"): "関門連系線(500kV)",
    ("chugoku", "shikoku"): "本四連系線(500kV・瀬戸大橋)",
    ("kansai", "shikoku"): "阿南紀北直流幹線(DC — AC線は存在しないのが正)",
    ("chubu", "kansai"): "三重東近江ほか",
    ("chubu", "hokuriku"): "南福光連系所(BTB — AC貫通線は存在しないのが正)",
    ("hokuriku", "kansai"): "越前嶺南ルート",
    ("chugoku", "kansai"): "西播東岡山・山崎智頭ほか",
    ("tohoku", "tokyo"): "相馬双葉幹線ほか",
}


def _lonlat(net, b):
    g = net.bus.at[b, "geo"]
    if isinstance(g, str):
        c = json.loads(g)["coordinates"]
        return float(c[0]), float(c[1])
    return float(g["x"]), float(g["y"])


def crossing_lines(net):
    """zone跨ぎ線(=tie_flows_by_pairの集計対象)をペア別に列挙する。"""
    zone = net.bus["zone"]
    pairs = defaultdict(list)
    for li in net.line.index:
        fb, tb = int(net.line.at[li, "from_bus"]), int(net.line.at[li, "to_bus"])
        za, zb = str(zone.get(fb)), str(zone.get(tb))
        if za == zb or za == "None" or zb == "None":
            continue
        lof, laf = _lonlat(net, fb)
        lot, lat_ = _lonlat(net, tb)
        pairs[tuple(sorted((za, zb)))].append({
            "line": int(li),
            "kv": float(net.bus.at[fb, "vn_kv"]),
            "parallel": int(net.line.at[li, "parallel"]),
            "length_km": round(float(net.line.at[li, "length_km"]), 1),
            "from": {"zone": za, "name": str(net.bus.at[fb, "name"]),
                     "lat": round(laf, 5), "lon": round(lof, 5)},
            "to": {"zone": zb, "name": str(net.bus.at[tb, "name"]),
                   "lat": round(lat_, 5), "lon": round(lot, 5)},
        })
    return pairs


def multi_zone_coords(net):
    """同一座標(k5)に複数zoneのバスが並存する箇所(bbox重なり由来の重複バス)。"""
    zone = net.bus["zone"]
    coord_zones = defaultdict(set)
    for b in net.bus.index:
        lon, lat = _lonlat(net, b)
        coord_zones[(round(lat, 5), round(lon, 5))].add(str(zone.get(b)))
    return Counter(tuple(sorted(zs))
                   for zs in coord_zones.values() if len(zs) > 1)


def plant_overlaps(island):
    """発電所geojsonの地域間の同名重複(attach_generatorsが二重付与する候補)。"""
    regions = [r for r, (isl, _f) in ISLAND_OF.items() if isl == island]
    feats_of = {}
    for r in regions:
        path = os.path.join(ROOT, "data", f"{r}_plants.geojson")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        feats_of[r] = {f["properties"].get("name")
                       for f in d.get("features", [])
                       if f["properties"].get("name")}
    dup = {}
    rs = sorted(feats_of)
    for i, a in enumerate(rs):
        for b in rs[i + 1:]:
            common = feats_of[a] & feats_of[b]
            if common:
                dup[f"{a}|{b}"] = {"count": len(common),
                                   "sample": sorted(common)[:10]}
    return dup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--island", default="west",
                    choices=["west", "east", "hokkaido", "okinawa"])
    args = ap.parse_args()
    freq = {"hokkaido": 50.0, "east": 50.0, "west": 60.0, "okinawa": 60.0}

    with open(BUILT, encoding="utf-8") as f:
        db = json.load(f)
    net, _, _ = build_island_net(args.island, db["nodes"], db["edges"],
                                 freq[args.island], {})
    print(f"{args.island}: {len(net.bus)} buses / {len(net.line)} lines")

    pairs = crossing_lines(net)
    print("\n== zone跨ぎ線(ペア別本数 / 実連系) ==")
    summary = {}
    for key in sorted(pairs):
        real = REAL_TIE_PAIRS.get(key, "**実在連系なし(幻ペア)**")
        n = len(pairs[key])
        kvd = dict(Counter(str(int(r["kv"])) for r in pairs[key]))
        print(f"  {key[0]}<->{key[1]}: {n}本 kv={kvd} — {real}")
        summary[f"{key[0]}<->{key[1]}"] = {"n": n, "kv": kvd, "real_tie": real}

    mz = multi_zone_coords(net)
    print(f"\n== 複数zone並存座標: {sum(mz.values())}箇所 ==")
    for p, c in mz.most_common():
        print(f"  {'|'.join(p)}: {c}")

    dup = plant_overlaps(args.island)
    print("\n== 発電所geojsonの地域間同名重複 ==")
    for k, v in sorted(dup.items()):
        print(f"  {k}: {v['count']}件 (例: {', '.join(v['sample'][:3])})")

    date = _dt.date.today().isoformat()
    out = {
        "_meta": {"island": args.island, "date": date,
                  "source": "docs/data/built/all.json",
                  "script": "scripts/diagnose_zone_contamination.py"},
        "crossing_pairs_summary": summary,
        "crossing_lines": {f"{k[0]}<->{k[1]}": v for k, v in sorted(pairs.items())},
        "multi_zone_coords": {"total": sum(mz.values()),
                              "by_pair": {"|".join(p): c for p, c in mz.items()}},
        "plant_name_overlaps": dup,
    }
    path = os.path.join(ROOT, "docs", "reports",
                        f"zone_contamination_{args.island}_{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nsaved: {path}")


if __name__ == "__main__":
    main()
