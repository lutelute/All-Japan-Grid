"""Bound traces must hold only bounds of the model that was solved."""

from scripts.uc_explorer_report import read_log

HIGHS_WARM = """\
MIP has 7716 rows; 4608 cols; 32224 nonzeros; 3072 integer variables (3072 binary)
Attempting to find feasible solution by solving MIP for user-supplied values of 576 / 3072 discrete variables
Src  Proc. InQueue |  Leaves   Expl. | BestBound       BestSol              Gap |   Cuts   InLp Confl. | LpIters     Time
         0       0         0   0.00%   569921394.2357  inf                  inf        0      0      0         0     0.0s
 R       0       0         0   0.00%   878837268.0765  878844733.9835     0.00%        0      0      0       654     0.0s
Solving report
Src  Proc. InQueue |  Leaves   Expl. | BestBound       BestSol              Gap |   Cuts   InLp Confl. | LpIters     Time
         0       0         0   0.00%   122745847.7131  878844733.9835    86.03%        0      0      0         0     0.2s
         4       3         1  12.50%   872684664.7764  878844733.9835     0.70%      675    174    507     50469     9.5s
Solving report
"""


def test_highs_start_submip_is_not_a_bound_of_the_full_model(tmp_path):
    log = tmp_path / "warm.solver.log"
    log.write_text(HIGHS_WARM)
    parsed = read_log(log, "HiGHS")
    assert parsed["start"] == {"t": 0.0, "ub": 878844733.9835}
    assert [p["lb"] for p in parsed["trace"]] == [122745847.7131, 872684664.7764]


def test_scip_completesol_start_is_recorded(tmp_path):
    log = tmp_path / "warm.solver.log"
    log.write_text("feasible solution found by completesol heuristic after 0.1 seconds, "
                   "objective value 3.967143e+09\n")
    assert read_log(log, "SCIP")["start"] == {"t": 0.1, "ub": 3.967143e9}


def test_presolved_size_comes_from_the_full_model(tmp_path):
    log = tmp_path / "warm.solver.log"
    log.write_text("72155 cols (672 binary, 0 integer)\n841450 cols (701234 binary, 0 integer)\n")
    assert read_log(log, "HiGHS")["dimensions"]["presolved_binary"] == 701234
