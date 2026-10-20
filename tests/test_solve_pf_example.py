"""配布の例題 dataset/01_matpower_powerflow/solve_pf.py の需給の集計。

from_mpc は同じバスの 2 台目以降の発電機を sgen に、タップ付きの枝を impedance に
する。v1.7.0 までの例題は sgen を発電に数えず、損失が負に見えていた(原因を
「pandapower は複数 slack を扱えない」と誤って説明していた)。
"""

import importlib.util
from pathlib import Path

import pandapower as pp
import pytest
from pandapower.converter.matpower import to_mpc
from scipy.io import savemat

from src.converter.matpower_exporter import canonical_mpc

ROOT = Path(__file__).resolve().parents[1]


def _load_example():
    path = ROOT / "dataset" / "01_matpower_powerflow" / "solve_pf.py"
    spec = importlib.util.spec_from_file_location("solve_pf_example", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mat_dir(tmp_path):
    """2 成分(各 1 slack)・同じバスに発電機 2 台の小さな島を okinawa.mat として書く。"""
    n = pp.create_empty_network(sn_mva=100.0)
    b = [pp.create_bus(n, vn_kv=66.0) for _ in range(5)]
    pp.create_ext_grid(n, b[0])
    pp.create_ext_grid(n, b[3])  # 2 つ目の成分
    for f, t in ((b[0], b[1]), (b[1], b[2]), (b[0], b[2]), (b[3], b[4])):
        pp.create_line_from_parameters(n, f, t, length_km=10.0, r_ohm_per_km=0.12,
                                       x_ohm_per_km=0.40, c_nf_per_km=10.0, max_i_ka=0.6)
    pp.create_gen(n, b[2], p_mw=20.0, vm_pu=1.0)
    pp.create_gen(n, b[2], p_mw=15.0, vm_pu=1.0)  # 同じバス → from_mpc で sgen
    for bus, p in ((b[1], 30.0), (b[2], 20.0), (b[4], 10.0)):
        pp.create_load(n, bus, p_mw=p, q_mvar=p * 0.2)
    pp.runpp(n)
    savemat(str(tmp_path / "okinawa.mat"), canonical_mpc(to_mpc(n, mode="pf")))
    return tmp_path


def test_generation_balances_load_plus_loss(mat_dir, capsys):
    mod = _load_example()
    assert mod.solve("okinawa", False, None, mat_dir) == 0
    out = capsys.readouterr().out
    assert "AC CONVERGED" in out
    assert "⚠" not in out
    vals = {}
    for line in out.splitlines():
        for key in ("total generation", "total load", "transmission loss"):
            if line.strip().startswith(key):
                vals[key] = float(line.split(":")[1].split("MW")[0])
    # 損失は 1 MW 未満(表示は 0)。旧版は sgen の 15 MW を落として -15 と出ていた
    assert vals["transmission loss"] >= 0
    assert vals["total generation"] == pytest.approx(
        vals["total load"] + vals["transmission loss"], abs=1.0)
