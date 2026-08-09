#!/usr/bin/env python3
"""感度行列で系統をスクリーニングする最小例。

反復解法を使わずに、行列ひとつの掛け算で次の3つを出します:

  1. 任意の注入パターンから枝潮流         flow = PTDF · injection
  2. 枝を1本止めたときの潮流の変化         flow' = flow + LODF[:,k]·flow[k]
  3. 地点別「1GW繋いだとき最も混む枝」     max_j |PTDF[j,b]|·1000 / capacity_j

3 は全地点を一度に出せるのが要点です。同じ答えを潮流の解き直しで得ると、
地点数だけ反復計算を回すことになり西日本では数日かかります。

usage:
    python screen.py                 # 沖縄（最小・数秒）
    python screen.py hokkaido
    python screen.py west            # 主成分 7,087 バス（行列の生成に約5秒）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist" / "sensitivity"


def load(island: str):
    """配布物を読む。行列本体は git 管理外なので、無ければその場で作る。"""
    npz = DIST / f"{island}_sensitivity.npz"
    if not npz.exists():
        print(f"[{island}] 行列が無いので生成します（数秒〜）…")
        subprocess.run([sys.executable, str(ROOT / "scripts/sensitivity/build_sensitivity.py"),
                        "--islands", island], check=True, cwd=ROOT)
    d = np.load(npz)
    bus = pd.read_csv(DIST / f"{island}_bus.csv")
    br = pd.read_csv(DIST / f"{island}_branch.csv")
    return d, bus, br


def main() -> None:
    island = sys.argv[1] if len(sys.argv) > 1 else "okinawa"
    d, bus, br = load(island)
    ptdf = d["ptdf"].astype(np.float64)
    lodf = d["lodf"].astype(np.float64) if "lodf" in d else None
    bridge = d["is_bridge"].astype(bool) if "is_bridge" in d else np.zeros(len(br), bool)
    cap = br["capacity_mva"].to_numpy(dtype=float)

    print(f"\n=== {island}: {ptdf.shape[1]:,} バス × {ptdf.shape[0]:,} 枝 "
          f"（橋 {bridge.sum():,} 本は N-1 の一括評価から外れます）\n")

    # ── 1. 注入 → 枝潮流 ─────────────────────────────────────
    # 最高電圧のバスに 1,000 MW 入れてみる（参照バスが残りを吸収する前提）
    src = int(bus["kv"].idxmax())
    inj = np.zeros(ptdf.shape[1])
    inj[src] = 1000.0
    flow = ptdf @ inj
    print(f"1) {bus.at[src, 'built_node_id']}（{bus.at[src, 'kv']:.0f}kV）に 1,000 MW 注入")
    top = np.argsort(-np.abs(flow))[:5]
    for k in top:
        print(f"     {br.at[k, 'kv']:>5.0f}kV {str(br.at[k, 'name'])[:34]:36s} "
              f"{flow[k]:+8.1f} MW（定格 {cap[k]:,.0f} MVA の {abs(flow[k])/cap[k]:5.1%}）")

    # ── 2. 枝を1本止める ─────────────────────────────────────
    if lodf is not None:
        cand = np.where(~bridge & (np.abs(flow) > 1.0))[0]
        if len(cand):
            k = int(cand[np.argmax(np.abs(flow[cand]))])
            after = flow + lodf[:, k] * flow[k]
            moved = np.argsort(-np.abs(after - flow))[:3]
            print(f"\n2) 最も潮流の大きい枝 #{k}（{br.at[k, 'kv']:.0f}kV, {flow[k]:+.1f} MW）を停止")
            for j in moved:
                print(f"     {br.at[j, 'kv']:>5.0f}kV {str(br.at[j, 'name'])[:34]:36s} "
                      f"{flow[j]:+8.1f} → {after[j]:+8.1f} MW")
            print("     ※ DC の枠内では LODF は近似ではなく厳密（解き直しと機械精度で一致）")

    # ── 3. 全地点の混雑感度を一括で ───────────────────────────
    import time
    t0 = time.perf_counter()
    capf = np.where(np.isfinite(cap) & (cap > 0), cap, np.inf)
    stress = np.zeros(ptdf.shape[1])
    for c0 in range(0, ptdf.shape[1], 512):          # メモリを抑えるため列を分割
        c1 = min(c0 + 512, ptdf.shape[1])
        stress[c0:c1] = (np.abs(ptdf[:, c0:c1]) * 1000.0 / capf[:, None]).max(axis=0) * 100
    sec = time.perf_counter() - t0

    out = bus.copy()
    out["worst_loading_pct_per_gw"] = stress.round(2)
    # 参照バス（slack）の列は定義上ゼロ。そこへの注入は「潮流を動かさない」のではなく
    # 「参照点なので変化を測れない」だけなので、地点の比較からは外す。
    out = out.drop(index=int(d["slack_col"][0]), errors="ignore")
    out = out.sort_values("worst_loading_pct_per_gw")
    csv = Path(__file__).parent / f"screening_{island}.csv"
    out.to_csv(csv, index=False)

    print(f"\n3) 全 {ptdf.shape[1]:,} 地点の「1GW 繋いだときの最悪混雑」を "
          f"{sec*1000:.0f} ミリ秒で算出 → {csv.name}")
    good = out.head(3)
    bad = out.tail(3).iloc[::-1]
    print("   繋ぎやすい地点:")
    for _, r in good.iterrows():
        print(f"     {r['built_node_id']:28s} {r['kv']:>5.0f}kV  {r['worst_loading_pct_per_gw']:7.1f} %/GW")
    print("   繋ぐと詰まる地点:")
    for _, r in bad.iterrows():
        print(f"     {r['built_node_id']:28s} {r['kv']:>5.0f}kV  {r['worst_loading_pct_per_gw']:7.1f} %/GW")
    print("\n   ※ 直流近似・熱容量のみのスクリーニングです。確定値は AC で解き直してください。")


if __name__ == "__main__":
    main()
