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

# Ybus は「バージョン管理された成果物」(オーナー認識 2026-07-02)。
# モデル・出荷物・検証が変わるたびに上げ、meta.json と .mat に刻印する。
YBUS_VERSION = "5.0.0"
CHANGELOG = {
    "1.0.0": "数値Ybus初出荷: built→makeYbus正典・対称/教科書式/条件数の3層検証・"
             ".mat/.npz/バス表",
    "2.0.0": "①バージョン刻印+行列フィンガープリント(sha256) "
             "②Kron縮約バックボーン(≥154kV, 回路論的に厳密・密Schur突合) "
             "③DC行列 Bbus 同梱(pandapower公式・PTDF/DC潮流用) "
             "④AC/DCバス順序の整合検証",
    "3.0.0": "①枝アドミタンス行列 Yf/Yt 同梱(線潮流 If=Yf·V が MATLAB で完結) "
             "②枝表 {island}_branch.csv(kind/名前/from-to ybus_index/長さ/par/tap) "
             "③再構成恒等式ゲート Ybus == Cf'Yf+Ct'Yt+diag(Ysh) (機械精度) "
             "④枝順序ゲート(lookup範囲=lines→trafos の整合検証)",
    "4.0.0": "①変圧器の実容量化: 出典必須DB(data/transformer_sources.jsonl, "
             "existing銘板のみ)→構造DB(TransformerSpec source=nameplate)→"
             "build_island_net の trafo sn_mva/parallel へ接続(電圧ペア厳密一致のみ・"
             "枝名に@nameplate刻印) "
             "②applyの階級フォールバック廃止(誤ペアへの銘板付与を防止) "
             "③built名の電圧サフィックス('… 500kV')を吸収する正規化照合 "
             "④meta.trafo_nameplate に適用数と伝播経路を記録",
    "5.0.0": "介入#21(bbox二重抽出のdedup)を既定ON化: ①重複ノード(同一座標6桁+kv)を"
             "1バスへ ②重複エッジ(同一バス対+同一経路)を1本へ(parはmax保存・本物の"
             "複線par>1は不変)。除去であって接続追加でない。west断片化2531→544成分・"
             "線二重計上の是正(境界線インピーダンス半減の解消)。"
             "--no-dedup-nodes で v4 相当(dedup無し)を再現可 "
             "(docs/reports/default_on_decision_2026-07-10.md)",
}
BACKBONE_KV = 154.0     # transforms.reduce_to_backbone と同じ閾値(WEST_AC_ANALYSIS)


def fingerprint(Y) -> str:
    """行列の再現性フィンガープリント(CSR正規形の sha256 先頭16桁)。"""
    import hashlib
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(Y.data).tobytes())
    h.update(np.ascontiguousarray(Y.indices).tobytes())
    h.update(np.ascontiguousarray(Y.indptr).tobytes())
    h.update(np.array(Y.shape).tobytes())
    return h.hexdigest()[:16]


def kron_reduce(Y, keep_mask):
    """Kron 縮約(回路論的に厳密な等価回路): Y_red = Ybb − Ybi · Yii⁻¹ · Yib.

    消去バスの影響(低圧網・シャント込み)を残置バス間の等価アドミタンスに
    畳み込む。捏造ではなく厳密な回路変換であり、provenance は "kron" と明示。

    残置バスを含まない連結成分は縮約の定義域外(Yii が特異)なので丸ごと
    落とし、件数を返す(正直に記録)。

    Returns:
        (Y_red csr, kept_idx, n_dropped_buses, fill_density)
    """
    import scipy.sparse.csgraph as csg
    from scipy.sparse.linalg import splu

    keep_mask = np.asarray(keep_mask, dtype=bool)
    pattern = (abs(Y) > 0).astype(np.int8)
    _n, labels = csg.connected_components(pattern, directed=False)
    comp_keep = np.unique(labels[keep_mask])
    in_scope = np.isin(labels, comp_keep)
    kept_idx = np.where(keep_mask & in_scope)[0]
    elim_idx = np.where(~keep_mask & in_scope)[0]
    n_dropped = int(np.sum(~in_scope))

    Ycsc = Y.tocsc()
    Ybb = Ycsc[kept_idx][:, kept_idx].toarray()
    if elim_idx.size:
        Ybi = Ycsc[kept_idx][:, elim_idx].tocsc()
        Yib = Ycsc[elim_idx][:, kept_idx].tocsc()
        Yii = Ycsc[elim_idx][:, elim_idx].tocsc()
        lu = splu(Yii)
        # メモリを抑えるため右辺を列チャンクで解く(west: 8k消去×1k残置)
        chunk = 256
        for s in range(0, kept_idx.size, chunk):
            e = min(s + chunk, kept_idx.size)
            X = lu.solve(Yib[:, s:e].toarray())
            Ybb[:, s:e] -= Ybi @ X
    Yred = sp.csr_matrix(Ybb)
    Yred.eliminate_zeros()
    fill = float(Yred.nnz) / max(Yred.shape[0] ** 2, 1)
    return Yred, kept_idx, n_dropped, fill


def extract_bdc(net):
    """DC 行列 Bbus(pandapower 公式 makeBdc 出力)を回収する。

    rundcpp はコピーに対して実行(AC 側の _ppc を汚さない)。バス順序が AC の
    Ybus と同一であることを呼び出し側で検証すること。
    """
    import copy as _copy
    net_dc = _copy.deepcopy(net)
    pp.rundcpp(net_dc)
    internal = net_dc._ppc["internal"]
    Bbus = sp.csr_matrix(internal["Bbus"])
    lookup = net_dc._pd2ppc_lookups["bus"]
    bus_ids = np.full(Bbus.shape[0], -1, dtype=int)
    for pd_idx in net_dc.bus.index:
        ppc_idx = int(lookup[pd_idx])
        if 0 <= ppc_idx < Bbus.shape[0] and bus_ids[ppc_idx] == -1:
            bus_ids[ppc_idx] = int(pd_idx)
    return Bbus, bus_ids


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
    internal = ppc.get("internal", {})
    Y = internal.get("Ybus")
    if Y is None or Y.shape[0] == 0:
        raise RuntimeError("Ybus was not assembled (pd2ppc failed)")
    Y = Y.tocsr()
    lookup = net._pd2ppc_lookups["bus"]          # pd bus idx -> ppc idx
    ppc_bus_ids = np.full(Y.shape[0], -1, dtype=int)
    for pd_idx in net.bus.index:
        ppc_idx = int(lookup[pd_idx])
        if 0 <= ppc_idx < Y.shape[0] and ppc_bus_ids[ppc_idx] == -1:
            ppc_bus_ids[ppc_idx] = int(pd_idx)
    return Y, ppc_bus_ids, internal


def branch_bundle(net, internal, Y):
    """枝行列 Yf/Yt と枝表(v3)を検証つきで取り出す。

    枝順序 = ppci 内部順。`_pd2ppc_lookups["branch"]` が
    {"line": (0, n_line), "trafo": (n_line, n_line+n_trafo)} を保証するので、
    行 i<n_line は net.line.iloc[i]、以降は net.trafo に対応する。
    その対応を internal branch 配列の F_BUS/T_BUS で行ごとに検証し、
    再構成恒等式 Ybus == Cf'·Yf + Ct'·Yt + diag(Ysh) を機械精度で確認する。
    """
    from pandapower.pypower.idx_brch import F_BUS, T_BUS, TAP
    from pandapower.pypower.idx_bus import BS, GS

    Yf = internal["Yf"].tocsr()
    Yt = internal["Yt"].tocsr()
    br = internal["branch"]
    bus_arr = internal["bus"]
    base = float(internal.get("baseMVA", 100.0))
    lk = net._pd2ppc_lookups["branch"]
    l0, l1 = lk["line"]
    t0, t1 = lk.get("trafo", (l1, l1))
    if Yf.shape[0] != br.shape[0] or t1 != br.shape[0]:
        raise RuntimeError("branch matrix/lookup shape mismatch")

    # --- 枝表(from/to は ybus_index = internal 順そのもの) ---
    rows = []
    line_idx = list(net.line.index)
    trafo_idx = list(net.trafo.index)
    for i in range(br.shape[0]):
        fb, tb = int(br[i, F_BUS].real), int(br[i, T_BUS].real)
        tap = float(br[i, TAP].real) or 1.0
        if l0 <= i < l1:
            li = line_idx[i - l0]
            rows.append((i, "line", int(li), str(net.line.at[li, "name"]),
                         fb, tb, float(net.line.at[li, "length_km"]),
                         int(net.line.at[li, "parallel"] or 1), tap))
        else:
            ti = trafo_idx[i - t0]
            rows.append((i, "trafo", int(ti), str(net.trafo.at[ti, "name"]),
                         fb, tb, 0.0,
                         int(getattr(net.trafo.at[ti, "parallel"], "real",
                                     net.trafo.at[ti, "parallel"]) or 1), tap))

    # --- 検証①: 枝順序(lookup 行の F_BUS が pandapower 側の from/hv と一致) ---
    lookup_bus = net._pd2ppc_lookups["bus"]
    n_mis = 0
    for i, kind, pidx, _nm, fb, _tb, _L, _p, _tap in rows:
        want = (int(lookup_bus[int(net.line.at[pidx, "from_bus"])])
                if kind == "line"
                else int(lookup_bus[int(net.trafo.at[pidx, "hv_bus"])]))
        if want != fb:
            n_mis += 1
    # --- 検証②: 再構成恒等式 ---
    nb, nl = Y.shape[0], br.shape[0]
    ii = np.arange(nl)
    Cf = sp.csr_matrix((np.ones(nl), (ii, br[:, F_BUS].real.astype(int))),
                       shape=(nl, nb))
    Ct = sp.csr_matrix((np.ones(nl), (ii, br[:, T_BUS].real.astype(int))),
                       shape=(nl, nb))
    Ysh = (bus_arr[:, GS].real + 1j * bus_arr[:, BS].real) / base
    Yrec = Cf.T @ Yf + Ct.T @ Yt + sp.diags(Ysh)
    drec = abs(Y - Yrec.tocsr())
    rec_err = float(drec.max()) if drec.nnz else 0.0
    rec_rel = rec_err / (float(abs(Y).max()) or 1.0)
    checks = {"branch_order_mismatches": int(n_mis),
              "reconstruction_rel_err": rec_rel}
    return Yf, Yt, rows, checks


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


def export_island(island, freq, nodes, edges, out_dir, dedup_nodes=True,
                  site_trafos=False, deenergize_unbuilt=False):
    t0 = time.time()
    geom = {}
    net, bus_of, bstats = build_island_net(island, nodes, edges, freq, geom,
                                           dedup_nodes=dedup_nodes,
                                           site_trafos=site_trafos,
                                           deenergize_unbuilt=deenergize_unbuilt)
    n_refs = add_ref_per_component(net)
    Y, bus_ids, internal = extract_ybus(net)
    checks = verify(Y, bus_ids, net)

    # --- 枝行列 Yf/Yt + 枝表(v3) ---
    Yf, Yt, branch_rows, br_checks = branch_bundle(net, internal, Y)
    checks.update(br_checks)

    # --- DC 行列(v2): 公式 Bbus。AC と同一バス順序であることを検証 ---
    Bbus, bus_ids_dc = extract_bdc(net)
    if Bbus.shape[0] == Y.shape[0] and np.array_equal(bus_ids, bus_ids_dc):
        dc_aligned = True
    else:                                   # 順序不一致は並べ替えて整合
        dc_aligned = False
        pos = {int(b): i for i, b in enumerate(bus_ids_dc)}
        perm = np.array([pos.get(int(b), -1) for b in bus_ids])
        if (perm >= 0).all():
            Bbus = Bbus[perm][:, perm]
            dc_aligned = True
    checks["dc_bus_order_aligned"] = bool(dc_aligned)

    from src.powerflow.ybus_gate import ybus_gate
    gate = ybus_gate(net)

    # --- Kron 縮約バックボーン(v2): ≥BACKBONE_KV を残置し厳密縮約 ---
    # 島の最高電圧が閾値未満(okinawa=132kV系)なら、その島の基幹=最高電圧
    # クラスへフォールバックする(空のバックボーンを出荷しない)。
    kv_arr = np.array([float(net.bus.at[int(b), "vn_kv"]) if b >= 0 else 0.0
                       for b in bus_ids])
    backbone_kv = BACKBONE_KV
    if not (kv_arr >= backbone_kv).any():
        backbone_kv = float(kv_arr.max())
    keep_mask = kv_arr >= backbone_kv
    Yred, kept_idx, n_dropped, fill = kron_reduce(Y, keep_mask)
    dsym_r = abs(Yred - Yred.T)
    checks["backbone_symmetry_max_abs_err"] = (float(dsym_r.max())
                                               if dsym_r.nnz else 0.0)

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

    # --- 枝表 CSV ---
    with open(os.path.join(out_dir, f"{island}_branch.csv"), "w",
              newline="") as f:
        w = csv.writer(f)
        w.writerow(["branch_index", "kind", "pp_index", "name",
                    "from_ybus_index", "to_ybus_index", "length_km", "par",
                    "tap"])
        w.writerows(branch_rows)

    # --- npz(scipy CSR + Bbus + Yf/Yt + バス/枝配列を同梱) ---
    np.savez_compressed(
        os.path.join(out_dir, f"{island}.npz"),
        ybus_version=np.array([YBUS_VERSION]),
        data=Y.data, indices=Y.indices, indptr=Y.indptr,
        shape=np.array(Y.shape), base_mva=np.array([100.0]), f_hz=np.array([freq]),
        bdc_data=Bbus.data, bdc_indices=Bbus.indices, bdc_indptr=Bbus.indptr,
        yf_data=Yf.data, yf_indices=Yf.indices, yf_indptr=Yf.indptr,
        yt_data=Yt.data, yt_indices=Yt.indices, yt_indptr=Yt.indptr,
        branch_shape=np.array(Yf.shape),
        branch_from=np.array([r[4] for r in branch_rows]),
        branch_to=np.array([r[5] for r in branch_rows]),
        bus_pp=np.array([r[1] for r in rows]),
        bus_kv=np.array([r[3] for r in rows]),
        bus_lat=np.array([r[4] for r in rows]),
        bus_lon=np.array([r[5] for r in rows]))

    # --- .mat(MATLAB: sparse complex + DC行列 + 枝行列 + 属性) ---
    from scipy.io import savemat
    savemat(os.path.join(out_dir, f"{island}.mat"), {
        "Ybus": Y.tocsc(),                     # MATLAB native sparse
        "Bbus": Bbus.tocsc(),                  # DC 行列(PTDF/DC潮流用)
        "Yf": Yf.tocsc(), "Yt": Yt.tocsc(),    # 枝行列(If = Yf*V)
        "branch_from": np.array([r[4] for r in branch_rows]),   # 0-based
        "branch_to": np.array([r[5] for r in branch_rows]),
        "branch_kind": np.array([r[1] for r in branch_rows], dtype=object),
        "branch_name": np.array([r[3] for r in branch_rows], dtype=object),
        "branch_par": np.array([r[7] for r in branch_rows]),
        "ybus_version": YBUS_VERSION,
        "base_mva": 100.0, "f_hz": freq,
        "bus_kv": np.array([r[3] for r in rows]),
        "bus_lat": np.array([r[4] for r in rows]),
        "bus_lon": np.array([r[5] for r in rows]),
        "bus_name": np.array([r[2] for r in rows], dtype=object),
        "bus_region": np.array([r[6] for r in rows], dtype=object),
    }, do_compression=True)

    # --- バックボーン縮約(≥BACKBONE_KV)の出荷 ---
    bb_rows = [rows[i] for i in kept_idx]
    with open(os.path.join(out_dir, f"{island}_backbone_bus.csv"), "w",
              newline="") as f:
        w = csv.writer(f)
        w.writerow(["ybus_index", "pp_bus", "name", "vn_kv", "lat", "lon",
                    "region", "full_index"])
        for j, r in enumerate(bb_rows):
            w.writerow([j, r[1], r[2], r[3], r[4], r[5], r[6],
                        int(kept_idx[j])])
    savemat(os.path.join(out_dir, f"{island}_backbone.mat"), {
        "Ybus": Yred.tocsc(), "ybus_version": YBUS_VERSION,
        "reduction": f"kron(keep >= {backbone_kv:.0f} kV)",
        "base_mva": 100.0, "f_hz": freq,
        "bus_kv": np.array([r[3] for r in bb_rows]),
        "bus_lat": np.array([r[4] for r in bb_rows]),
        "bus_lon": np.array([r[5] for r in bb_rows]),
        "bus_name": np.array([r[2] for r in bb_rows], dtype=object),
        "full_index": kept_idx,
    }, do_compression=True)
    np.savez_compressed(
        os.path.join(out_dir, f"{island}_backbone.npz"),
        ybus_version=np.array([YBUS_VERSION]),
        data=Yred.data, indices=Yred.indices, indptr=Yred.indptr,
        shape=np.array(Yred.shape), full_index=kept_idx,
        bus_kv=np.array([r[3] for r in bb_rows]),
        bus_lat=np.array([r[4] for r in bb_rows]),
        bus_lon=np.array([r[5] for r in bb_rows]))

    meta = {
        "island": island, "f_hz": freq,
        "ybus_version": YBUS_VERSION,
        "fingerprint": fingerprint(Y),
        "n_bus": int(Y.shape[0]), "nnz": int(Y.nnz),
        "density": float(Y.nnz) / (Y.shape[0] ** 2),
        "n_line": int(len(net.line)), "n_trafo": int(len(net.trafo)),
        "trafo_nameplate": {
            "n_applied": int(bstats.get("n_trafo_nameplate", 0)),
            "source": "transformer_sources.jsonl(existing) → structures/*.json"
                      "(source=nameplate) → sn_mva/parallel (v4)",
        },
        "dedup_nodes": {
            "enabled": bool(dedup_nodes),
            "n_node_merged": int(bstats.get("n_dedup_merged", 0)),
            "n_edge_dup_removed": int(bstats.get("n_edge_dup_removed", 0)),
            "note": "介入#21(v5既定ON): bbox二重抽出の除去。"
                    "--no-dedup-nodes=v4相当",
        },
        "site_trafos": {
            "enabled": bool(site_trafos),
            "n_added": int(bstats.get("n_site_trafo", 0)),
            "note": "介入#22(既定OFF): 同名変電所+0.6kmの異電圧階級を連結",
        },
        "deenergize_unbuilt": {
            "enabled": bool(deenergize_unbuilt),
            "n_lines": int(bstats.get("n_deenergized", 0)),
            "note": "介入#23(既定OFF): 未供用線をin_service=Falseで建てる"
                    "(out-of-service枝はpandapowerがYbusから自動除外)",
        },
        "n_components_refs": int(n_refs),
        "dc": {"included": True, "nnz": int(Bbus.nnz),
               "aligned": bool(checks["dc_bus_order_aligned"])},
        "branch_matrices": {"included": True, "n_branch": int(Yf.shape[0]),
                            "order": "lines then trafos (lookup-verified)"},
        "backbone": {
            "keep_kv_min": backbone_kv,
            "n_bus": int(Yred.shape[0]), "nnz": int(Yred.nnz),
            "fill_density": round(fill, 4),
            "n_dropped_buses": int(n_dropped),
            "fingerprint": fingerprint(Yred),
        },
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
    ap.add_argument("--dedup-nodes", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="bbox二重抽出のdedup(介入#21)。既定ON(v5.0.0)。"
                         "--no-dedup-nodes=v4相当(回帰比較用)")
    ap.add_argument("--site-trafos", action=argparse.BooleanOptionalAction,
                    default=False,
                    help="介入#22 サイト内変圧器リンク。既定OFF(正典比較性)")
    ap.add_argument("--deenergize-unbuilt", action=argparse.BooleanOptionalAction,
                    default=False,
                    help="介入#23 未供用線の正直化。既定OFF。ONにすると"
                         "out-of-service枝はYbusから自動除外される")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    built = json.load(open(BUILT))
    nodes, edges = built["nodes"], built["edges"]
    freq_of = dict(ISLANDS)

    metas = {}
    for island in args.islands:
        meta = export_island(island, freq_of[island], nodes, edges, args.out,
                             dedup_nodes=args.dedup_nodes,
                             site_trafos=args.site_trafos,
                             deenergize_unbuilt=args.deenergize_unbuilt)
        metas[island] = meta
        c = meta["checks"]
        bb = meta["backbone"]
        print(f"[{island}] bus={meta['n_bus']} nnz={meta['nnz']} "
              f"trafo={meta['n_trafo']} | sym={c['symmetry_rel_err']:.0e} "
              f"offdiag_p99={c['offdiag_rel_err_p99']:.1e} | "
              f"dc={'OK' if meta['dc']['aligned'] else 'MISALIGNED'} | "
              f"branch: n={meta['branch_matrices']['n_branch']} "
              f"order_mis={c['branch_order_mismatches']} "
              f"rec_rel={c['reconstruction_rel_err']:.1e} | "
              f"backbone {bb['n_bus']}bus fill={bb['fill_density']:.3f} "
              f"drop={bb['n_dropped_buses']} | "
              f"gate={'PASS' if meta['gate']['pass'] else 'FAIL'} "
              f"({meta['elapsed_s']}s)")

    from datetime import date
    with open(os.path.join(args.out, "meta.json"), "w") as f:
        json.dump({"generated": date.today().isoformat(),
                   "ybus_version": YBUS_VERSION,
                   "changelog": CHANGELOG,
                   "source": BUILT,
                   "note": "4 frequency islands are asynchronous; the national "
                           "Ybus is the block-diagonal direct sum of these.",
                   "islands": metas}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
