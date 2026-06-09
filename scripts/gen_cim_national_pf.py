#!/usr/bin/env python3
"""Generate the national power-flow map (fig_cim_national_pf.png).

Every region is built and AC-solved; each bus is plotted at its WGS84
location coloured by its solved voltage magnitude (pu). The west 60 Hz
regions (notably kansai) do not AC-converge natively because of the
synthetic sub-154 kV network (see docs/WEST_AC_ANALYSIS.md), so this tool
falls back to a documented demand-scale ladder until the region solves —
the same device the CIM Level-2 export uses — and annotates which regions
were scaled, instead of leaving them blank/grey on the map.

    PYTHONPATH=. python3 scripts/gen_cim_national_pf.py
    PYTHONPATH=. python3 scripts/gen_cim_national_pf.py --out docs/assets/figs/fig_cim_national_pf.png

Honest by construction: a scaled region's voltages are a solvability
expedient on synthetic parameters, not an operational result — the caption
says so. Trends, not absolute values (docs/COVERAGE.md, VISION §2).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.powerflow.load_estimator import load_demand_config  # noqa: E402
from src.powerflow.pipeline import build_and_solve  # noqa: E402
from src.regions import REGIONS  # noqa: E402

#: try native (1.0) first, then scale a stubborn region's peak demand down
#: until AC converges. Lower demand → higher voltages → solvable.
DEMAND_LADDER = (1.0, 0.6, 0.4, 0.3, 0.2, 0.1)


def _scaled_cfg(cfg, region, factor):
    if factor == 1.0:
        return cfg
    c = copy.deepcopy(cfg)
    c["regional_peak_demand_mw"] = dict(c["regional_peak_demand_mw"])
    c["regional_peak_demand_mw"][region] *= factor
    return c


def solve_region(region, cfg):
    """Return (lons, lats, vm_pu, factor) for a region, scaling demand if needed."""
    for factor in DEMAND_LADDER:
        res = build_and_solve(region, _scaled_cfg(cfg, region, factor),
                              topology="snapped", reconnect=True)
        if res is None:
            return None
        net, ac = res[2], res[3]
        if not ac["converged"]:
            continue
        lons, lats, vms = [], [], []
        vm = net.res_bus["vm_pu"]
        for idx, geo in net.bus["geo"].items():
            if not isinstance(geo, str) or idx not in vm.index:
                continue
            v = vm.at[idx]
            if v != v:  # NaN
                continue
            try:
                lon, lat = json.loads(geo)["coordinates"][:2]
            except Exception:  # noqa: BLE001
                continue
            lons.append(lon); lats.append(lat); vms.append(v)
        return lons, lats, vms, factor
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="docs/assets/figs/fig_cim_national_pf.png")
    ap.add_argument("--vmin", type=float, default=0.85)
    ap.add_argument("--vmax", type=float, default=1.05)
    args = ap.parse_args(argv)

    cfg = load_demand_config()
    all_lon, all_lat, all_vm = [], [], []
    scaled, failed, n_solved = [], [], 0
    for r in REGIONS:
        out = solve_region(r, cfg)
        if out is None:
            failed.append(r)
            print(f"  {r:10s} FAILED to converge at any demand scale")
            continue
        lons, lats, vms, factor = out
        all_lon += lons; all_lat += lats; all_vm += vms
        n_solved += 1
        tag = "" if factor == 1.0 else f"  (demand x{factor:g})"
        if factor != 1.0:
            scaled.append(f"{r} x{factor:g}")
        print(f"  {r:10s} OK  {len(vms):5d} buses  vmin={min(vms):.3f}{tag}")

    fig, ax = plt.subplots(figsize=(8, 9))
    sc = ax.scatter(all_lon, all_lat, c=all_vm, cmap="RdYlGn",
                    vmin=args.vmin, vmax=args.vmax, s=4, linewidths=0)
    cb = fig.colorbar(sc, ax=ax, shrink=0.6, label="bus voltage [pu]")
    cb.ax.tick_params(labelsize=8)
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    ax.set_aspect(1.18)
    title = (f"All-Japan-Grid — national AC power-flow  "
             f"({len(all_vm):,} buses, {n_solved}/{len(REGIONS)} regions solved)")
    sub = "OSM topology → snapped → pandapower runpp"
    if scaled:
        sub += f"\ndemand-scaled for solvability (synthetic params): {', '.join(scaled)}"
    if failed:
        sub += f"  |  not converged: {', '.join(failed)}"
    ax.set_title(title + "\n" + sub, fontsize=8)
    fig.tight_layout()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=150, bbox_inches="tight")
    print(f"-> {args.out}  ({len(all_vm):,} buses, scaled: {scaled or 'none'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
