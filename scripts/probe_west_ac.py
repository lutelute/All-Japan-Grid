#!/usr/bin/env python3
"""西日本フルAC正典化キャンペーン 第1波 — 介入候補のプローブ行列(2026-08-29).

オーナー指示「西ACが回るための正典を作っていきたい」。

正典の現状: west フルスケールはAC不成立(見せかけACはserved_fracガードで棄却済み、
docs/WEST_AC_ANALYSIS.md)。既知の候補レバー(v1.5 Known issues / #20/#22):
  - 介入#22 site_trafos: 同名サイトの異電圧ヤードを変圧器で連結(T-gap解消)
  - 介入#20 の factor 引き上げ 0.6→0.8 (Shikoku EGC 2024 実測換算≈0.8 —
    docs/reports/reactive_comp_provenance_2026-07-10.md で出典アンカー済み)
  - #20精緻化 hourly_shunts: シャントを時刻別負荷スケールに追従

本スクリプトは west ピーク断面(UC注入)で下の行列を回し、AC成立可否と
served_frac・電圧分布を測る。**正典は書き換えない**(プローブのみ・報告書出力)。

  v0: 現行既定 (rc=0.6, site_trafos=OFF)
  v1: +site_trafos
  v2: rc=0.8
  v3: site_trafos + rc=0.8
  v4: site_trafos + rc=0.8 + hourly_shunts(ピーク断面スケール)

出力: docs/reports/west_ac_probe_2026-08-29.{md,json}
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from scripts.run_full_powerflow_from_db import (  # noqa: E402
    BUILT, ISLAND_OF, add_per_component_slacks, allocate_loads,
    attach_generators, GEN_ATTACH_DEFAULT, build_island_net)
from scripts.uc_to_pf_built import solve_hour  # noqa: E402
from src.powerflow.load_estimator import load_demand_config  # noqa: E402
from src.powerflow.pipeline import add_reactive_compensation  # noqa: E402
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402

VARIANTS = [
    ("v0_base", dict(site_trafos=False, rc=0.6, hourly=False)),
    ("v1_site", dict(site_trafos=True, rc=0.6, hourly=False)),
    ("v2_rc08", dict(site_trafos=False, rc=0.8, hourly=False)),
    ("v3_site_rc08", dict(site_trafos=True, rc=0.8, hourly=False)),
    ("v4_site_rc08_hshunt", dict(site_trafos=True, rc=0.8, hourly=True)),
]


def main():
    print("UC求解...")
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    assert uc.is_optimal
    regions = sorted(r for r, (isl, _f) in ISLAND_OF.items() if isl == "west")
    net_dem = sum(np.asarray(scn.net_demand_r[r]) for r in regions)
    h = int(np.argmax(net_dem))
    built = json.load(open(BUILT))
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(built["nodes"])
    fuel_by_zone = {r: uc_snapshot(uc, scn.generators, h, region=r)
                    for r in regions}
    demand = {r: float(scn.net_demand_r[r][h]) for r in regions}

    results = []
    base_cache = {}
    for name, v in VARIANTS:
        t0 = time.monotonic()
        key = v["site_trafos"]
        if key not in base_cache:
            geom = {}
            b, bus_of, bstats = build_island_net(
                "west", built["nodes"], built["edges"], 60.0, geom,
                site_trafos=v["site_trafos"])
            attach_generators(b, bus_of, built["nodes"], "west",
                              attach_mode=GEN_ATTACH_DEFAULT)
            allocate_loads(b, cfg, pref_gwh=pref_gwh)
            base_cache[key] = (b, bstats)
        b0, bstats = base_cache[key]
        net = copy.deepcopy(b0)
        n_shunt = add_reactive_compensation(net, factor=v["rc"])
        add_per_component_slacks(net)
        inj = inject_dispatch_by_zone(net, fuel_by_zone, demand)
        if v["hourly"] and len(net.shunt):
            zb = net.bus["zone"]
            for si in net.shunt.index:
                z = zb.at[int(net.shunt.at[si, "bus"])]
                sc = inj.get(z, {}).get("load_scale")
                if sc:
                    net.shunt.at[si, "q_mvar"] = \
                        float(net.shunt.at[si, "q_mvar"]) * float(sc)
        pre = float(net.load.loc[net.load.in_service, "p_mw"].sum())
        net_s, mode = solve_hour(net, "ac")
        served = float(net_s.res_load.p_mw.sum()) if mode != "dc" or True \
            else 0.0
        vm = net_s.res_bus.vm_pu.dropna()
        row = dict(
            variant=name, config=v, mode=mode,
            n_site_trafo=int(bstats.get("n_site_trafo", 0) or 0),
            n_shunt=n_shunt,
            load_mw=round(pre, 1), served_mw=round(served, 1),
            served_frac=round(served / max(pre, 1e-9), 4),
            vm_min=round(float(vm.min()), 4) if len(vm) else None,
            vm_p01=round(float(vm.quantile(0.01)), 4) if len(vm) else None,
            vm_max=round(float(vm.max()), 4) if len(vm) else None,
            elapsed_s=round(time.monotonic() - t0, 1))
        results.append(row)
        print(f"[{name}] mode={mode} served={row['served_frac']:.1%} "
              f"vm[{row['vm_min']}, {row['vm_max']}] "
              f"site_trafo={row['n_site_trafo']} ({row['elapsed_s']:.0f}s)")

    doc = {"note": ("西フルAC正典化の第1波プローブ。正典は不変更。"
                    "mode=ac が出れば prune ladder + served≥95% ガードを"
                    "通過した正直なAC解"),
           "peak_hour": h, "demand_mw": round(float(net_dem[h]), 1),
           "variants": results}
    os.makedirs("docs/reports", exist_ok=True)
    json.dump(doc, open("docs/reports/west_ac_probe_2026-08-29.json", "w"),
              ensure_ascii=False, indent=1)
    lines = ["# 西フルAC プローブ第1波 (2026-08-29)\n",
             f"westピーク断面 t={h} 純需要 {net_dem[h]:,.0f} MW。"
             "正典不変更・プローブのみ。\n",
             "| variant | mode | served | vm_min | vm_p01 | vm_max | "
             "site_trafo | shunt |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(
            f"| {r['variant']} | **{r['mode']}** | {r['served_frac']:.1%} | "
            f"{r['vm_min']} | {r['vm_p01']} | {r['vm_max']} | "
            f"{r['n_site_trafo']} | {r['n_shunt']} |")
    open("docs/reports/west_ac_probe_2026-08-29.md", "w").write(
        "\n".join(lines) + "\n")
    print("-> docs/reports/west_ac_probe_2026-08-29.{md,json}")


if __name__ == "__main__":
    main()
