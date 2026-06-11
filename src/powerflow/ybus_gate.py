"""Ybus conditioning gate — shipping-quality check for downstream solvers.

    PYTHONPATH=. python -m src.powerflow.ybus_gate tokyo [--threshold 1e8]

Unit commitment is developed in a separate project; THIS project's
responsibility is handing over a network whose admittance matrix a
solver can actually factorize. The west-island campaign proved the
failure mode is real and silent: chains of high-ratio sub-transmission
transformers made the AC Jacobian near-singular while everything
LOOKED connected (docs/WEST_AC_ANALYSIS.md). This gate makes that
lesson a permanent instrument.

Per electrical island the AC Ybus is built from the solved model's
branch parameters, the island's reference row/column is removed (what
a Newton solver actually factorizes), and the 1-norm condition number
is estimated (onenormest x LU-solve operator — no dense inversion).
Islands above the threshold are named, with the honest verdict in
``pass``: downstream optimization on a failing island is numerically
meaningless even if a solver emits numbers.
"""

from __future__ import annotations

import argparse
import sys

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# Calibrated against the 10 single-region full models, all of which
# converge AC (known-good): cond_1norm spans 5.6e5 (okinawa) to 1.22e8
# (chubu), so the gate sits one decade above the worst known-good. The
# known-bad anchor (the merged west island whose chained high-ratio
# sub-transmission transformers defeated AC NR — WEST_AC_ANALYSIS) is
# expected far above this; measuring it on the next west build is the
# recorded follow-up.
DEFAULT_THRESHOLD = 1e9


def ybus_gate(net, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Per-island reduced-Ybus condition estimate on a built pp net."""
    import networkx as nx
    import numpy as np
    import scipy.sparse as sp
    from scipy.sparse.linalg import LinearOperator, onenormest, splu

    vn = net.bus["vn_kv"]
    base_mva = float(net.sn_mva or 100.0)

    # branch admittances (series only + line charging; the gate cares
    # about factorization, not exact shunt bookkeeping)
    edges = []   # (a, b, y_series complex, b_charge_half)
    for idx in net.line.index:
        if not bool(net.line.at[idx, "in_service"]):
            continue
        fb, tb = int(net.line.at[idx, "from_bus"]), int(net.line.at[idx, "to_bus"])
        par = max(int(net.line.at[idx, "parallel"] or 1), 1)
        length = float(net.line.at[idx, "length_km"])
        vkv = float(vn.get(fb, 0)) or 1.0
        zb = vkv * vkv / base_mva
        r = float(net.line.at[idx, "r_ohm_per_km"]) * length / par / zb
        x = float(net.line.at[idx, "x_ohm_per_km"]) * length / par / zb
        z = complex(r, x) if (r or x) else complex(0, 1e-6)
        c_nf = float(net.line.at[idx, "c_nf_per_km"]) * length * par
        b_ch = 2 * np.pi * float(net.f_hz) * c_nf * 1e-9 * zb
        edges.append((fb, tb, 1.0 / z, b_ch / 2.0))
    for t in net.trafo.itertuples():
        if not t.in_service:
            continue
        zk = max(float(t.vk_percent), 0.01) / 100.0 * base_mva / float(t.sn_mva)
        rk = float(t.vkr_percent) / 100.0 * base_mva / float(t.sn_mva)
        xk = max(zk * zk - rk * rk, 1e-12) ** 0.5
        edges.append((int(t.hv_bus), int(t.lv_bus), 1.0 / complex(rk, xk), 0.0))

    G = nx.Graph((a, b) for a, b, _y, _c in edges)
    refs = {int(e.bus) for e in net.ext_grid.itertuples() if e.in_service}

    islands = []
    for comp in nx.connected_components(G):
        if len(comp) < 2:
            continue
        nodes = sorted(comp)
        col = {b: i for i, b in enumerate(nodes)}
        n = len(nodes)
        Y = sp.lil_matrix((n, n), dtype=complex)
        for a, b, y, bc in edges:
            if a not in col or b not in col:
                continue
            ia, ib = col[a], col[b]
            Y[ia, ia] += y + 1j * bc
            Y[ib, ib] += y + 1j * bc
            Y[ia, ib] -= y
            Y[ib, ia] -= y
        ref = next((b for b in nodes if b in refs), nodes[0])
        keep = [i for b, i in col.items() if b != ref]
        Yr = Y.tocsr()[keep][:, keep].tocsc()
        try:
            lu = splu(Yr)
            inv_op = LinearOperator(Yr.shape, matvec=lu.solve,
                                    rmatvec=lambda v: lu.solve(v, trans="H"),
                                    dtype=complex)
            cond = float(onenormest(Yr) * onenormest(inv_op))
            singular = False
        except RuntimeError:
            cond, singular = float("inf"), True
        islands.append({
            "n_buses": n, "ref_bus": int(ref),
            "ref_name": str(net.bus.at[ref, "name"] or ref)[:40],
            "has_ext_grid": ref in refs,
            "cond_1norm_est": cond if cond == cond else float("inf"),
            "singular": singular,
            "pass": (not singular) and cond < threshold,
        })

    islands.sort(key=lambda d: -d["n_buses"])
    out = {
        "threshold": threshold,
        "n_islands": len(islands),
        "cond_max": max((i["cond_1norm_est"] for i in islands),
                        default=0.0),
        "pass": all(i["pass"] for i in islands),
        "failing": [i for i in islands if not i["pass"]],
        "islands": islands[:10],
    }
    logger.info("ybus gate: pass=%s cond_max=%.2e islands=%d",
                out["pass"], out["cond_max"], out["n_islands"])
    return out


def gate_region(region: str, threshold: float = DEFAULT_THRESHOLD,
                backbone_kv: float | None = None) -> dict:
    """Build-and-gate convenience used by the CLI and the sweep."""
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pipeline import build_and_solve

    res = build_and_solve(region, load_demand_config(), topology="snapped",
                          reconnect=True, backbone_kv=backbone_kv)
    if res is None:
        return {"error": f"no network for {region}"}
    net_dc = res[0]
    out = ybus_gate(net_dc, threshold=threshold)
    out["region"] = region
    return out


def render(g: dict) -> str:
    rows = [f"{g.get('region', '?')}: Ybus gate "
            f"{'PASS' if g['pass'] else '** FAIL **'} "
            f"(islands {g['n_islands']}, cond_max {g['cond_max']:.2e}, "
            f"threshold {g['threshold']:.0e})"]
    for i in g["islands"][:6]:
        rows.append(
            f"  island n={i['n_buses']:>5} ref={i['ref_name']:<20} "
            f"cond={i['cond_1norm_est']:.2e} "
            f"{'ok' if i['pass'] else 'FAIL'}")
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("regions", nargs="*", default=["tokyo"])
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--backbone", nargs="?", const=154.0, type=float,
                    default=None)
    args = ap.parse_args(argv)
    rc = 0
    for region in args.regions:
        g = gate_region(region, threshold=args.threshold,
                        backbone_kv=args.backbone)
        if "error" in g:
            print(g["error"])
            rc = 2
            continue
        print(render(g))
        if not g["pass"]:
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
