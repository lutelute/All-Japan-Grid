#!/usr/bin/env python3
"""九州/沖縄プレースホルダ発電所 × gem.wiki日本ページ の決定的突合.

分類:
  AUTO      — 相互最近傍・距離/名前の強い証拠・燃料整合(自動採用候補→サンプル反証検証へ)
  AMBIG     — 候補はあるが証拠が弱い/競合あり(ワークフロー裁定へ)
  UNMATCHED — 候補なし(大物のみ捜索対象リストへ)

使い方: python3 match_gem_placeholders.py gem_japan_pages.jsonl <repo_root> out_prefix
"""
import json
import math
import re
import sys
import unicodedata

FUEL_TRACKER = {
    "solar": {"Solar farms in Japan"},
    "wind": {"Wind farms in Japan"},
    "hydro": {"Hydroelectric power plants in Japan"},
    "pumped_hydro": {"Hydroelectric power plants in Japan"},
    "nuclear": {"Nuclear power plants in Japan"},
    "coal": {"Coal power stations in Japan", "Bioenergy power stations in Japan"},
    "gas": {"Oil & Gas power stations in Japan"},
    "lng": {"Oil & Gas power stations in Japan"},
    "oil": {"Oil & Gas power stations in Japan", "Coal power stations in Japan"},
    "biomass": {"Bioenergy power stations in Japan", "Coal power stations in Japan"},
    "waste": {"Bioenergy power stations in Japan"},
    "geothermal": {"Geothermal power plants in Japan"},
    "battery": set(),
    "mixed": None,     # None = 全カテゴリ許容(要裁定)
    "unknown": None,
}
MAJOR_FUELS = {"nuclear", "coal", "gas", "lng", "oil", "geothermal",
               "hydro", "pumped_hydro", "wind", "biomass", "waste", "mixed", "unknown"}


def norm_name(s):
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"[\s　]", "", s)
    for w in ("発電所", "株式会社", "合同会社", "太陽光", "ソーラー", "メガソーラー",
              "パーク", "ファーム", "・"):
        s = s.replace(w, "")
    return s


def hav_m(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def centroid(geom):
    t = geom.get("type")
    c = geom.get("coordinates")
    if t == "Point":
        return (c[1], c[0])
    pts = []

    def walk(x):
        if isinstance(x, list) and x and isinstance(x[0], (int, float)):
            pts.append(x)
        elif isinstance(x, list):
            for y in x:
                walk(y)
    walk(c)
    if not pts:
        return None
    return (sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts))


def main():
    gem_path, repo, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
    gem = [json.loads(l) for l in open(gem_path, encoding="utf-8")]
    gem = [g for g in gem if g.get("lat") is not None]
    print(f"GEM pages with coords: {len(gem)}")

    plants = []
    for reg in ("kyushu", "okinawa"):
        d = json.load(open(f"{repo}/data/{reg}_plants.geojson", encoding="utf-8"))
        for i, f in enumerate(d["features"]):
            p = f.get("properties") or {}
            if p.get("capacity_mw") not in (-1, -1.0):
                continue
            ll = centroid(f.get("geometry") or {})
            if not ll:
                continue
            plants.append({"region": reg, "idx": i, "name": p.get("name") or "",
                           "fuel": p.get("fuel_type") or "unknown",
                           "lat": ll[0], "lon": ll[1],
                           "norm": norm_name(p.get("name"))})
    print(f"placeholder plants: {len(plants)}")

    # 空間グリッドで近傍探索を高速化
    grid = {}
    for j, g in enumerate(gem):
        key = (round(g["lat"], 1), round(g["lon"], 1))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                grid.setdefault((round(key[0] + dy * 0.1, 1),
                                 round(key[1] + dx * 0.1, 1)), []).append(j)

    def cands_for(pl, radius_m):
        key = (round(pl["lat"], 1), round(pl["lon"], 1))
        seen, out = set(), []
        for j in grid.get(key, []):
            if j in seen:
                continue
            seen.add(j)
            g = gem[j]
            d = hav_m((pl["lat"], pl["lon"]), (g["lat"], g["lon"]))
            if d <= radius_m:
                out.append((d, j))
        return sorted(out)

    # GEM側の最良割当を追跡(1ページ1プラント原則)
    auto, ambig, unmatched = [], [], []
    claim = {}   # gem_j -> (dist, plant_key)

    results = []
    for pl in plants:
        allowed = FUEL_TRACKER.get(pl["fuel"], None)
        cands = []
        for d, j in cands_for(pl, 3000):
            g = gem[j]
            fuel_ok = (allowed is None) or (g["category"] in allowed)
            name_eq = bool(pl["norm"]) and (
                pl["norm"] == norm_name(g.get("ja_name")) or
                (norm_name(g.get("ja_name")) and pl["norm"] in norm_name(g.get("ja_name"))) or
                (norm_name(g.get("ja_name")) and norm_name(g.get("ja_name")) in pl["norm"]))
            cands.append({"j": j, "d": round(d), "fuel_ok": fuel_ok,
                          "name_eq": name_eq, "title": g["title"],
                          "ja_name": g.get("ja_name"), "category": g["category"]})
        results.append((pl, cands))

    for pl, cands in results:
        ok = [c for c in cands if c["fuel_ok"]]
        strong = [c for c in ok if (c["d"] <= 400) or (c["name_eq"] and c["d"] <= 2500)]
        pl_key = f"{pl['region']}:{pl['idx']}"
        if strong:
            best = min(strong, key=lambda c: (not c["name_eq"], c["d"]))
            second = [c for c in ok if c["j"] != best["j"]]
            near_rival = [c for c in second
                          if c["d"] <= max(800, 2 * best["d"]) and not best["name_eq"]]
            if not near_rival:
                auto.append({"plant": pl, "match": best, "rivals": second[:3]})
                continue
            ambig.append({"plant": pl, "cands": [best] + near_rival[:4]})
        elif ok:
            ambig.append({"plant": pl, "cands": ok[:5]})
        else:
            unmatched.append(pl)

    # GEM側の重複請求(同一ページを複数プラントがAUTO)→曖昧へ降格
    by_gem = {}
    for a in auto:
        by_gem.setdefault(a["match"]["j"], []).append(a)
    auto2, demoted = [], 0
    for j, lst in by_gem.items():
        if len(lst) == 1:
            auto2.append(lst[0])
        else:
            lst.sort(key=lambda a: a["match"]["d"])
            auto2.append(lst[0])       # 最近傍のみ残す
            for a in lst[1:]:
                ambig.append({"plant": a["plant"], "cands": [a["match"]],
                              "note": "gem page claimed by closer plant"})
                demoted += 1

    big_unmatched = [p for p in unmatched if p["fuel"] in MAJOR_FUELS]
    print(f"AUTO={len(auto2)} (demoted {demoted}) AMBIG={len(ambig)} "
          f"UNMATCHED={len(unmatched)} (major {len(big_unmatched)})")

    def dump(path, rows):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    dump(f"{prefix}_auto.jsonl", auto2)
    dump(f"{prefix}_ambig.jsonl", ambig)
    dump(f"{prefix}_unmatched_major.jsonl", big_unmatched)


if __name__ == "__main__":
    main()
