"""Compact the year summary for the page: lines projected like the Japan map, daily series.

Usage: year_prep.py year_summary.json out.json [suspects.json]
"""
import json
import math
import sys
from pathlib import Path

summary = json.loads(Path(sys.argv[1]).read_text())
out_path = Path(sys.argv[2])
suspects = json.loads(Path(sys.argv[3]).read_text()) if len(sys.argv) > 3 else None
LON0, LAT1, K = 128.4, 45.65, 70.7
CX = math.cos(math.radians(37.5))
OKI = (15.6, 6.4)
REASON = {"named_unbuilt": "u", "disclosure_backbone": "d", "plant_connection": "p", "other": "o"}
# real routes from the canonical built model, matched by the two end points (optional 4th argument: built/all.json)
ROUTE = {}
if len(sys.argv) > 4:
    sys.path.insert(0, str(Path(__file__).parent))
    from net_prep import d_of, path_of, simplify
    for e in json.loads(Path(sys.argv[4]).read_text())["edges"]:
        a = json.loads(e["a"]) if isinstance(e["a"], str) else e["a"]
        b = json.loads(e["b"]) if isinstance(e["b"], str) else e["b"]
        if not a or not b or a[0] is None or b[0] is None:
            continue
        key = (round(a[0], 4), round(a[1], 4), round(b[0], 4), round(b[1], 4))
        d = d_of(simplify(path_of(e), 0.4))
        ROUTE.setdefault(key, d)
        ROUTE.setdefault((key[2], key[3], key[0], key[1]), d)


def proj(lat, lon):
    if lat < 27.5:
        lon, lat = lon + OKI[0], lat + OKI[1]
    return [round((lon - LON0) * CX * K, 1), round((LAT1 - lat) * K, 1)]


why = {}
plants = {}
if suspects:
    for isl, v in suspects["islands"].items():
        for r in v["lines"]:
            p = r["plants_near"][0] if r["plants_near"] else None
            why[(isl, r["k"])] = (REASON[r["reason"]], p and f"{p['name']} {p['cap_mw']:,.0f} MW（{p['attach_kv']:.0f}kV）")
        plants[isl] = [{"n": p["name"], "cap": p["cap_mw"], "kv": p["attach_kv"], "l": p["lines"], "h": p["hours"],
                        "mx": round(p["max_mw"])} for p in v["plants"][:8]]

lines = []
for isl, v in summary["islands"].items():
    seen = set()
    # data-suspect layer: lines over before redispatch and still over after it in the same hour
    stuck = v.get("stuck")
    if stuck is None:
        stuck = [r for r in v["residual"] if r["hours_over"] > 0]
    for kind, rows in (("residual", stuck), ("congestion", v["congestion"])):
        for r in rows:
            if not r["a"] or not r["b"] or r["a"][0] is None or r["b"][0] is None:
                continue
            key = (isl, r["k"], kind)
            if key in seen:
                continue
            seen.add(key)
            row = {"i": isl, "k": kind, "n": r["name"][:40], "kv": r["kv"], "p": proj(*r["a"]) + proj(*r["b"]),
                   "h": r["hours_over"], "hr": r["hours_residual"], "hs": r.get("hours_stuck", r["hours_residual"]),
                   "v": r["value_yen_per_mw_year"], "hb": r.get("hours_binding", 0), "dr": r["days_residual"],
                   "m": r["month_hours"]}
            g = ROUTE.get((round(r["a"][0], 4), round(r["a"][1], 4), round(r["b"][0], 4), round(r["b"][1], 4)))
            if g:
                row["g"] = g
            if kind == "residual" and (isl, r["k"]) in why:
                row["rs"], row["pl"] = why[(isl, r["k"])]
            lines.append(row)
daily = []
for d in summary["daily"]:
    isl = {k: d.get(k) or {} for k in ("hokkaido", "east", "west", "okinawa")}
    daily.append({"d": d["date"], "c": round((d["cost"] or 0) / 1e8, 2), "pk": round((d["peak_mw"] or 0) / 1000, 1),
                  "n1": round((d.get("n1_shortfall_mwh") or 0) / 1000, 2), "tie": d.get("tie_hours_at_limit") or 0,
                  "ra": round(sum((v.get("over_after_mw") or 0) for v in isl.values()) / 1000, 1),
                  "rb": round(sum((v.get("over_before_mw") or 0) for v in isl.values()) / 1000, 1),
                  "rd": round(sum((v.get("redispatch_yen") or 0) for v in isl.values()) / 1e8, 3),
                  "ok": bool(d.get("verified"))})
stats = {isl: {k: v.get(k) for k in ("monitored", "lines_ever_over", "lines_residual", "lines_stuck")}
         for isl, v in summary["islands"].items()}
out = {"days": summary["days"], "method": summary.get("method", "penalty"), "lines": lines, "daily": daily,
       "stats": stats, "plants": plants, "lp_failed": summary.get("lp_failed_hours"), "probe_failed": summary.get("probe_failed")}
out_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
print(sum(1 for l in lines if "g" in l), "with routes,", len(lines), "lines", len(daily), "days", len(out_path.read_text()) // 1024, "KB")
