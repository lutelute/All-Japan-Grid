"""Native solve evidence; never infer a zero gap from PuLP's Optimal code."""

import math

import pulp

from src.uc.models import UCResult


def _finite(value):
    value = float(value)
    return value if math.isfinite(value) and abs(value) < 1e19 else None


def capture_solve_metrics(model, solver, result: UCResult) -> None:
    """Capture before any commitment-fixed LP re-solve changes native state."""
    result.effective_solver = solver.name
    native = getattr(model, "solverModel", None)
    if solver.name == "SCIP_PY":
        reason = str(native.getStatus())
        result.has_incumbent = native.getNSols() > 0
        result.dual_bound = _finite(native.getDualbound())
        result.node_count = int(native.getNNodes())
        if result.has_incumbent:
            # PuLP omits some native limit statuses (e.g. solution limit).
            solution = native.getBestSol()
            for variable in model.variables():
                variable.varValue = native.getSolVal(solution, variable.solverVar)
            result.solver_native_gap = _finite(native.getGap())
            result.primal_bound = _finite(native.getObjVal())
        optimal = reason == "optimal"
    elif solver.name == "HiGHS" and native is not None:
        import highspy

        info = native.getInfo()
        reason = native.modelStatusToString(native.getModelStatus())
        result.has_incumbent = (
            info.primal_solution_status == highspy.SolutionStatus.kSolutionStatusFeasible
        )
        is_mip = solver.mip and any(v.isInteger() for v in model.variables())
        optimal = native.getModelStatus() == highspy.HighsModelStatus.kOptimal
        # mip_* fields are not certificates for an LP solve. An optimal LP
        # objective is a lower bound for the original UC MILP.
        result.dual_bound = _finite(info.mip_dual_bound) if is_mip else (
            _finite(info.objective_function_value) if optimal else None)
        result.node_count = int(info.mip_node_count) if is_mip else 0
        if result.has_incumbent:
            result.primal_bound = _finite(info.objective_function_value)
            result.solver_native_gap = _finite(info.mip_gap) if is_mip else None
        if optimal and result.solver_native_gap is not None and result.solver_native_gap > 1e-9:
            reason = "gap_limit"
            optimal = False
    else:
        # CLI adapters do not expose a reliable dual bound. Keep it unknown.
        result.has_incumbent = model.sol_status in (
            pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible,
        )
        reason = "pulp_" + pulp.LpSolution.get(model.sol_status, "unknown")
        optimal = False
        if result.has_incumbent:
            result.primal_bound = _finite(pulp.value(model.objective))

    result.termination_reason = reason
    if result.has_incumbent:
        result.status = "Optimal" if optimal else "Feasible"
    elif "infeasible" in reason.lower() and "unbounded" not in reason.lower():
        result.status = "Infeasible"
    elif reason.lower() == "unbounded":
        result.status = "Unbounded"
    else:
        result.status = "Not Solved"


def finalize_bounds(result: UCResult) -> None:
    """Expose common gaps only for a verified incumbent of this same model."""
    result.gap = result.gap_abs = None
    if not result.feasibility_verified:
        result.primal_bound = None
        return
    if result.primal_bound is None or result.dual_bound is None:
        return
    difference = result.primal_bound - result.dual_bound
    tol = 1e-4 + 1e-9 * max(1.0, abs(result.primal_bound))
    if difference < -tol:
        result.warnings.append("Invalid bounds: dual bound exceeds primal bound")
        result.status = "Invalid Bounds"
        return
    result.gap_abs = max(0.0, difference)
    result.gap = result.gap_abs / max(1.0, abs(result.primal_bound))
