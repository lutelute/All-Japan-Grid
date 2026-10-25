"""Sort the overloaded lines of a SCUC evaluation into "next to a big plant" and "elsewhere".

A 154 kV line loaded to several hundred percent right next to a multi-GW plant usually means
the plant is attached to too low a voltage in the model (the known root cause of overloads in
All-Japan-Grid), not real congestion. Lines with an end within --km of a UC generator of at
least --big-mw are listed under that plant; the rest are the congestion candidates.

    python -m scripts.scuc_overload_triage --eval scuc_eval_ref.json --out triage.json
"""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

from src.uc.scenario import build_national_scenario


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval", type=Path, required=True)
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--big-mw", type=float, default=1000)
    ap.add_argument("--km", type=float, default=15)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    ev = json.loads(args.eval.read_text())
    feats = {}
    big = []
    for g in build_national_scenario(scenario=args.scenario).generators:
        if g.capacity_mw < args.big_mw:
            continue
        if "_g" not in g.id or not g.id.rsplit("_g", 1)[1].isdigit():
            continue                       # not a plant feature (no point to place)
        r, i = g.id.rsplit("_g", 1)
        if r not in feats:
            feats[r] = json.loads(Path(f"data/{r}_plants.geojson").read_text())["features"]
        geo = feats[r][int(i)].get("geometry") or {}
        if geo.get("type") == "Point":
            lon, lat = geo["coordinates"][:2]
            big.append({"id": g.id, "name": g.name, "fuel": g.fuel_type, "mw": g.capacity_mw, "at": (lat, lon)})
    out = {"eval": str(args.eval), "big_mw": args.big_mw, "km": args.km, "islands": []}
    for isl in ev["islands"]:
        near, elsewhere, by_plant = [], [], defaultdict(list)
        for line in isl["overloaded_lines"]:
            ends = [tuple(p) for p in (line["a"], line["b"]) if p and p[0] is not None]
            best = min(((km(e, p["at"]), p) for e in ends for p in big), default=(math.inf, None), key=lambda x: x[0])
            row = {k: line[k] for k in ("name", "kv", "class", "hours_over", "max_loading")}
            if best[1] is not None and best[0] <= args.km:
                row.update(plant=best[1]["name"], plant_mw=best[1]["mw"], km=round(best[0], 1))
                near.append(row)
                by_plant[best[1]["name"]].append(row)
            else:
                elsewhere.append(row)
        plants = sorted(({"plant": n, "mw": rows[0]["plant_mw"], "lines": len(rows), "worst": max(r["max_loading"] for r in rows)}
                         for n, rows in by_plant.items()), key=lambda x: -x["worst"])
        out["islands"].append({"island": isl["island"], "near_big_plant": len(near), "elsewhere": len(elsewhere),
                               "plants": plants, "near": near, "elsewhere_lines": elsewhere})
        print(isl["island"], "near", len(near), "elsewhere", len(elsewhere),
              "| worst plants:", "; ".join(f"{p['plant']} {p['mw']:.0f}MW→{p['worst']:.0f}%({p['lines']})" for p in plants[:5]))
        for r in sorted(elsewhere, key=lambda r: -r["max_loading"])[:5]:
            print("    elsewhere:", r["name"][:36], r["kv"], r["class"], r["hours_over"], "h", r["max_loading"], "%")
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
