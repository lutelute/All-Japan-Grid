#!/usr/bin/env python3
"""感度行列の「数値誤差」を切り分けて測る。

精度には性質の違う3層があり、混ぜると議論が濁る:

  ① 数値誤差   — 浮動小数点・条件数・保存形式で失われる桁。手法とは無関係に生じる
  ② 求解の残差 — 基準としている AC 解そのものの収束の甘さ
  ③ モデル誤差 — DC 線形化が AC と食い違う分（benchmark_sensitivity.py が測る本体）

①②が③より十分小さいことを示して初めて、③を「線形化の代償」と呼べる。
本スクリプトは①②を測り、③と同じ土俵（MW）に並べる。

usage: python3 scripts/sensitivity/audit_numerics.py [--islands hokkaido ...]
出力: docs/reports/sensitivity_numerics_<date>.{md,json}
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT)

import numpy as np
import pandapower as pp
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from pandapower.pypower.idx_brch import PF
from pandapower.pypower.idx_bus import PD
from pandapower.pypower.idx_gen import GEN_BUS, PG
from pandapower.pypower.makeBdc import makeBdc
from pandapower.pypower.makePTDF import makePTDF

from benchmark_sensitivity import main_component_subnet, production_net
from scripts.run_full_powerflow_from_db import ISLAND_FREQ, load_demand_config, solve_island

REPORTS = ROOT / "docs" / "reports"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"


def cond_1norm(A: sp.spmatrix) -> float:
    """1ノルム条件数の推定 ‖A‖₁·‖A⁻¹‖₁（A⁻¹ は LU 分解を作用素として推定）。

    密 SVD は 7000 次元では現実的でないため、onenormest を使う。
    """
    A = sp.csc_matrix(A)
    lu = spla.splu(A)
    n = A.shape[0]
    inv_op = spla.LinearOperator(
        (n, n), matvec=lu.solve, rmatvec=lambda x: lu.solve(x, trans="T"), dtype=float)
    return float(spla.norm(A, 1) * spla.onenormest(inv_op))


def audit(island: str, nodes, edges, cfg, pref_gwh) -> dict:
    net = production_net(island, nodes, edges, cfg, pref_gwh)
    sub, _ = main_component_subnet(net)
    pp.rundcpp(sub)
    ppc = sub._ppc
    ref = int(sub._pd2ppc_lookups["bus"][int(sub.ext_grid.bus.iloc[0])])
    r = {"island": island, "n_bus": int(len(ppc["bus"])), "n_branch": int(ppc["branch"].shape[0])}

    # ── ① 条件数: PTDF は Bbus の非参照部分を解いて作る ────────────
    Bbus, _, _, _, _ = makeBdc(ppc["bus"], ppc["branch"])
    keep = [i for i in range(Bbus.shape[0]) if i != ref]
    Bred = sp.csc_matrix(Bbus)[keep][:, keep]
    t0 = time.perf_counter()
    r["cond_bbus_reduced"] = cond_1norm(Bred)
    r["sec_cond"] = round(time.perf_counter() - t0, 1)
    # 条件数 κ に対し、相対誤差はおよそ κ·ε（ε=2.2e-16）まで増幅されうる
    r["worst_case_rel_error_f64"] = r["cond_bbus_reduced"] * np.finfo(np.float64).eps

    # ── ① 保存形式: float32 で保存した PTDF がどれだけ桁を失うか ──
    ptdf64 = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"], slack=ref)
    ptdf32 = ptdf64.astype(np.float32).astype(np.float64)
    pinj = -ppc["bus"][:, PD].astype(float).copy()
    for g in ppc["gen"]:
        pinj[int(g[GEN_BUS].real)] += float(g[PG].real)
    f64, f32 = ptdf64 @ pinj, ptdf32 @ pinj
    d = np.abs(f64 - f32)
    r["float32_storage"] = {
        "max_abs_mw": float(d.max()), "mean_abs_mw": float(d.mean()),
        "p95_abs_mw": float(np.percentile(d, 95)),
        "max_elem_diff": float(np.abs(ptdf64 - ptdf32).max()),
    }

    # ── ① 実装検証（再掲）: PTDF·P vs pandapower の DC 解 ──────────
    e = np.abs(f64 - ppc["branch"][:, PF].real.astype(float))
    r["ptdf_vs_dcpf"] = {"max_abs_mw": float(e.max()), "mean_abs_mw": float(e.mean())}

    # ── ② 基準にしている AC 解そのものの残差 ────────────────────────
    _, _, net_ac, ac = solve_island(net, max_ac_buses=10**9)
    if ac.get("converged") and net_ac is not None:
        # 大域の電力収支で解の物理的整合を測る。
        # 注意: `internal["Sbus"]` と `internal["Ybus"]` からバス毎の残差を作る方法は
        # このモデルでは使えない。無効電力補償で入れたシャント(west は 4,136 個)が
        # Ybus 側にだけ載り Sbus に無いため、見かけ上 541MW の残差が出る（測定の artifact）。
        # 実際の収支は下のとおり west でも 0.002% に閉じている。
        g = float(net_ac.res_gen.p_mw.sum()) if len(net_ac.res_gen) else 0.0
        sg = float(net_ac.res_sgen.p_mw.sum()) if len(net_ac.res_sgen) else 0.0
        ext = float(net_ac.res_ext_grid.p_mw.sum()) if len(net_ac.res_ext_grid) else 0.0
        ld = float(net_ac.res_load.p_mw.sum()) if len(net_ac.res_load) else 0.0
        loss = float(net_ac.res_line.pl_mw.sum())
        if len(net_ac.res_trafo):
            loss += float(net_ac.res_trafo.pl_mw.sum())
        imb = g + sg + ext - ld - loss
        r["ac_balance"] = {
            "gen_mw": round(g + sg, 1), "slack_mw": round(ext, 1), "load_mw": round(ld, 1),
            "loss_mw": round(loss, 1), "imbalance_mw": round(imb, 3),
            "imbalance_frac_of_load": round(abs(imb) / ld, 8) if ld else None,
            "tolerance_mva": net_ac._options.get("tolerance_mva"),
            "served_frac": ac.get("served_frac"),
        }
    else:
        r["ac_balance"] = {"error": "AC not converged"}
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=None)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()

    d = json.load(open(BUILT))
    nodes, edges = d["nodes"], d["edges"]
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    out = []
    for isl in (args.islands or list(ISLAND_FREQ.keys())):
        r = audit(isl, nodes, edges, cfg, pref_gwh)
        out.append(r)
        f32, ar = r["float32_storage"], r["ac_balance"]
        print(f"[{isl:9s}] κ(Bbus)={r['cond_bbus_reduced']:.2e} "
              f"| f64理論限界 {r['worst_case_rel_error_f64']:.1e} "
              f"| float32保存の誤差 max {f32['max_abs_mw']:.3g}MW "
              f"| PTDF vs DC {r['ptdf_vs_dcpf']['max_abs_mw']:.1e}MW "
              f"| AC収支 {ar.get('imbalance_mw', float('nan')):+.2f}MW ({(ar.get('imbalance_frac_of_load') or 0)*100:.4f}%)")

    json.dump({"date": date, "islands": out},
              open(REPORTS / f"sensitivity_numerics_{date}.json", "w"), ensure_ascii=False, indent=1)

    L = [
        f"# 感度行列の数値精度 — 誤差の切り分け（{date}）",
        "",
        "精度には性質の違う層がある。**数値誤差**（浮動小数点・条件数・保存形式）と",
        "**基準の残差**（AC 解そのものの収束の甘さ）が、**モデル誤差**（DC 線形化の代償）より",
        "十分小さいことを示して初めて、後者を「線形化の代償」と呼べる。ここでは前二者を測る。",
        "",
        "## 1. 条件数と浮動小数点の理論限界",
        "",
        "PTDF は Bbus の参照バスを除いた行列を解いて作る。その条件数 κ に対し、",
        "倍精度の相対誤差はおよそ κ·ε（ε≈2.2e-16）まで増幅されうる。",
        "",
        "| 島 | バス | κ(Bbus縮約) | κ·ε（f64の理論限界） | 推定時間 |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in out:
        L.append(f"| {r['island']} | {r['n_bus']} | {r['cond_bbus_reduced']:.2e} | "
                 f"{r['worst_case_rel_error_f64']:.1e} | {r['sec_cond']:.1f} s |")
    L += [
        "",
        "## 2. 実装と保存形式による誤差",
        "",
        "`PTDF·P` が pandapower の DC 解を再現するか（実装の正しさ）と、",
        "配布用に float32 で保存した場合に失う桁（保存形式の代償）。",
        "",
        "| 島 | PTDF·P vs DC解 最大差 | float32保存 最大差 | 同 p95 | PTDF要素の最大差 |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in out:
        f = r["float32_storage"]
        L.append(f"| {r['island']} | {r['ptdf_vs_dcpf']['max_abs_mw']:.2e} MW | "
                 f"{f['max_abs_mw']:.3g} MW | {f['p95_abs_mw']:.3g} MW | {f['max_elem_diff']:.2e} |")
    L += [
        "",
        "## 3. 基準にしている AC 解の物理的整合",
        "",
        "モデル誤差の基準は本番 `solve_island` の AC 解。その解が電力収支を閉じているかを測る。",
        "",
        "> **測定上の注意**: `internal[\"Sbus\"]` と `internal[\"Ybus\"]` からバス毎の残差を作る方法は",
        "> このモデルでは使えない。無効電力補償で入れたシャント（west は 4,136 個）が Ybus 側に",
        "> だけ載り Sbus に無いため、見かけ上 541 MW の残差が出る。これは解の欠陥ではなく",
        "> 測定の artifact で、実際の収支は下表のとおり閉じている。",
        "",
        "| 島 | 発電 | slack | 負荷 | 損失 | 収支 | 負荷比 | 求解tol | 給電率 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in out:
        a = r["ac_balance"]
        if "error" in a:
            L.append(f"| {r['island']} | — | — | — | — | — | — | — | （{a['error']}） |")
            continue
        L.append(f"| {r['island']} | {a['gen_mw']:.0f} MW | {a['slack_mw']:+.0f} MW | {a['load_mw']:.0f} MW | "
                 f"{a['loss_mw']:.0f} MW | **{a['imbalance_mw']:+.2f} MW** | "
                 f"{(a['imbalance_frac_of_load'] or 0)*100:.4f}% | {a['tolerance_mva']} MVA | "
                 f"{(a.get('served_frac') or float('nan')):.1%} |")
    L += [
        "",
        "## 読み方",
        "",
        "モデル誤差（`sensitivity_bench_*.md`）は枝潮流で中央値 0.2〜0.6 MW・p95 4〜48 MW。",
        "上の①②がこれより桁で小さければ、あの差は数値の問題ではなく**線形化そのものの代償**だと言える。",
        "逆にどちらかが同じ桁に来ていれば、その分は手法の優劣ではなく計算環境の話になる。",
        "",
        "---",
        "生成: `scripts/sensitivity/audit_numerics.py`",
        "",
    ]
    (REPORTS / f"sensitivity_numerics_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/sensitivity_numerics_{date}.md")


if __name__ == "__main__":
    main()
