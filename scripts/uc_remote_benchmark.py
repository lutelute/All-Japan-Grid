"""Stage the synthetic UC benchmark in a private remote directory and collect it.

Only Python sources needed for synthetic cases are uploaded; no grid data or
credentials are copied. Uses existing SSH access and an isolated remote venv.
Each solver gets one CPU, a native time limit and a 15-minute process timeout.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", required=True, help="Existing authorized SSH destination")
    ap.add_argument("--label", required=True)
    ap.add_argument("--units", type=int, default=800)
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--time-limit", type=float, default=60)
    ap.add_argument("--mode", choices=["pair", "frontier"], default="pair")
    ap.add_argument("--memory-limit-gib", type=float, default=8)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.target.startswith("-") or any(c.isspace() for c in args.target):
        ap.error("invalid SSH destination")
    if not args.label.replace("-", "").replace("_", "").isalnum():
        ap.error("label must contain only letters, numbers, hyphen, underscore")
    if not (4 <= args.units <= 800 and 1 <= args.hours <= 168 and 0 < args.time_limit <= 600):
        ap.error("initial experiments are bounded to 800 units, 168 hours, 600 solver seconds")
    if args.memory_limit_gib <= 0:
        ap.error("memory limit must be positive")
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2", args.target]
    root = Path(__file__).resolve().parents[1]
    files = [root / "src/__init__.py", root / "scripts/uc_open_solver_benchmark.py",
             root / "scripts/uc_limit_benchmark.py"]
    for directory in ("src/model", "src/uc", "src/utils"):
        files.extend(sorted((root / directory).glob("*.py")))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(root)))
    archive = buf.getvalue()
    archive_hash = hashlib.sha256(archive).hexdigest()
    source_files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    source_hash = hashlib.sha256(json.dumps(source_files, sort_keys=True).encode()).hexdigest()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{args.label}-n{args.units}-t{args.hours}-{source_hash[:12]}-{stamp}"

    def remote(code, *, data=None, timeout=1200):
        return subprocess.run(ssh + ["python3 -c " + shlex.quote(code)],
                              input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              check=True, timeout=timeout)

    print(f"Preparing {args.label}: {run_id}", flush=True)
    setup = '''import io,json,os,platform,subprocess,sys,tarfile
from pathlib import Path
root=Path.home()/"uc800-open-solver"/"20261023"
root.mkdir(parents=True,exist_ok=True)
venv=root/".venv"
if not (venv/"bin/python").exists():
    subprocess.run([sys.executable,"-m","venv",str(venv)],check=True)
with (root/"environment-install.log").open("w") as log:
    subprocess.run([str(venv/"bin/python"),"-m","pip","install","--disable-pip-version-check",
      "pulp==3.3.1","highspy==1.14.0","pyscipopt==6.3.0","numpy","pyyaml","psutil"],
      stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
run=root/RUN_ID
run.mkdir(exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:gz") as tar:
    tar.extractall(run,filter="data")
info={"host":platform.node(),"architecture":platform.machine(),"logical_cpus":os.cpu_count(),
      "affinity_cpus":len(os.sched_getaffinity(0)),"loadavg":os.getloadavg(),
      "memory":{k:v.strip() for line in Path("/proc/meminfo").read_text().splitlines()
      for k,v in [line.split(":",1)] if k in ("MemTotal","MemAvailable")}}
(run/"hardware.json").write_text(json.dumps(info,indent=2))
print(json.dumps(info))
'''.replace("RUN_ID", repr(run_id))
    stage = "connection_preflight"
    try:
        remote("print('uc800-ssh-ready')", timeout=20)
        stage = "environment_setup"
        prepared = remote(setup, data=archive, timeout=420)
        print(prepared.stdout.decode().strip(), flush=True)
        jobs = '''import json,os,subprocess
from pathlib import Path
root=Path.home()/"uc800-open-solver"/"20261023"
run=root/RUN_ID
cpus=sorted(os.sched_getaffinity(0))
env=dict(os.environ,OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
handles=[]
for i,solver in enumerate(("HiGHS","SCIP")):
    stem=solver.lower()
    log=(run/(stem+".runner.log")).open("w")
    cmd=["taskset","-c",str(cpus[-1-i]),str(root/".venv/bin/python"),"-m",
         "scripts.uc_open_solver_benchmark","--units",str(UNITS),"--hours",str(HOURS),
         "--time-limit",str(LIMIT),"--threads","1","--solver",solver,
         "--out",stem+".json","--export-mps",stem+".mps"]
    handles.append((solver,subprocess.Popen(cmd,cwd=run,env=env,stdout=log,stderr=subprocess.STDOUT),log))
codes={}
for solver,proc,log in handles:
    try:
        codes[solver]=proc.wait(timeout=900)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        codes[solver]="process_timeout"
    finally:
        log.close()
(run/"process_exit_codes.json").write_text(json.dumps(codes,indent=2))
print(json.dumps(codes))
'''.replace("RUN_ID", repr(run_id)).replace("UNITS", str(args.units)).replace("HOURS", str(args.hours)).replace("LIMIT", repr(args.time_limit))
        if args.mode == "frontier":
            jobs = '''import subprocess
from pathlib import Path
root=Path.home()/"uc800-open-solver"/"20261023"
run=root/RUN_ID
subprocess.run([str(root/".venv/bin/python"),"-m","scripts.uc_limit_benchmark",
 "--units",str(UNITS),"--hours","24","48",str(HOURS),
 "--time-limit",str(LIMIT),"--wall-limit","300","--total-wall-limit","1800",
 "--memory-limit-gib",str(MEMORY),"--min-system-available-gib","4",
 "--out","frontier","--execute"],cwd=run,check=True)
'''.replace("RUN_ID", repr(run_id)).replace("UNITS", str(args.units)).replace("HOURS", str(args.hours)).replace("LIMIT", repr(args.time_limit)).replace("MEMORY", repr(args.memory_limit_gib))
        print(f"Running {args.mode} with {args.time_limit}s native limits", flush=True)
        stage = "benchmark"
        completed = remote(jobs, timeout=2000)
        print(completed.stdout.decode().strip(), flush=True)
        collect = '''import sys,tarfile
from pathlib import Path
run=Path.home()/"uc800-open-solver"/"20261023"/RUN_ID
with tarfile.open(fileobj=sys.stdout.buffer,mode="w|gz") as tar:
    for p in sorted(run.rglob("*")):
        if p.is_file() and (p.suffix in (".json",".log") or p.name.endswith(".json.gz")):
            tar.add(p,arcname=str(p.relative_to(run)))
'''.replace("RUN_ID", repr(run_id))
        payload = remote(collect, timeout=180).stdout
        args.out.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
            tar.extractall(args.out, filter="data")
        manifest = {"run_id": run_id, "source_archive_sha256": archive_hash,
            "source_manifest_sha256": source_hash, "source_files": source_files,
            "scope": "synthetic_not_observed", "parallel_mode": (
                "sequential_frontier" if args.mode == "frontier" else "independent_one_cpu_processes_not_UG"),
            "solver_limit_seconds_each": args.time_limit, "remote_mps_retained": args.mode == "pair"}
        (args.out / "deployment.json").write_text(json.dumps(manifest, indent=2) + "\n")
        for solver in (() if args.mode == "frontier" else ("highs", "scip")):
            p = args.out / f"{solver}.json"
            if p.exists():
                report = json.loads(p.read_text())
                print(json.dumps({"solver": solver, "wall_time_s": report["wall_time_s"], **report["result"]}))
            else:
                print(f"Missing {solver} report; inspect {args.out}/{solver}.runner.log")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (exc.stderr or b"").decode(errors="replace")
        failure = {"label": args.label, "run_id": run_id, "stage": stage,
                   "error": type(exc).__name__, "stderr": detail,
                   "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                   "benchmark_launch_attempted": stage == "benchmark"}
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "failure.json").write_text(json.dumps(failure, indent=2) + "\n")
        print(f"{args.label}: {stage}: {type(exc).__name__}: {detail.strip()}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
