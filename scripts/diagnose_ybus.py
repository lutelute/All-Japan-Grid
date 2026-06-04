#!/usr/bin/env python3
"""Diagnose Ybus conditioning per region — reveal why AC power flow struggles.

For each region it builds the snapped network, forms the bus admittance matrix
(Ybus) and reports:
  * condition number and eigenvalue spread (numerical ill-conditioning)
  * diagonal dominance (how many rows are not diagonally dominant)
  * the |Ydiag| spread and the weakest buses (giant/zero self-admittances that
    come from extremely short lines or isolated buses)

This is how the kansai non-convergence was root-caused: a huge |Ydiag| spread
(6.9e20) from ~5 m vertex-snap lines, on top of a genuine capacity shortfall.

Requires pandapower — run on the compute server:
    python scripts/diagnose_ybus.py --regions kansai tokyo okinawa
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np  # noqa: E402
import pandapower as pp  # noqa: E402
from pandapower.pypower.makeYbus import makeYbus  # noqa: E402

from scripts.export_powerflow_pages import build_and_solve  # noqa: E402
from src.powerflow.load_estimator import load_demand_config  # noqa: E402


def diagnose(region: str, cfg) -> dict:
    """Build the region, form Ybus and return its conditioning metrics."""
    res = build_and_solve(region, cfg, topology="snapped", reconnect=True)
    net = [x for x in res if isinstance(x, pp.auxiliary.pandapowerNet)][-1]
    pp.rundcpp(net)  # DC always populates net._ppc
    ppc = net._ppc
    ybus, _, _ = makeYbus(ppc["baseMVA"], ppc["bus"], ppc["branch"])
    n = ybus.shape[0]

    ydiag = np.abs(ybus.diagonal())
    absy = np.abs(ybus)
    offdiag = np.asarray(absy.sum(axis=1)).ravel() - ydiag
    nondom = int(np.sum(ydiag < offdiag - 1e-9))

    full = ybus.toarray()
    cond = float(np.linalg.cond(full))
    eig = np.sort(np.abs(np.linalg.eigvals(full)))
    weak = np.argsort(ydiag)[:5]
    return {
        "region": region,
        "n": n,
        "nnz": int(ybus.nnz),
        "non_dominant_rows": nondom,
        "ydiag_min": float(ydiag.min()),
        "ydiag_max": float(ydiag.max()),
        "ydiag_ratio": float(ydiag.max() / max(ydiag.min(), 1e-12)),
        "cond": cond,
        "eig_min": float(eig[0]),
        "eig_max": float(eig[-1]),
        "weakest_ydiag": [float(ydiag[i]) for i in weak],
    }


def main() -> int:
    """Diagnose Ybus conditioning for the requested regions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regions", nargs="*", default=["kansai", "tokyo", "okinawa"])
    args = parser.parse_args()
    cfg = load_demand_config()
    for region in args.regions:
        d = diagnose(region, cfg)
        print(f"{d['region']}: n={d['n']} nnz={d['nnz']} "
              f"non-dominant_rows={d['non_dominant_rows']}/{d['n']}")
        print(f"  |Ydiag| [{d['ydiag_min']:.2e}, {d['ydiag_max']:.2e}] "
              f"ratio={d['ydiag_ratio']:.1e}")
        print(f"  cond={d['cond']:.2e} eig_min={d['eig_min']:.2e} "
              f"eig_max={d['eig_max']:.2e}")
        print(f"  weakest |Ydiag|: {[f'{v:.2e}' for v in d['weakest_ydiag']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
