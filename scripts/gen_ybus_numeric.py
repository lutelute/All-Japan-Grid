"""数値 Ybus の正典生成器 — built 正典から検証済みアドミタンス行列を出荷する.

オーナー指示(2026-07-02): 「Ybus をとにかくいいものに作り上げていく」。
従来の Ybus 資産は可視化(スパーシティ図, gen_ybus_from_db.py)のみで、
**数値としての Ybus 成果物が存在しなかった**。本スクリプトがそれを埋める:

  built(docs/data/built/all.json, 接続の正典)
    → build_island_net(周波数島ごとの全規模 pandapower net,
       run_full_powerflow_from_db と同一 = 潮流と同じモデル)
    → pandapower/pypower makeYbus(業界標準実装) = **正典 Ybus**
    → 検証: ①複素対称性 ②自前式(ybus_gate 系)との相互アドミタンス突合
             ③条件数ゲート(ybus_gate)
    → 出荷: {island}.npz(scipy) / {island}.mat(MATLAB) / {island}_bus.csv /
             meta.json(次元・nnz・検証結果つき)

4周波数島(hokkaido 50Hz / east 50Hz / west 60Hz / okinawa 60Hz)は非同期のため
別行列が物理的に正しい。「全国」はこの4ブロックの直和である(meta に明記)。

Usage:
    PYTHONPATH=. .venv/bin/python scripts/gen_ybus_numeric.py            # 全4島
    PYTHONPATH=. .venv/bin/python scripts/gen_ybus_numeric.py --islands okinawa
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np
import pandapower as pp
import scipy.sparse as sp

from scripts.run_full_powerflow_from_db import (
    BUILT,
    build_island_net,
)

OUT_DIR = "dist/ybus"
ISLANDS = [("hokkaido", 50.0), ("east", 50.0), ("west", 60.0),
           ("okinawa", 60.0)]


def add_ref_per_component(net):
    """全連結成分に ext_grid を置く(Ybus 抽出用の参照。負荷ゼロなので潮流は恒等)。

    ref の無い成分は pandapower の connectivity check で out-of-service に
    落とされ Ybus から消えるため、「全規模の Ybus」には全成分 ref が必要。
    """
    import networkx as nx
    import pandapower.topology as top

    g = top.create_nxgraph(net, respect_switches=False)
    has_ref = {int(e.bus) for e in net.ext_grid.itertuples()}
    n_added = 0
    for comp in nx.connected_components(g):
        if comp & has_ref:
            continue
        best = max(sorted(comp),
                   key=lambda b: (float(net.bus.at[b, "vn_kv"]),
                                  str(net.bus.at[b, "type"]) == "b"))
        pp.create_ext_grid(net, bus=best, vm_pu=1.0,
                           name=f"ybus_ref_{n_added}")
        n_added += 1
    return n_added


def extract_ybus(net):
    """pandapower 公式経路で Ybus を取り出す(正典)。

    負荷ゼロ+全成分 slack の flat start でほぼ恒等だが、west 島は既知の数値
    悪条件(下位網変圧器チェーン, WEST_AC_ANALYSIS)で NR が収束しないことが
    ある。**Ybus(makeYbus 出力)は NR 反復の前に組み上がる**ため、収束例外は
    握りつぶして `net._ppc["internal"]["Ybus"]` を回収する(値は反復と無関係)。
    行列順序は ppc 内部順 → `net._pd2ppc_lookups["bus"]` で pandapower バス
    index に引き戻す。
    """
    try:
        pp.runpp(net, init="flat", calculate_voltage_angles=True,
                 enforce_q_lims=False, numba=False)
    except pp.LoadflowNotConverged:
        pass    # 行列は net._ppc に既に在る(下で検証つき回収)
    ppc = net.get("_ppc") or {}
    Y = ppc.get("internal", {}).get("Ybus")
    if Y is None or Y.shape[0] == 0:
        raise RuntimeError("Ybus was not assembled (pd2ppc failed)")
    Y = Y.tocsr()
    lookup = net._pd2ppc_lookups["bus"]          # pd bus idx -> ppc idx
    ppc_bus_ids = np.full(Y.shape[0], -1, dtype=int)
    for pd_idx in net.bus.index:
        ppc_idx = int(lookup[pd_idx])
        if 0 <= ppc_idx < Y.shape[0] and ppc_bus_ids[ppc_idx] == -1:
            ppc_bus_ids[ppc_idx] = int(pd_idx)
    return Y, ppc_bus_ids


def own_offdiag(net, base_mva=100.0):
    """自前式(ybus_gate と同系)の相互アドミタンス dict {(a,b): y}。

    透明性の担保: 正典(makeYbus)の off-diagonal が、教科書式
    y = 1/(r+jx)(線路は per-unit 換算・並列回線合成、変圧器は vk/vkr から)
    と一致することを突合するための対向実装。
    """
    y_of = {}

    def acc(a, b, y):
        k = (min(a, b), max(a, b))
        y_of[k] = y_of.get(k, 0j) + y

    vn = net.bus["vn_kv"]
    for idx in net.line.index:
        if not bool(net.line.at[idx, "in_service"]):
            continue
        fb = int(net.line.at[idx, "from_bus"])
        tb = int(net.line.at[idx, "to_bus"])
        par = max(int(net.line.at[idx, "parallel"] or 1), 1)
        length = float(net.line.at[idx, "length_km"])
        zb = float(vn.get(fb, 0)) ** 2 / base_mva or 1.0
        r = float(net.line.at[idx, "r_ohm_per_km"]) * length / par / zb
        x = float(net.line.at[idx, "x_ohm_per_km"]) * length / par / zb
        z = complex(r, x) if (r or x) else complex(0, 1e-6)
        acc(fb, tb, 1.0 / z)
    for t in net.trafo.itertuples():
        if not t.in_service:
            continue
        n_par = max(int(getattr(t, "parallel", 1) or 1), 1)
        zk = max(float(t.vk_percent), 1e-6) / 100.0 * base_mva / float(t.sn_mva)
        rk = float(t.vkr_percent) / 100.0 * base_mva / float(t.sn_mva)
        xk = max(zk * zk - rk * rk, 1e-12) ** 0.5
        acc(int(t.hv_bus), int(t.lv_bus), n_par / complex(rk, xk))
    return y_of


def verify(Y, bus_ids, net):
    """正典 Ybus の検証(対称性・自前式突合)。"""
    # ① 複素対称性(送電網は相互 = Y == Y^T)
    dsym = abs(Y - Y.T)
    sym_err = float(dsym.max()) if dsym.nnz else 0.0
    denom = float(abs(Y).max()) or 1.0

    # ② 相互アドミタンス突合(makeYbus vs 教科書式)
    own = own_offdiag(net, base_mva=float(net.sn_mva or 100.0))
    pos_of = {int(b): i for i, b in enumerate(bus_ids) if b >= 0}
    coo = Y.tocoo()
    canon = {}
    for i, j, v in zip(coo.row, coo.col, coo.data):
        if i < j:
            canon[(i, j)] = v
    rel_errs = []
    n_checked = 0
    for (a, b), y in own.items():
        ia, ib = pos_of.get(a), pos_of.get(b)
        if ia is None or ib is None:
            continue                      # out-of-service 側(孤立で落ちた等)
        key = (min(ia, ib), max(ia, ib))
        yc = canon.get(key)
        if yc is None:
            continue
        n_checked += 1
        rel_errs.append(abs((-y) - yc) / max(abs(yc), 1e-12))
    rel = np.array(rel_errs) if rel_errs else np.array([np.inf])
    return {
        "symmetry_max_abs_err": sym_err,
        "symmetry_rel_err": sym_err / denom,
        "offdiag_checked": int(n_checked),
        "offdiag_rel_err_median": float(np.median(rel)),
        "offdiag_rel_err_p99": float(np.percentile(rel, 99)),
    }


def export_island(island, freq, nodes, edges, out_dir):
    t0 = time.time()
    geom = {}
    net, bus_of, _stats = build_island_net(island, nodes, edges, freq, geom)
    n_refs = add_ref_per_component(net)
    Y, bus_ids = extract_ybus(net)
    checks = verify(Y, bus_ids, net)

    from src.powerflow.ybus_gate import ybus_gate
    gate = ybus_gate(net)

    # バス→ソースノード(lat/lon/region は built から直接引く。pandapower の
    # geodata API はバージョン差があるため使わない)
    node_of_bus = {b: nodes[i] for i, b in bus_of.items()}

    # --- バス表(行列 index 順 = MATLAB/科学計算からそのまま引ける) ---
    rows = []
    for i, b in enumerate(bus_ids):
        if b < 0:
            rows.append((i, -1, "", 0.0, np.nan, np.nan, ""))
            continue
        nd = node_of_bus.get(int(b), {})
        rows.append((i, int(b), str(net.bus.at[b, "name"]),
                     float(net.bus.at[b, "vn_kv"]),
                     float(nd.get("lat", np.nan)),
                     float(nd.get("lon", np.nan)),
                     str(nd.get("region") or "")))
    import csv
    with open(os.path.join(out_dir, f"{island}_bus.csv"), "w",
              newline="") as f:
        w = csv.writer(f)
        w.writerow(["ybus_index", "pp_bus", "name", "vn_kv", "lat", "lon",
                    "region"])
        w.writerows(rows)

    # --- npz(scipy CSR + バス配列を同梱) ---
    np.savez_compressed(
        os.path.join(out_dir, f"{island}.npz"),
        data=Y.data, indices=Y.indices, indptr=Y.indptr,
        shape=np.array(Y.shape), base_mva=np.array([100.0]), f_hz=np.array([freq]),
        bus_pp=np.array([r[1] for r in rows]),
        bus_kv=np.array([r[3] for r in rows]),
        bus_lat=np.array([r[4] for r in rows]),
        bus_lon=np.array([r[5] for r in rows]))

    # --- .mat(MATLAB: sparse complex + バス属性) ---
    from scipy.io import savemat
    savemat(os.path.join(out_dir, f"{island}.mat"), {
        "Ybus": Y.tocsc(),                     # MATLAB native sparse
        "base_mva": 100.0, "f_hz": freq,
        "bus_kv": np.array([r[3] for r in rows]),
        "bus_lat": np.array([r[4] for r in rows]),
        "bus_lon": np.array([r[5] for r in rows]),
        "bus_name": np.array([r[2] for r in rows], dtype=object),
        "bus_region": np.array([r[6] for r in rows], dtype=object),
    }, do_compression=True)

    meta = {
        "island": island, "f_hz": freq,
        "n_bus": int(Y.shape[0]), "nnz": int(Y.nnz),
        "density": float(Y.nnz) / (Y.shape[0] ** 2),
        "n_line": int(len(net.line)), "n_trafo": int(len(net.trafo)),
        "n_components_refs": int(n_refs),
        "checks": checks,
        "gate": {"pass": gate["pass"], "cond_max": gate["cond_max"],
                 "n_islands": gate["n_islands"]},
        "elapsed_s": round(time.time() - t0, 1),
    }
    return meta


def main():
    ap = argparse.ArgumentParser(description="数値Ybusの正典生成(built由来)")
    ap.add_argument("--islands", nargs="*",
                    default=[i for i, _ in ISLANDS])
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    built = json.load(open(BUILT))
    nodes, edges = built["nodes"], built["edges"]
    freq_of = dict(ISLANDS)

    metas = {}
    for island in args.islands:
        meta = export_island(island, freq_of[island], nodes, edges, args.out)
        metas[island] = meta
        c = meta["checks"]
        print(f"[{island}] bus={meta['n_bus']} nnz={meta['nnz']} "
              f"line={meta['n_line']} trafo={meta['n_trafo']} | "
              f"sym_rel={c['symmetry_rel_err']:.1e} "
              f"offdiag_med={c['offdiag_rel_err_median']:.1e} "
              f"p99={c['offdiag_rel_err_p99']:.1e} "
              f"(checked {c['offdiag_checked']}) | "
              f"gate={'PASS' if meta['gate']['pass'] else 'FAIL'} "
              f"cond={meta['gate']['cond_max']:.2e} ({meta['elapsed_s']}s)")

    from datetime import date
    with open(os.path.join(args.out, "meta.json"), "w") as f:
        json.dump({"generated": date.today().isoformat(),
                   "source": BUILT,
                   "note": "4 frequency islands are asynchronous; the national "
                           "Ybus is the block-diagonal direct sum of these.",
                   "islands": metas}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
