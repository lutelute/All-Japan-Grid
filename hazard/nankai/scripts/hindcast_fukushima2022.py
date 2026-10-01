#!/usr/bin/env python3
"""2022-03-16 福島県沖地震(東 50 Hz)の簡易ヒンドキャスト: 大規模な火力の即時脱落で UFR が動作し、全停しなかったことを再現できるか。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/hindcast_fukushima2022.py

一次資料(資源エネルギー庁 第46回 電力・ガス基本政策小委員会 資料3-1、経産省 電気保安 資料1、送配電網協議会「大規模停電回避に向けて」):
  - 火力 14 基・計 647.9 万 kW が停止(東京・東北)、水力 25 か所も停止(被害は軽微)
  - UFR 動作で東京エリア最大約 210 万戸・東北エリア約 16 万戸が停電。全停せず(「系統崩壊によるブラックアウトを防いだ」)
  - 周波数変換所の EPPS で 63 万 kW を緊急送電
仮定(記録に無い): 23:36 の東 50 Hz の需要 40 GW、脱落は 10 秒かけて起こる、需要家 1 戸あたり 1.3 kW(UFR 遮断量の換算)、
水力の停止は 25 か所で計 0.5 GW、発電機の内訳(火力 80%・水力 10%・原子力 0・その他 10%)。
比べるもの: 全停しないこと、UFR 遮断量が「約 226 万戸 × 1.3 kW ≒ 2.9 GW」と同じ桁であること。
"""
from __future__ import annotations
import copy, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, yaml
from nankai.dynamics import FreqCore, Link

NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def run(cfg, load=40000.0, lost=6479.0, hydro_lost=500.0, spread_s=10.0, epps=630.0):
    gens = [("thermal", 0.80 * load - lost, 0.80 * load * 1.08), ("thermal", lost, lost), ("hydro", 0.10 * load - hydro_lost, 0.10 * load * 1.3), ("hydro", hydro_lost, hydro_lost), ("solar", 0.10 * load, 0.10 * load)]
    core = FreqCore(cfg, 50.0, [g[0] for g in gens], [0] * len(gens), [g[1] for g in gens], [g[2] for g in gens], np.array([load]))
    core.links.append(Link("EPPS", epps, "external", np.array([0])))
    F = []; rec = lambda c: F.append(50 + c.df[0])
    n = 10
    for k in range(n):                                    # 10 秒かけて脱落(火力の一部を順に止める)
        core.p0[1] -= lost / n; core.pmax[1] = max(core.p0[1], 0)
        core.E[1] *= (n - k - 1) / (n - k) if n - k > 0 else 0
        if k == n // 2:
            core.trip_gens([3], "hydro")
        core.run_until(spread_s * (k + 1) / n, rec)
    core.run_until(120.0, rec)
    shed = float((core.L0 * core.shed * core.bus_on).sum())
    return min(F), shed, bool(core.collapsed[0])


def main():
    cfg = yaml.safe_load(open(os.path.join(NANKAI, "config", "dynamics_default.yaml"), encoding="utf-8"))
    print("観測: 全停せず・UFR で約 226 万戸(1.3 kW/戸なら約 2.9 GW)・EPPS 63 万 kW")
    for lab, c in (("既定(時限は対数間隔)", cfg),):
        for load in (35000.0, 40000.0, 45000.0):
            nad, shed, col = run(copy.deepcopy(c), load=load)
            print(f"{lab} 需要 {load/1e3:.0f} GW: 最下点 {nad:.2f} Hz・UFR {shed/1e3:.2f} GW・{'全停' if col else '全停せず'}")
    lin = copy.deepcopy(cfg)
    for st in lin["ufls"]["stages"]:
        st["spacing"] = "linear"
    for load in (35000.0, 40000.0, 45000.0):
        nad, shed, col = run(copy.deepcopy(lin), load=load)
        print(f"旧設定(等間隔) 需要 {load/1e3:.0f} GW: 最下点 {nad:.2f} Hz・UFR {shed/1e3:.2f} GW・{'全停' if col else '全停せず'}")


if __name__ == "__main__":
    main()
