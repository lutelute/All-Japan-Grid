"""Probe: LP relaxation of the synthetic 800x48h UC by dual simplex vs PDLP (first-order, GPU-capable family)."""
import json, sys, time
import highspy, numpy as np
from src.uc.benchmark_cases import synthetic_case
from src.uc.solver import solve_uc

mps, out = sys.argv[1], sys.argv[2]
p = synthetic_case(800, 48, 17)
p.solver_name = "HiGHS"; p.solver_time_limit_s = 1; p.model_export_path = mps
p.solver_options = {"threads": 1}
solve_uc(p)  # builds the same MILP and writes MPS; the 1 s solve is discarded
rows = []
for solver in ("simplex", "ipm", "pdlp"):
    h = highspy.Highs(); h.setOptionValue("output_flag", False)
    h.readModel(mps)
    n = h.getNumCol()
    h.changeColsIntegrality(n, np.arange(n, dtype=np.int32), np.zeros(n, dtype=np.uint8))
    for k, v in {"solver": solver, "threads": 1, "time_limit": 900.0, "presolve": "on"}.items():
        h.setOptionValue(k, v)
    highspy.Highs.resetGlobalScheduler(True)
    t = time.monotonic(); h.run(); dt = time.monotonic() - t
    info = h.getInfo()
    rows.append({"solver": solver, "status": h.modelStatusToString(h.getModelStatus()), "seconds": round(dt, 1),
                 "objective": info.objective_function_value, "iterations": {"simplex": info.simplex_iteration_count,
                 "ipm": info.ipm_iteration_count, "pdlp": info.pdlp_iteration_count}[solver],
                 "max_primal_infeas": info.max_primal_infeasibility, "max_dual_infeas": info.max_dual_infeasibility})
    print(json.dumps(rows[-1]), flush=True)
    json.dump(rows, open(out, "w"), indent=1)
