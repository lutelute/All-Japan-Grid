"""潮流計算結果を pf_buses.geojson / pf_branches.geojson として出力.

修正点 (vs 旧 aeef9bf):
  - 負荷配分を kV² → 実態反映型 (66/77kV 集中, 500/275kV ゼロ) に変更
  - 北海道サブシステムを検出・分離して独立解析
  - sld_data.json の Pd/Vm フィールドも更新

Usage::
    PYTHONPATH=. python scripts/gen_pf_geojson.py [--lf 0.25] [--hops 4]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
os.chdir(ROOT)

for _p in [
    os.path.join(ROOT, "..", "psdat-python"),
    os.path.expanduser("~/Documents/GitHub/psdat-python"),
]:
    if os.path.isdir(_p) and os.path.isdir(os.path.join(_p, "psdat")):
        sys.path.insert(0, os.path.abspath(_p))
        break

from src.matpower.exporter import build_matpower_case, BUS_I, BASE_KV, VM, VA, PD

OUT_DIR = "docs/data/powerflow"
SLD_JSON = "docs/data/powerflow/sld_data.json"


# ─────────────────────────────────────────────────────────────────────────────
def run_dc_pf(BUS: np.ndarray, BRANCH: np.ndarray,
              GEN: np.ndarray, baseMVA: float) -> dict:
    """DC潮流 (線形, 常に収束). θ = B^{-1} × P_inj を解く."""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla

    n = BUS.shape[0]
    bus_nums = BUS[:, 0].astype(int)
    bus_map = {int(b): i for i, b in enumerate(bus_nums)}

    from src.matpower.exporter import (
        F_BUS, T_BUS, BR_X, TAP, BUS_I, BUS_TYPE, PD, VM, VA, REF_BUS,
        GEN_BUS, PG
    )

    # 行列要素を積み上げ
    rows, cols, vals = [], [], []
    for k in range(BRANCH.shape[0]):
        fi = bus_map.get(int(BRANCH[k, F_BUS]))
        ti = bus_map.get(int(BRANCH[k, T_BUS]))
        if fi is None or ti is None:
            continue
        X = BRANCH[k, BR_X]
        if X < 1e-10:
            continue
        tap = BRANCH[k, TAP] or 1.0
        b = 1.0 / (X * tap)
        rows += [fi, ti, fi, ti]
        cols += [fi, ti, ti, fi]
        vals += [b, b, -b, -b]

    B = sp.coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()

    # P注入 (MW → pu): 負荷(負) + 発電(正)
    P_inj = np.zeros(n)
    for i in range(n):
        P_inj[i] = -BUS[i, PD] / baseMVA
    for g in range(GEN.shape[0]):
        bi = bus_map.get(int(GEN[g, GEN_BUS]))
        if bi is not None:
            P_inj[bi] += GEN[g, PG] / baseMVA

    total_gen = sum(GEN[g, PG] for g in range(GEN.shape[0]))
    total_load = BUS[:, PD].sum()
    print(f"  P注入バランス: 発電={total_gen:.0f} MW  負荷={total_load:.0f} MW  "
          f"差={total_gen - total_load:.0f} MW (スラックが吸収)")

    # スラックバスを接地
    ref_idx = np.where(BUS[:, BUS_TYPE].astype(int) == REF_BUS)[0]
    if len(ref_idx) == 0:
        ref_idx = np.array([0])
    ref = int(ref_idx[0])

    # 方程式: B × θ = P_inj (ref列・行を除外)
    pq_mask = np.ones(n, dtype=bool)
    pq_mask[ref] = False
    B_red = B[pq_mask, :][:, pq_mask]
    P_red = P_inj[pq_mask]

    # 対角スケーリングで前処理: D^{-1} B_red D^{-1} θ' = D^{-1} P_red, θ = D^{-1} θ'
    # (ラプラシアンは対角が常に正なのでスケーリング安全)
    d = np.array(B_red.diagonal())
    d = np.where(d > 0, d, 1.0)   # 0対角バス保護
    d_inv = 1.0 / np.sqrt(d)
    D_inv = sp.diags(d_inv, format="csr")
    B_scaled = D_inv @ B_red @ D_inv
    B_scaled = B_scaled + sp.eye(B_red.shape[0], format="csr") * 1e-8
    P_scaled = d_inv * P_red

    try:
        theta_scaled = spla.spsolve(B_scaled.tocsc(), P_scaled)
        theta_red = d_inv * theta_scaled
    except Exception as e:
        print(f"  ⚠ spsolve失敗: {e} — lsqrフォールバック")
        result = spla.lsqr(B_red + sp.eye(B_red.shape[0]) * 1e-4, P_red,
                           atol=1e-6, btol=1e-6, conlim=0, iter_lim=20000)
        theta_red = result[0]

    max_deg = float(np.degrees(np.abs(theta_red)).max())
    print(f"  DC解: max_angle={max_deg:.1f}°  (NaN={np.isnan(theta_red).sum()})")

    theta = np.zeros(n)
    theta[pq_mask] = theta_red

    V = np.exp(1j * theta)   # |V|=1 pu (DCでは定電圧)

    print(f"  DC潮流完了: angle={np.degrees(theta).min():.1f}–{np.degrees(theta).max():.1f}°")
    return {"converged": True, "V": V, "iterations": 1, "mismatch": 0.0}


def run_pf(case: dict, branch_dc: np.ndarray | None = None) -> dict:
    """AC NR を試み、収束しなければ DC フォールバックを行う.
    branch_dc: DC 用分岐行列。None の場合は case["BRANCH"] を使用。
               AC 用に高 X 分岐を除外した場合はここにフル BRANCH を渡す。
    """
    from psdat.models.powerflow import run_powerflow
    BUS = case["BUS"]; BRANCH = case["BRANCH"]; GEN = case["GEN"]
    t0 = time.monotonic()
    pf = run_powerflow(BUS, BRANCH, GEN, baseMVA=case["baseMVA"],
                       max_iter=50, tol=1e-5)
    dt = time.monotonic() - t0
    if pf.get("converged"):
        V = pf["V"]
        Vm = np.abs(V); Va = np.degrees(np.angle(V))
        print(f"  AC収束: {pf['iterations']}反復 {dt:.1f}s  "
              f"V={Vm.min():.3f}–{Vm.max():.3f}pu  "
              f"angle={Va.min():.1f}–{Va.max():.1f}°")
        return pf
    else:
        print(f"  AC収束せず → DCフォールバック (フル分岐使用)")
        dc_branch = branch_dc if branch_dc is not None else BRANCH
        return run_dc_pf(BUS, dc_branch, GEN, case["baseMVA"])


def compute_loading(BRANCH: np.ndarray, V: np.ndarray,
                    baseMVA: float, bus_map: dict) -> np.ndarray:
    """Return loading_pct per branch."""
    n_br = BRANCH.shape[0]
    loading = np.zeros(n_br)
    from src.matpower.exporter import F_BUS, T_BUS, BR_R, BR_X, BR_B, RATE_A, TAP
    for k in range(n_br):
        fi = bus_map[int(BRANCH[k, F_BUS])]
        ti = bus_map[int(BRANCH[k, T_BUS])]
        R = BRANCH[k, BR_R]; X = BRANCH[k, BR_X]
        B = BRANCH[k, BR_B]; tap = BRANCH[k, TAP] or 1.0
        rating = BRANCH[k, RATE_A]
        if rating <= 0:
            continue
        Vf = V[fi]; Vt = V[ti]
        y = 1.0 / complex(R, X) if (R**2 + X**2) > 1e-20 else 0
        yc = 0.5j * B
        If = (Vf / (tap**2) - Vt / tap) * y + Vf / (tap**2) * yc
        Sf = Vf / tap * np.conj(If) * baseMVA
        loading[k] = abs(Sf) / rating * 100.0
    return loading


# ─────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lf", type=float, default=0.25, help="負荷率 (load factor)")
    ap.add_argument("--hops", type=int, default=4, help="HVフィルタホップ数")
    args = ap.parse_args()

    print("=" * 60)
    print("全国潮流計算 → GeoJSON 出力")
    print(f"  load_factor={args.lf}  hv_hops={args.hops}")
    print("=" * 60)

    case = build_matpower_case(
        voltage_levels=[500, 275, 154, 110, 77, 66],
        load_factor=args.lf,
        hv_hops=args.hops,
        shunt_compensation="local",   # 線路充電によるQ余剰をリアクトルで補償
        compensation_alpha=0.9,
    )
    BUS = case["BUS"]; BRANCH = case["BRANCH"]
    bus_names = case["bus_names"]
    baseMVA = case["baseMVA"]
    n_bus = case["n_bus"]

    print(f"\n系統: {n_bus}バス  負荷合計: {BUS[:, PD].sum():.0f} MW")

    # 電圧別負荷分布を確認
    from collections import defaultdict
    kv_pd = defaultdict(float)
    for i in range(n_bus):
        kv_pd[int(round(BUS[i, BASE_KV]))] += BUS[i, PD]
    print("  負荷分布:")
    for kv in sorted(kv_pd, reverse=True):
        print(f"    {kv:4d}kV: {kv_pd[kv]:.0f} MW")

    # 高インピーダンス分岐の除外 (X > 0.4 pu → NR発散の原因)
    from src.matpower.exporter import BR_X
    hi_x_mask = BRANCH[:, BR_X] > 0.40
    n_removed = int(hi_x_mask.sum())
    BRANCH_pf = BRANCH[~hi_x_mask]
    if n_removed:
        print(f"\n⚠ 高X分岐除外: {n_removed}本 (X>0.40pu) → {BRANCH_pf.shape[0]}本でNR実行")

    case_pf = dict(case)
    case_pf["BRANCH"] = BRANCH_pf

    print("\n潮流計算...")
    pf = run_pf(case_pf, branch_dc=BRANCH)  # DCフォールバックはフルBRANCH使用

    converged = pf.get("converged", False)
    V = pf.get("V", None)
    if V is None or not converged:
        # フォールバック: 初期値 (V=1 pu)
        print("  フォールバック: 初期電圧 1.0 pu を使用")
        V = np.ones(n_bus, dtype=complex)

    Vm = np.abs(V)
    Va_deg = np.degrees(np.angle(V))

    bus_map = {int(BUS[i, BUS_I]): i for i in range(n_bus)}

    # ── pf_buses.geojson ─────────────────────────────────────────────────
    # 座標は all_ac_buses から取得
    with open(f"{OUT_DIR}/all_ac_buses.geojson") as f:
        all_buses = json.load(f)["features"]

    bus_coord = {}  # name → [lon, lat]
    bus_coord_by_id = {}
    for feat in all_buses:
        p = feat["properties"]
        geom = feat["geometry"]
        if geom and geom["type"] == "Point":
            bus_coord[p["name"]] = geom["coordinates"]
            bus_coord_by_id[p.get("bus_id")] = geom["coordinates"]

    gen_bus_set = set(int(g) - 1 for g in case["gen_buses_1idx"])
    gen_fuel_map = {int(case["gen_buses_1idx"][g])-1: case["gen_fuel"][g]
                    for g in range(case["n_gen"])}
    gen_pg_map = {int(BUS[i, BUS_I])-1: case["GEN"][g, 1]
                  for g, i in enumerate(
                      [int(case["gen_buses_1idx"][g])-1 for g in range(case["n_gen"])])}

    bus_features = []
    for i in range(n_bus):
        name = bus_names[i]
        kv = float(BUS[i, BASE_KV])
        is_gen = i in gen_bus_set

        coord = bus_coord.get(name)
        if coord is None:
            # 近似: all_ac_buses から同名検索できなければスキップ
            continue

        feat = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coord},
            "properties": {
                "bus_id": i,
                "name": name,
                "kv": kv,
                "v_pu": round(float(Vm[i]), 4),
                "v_ang": round(float(Va_deg[i]), 2),
                "is_gen": is_gen,
                "fuel": gen_fuel_map.get(i),
                "pg_mw": round(float(gen_pg_map.get(i, 0)), 1),
            },
        }
        bus_features.append(feat)

    pf_buses_path = f"{OUT_DIR}/pf_buses.geojson"
    with open(pf_buses_path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": bus_features},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n書き出し: {pf_buses_path} ({len(bus_features)} バス)")

    # ── pf_branches.geojson ───────────────────────────────────────────────
    loading_arr = compute_loading(BRANCH, V, baseMVA, bus_map)

    with open(f"{OUT_DIR}/all_ac_lines.geojson") as f:
        all_lines = json.load(f)["features"]

    # branch_id → geometry の対応を構築
    line_geom_by_ends = {}  # (from_name, to_name) → coordinates
    for feat in all_lines:
        p = feat["properties"]
        geom = feat["geometry"]
        if geom:
            key = (p.get("from_name", ""), p.get("to_name", ""))
            line_geom_by_ends[key] = geom["coordinates"]

    from src.matpower.exporter import F_BUS, T_BUS, BR_R, BR_X, RATE_A
    branch_features = []
    for k in range(BRANCH.shape[0]):
        fi = bus_map.get(int(BRANCH[k, F_BUS]))
        ti = bus_map.get(int(BRANCH[k, T_BUS]))
        if fi is None or ti is None:
            continue
        fn = bus_names[fi]; tn = bus_names[ti]

        # line geometry: look up from all_ac_lines or use point-to-point
        coords = line_geom_by_ends.get((fn, tn)) or line_geom_by_ends.get((tn, fn))
        if coords is None:
            cf = bus_coord.get(fn); ct = bus_coord.get(tn)
            if cf and ct:
                coords = [cf, ct]
            else:
                continue

        # Flow: compute from V (already done in loading_arr)
        R = BRANCH[k, BR_R]; X = BRANCH[k, BR_X]
        z = complex(R, X)
        Sf_mw = 0.0
        if abs(z) > 1e-15:
            Vf = V[fi]; Vt = V[ti]
            If = (Vf - Vt) / z
            Sf_mw = float((Vf * np.conj(If) * baseMVA).real)

        from_kv = float(BUS[fi, BASE_KV])

        feat = {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "from_bus": int(BRANCH[k, F_BUS]) - 1,
                "to_bus":   int(BRANCH[k, T_BUS]) - 1,
                "from_kv":  from_kv,
                "p_mw":     round(Sf_mw, 1),
                "q_mvar":   0.0,
                "loading_pct": round(float(loading_arr[k]), 1),
            },
        }
        branch_features.append(feat)

    pf_branches_path = f"{OUT_DIR}/pf_branches.geojson"
    with open(pf_branches_path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": branch_features},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"書き出し: {pf_branches_path} ({len(branch_features)} 分岐)")

    # ── sld_data.json の Pd/Vm を更新 ─────────────────────────────────────
    if os.path.exists(SLD_JSON):
        with open(SLD_JSON) as f:
            sld = json.load(f)

        sld_name_to_i = {bus_names[i]: i for i in range(n_bus)}
        updated = 0
        for b in sld["buses"]:
            i = sld_name_to_i.get(b.get("name"))
            if i is not None:
                b["vm"] = round(float(Vm[i]), 4)
                b["Pd"] = round(float(BUS[i, PD]), 1)
                updated += 1

        with open(SLD_JSON, "w") as f:
            json.dump(sld, f, ensure_ascii=False, separators=(",", ":"))
        print(f"更新: {SLD_JSON} ({updated}/{len(sld['buses'])} バス)")

    print("\n完了.")


if __name__ == "__main__":
    main()
