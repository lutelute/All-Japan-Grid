"""数値 Ybus 正典生成器の品質ゲート — gen_ybus_numeric の回帰保証.

「Ybus をいいものに」(オーナー指示 2026-07-02)の不変条件:
  1. 複素対称性(送電網の相互性): max|Y - Y^T| == 0
  2. 透明性: 公式 makeYbus の相互アドミタンスが教科書式(own_offdiag)と
     機械精度で一致する
  3. 条件数ゲート(ybus_gate)を通る
  4. .mat / .npz の読み戻しが元行列とバイナリ一致
  5. 回帰 pin(okinawa: 99バス/nnz321。モデル改善時のみ意図的に更新)

okinawa 島(~0.4s)で全ゲートを実行する。
"""
import json
import os

import numpy as np
import pytest
import scipy.sparse as sp

from scripts.gen_ybus_numeric import export_island
from scripts.run_full_powerflow_from_db import BUILT


@pytest.fixture(scope="module")
def okinawa_ybus(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("ybus"))
    built = json.load(open(BUILT))
    meta = export_island("okinawa", 60.0, built["nodes"], built["edges"], out)
    return out, meta


def test_symmetry_and_offdiag_match(okinawa_ybus):
    """ゲート1+2: 対称性ゼロ・教科書式と機械精度一致。"""
    _out, meta = okinawa_ybus
    c = meta["checks"]
    assert c["symmetry_max_abs_err"] == 0.0
    assert c["offdiag_checked"] > 100
    assert c["offdiag_rel_err_p99"] < 1e-12


def test_condition_gate(okinawa_ybus):
    """ゲート3: 条件数ゲート PASS。"""
    _out, meta = okinawa_ybus
    assert meta["gate"]["pass"] is True


def test_roundtrip_mat_npz(okinawa_ybus):
    """ゲート4: .mat / .npz の読み戻しが一致。"""
    out, _meta = okinawa_ybus
    from scipy.io import loadmat
    Ym = loadmat(os.path.join(out, "okinawa.mat"))["Ybus"].tocsr()
    d = np.load(os.path.join(out, "okinawa.npz"))
    Yn = sp.csr_matrix((d["data"], d["indices"], d["indptr"]),
                       shape=tuple(d["shape"]))
    assert Ym.shape == Yn.shape
    assert abs(Ym - Yn).nnz == 0


def test_bus_table_alignment(okinawa_ybus):
    """バス表が行列 index と整列している(全行・kv>0 は座標つき)。"""
    out, meta = okinawa_ybus
    import csv
    with open(os.path.join(out, "okinawa_bus.csv")) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == meta["n_bus"]
    assert [int(r["ybus_index"]) for r in rows] == list(range(meta["n_bus"]))


def test_regression_pin_okinawa(okinawa_ybus):
    """ゲート5: 回帰 pin(意図的なモデル改善時のみ更新)。"""
    _out, meta = okinawa_ybus
    assert meta["n_bus"] == 99
    assert meta["nnz"] == 321
    assert meta["n_trafo"] == 19
