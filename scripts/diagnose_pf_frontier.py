#!/usr/bin/env python3
"""潮流計算の「どこまで計算できるか」を成分構造から診断する。

収束したかどうかだけでは計算の意味は測れない。網が断片化していれば、
各断片が自前の合成 slack で不均衡を吸収して形式的に収束するだけになる。
そこで**最大連結成分が需要のどれだけを抱えるか**を測り、
「計算に意味がある範囲」を定量化する。

潮流本体と同一のモデル構築器（build_island_net）を使うので、
ここで測った成分構造は実際に解いた系統そのもの。

usage: python3 scripts/diagnose_pf_frontier.py [--islands east west ...]
出力: docs/reports/pf_frontier_<date>.{md,json}
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import networkx as nx
import numpy as np
import pandapower.topology as top

from scripts.run_full_powerflow_from_db import (
    GEN_ATTACH_DEFAULT, attach_default_for, GEN_ZONE_BY_OPERATOR, ISLAND_FREQ, add_per_component_slacks, allocate_loads,
    attach_generators,
    balance_by_zone, build_island_net, load_demand_config, solve_island,
)

REPORTS = ROOT / "docs" / "reports"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"


def analyze(island: str, nodes, edges, cfg, pref_gwh, solve: bool = True) -> dict:
    """潮流本体と同じ手順で島ネットを組み、成分構造・収束・電圧品質を測る。"""
    freq = ISLAND_FREQ[island]
    net, bus_of, _ = build_island_net(island, nodes, edges, freq, {})
    attach_generators(net, bus_of, nodes, island, attach_mode=attach_default_for(island))
    allocate_loads(net, cfg, pref_gwh=pref_gwh)

    g = top.create_nxgraph(net, respect_switches=False)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)

    load_by_bus = net.load.groupby("bus")["p_mw"].sum().to_dict()
    gen_p = {}
    for tbl in ("gen", "sgen"):
        if len(getattr(net, tbl)):
            for b, p in getattr(net, tbl).groupby("bus")["p_mw"].sum().items():
                gen_p[b] = gen_p.get(b, 0.0) + float(p)

    total_load = float(sum(load_by_bus.values()))
    total_gen = float(sum(gen_p.values()))
    rows = []
    for c in comps:
        ld = sum(load_by_bus.get(b, 0.0) for b in c)
        gn = sum(gen_p.get(b, 0.0) for b in c)
        rows.append({"n_bus": len(c), "load_mw": round(ld, 1), "gen_mw": round(gn, 1)})

    main = rows[0] if rows else {"n_bus": 0, "load_mw": 0.0, "gen_mw": 0.0}
    # 需要を持つ成分だけが潮流上の実体（無負荷の断片は解いても情報がない）
    with_load = [r for r in rows if r["load_mw"] > 0.1]
    tiny = sum(1 for r in rows if r["n_bus"] <= 3)

    r = {
        "island": island,
        "n_bus": int(len(net.bus)),
        "n_components": len(comps),
        "total_load_mw": round(total_load, 1),
        "total_gen_mw": round(total_gen, 1),
        "main_component": main,
        "main_bus_share": round(main["n_bus"] / len(net.bus), 4) if len(net.bus) else 0,
        "main_load_share": round(main["load_mw"] / total_load, 4) if total_load else 0,
        "n_components_with_load": len(with_load),
        "n_components_tiny": tiny,
        "top10": rows[:10],
    }
    if not solve:
        return r

    # 解いて品質まで測る。max_ac_buses は上限なし（west 8213 を含め全島でACを試す）
    # 無効電力補償は本体の既定（介入。factor は config）。これを外すと west が
    # 非収束になり沖縄の電圧帯も崩れる = 本体と同じ手順でなければ到達範囲を測れない。
    from src.powerflow.pipeline import add_reactive_compensation
    rfac = cfg.get("reactive_compensation_factor", 0.6)
    r["reactive_comp_factor"] = rfac
    r["n_shunt"] = int(add_reactive_compensation(net, factor=rfac))
    n_comp, n_slack, n_synth = add_per_component_slacks(net)
    balance_by_zone(net, cfg, use_zone_src=GEN_ZONE_BY_OPERATOR)
    t0 = time.time()
    net_dc, dc, net_ac, ac = solve_island(net, max_ac_buses=10**9)
    r["n_synthetic_slack"] = int(n_synth)
    r["dc_converged"] = bool(dc.get("converged"))
    r["ac_converged"] = bool(ac.get("converged"))
    r["ac_error"] = ac.get("error")
    r["solve_sec"] = round(time.time() - t0, 1)
    if ac.get("converged"):
        vm = net_ac.res_bus["vm_pu"].to_numpy()
        vm = vm[~np.isnan(vm)]
        r["vm"] = {
            "n": int(len(vm)),
            "min": round(float(vm.min()), 4), "max": round(float(vm.max()), 4),
            "in_095_105": round(float(((vm >= 0.95) & (vm <= 1.05)).mean()), 4),
            "in_090_110": round(float(((vm >= 0.90) & (vm <= 1.10)).mean()), 4),
            "n_below_080": int((vm < 0.80).sum()),
            "n_above_110": int((vm > 1.10).sum()),
        }
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

    targets = args.islands or list(ISLAND_FREQ.keys())
    out = []
    for isl in targets:
        r = analyze(isl, nodes, edges, cfg, pref_gwh)
        out.append(r)
        print(f"[{isl:9s}] バス{r['n_bus']:5d} 成分{r['n_components']:4d} "
              f"最大成分 {r['main_component']['n_bus']:5d}バス({r['main_bus_share']:.1%}) "
              f"負荷 {r['main_component']['load_mw']:8.0f}MW / 全{r['total_load_mw']:8.0f}MW "
              f"({r['main_load_share']:.1%})  需要を持つ成分 {r['n_components_with_load']}")

    json.dump({"date": date, "islands": out},
              open(REPORTS / f"pf_frontier_{date}.json", "w"), ensure_ascii=False, indent=1)

    L = [
        f"# 潮流計算の到達範囲 — 成分構造による診断（{date}）",
        "",
        "収束したかどうかだけでは計算の意味は測れない。網が断片化していれば各断片が",
        "自前の合成 slack で不均衡を吸収し、形式的には収束する。**最大連結成分が需要の",
        "どれだけを抱えるか**が、実質的に解けている範囲を表す。",
        "",
        "## 1. 解けるか — 収束と電圧品質",
        "",
        "AC はバス数上限を設けずに全島で試行した。",
        "",
        "| 島 | バス | DC | AC | 求解秒 | vm 範囲 | 0.95-1.05 | 0.90-1.10 | <0.80 |",
        "|---|---:|---|---|---:|---|---:|---:|---:|",
    ]
    for r in out:
        v = r.get("vm")
        L.append(f"| {r['island']} | {r['n_bus']} | {'OK' if r.get('dc_converged') else 'FAIL'} | "
                 f"{'OK' if r.get('ac_converged') else 'FAIL'} | {r.get('solve_sec','—')} | "
                 + (f"{v['min']:.3f}–{v['max']:.3f} | {v['in_095_105']:.1%} | {v['in_090_110']:.1%} | {v['n_below_080']} |"
                    if v else "— | — | — | — |"))
    L += [
        "",
        "## 2. 意味があるか — 成分構造",
        "",
        "断片化した網は各断片が自前の合成 slack で不均衡を吸収し、形式的には収束する。",
        "**最大連結成分が需要のどれだけを抱えるか**が実質的に解けている範囲を表す。",
        "",
        "| 島 | 成分 | 合成slack | 最大成分バス | バス占有 | 最大成分負荷 | 全負荷 | **負荷占有** | 需要を持つ成分 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in out:
        L.append(f"| {r['island']} | {r['n_components']} | {r.get('n_synthetic_slack','—')} | "
                 f"{r['main_component']['n_bus']} | {r['main_bus_share']:.1%} | "
                 f"{r['main_component']['load_mw']:.0f} MW | {r['total_load_mw']:.0f} MW | "
                 f"**{r['main_load_share']:.1%}** | {r['n_components_with_load']} |")
    L += [
        "",
        "",
        "**読み方**: 負荷占有が高いほど「一枚の網として解けている」。低ければ、収束は",
        "断片ごとの局所解の寄せ集めであり、系統全体の潮流としては読めない。",
        "残る負荷（1 − 負荷占有）は孤立断片に載っており、その需要は合成 slack という",
        "**実在しない電源**が供給している。これが現時点の計算の限界そのもの。",
        "",
        "---",
        "生成: `scripts/diagnose_pf_frontier.py`（潮流本体と同一の `build_island_net` を使用）",
        "",
    ]
    (REPORTS / f"pf_frontier_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/pf_frontier_{date}.md")


if __name__ == "__main__":
    main()
