"""Write the synthetic 800-unit UC MILP to MPS without solving. Usage: export_mps2.py <hours> [strengthen...]"""
import hashlib, json, sys
from dataclasses import asdict
import src.uc.solver as S
from src.uc.benchmark_cases import synthetic_case

class Exported(Exception):
    pass

def stop(params):
    raise Exported

S._select_solver = stop  # the MPS is written before the solver is chosen
hours, strengthen = int(sys.argv[1]), tuple(sys.argv[2:])
p = synthetic_case(800, hours, 17)
sha = hashlib.sha256(json.dumps(asdict(p), sort_keys=True, default=str).encode()).hexdigest()
p.strengthen = strengthen
tag = "-".join(strengthen) or "base"
p.model_export_path = f"mps/n800-t{hours}-{tag}.mps"
try:
    S.solve_uc(p)
except Exported:
    pass
print(json.dumps({"hours": hours, "strengthen": strengthen, "mps": p.model_export_path, "input_sha256": sha}), flush=True)
