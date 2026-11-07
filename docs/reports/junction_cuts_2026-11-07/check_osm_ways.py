#!/usr/bin/env python3
"""台帳の点を、正典の元の OSM(data/<地域>_lines.geojson と _supplement)の way で確かめる。

点を通る way(点から 5 m 以内に頂点がある)ごとに、電圧タグ・名前・点が way の端か途中か を出す。
「交差・併架」と言えるのは、電圧タグの違う way がどちらもこの点を頂点に持つとき。電圧タグの無い way が
関わるときは、正典の電圧は推し量り(propagate_voltage)で、交差でなく分岐のことがある(#13)。

    PYTHONPATH=. python3 docs/reports/junction_cuts_2026-11-07/check_osm_ways.py
→ docs/reports/junction_cuts_2026-11-07/osm_ways.json
"""
import glob
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

R_M = 5.0


def main():
    led = json.load(open(os.path.join(ROOT, "data", "reference", "junction_misconnects.json"), encoding="utf-8"))
    pts = led["items"]
    feats = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "*_lines*.geojson"))):
        reg = os.path.basename(p).split("_")[0]
        for f in json.load(open(p, encoding="utf-8"))["features"]:
            g = f["geometry"]
            parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
            for cs in parts:
                feats.append((reg, f["properties"], cs))
    out = []
    for it in pts:
        la, lo = it["lat"], it["lon"]
        kx = math.cos(math.radians(la))
        ways = {}
        for reg, pr, cs in feats:
            for i, q in enumerate(cs):
                d = math.hypot(q[1] - la, (q[0] - lo) * kx) * 111195
                if d <= R_M:
                    wid = pr.get("osm_id") or pr.get("id") or pr.get("@id")
                    pos = "end" if i in (0, len(cs) - 1) else "through"
                    ways.setdefault(wid, {"osm_id": wid, "name": pr.get("name"), "voltage": pr.get("voltage"),
                                          "regions": set(), "pos": pos})["regions"].add(reg)
                    break
        ws = [dict(w, regions=sorted(w["regions"])) for w in ways.values()]
        tagged = {str(w["voltage"]) for w in ws if w["voltage"]}
        untagged = [w for w in ws if not w["voltage"]]
        out.append({"no": it["no"], "lat": la, "lon": lo, "ways": ws, "n_voltage_tags": len(tagged),
                    "has_untagged": bool(untagged)})
        print(f"#{it['no']:>2} tags={sorted(tagged)} untagged={[w['name'] for w in untagged]}")
        for w in ws:
            print(f"      {w['pos']:<7} {str(w['voltage']):<14} {str(w['name'])[:30]:<30} {w['osm_id']} {w['regions']}")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "osm_ways.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
