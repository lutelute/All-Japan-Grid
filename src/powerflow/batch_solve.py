"""Batch power-flow solver for the reconstruction pipeline.

``run_powerflow(net, mode)`` is the solver used by ``build_and_solve`` and
the batch scripts: it runs DC or AC power flow and returns a flat summary
**dict** (convergence + loss / loading / voltage stats). The AC path walks
a Newton-Raphson fallback chain tuned so the AC-non-convergent west island
fails fast and falls back to DC instead of stalling for ~minutes on
Gauss-Seidel.

This is distinct from :func:`src.powerflow.powerflow_runner.run_powerflow`,
which returns a structured ``PowerFlowResult`` for the web server — same
name, different contract, different consumer. Promoted here from
``examples/run_powerflow_all`` so the dependency flows src <- scripts
(Phase C pipeline promotion); the example re-exports it for back-compat.
"""

from __future__ import annotations

import pandapower as pp


def run_powerflow(net, mode: str = "dc") -> dict:
    """Run DC or AC power flow; return a summary dict (``converged`` etc.)."""
    result = {"mode": mode, "converged": False}
    try:
        if mode == "dc":
            pp.rundcpp(net)
            result["converged"] = True
        else:
            # Solver fallback chain. The first attempts enforce generator
            # Q-limits (PV->PQ switching at the capability curve) — the
            # physical solution; later fallbacks relax them for
            # convergence, which run_powerflow reports via "solver".
            solvers = [
                {"algorithm": "nr", "init": "dc", "max_iteration": 100, "tolerance_mva": 1e-2,
                 "enforce_q_lims": True},
                {"algorithm": "nr", "init": "flat", "max_iteration": 100, "tolerance_mva": 1e-2,
                 "enforce_q_lims": True},
                {"algorithm": "nr", "init": "dc", "max_iteration": 100, "tolerance_mva": 1e-2},
                {"algorithm": "nr", "init": "dc", "max_iteration": 200, "tolerance_mva": 1e-1},
                {"algorithm": "nr", "init": "dc", "max_iteration": 300, "tolerance_mva": 1.0},
                {"algorithm": "nr", "init": "dc", "max_iteration": 300, "tolerance_mva": 10.0},
                # fdbx/fdxb/gs は除外: west島(AC非収束が確定)で gs 5000反復が
                # ~105分の膠着を招くため。nr系のみで east/hokkaido/okinawa は収束し、
                # west は速やかに非収束判定 -> DC にフォールバックする。
            ]
            last_err = ""
            for solver_opts in solvers:
                try:
                    pp.runpp(net, numba=True, **solver_opts)
                    if net.converged:
                        result["converged"] = True
                        result["solver"] = solver_opts["algorithm"]
                        result["q_lims_enforced"] = bool(
                            solver_opts.get("enforce_q_lims", False))
                        break
                except Exception as e:  # noqa: BLE001
                    last_err = f"{solver_opts['algorithm']}: {str(e)[:60]}"
                    continue
            if not result["converged"]:
                result["error"] = last_err or "all solvers failed to converge"

        if result.get("converged") or mode == "dc":
            if hasattr(net, "res_line") and len(net.res_line) > 0:
                active = net.line["in_service"]
                res = net.res_line.loc[active]
                result["total_loss_mw"] = float(res["pl_mw"].sum()) if "pl_mw" in res.columns else 0.0
                result["max_loading_pct"] = float(res["loading_percent"].max()) if "loading_percent" in res.columns else 0.0
                result["mean_loading_pct"] = float(res["loading_percent"].mean()) if "loading_percent" in res.columns else 0.0
            if hasattr(net, "res_bus"):
                active_bus = net.bus["in_service"]
                res_bus = net.res_bus.loc[active_bus]
                result["vm_pu_mean"] = float(res_bus["vm_pu"].mean())
                result["vm_pu_min"] = float(res_bus["vm_pu"].min())
                result["vm_pu_max"] = float(res_bus["vm_pu"].max())
                result["va_deg_min"] = float(res_bus["va_degree"].min())
                result["va_deg_max"] = float(res_bus["va_degree"].max())
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    return result
