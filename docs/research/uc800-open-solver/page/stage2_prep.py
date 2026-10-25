"""Compact the SCUC stage-2 result for the page: usage stage2_prep.py stage2.json year_summary.json out.json"""
import json, sys

d, y = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
cat = {(isl, r["k"]): r for isl, v in y["islands"].items() for key in ("residual", "congestion", "stuck") for r in v[key]}
after = {(r["island"], r["k"]): r for r in d["over_scuc"] or []}
lines = []
for r in sorted(d["over_uc"], key=lambda r: -r["hours"] * r["max_over_mw"]):
    c, a = cat[(r["island"], r["k"])], after.get((r["island"], r["k"]))
    lines.append({"n": c["name"], "kv": c["kv"], "i": r["island"], "h": r["hours"], "mx": r["max_over_mw"],
                  "ha": a["hours"] if a else 0, "mxa": a["max_over_mw"] if a else 0, "hy": c["hours_over"]})
units = [u for u in d["commitment_changed"] if u["fuel"] not in ("pumped_hydro", "battery")]
units.sort(key=lambda u: -abs(u["on_hours_scuc"] - u["on_hours_uc"]) * u["cap_mw"])
log = [{"p": e["pass"], "it": e["iter"], "cuts": e["cuts"], "new": e["new"], "ov": e["over_mw_sum"], "c": round(e["cost"] / 1e8, 3),
        "gap": e["gap"], "s": e["s"]} for e in d["log"] if e["pass"] in ("A", "B")]
gu, gs = d["log"][0]["gap"], d["gap_scuc"]
out = {"date": d["date"], "cost_uc": round(d["cost_uc"] / 1e8, 2), "cost_scuc": round(d["cost_scuc"] / 1e8, 2),
       "price": round(d["grid_price_yen"]), "price_lo": round(d["cost_scuc"] * (1 - gs) - d["cost_uc"]),
       "price_hi": round(d["cost_scuc"] - d["cost_uc"] * (1 - gu)), "gap_uc": gu, "gap_scuc": gs,
       "over_pairs_all": d["log"][0]["over_pairs"], "over_pairs": d["log"][1]["over_pairs"], "over_mwh": d["log"][1]["over_mw_sum"],
       "excluded": sum(len(v) for v in d["excluded_lines"].values()), "cuts": d["cuts"], "held": len(d["held_after_a"]),
       "build_s": d["network_build_s"], "solve_s": round(sum(e["s"] for e in log), 1), "wall_s": d["wall_s"],
       "changed": len(d["commitment_changed"]), "changed_storage": len(d["commitment_changed"]) - len(units),
       "lines": lines, "units": [{"n": u["name"], "f": u["fuel"], "cap": u["cap_mw"], "a": u["on_hours_uc"], "b": u["on_hours_scuc"]} for u in units[:12]],
       "units_more": sum(1 for u in units if u["on_hours_scuc"] > u["on_hours_uc"]), "units_less": sum(1 for u in units if u["on_hours_scuc"] < u["on_hours_uc"]),
       "log": log}
# other HiGHS seeds of the same day (stage2_<date>_s<n>.json next to the first file): what moves in every seed is the grid's doing
import glob, os
seeds = [{"seed": 0, "price": out["price"], "uc": out["cost_uc"], "scuc": out["cost_scuc"], "changed": out["changed"]}]
runs = []
for f in sorted(glob.glob(os.path.join(os.path.dirname(sys.argv[1]), f"stage2_{d['date'].replace('-', '')}_s*.json"))):
    e = json.load(open(f))
    seeds.append({"seed": e["seed"], "price": round(e["grid_price_yen"]), "uc": round(e["cost_uc"] / 1e8, 2),
                  "scuc": round(e["cost_scuc"] / 1e8, 2), "changed": len(e["commitment_changed"])})
    runs.append(e)
out["seeds"] = seeds
if runs:
    info = {c["id"]: c for e in runs + [d] for c in e["commitment_changed"]}
    keep = []
    for g in set().union(*[set(e["on_hours_uc"]) for e in runs]):
        uc = [e["on_hours_uc"].get(g, 0) for e in runs]; sc = [e["on_hours_scuc"].get(g, 0) for e in runs]
        if max(sc) < min(uc) or min(sc) > max(uc):
            c = info[g]
            keep.append({"n": c["name"], "f": c["fuel"], "cap": c["cap_mw"], "uc": uc, "sc": sc})
    keep.sort(key=lambda k: -abs(sum(k["sc"]) - sum(k["uc"])) * k["cap"])
    out["consistent"] = keep
    out["noise_uc"] = [len({g for g in set(a["on_hours_uc"]) | set(b["on_hours_uc"]) if a["on_hours_uc"].get(g, 0) != b["on_hours_uc"].get(g, 0)})
                       for i, a in enumerate(runs) for b in runs[i + 1:]]
# routes of the lines (canonical built model, by end points) and positions of the plants (the Japan map's plant list, by name)
if len(sys.argv) > 4:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from net_prep import d_of, path_of, proj, simplify
    route = {}
    for e in json.load(open(sys.argv[4]))["edges"]:
        a = json.loads(e["a"]) if isinstance(e["a"], str) else e["a"]; b = json.loads(e["b"]) if isinstance(e["b"], str) else e["b"]
        if a and b and a[0] is not None and b[0] is not None:
            key = (round(a[0], 4), round(a[1], 4), round(b[0], 4), round(b[1], 4))
            d_ = d_of(simplify(path_of(e), 0.3)); route.setdefault(key, d_); route.setdefault((key[2], key[3], key[0], key[1]), d_)
    for l, r in zip(out["lines"], sorted(d["over_uc"], key=lambda r: -r["hours"] * r["max_over_mw"])):
        c = cat[(r["island"], r["k"])]
        l["g"] = route.get((round(c["a"][0], 4), round(c["a"][1], 4), round(c["b"][0], 4), round(c["b"][1], 4)))
        if not l["g"]:
            (x1, y1), (x2, y2) = proj(*c["a"]), proj(*c["b"]); l["g"] = f"M{x1:.1f},{y1:.1f}L{x2:.1f},{y2:.1f}"
    geo = json.load(open(os.path.join(os.path.dirname(sys.argv[3]) or ".", "geo_compact.json")))
    where = {pl["n"]: (pl["x"], pl["y"]) for pl in geo["plants"] if pl.get("x") is not None}
    for u in out.get("consistent", []):
        if u["n"] in where:
            u["xy"] = where[u["n"]]
json.dump(out, open(sys.argv[3], "w"), ensure_ascii=False, separators=(",", ":"))
print({k: v for k, v in out.items() if k not in ("lines", "units", "log")})
for u in out["units"]: print(u)
