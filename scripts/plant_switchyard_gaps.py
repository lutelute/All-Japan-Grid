"""発電所の連系変電所(switchyard)がOSMに欠落しているケースを検出する。

オーナー指摘(2026-06-16, 金武火力で発見): 発電所点はOSMにあるが、送電線を繋ぐ
**連系変電所ノードが無い** → builderは発電機を遠方の変電所に繋いでしまう(金武火力600MWが
伊芸変電所5kmへ)。実際は線が発電所直近(~0.5km)で終端=そこに連系点がある。

検出ロジック(物理的証拠ベース・捏造でない):
  各発電所について
    - 最寄り変電所までの距離 nsub
    - 発電所に最も近い「線の終端(端点)」までの距離 nline
  nsub > far_km かつ nline < near_km → **連系点欠落の疑い**。
  推奨switchyard座標 = その線終端(線が実際に来ている=連系点)。

人間が確認して `{region}_substations_supplement.geojson` に追記(adopt)すれば、
発電機も線もその連系点に正しく繋がる。距離一律でなく「線終端が直近にある」証拠を要件にする。

Usage:
    PYTHONPATH=. python scripts/plant_switchyard_gaps.py --region okinawa
    PYTHONPATH=. python scripts/plant_switchyard_gaps.py --region okinawa --emit-supplement  # 候補をsupplementに追記
"""
import argparse
import json
import math
import os


def _km(a, b, c, d):
    return math.hypot((a - c) * 111.0, (b - d) * 100.0)


def _load(region, layer):
    p = os.path.join("data", f"{region}_{layer}.geojson")
    if not os.path.exists(p):
        return []
    return json.load(open(p, encoding="utf-8")).get("features", [])


def detect(region, far_km=2.0, near_km=1.0):
    plants = _load(region, "plants")
    subs = _load(region, "substations")
    lines = _load(region, "lines")
    subpts = [(s["geometry"]["coordinates"][1], s["geometry"]["coordinates"][0])
              for s in subs if s["geometry"]["type"] == "Point"]
    # 線の終端(端点)を集める: (lat, lon, voltage)
    ends = []
    for ln in lines:
        co = ln["geometry"]["coordinates"]
        if len(co) < 2:
            continue
        v = (ln.get("properties") or {}).get("voltage")
        for e in (co[0], co[-1]):
            ends.append((e[1], e[0], v))

    out = []
    for f in plants:
        if f["geometry"]["type"] != "Point":
            continue
        c = f["geometry"]["coordinates"]
        pla, plo = c[1], c[0]
        name = (f.get("properties") or {}).get("name") or "?"
        nsub = min((_km(pla, plo, s[0], s[1]) for s in subpts), default=9e9)
        # 最寄り線終端
        best = None
        bd = 9e9
        for ela, elo, ev in ends:
            d = _km(pla, plo, ela, elo)
            if d < bd:
                bd, best = d, (ela, elo, ev)
        if nsub > far_km and bd < near_km and best:
            out.append({
                "plant": name, "plant_lat": round(pla, 5), "plant_lon": round(plo, 5),
                "nearest_sub_km": round(nsub, 2), "line_end_km": round(bd, 2),
                "switchyard_lat": round(best[0], 5), "switchyard_lon": round(best[1], 5),
                "voltage": best[2],
            })
    out.sort(key=lambda x: (-x["nearest_sub_km"]))
    return out


def emit_supplement(region, candidates):
    """候補を {region}_substations_supplement.geojson に連系点として追記(可逆・provenance付き)。"""
    p = os.path.join("data", f"{region}_substations_supplement.geojson")
    if os.path.exists(p):
        fc = json.load(open(p, encoding="utf-8"))
    else:
        fc = {"type": "FeatureCollection", "features": []}
    have = {(round(f["geometry"]["coordinates"][1], 5),
             round(f["geometry"]["coordinates"][0], 5))
            for f in fc["features"] if f["geometry"]["type"] == "Point"}
    added = 0
    for c in candidates:
        key = (c["switchyard_lat"], c["switchyard_lon"])
        if key in have:
            continue
        fc["features"].append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [c["switchyard_lon"], c["switchyard_lat"]]},
            "properties": {"power": "substation",
                           "name": f"{c['plant']} 連系点(OSM欠落・curated)",
                           "voltage": c["voltage"],
                           "source": "plant_switchyard_gap",
                           "provenance": (f"発電所{c['plant']}は最寄り変電所{c['nearest_sub_km']}kmだが"
                                          f"線終端が{c['line_end_km']}km=連系点。OSM欠落を物理証拠で補完")},
        })
        have.add(key)
        added += 1
    json.dump(fc, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True)
    ap.add_argument("--far-km", type=float, default=2.0)
    ap.add_argument("--near-km", type=float, default=1.0)
    ap.add_argument("--emit-supplement", action="store_true")
    args = ap.parse_args()
    cands = detect(args.region, args.far_km, args.near_km)
    print(f"=== {args.region}: 連系変電所(switchyard)欠落の疑い {len(cands)}件 ===")
    print(f"{'発電所':<24}{'最寄sub':>8}{'線終端':>8}  推奨連系点(switchyard)")
    for c in cands:
        print(f"{c['plant'][:24]:<24}{c['nearest_sub_km']:>6}km{c['line_end_km']:>6}km  "
              f"{c['switchyard_lat']},{c['switchyard_lon']} ({c['voltage']})")
    if args.emit_supplement:
        n = emit_supplement(args.region, cands)
        print(f"\n{n}件を {args.region}_substations_supplement.geojson に追記(adopt/反映でモデル反映・可逆)")


if __name__ == "__main__":
    main()
