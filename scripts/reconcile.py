"""OCCTO-actuals reconciliation report (PLAN_66KV M10-3).

    ajgrid reconcile                       # config/demand vs OCCTO actuals
    ajgrid reconcile --uc-csv results.csv  # external UC output cross-check
    ajgrid reconcile --json out.json

Compares, against the calibrated DB (``measured_area_stats``, written
by ``scripts/db/calibrate.py --occto``):

- each region's configured peak demand vs the OCCTO-measured area
  demand (q50/p95) — the honesty check on the demand scaling the whole
  pipeline rests on;
- the boundary utilisations in effect (DB-derived, hardcode fallback);
- optionally an EXTERNAL time-series CSV (the separately developed UC
  drops its results in): columns ``area,metric,value_mw`` — each row is
  judged against the measured band (q50..p95), the agreed intake
  contract from docs/UC_HANDOFF.md.

Verdicts are bands, not pass/fail theatre: ``<q50`` / ``q50..p95`` /
``>p95`` with ratios printed, because a single snapshot legitimately
sits anywhere in the annual distribution.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AREA_OF_REGION = {
    "hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京",
    "chubu": "中部", "hokuriku": "北陸", "kansai": "関西",
    "chugoku": "中国", "shikoku": "四国", "kyushu": "九州",
    "okinawa": "沖縄",
}


def _band(value, q50, p95):
    if value < q50:
        return "<q50"
    if value <= p95:
        return "q50..p95"
    return ">p95"


_MODEL_FUEL = {"gas": "gas", "lng": "gas", "coal": "coal", "oil": "oil",
               "hydro": "hydro", "nuclear": "nuclear", "solar": "solar",
               "wind": "wind", "geothermal": "geothermal",
               "biomass": "biomass", "pumped": "pumped"}


def dispatch_by_fuel(region: str) -> dict:
    """Solve the region's full model and aggregate dispatch by fuel."""
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pipeline import build_and_solve

    res = build_and_solve(region, load_demand_config(), topology="snapped",
                          reconnect=True, backbone_kv=0.0)
    net = res[0]
    out: dict = {}
    g = net.gen[net.gen["in_service"]]
    for t, grp in g.groupby(g["type"].fillna("unknown").str.split(";").str[0]):
        fuel = _MODEL_FUEL.get(str(t).lower())
        if fuel:
            out[fuel] = out.get(fuel, 0.0) + float(grp["p_mw"].sum())
    # boundary injections approximate the interconnector draw
    sg = net.sgen[net.sgen["in_service"]] if len(net.sgen) else None
    if sg is not None:
        b = sg[sg["name"].astype(str).str.startswith("boundary_")]
        if len(b):
            out["interconnect"] = float(b["p_mw"].sum())
    return out


def reconcile(db_path: str = "data/grid.db", uc_csv: str | None = None,
              solve_region: str | None = None) -> dict:
    from src.db.calibration import load_measured_area_stats
    from src.powerflow.boundary import (
        MEASURED_UTILISATION,
        measured_utilisation_from_db,
    )
    from src.powerflow.load_estimator import load_demand_config

    out: dict = {"db": db_path}
    demand_stats = load_measured_area_stats(db_path, metric="demand_mw")
    cfg = load_demand_config()
    peaks = cfg["regional_peak_demand_mw"]
    lf = float(cfg.get("load_factor", 0.85))

    rows = []
    if demand_stats:
        for region, area in AREA_OF_REGION.items():
            s = demand_stats.get(area)
            peak = peaks.get(region)
            if not s or not peak:
                continue
            snap = peak * lf
            rows.append({
                "region": region, "area": area,
                "config_peak_mw": peak, "config_snapshot_mw": round(snap, 0),
                "occto_q50_mw": round(s["q50"], 0),
                "occto_p95_mw": round(s["p95"], 0),
                "snapshot_over_p95": round(snap / s["p95"], 2),
                "band": _band(snap, s["q50"], s["p95"]),
            })
    out["demand"] = rows
    out["demand_note"] = ("config snapshot = peak x load_factor; OCCTO "
                          "window is API-retention (~14 months), so a "
                          "snapshot above p95 means the config peak is a "
                          "design peak, not last year's")

    db_util = measured_utilisation_from_db(db_path)
    out["boundary_utilisation"] = {
        "source": "db" if db_util else "hardcoded_fallback",
        "values": db_util or dict(MEASURED_UTILISATION),
    }

    if solve_region:
        area = AREA_OF_REGION.get(solve_region, solve_region)
        fuels = load_measured_area_stats(db_path) or {}
        disp = dispatch_by_fuel(solve_region)
        checks = []
        for fuel, mw in sorted(disp.items(), key=lambda kv: -kv[1]):
            s = fuels.get((area, f"gen_by_fuel:{fuel}"))
            if not s:
                checks.append({"fuel": fuel, "model_mw": round(mw, 0),
                               "verdict": "no_reference"})
                continue
            checks.append({"fuel": fuel, "model_mw": round(mw, 0),
                           "meas_q50_mw": round(s["q50"], 0),
                           "meas_p95_mw": round(s["p95"], 0),
                           "verdict": _band(mw, s["q50"], s["p95"])})
        # 合算火力しか公表しない社（関西・中国の nas03 在庫等）: モデルの
        # gas+coal+oil 合計を thermal_combined 帯に通す
        s = fuels.get((area, "gen_by_fuel:thermal_combined"))
        if s and not fuels.get((area, "gen_by_fuel:gas")):
            mw = sum(disp.get(f, 0.0) for f in ("gas", "coal", "oil"))
            checks.append({"fuel": "thermal(gas+coal+oil)",
                           "model_mw": round(mw, 0),
                           "meas_q50_mw": round(s["q50"], 0),
                           "meas_p95_mw": round(s["p95"], 0),
                           "verdict": _band(mw, s["q50"], s["p95"])})
        out["dispatch_checks"] = {"region": solve_region, "rows": checks,
                                  "note": ("model = one synthetic snapshot at "
                                           "peak x LF vs measured annual "
                                           "q50..p95 band — judge ordering "
                                           "and band, not exact MW")}

    if uc_csv:
        import csv as _csv

        all_stats = load_measured_area_stats(db_path) or {}
        checks = []
        with open(uc_csv, encoding="utf-8-sig", newline="") as f:
            for r in _csv.DictReader(f):
                area = (r.get("area") or "").strip()
                metric = (r.get("metric") or "demand_mw").strip()
                try:
                    val = float(r.get("value_mw", ""))
                except ValueError:
                    continue
                s = all_stats.get((area, metric))
                if not s:
                    checks.append({"area": area, "metric": metric,
                                   "value_mw": val, "verdict": "no_reference"})
                    continue
                checks.append({
                    "area": area, "metric": metric, "value_mw": val,
                    "occto_q50_mw": round(s["q50"], 0),
                    "occto_p95_mw": round(s["p95"], 0),
                    "ratio_to_q50": round(val / max(s["q50"], 1e-9), 2),
                    "verdict": _band(val, s["q50"], s["p95"]),
                })
        out["uc_checks"] = checks
    return out


def render(m: dict) -> str:
    lines = ["OCCTO reconciliation (measured_area_stats vs model config)"]
    if not m["demand"]:
        lines.append("  no demand stats in DB — run scripts/db/calibrate.py "
                     "--occto first")
    else:
        lines.append(f"  {'region':9} {'snapshot':>9} {'occto_q50':>10} "
                     f"{'occto_p95':>10} {'snap/p95':>9}  band")
        for r in m["demand"]:
            lines.append(
                f"  {r['region']:9} {r['config_snapshot_mw']:>9,.0f} "
                f"{r['occto_q50_mw']:>10,.0f} {r['occto_p95_mw']:>10,.0f} "
                f"{r['snapshot_over_p95']:>9} {r['band']:>9}")
    bu = m["boundary_utilisation"]
    vals = "  ".join(f"{k}={v:+.2f}" for k, v in sorted(bu["values"].items()))
    lines.append(f"  boundary util [{bu['source']}]: {vals}")
    dc = m.get("dispatch_checks")
    if dc:
        lines.append(f"  fuel dispatch ({dc['region']} model vs measured band):")
        for r in dc["rows"]:
            ref = (f" (q50 {r['meas_q50_mw']:,.0f} / p95 {r['meas_p95_mw']:,.0f})"
                   if "meas_q50_mw" in r else "")
            lines.append(f"    {r['fuel']:12} {r['model_mw']:>8,.0f} MW "
                         f"-> {r['verdict']}{ref}")
    for c in m.get("uc_checks", []):
        lines.append(f"  UC {c['area']}/{c['metric']}: {c['value_mw']:,.0f} MW "
                     f"-> {c['verdict']}"
                     + (f" (q50 {c['occto_q50_mw']:,.0f} / p95 "
                        f"{c['occto_p95_mw']:,.0f})"
                        if "occto_q50_mw" in c else ""))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/grid.db")
    ap.add_argument("--uc-csv", help="external UC results: area,metric,value_mw")
    ap.add_argument("--solve-region",
                    help="solve this region and band-check its per-fuel "
                         "dispatch against gen_by_fuel:* actuals (F4)")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    m = reconcile(args.db, uc_csv=args.uc_csv,
                  solve_region=args.solve_region)
    print(render(m))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1, ensure_ascii=False)
        print(f"report -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
