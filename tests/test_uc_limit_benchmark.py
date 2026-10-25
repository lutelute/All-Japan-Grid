"""The sweep must preserve budget cutoffs and never call them solved cases."""

import json
import sys

from scripts.uc_limit_benchmark import classify, main, supervise


def test_wall_cutoff_stops_owned_process_and_records_failure(tmp_path):
    evidence = supervise([sys.executable, "-c", "import time; time.sleep(20)"],
                         cwd=tmp_path, log_path=tmp_path / "child.log",
                         memory_bytes=2**30, wall_seconds=0.1,
                         min_available_bytes=0, poll_seconds=0.02)
    assert evidence["controller_stop_reason"] == "wall_budget_exceeded"
    assert evidence["return_code"] != 0
    assert evidence["observed_wall_s"] < 5
    assert classify(None, evidence, 0.001) == "wall_budget_exceeded"


def test_memory_cutoff_is_distinct_from_solver_failure(tmp_path):
    evidence = supervise([sys.executable, "-c", "import time; x=bytearray(32*1024**2); time.sleep(20)"],
                         cwd=tmp_path, log_path=tmp_path / "child.log",
                         memory_bytes=20*1024**2, wall_seconds=5,
                         min_available_bytes=0, poll_seconds=0.02)
    assert evidence["controller_stop_reason"] == "memory_budget_exceeded"
    assert evidence["sampled_peak_tree_rss_bytes"] >= 20*1024**2


def test_plan_does_not_launch_or_claim_measured_results(tmp_path):
    assert main(["--units", "800", "--hours", "24", "8760", "--out", str(tmp_path)]) == 0
    manifest = json.loads((tmp_path / "sweep.json").read_text())
    assert not manifest["execution"]
    assert len(manifest["cells"]) == 4
    assert all(c["outcome"] == "planned" for c in manifest["cells"])
    assert manifest["cells"][-1]["binary_count_6NT_reference"] == 42048000


def test_verified_feasible_is_not_target_reached_when_gap_missing():
    report = {"result": {"feasibility_verified": True, "gap": None}}
    assert classify(report, {"controller_stop_reason": None}, 0.001) == "feasible_gap_unknown"


def test_plan_crosses_warm_start_with_each_solver(tmp_path):
    assert main(["--units", "800", "--hours", "48", "--warm-starts", "none", "rolling",
                 "--out", str(tmp_path)]) == 0
    cells = json.loads((tmp_path / "sweep.json").read_text())["cells"]
    assert [(c["solver"], c["warm_start"]) for c in cells] == [
        ("HiGHS", "none"), ("HiGHS", "rolling"), ("SCIP", "none"), ("SCIP", "rolling")]


def test_rolling_start_is_reported_and_never_worsened(tmp_path):
    from scripts.uc_open_solver_benchmark import main as bench

    out = tmp_path / "n8-t48.json"
    code = bench(["--units", "8", "--hours", "48", "--solver", "HiGHS", "--time-limit", "20",
                  "--warm-start", "rolling", "--rolling-time-limit", "20", "--out", str(out)])
    report = json.loads(out.read_text())
    start = report["warm_start"]
    assert code == 0 and report["result"]["feasibility_verified"]
    assert start["used"] and start["feasibility_verified"] and start["n_windows"] == 2
    assert start["final_minus_start"] <= 1e-6 * abs(start["primal_bound"])
    assert report["settings"]["warm_start"] == "rolling"
