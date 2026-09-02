#!/usr/bin/env python3
"""介入#40(人口メッシュ傾斜)の再判定行列 — 全国メッシュ整備後の ON/OFF 比較.

#40 は 2026-08-30 に「手元メッシュが関東・中部タイルのみの部分被覆」を理由に既定OFFで
登録された(docs/MODEL_INTERVENTIONS.md #40)。全国 1次メッシュ(≈180タイル)を
`scripts/fetch_estat_mesh.py --all-japan` で整備した後、同じ物差しで再判定する。

判定材料(台帳の再判定条件そのもの):
  0. メッシュ被覆: 人口合計 ≈ 1.26億(国勢調査2020 総人口 126,146,099)であること
  1. 江田島4バス(広島県・県別×電圧階級一様按分で 34.47MW/バス=実勢の4〜5倍)が
     ON で半減方向に動くこと(標的の症状が消えるか)
  2. east/west フルAC(ピーク断面)が dc_fallback に退行しないこと(08-30 の退行理由)
  3. west backbone AC 維持・west 24/24 AC 維持
  4. slack(需給整合KPI)の変化

使い方:
    PYTHONPATH=. python3 scripts/eval_pop_tilt_matrix.py --check-only     # 0と1だけ(軽い)
    PYTHONPATH=. python3 scripts/eval_pop_tilt_matrix.py                  # 全行列(重い・~1h)
    PYTHONPATH=. python3 scripts/eval_pop_tilt_matrix.py --cases west_sel east_sel

出力: docs/reports/pop_tilt_rejudge_<date>.{json,md}
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

REPORTS = "docs/reports"
SCRATCH = "output/pop_tilt_rejudge"
CENSUS_2020_TOTAL = 126_146_099        # 国勢調査2020 総人口(総務省統計局・確定値)

# 江田島市(広島県)の概略bbox — 江田島・能美島。バス名の照合と併用し、一覧を開示する
ETAJIMA_BBOX = (34.15, 34.33, 132.38, 132.56)      # lat0, lat1, lon0, lon1

CASES = {
    #  name        : (islands, model, all_hours)
    "west_sel":      ("west", "full", False),
    "east_sel":      ("east", "full", False),
    "west_backbone": ("west", "backbone", False),
    "west_allhours": ("west", "full", True),
}


def mesh_coverage() -> dict:
    from src.powerflow.load_estimator import MESH_POP_DIR, _load_mesh_population
    import glob
    files = sorted(glob.glob(os.path.join(MESH_POP_DIR, "tblT001140S*.txt")))
    cells = _load_mesh_population(MESH_POP_DIR)
    pop = float(sum(c[2] for c in cells))
    return {
        "n_files": len(files),
        "n_cells": len(cells),
        "population_sum": round(pop),
        "census_2020_total": CENSUS_2020_TOTAL,
        "coverage_ratio": round(pop / CENSUS_2020_TOTAL, 4),
        "note": "1kmメッシュ人口(T001140001)の合計。秘匿・按分セルの扱いで確定値と"
                "数%ずれ得る。0.97以上なら全国被覆とみなす",
    }


def etajima_loads() -> dict:
    """west 網を1回組み、pop_tilt OFF/ON で allocate_loads だけ行い江田島バスの負荷を比べる。"""
    import scripts.run_full_powerflow_from_db as pf
    from src.powerflow.pref_demand import pref_zone_gwh

    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)
    t0 = time.perf_counter()
    net0, bus_of, _ = pf.build_island_net(
        "west", nodes, edges, pf.ISLAND_FREQ["west"], {},
        dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
    build_s = round(time.perf_counter() - t0, 1)

    # バス→(lat, lon, name)。bus_of は node index → bus
    lat0, lat1, lon0, lon1 = ETAJIMA_BBOX
    target = {}
    for ni, b in bus_of.items():
        n = nodes[int(ni)]
        la, lo = float(n["lat"]), float(n["lon"])
        nm = str(n.get("name", ""))
        if (lat0 <= la <= lat1 and lon0 <= lo <= lon1) or "江田島" in nm:
            target[int(b)] = {"name": nm, "lat": la, "lon": lo,
                              "kv": float(net0.bus.at[int(b), "vn_kv"])}

    out = {"build_s": build_s, "n_target_bus": len(target), "buses": target}
    for label, tilt in (("off", False), ("on", True)):
        net = copy.deepcopy(net0)
        pf.allocate_loads(net, cfg, pref_gwh=pref_gwh, pop_tilt=tilt)
        led = getattr(net, "_pop_tilt_ledger", None)
        per = {}
        for b in target:
            per[b] = round(float(net.load.loc[net.load.bus == b, "p_mw"].sum()), 2)
        out[label] = {
            "etajima_load_mw": round(sum(per.values()), 1),
            "per_bus_mw": per,
            "n_bus_tilted": (led or {}).get("n_bus_tilted"),
            "total_load_mw": round(float(net.load.p_mw.sum()), 1),
        }
    off, on = out["off"]["etajima_load_mw"], out["on"]["etajima_load_mw"]
    out["ratio_on_off"] = round(on / off, 3) if off else None
    return out


def run_case(name: str, tilt: bool, date: str) -> dict:
    islands, model, all_hours = CASES[name]
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, f"{name}_{'on' if tilt else 'off'}_{date}.json")
    cmd = [sys.executable, "scripts/uc_to_pf_built.py", "--islands", islands,
           "--model", model, "--pop-tilt" if tilt else "--no-pop-tilt", "--out", out]
    if all_hours:
        cmd.append("--all-hours")
    t0 = time.perf_counter()
    env = dict(os.environ, PYTHONPATH=".")
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    sec = round(time.perf_counter() - t0, 1)
    if r.returncode != 0 or not os.path.exists(out):
        return {"ok": False, "sec": sec, "cmd": " ".join(cmd),
                "stderr_tail": r.stderr[-1500:]}
    return summarize_case(name, out, sec)


def summarize_case(name: str, out: str, sec) -> dict:
    islands = CASES[name][0]
    with open(out, encoding="utf-8") as f:
        d = json.load(f)
    isl = d["islands"][islands]
    hours = isl.get("hours", {})
    solvers = [h.get("solver") for h in hours.values()]
    return {
        "ok": True, "sec": sec, "out": out,
        "mode": isl.get("mode"), "n_bus": isl.get("n_bus"),
        "n_hours": isl.get("n_hours"), "n_converged": isl.get("n_converged"),
        "all_converged": isl.get("all_converged"),
        "n_ac": sum(1 for s in solvers if s == "ac"),
        "n_dc_fallback": sum(1 for s in solvers if s and s != "ac"),
        "slack_abs_mw": {h: v.get("slack_abs_mw") for h, v in hours.items()},
        "vm_min": {h: v.get("vm_min") for h, v in hours.items()},
        "n_bus_tilted": (isl.get("pop_tilt_ledger") or {}).get("n_bus_tilted"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check-only", action="store_true",
                    help="メッシュ被覆と江田島負荷だけ(潮流は解かない)")
    ap.add_argument("--cases", nargs="*", default=list(CASES),
                    choices=list(CASES))
    ap.add_argument("--date", default=_dt.date.today().isoformat())
    ap.add_argument("--assemble", action="store_true",
                    help="潮流を解かず、SCRATCH に残る各ケースの JSON から行列を組み直す"
                         "(長い行列を途中で止めて分割実行したときの集計用)")
    args = ap.parse_args(argv)

    rep = {"date": args.date, "purpose": "介入#40 再判定(全国メッシュ整備後)",
           "mesh": mesh_coverage()}
    print(f"メッシュ: {rep['mesh']['n_files']}ファイル / {rep['mesh']['n_cells']:,}セル / "
          f"人口 {rep['mesh']['population_sum']:,} "
          f"({rep['mesh']['coverage_ratio']*100:.1f}% of 2020国勢調査)")
    rep["etajima"] = etajima_loads()
    e = rep["etajima"]
    print(f"江田島 {e['n_target_bus']}バス: OFF {e['off']['etajima_load_mw']}MW → "
          f"ON {e['on']['etajima_load_mw']}MW (×{e['ratio_on_off']})")
    if args.assemble:
        rep["matrix"] = {}
        for name in CASES:
            for tilt in (False, True):
                key = f"{name}/{'on' if tilt else 'off'}"
                out = os.path.join(SCRATCH, f"{name}_{'on' if tilt else 'off'}_{args.date}.json")
                if os.path.exists(out):
                    rep["matrix"][key] = summarize_case(name, out, sec=None)
                else:
                    rep["matrix"][key] = {"ok": False, "sec": None, "note": "未計測(分割実行で省略)"}
    elif not args.check_only:
        rep["matrix"] = {}
        for name in args.cases:
            for tilt in (False, True):
                key = f"{name}/{'on' if tilt else 'off'}"
                print(f"  {key} ...", flush=True)
                rep["matrix"][key] = run_case(name, tilt, args.date)
                r = rep["matrix"][key]
                print(f"    ok={r['ok']} {r.get('mode')} conv={r.get('n_converged')}/"
                      f"{r.get('n_hours')} ac={r.get('n_ac')} dc_fb={r.get('n_dc_fallback')} "
                      f"{r['sec']}s", flush=True)

    os.makedirs(REPORTS, exist_ok=True)
    jp = os.path.join(REPORTS, f"pop_tilt_rejudge_{args.date}.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    md = [f"# 介入#40 再判定 — 全国メッシュ整備後の人口傾斜 ON/OFF ({args.date})", "",
          f"- メッシュ: {rep['mesh']['n_files']} ファイル・{rep['mesh']['n_cells']:,} セル・"
          f"人口合計 {rep['mesh']['population_sum']:,}"
          f"（2020国勢調査比 {rep['mesh']['coverage_ratio']*100:.1f}%）",
          f"- 江田島 {e['n_target_bus']} バス負荷: OFF {e['off']['etajima_load_mw']} MW → "
          f"ON {e['on']['etajima_load_mw']} MW（×{e['ratio_on_off']}、"
          f"傾斜バス {e['on']['n_bus_tilted']}）", ""]
    if "matrix" in rep:
        md += ["| ケース | tilt | mode | conv | AC/DCfb | slack(MW) | vm_min |", "|---|---|---|---|---|---|---|"]
        for key, r in rep["matrix"].items():
            if not r["ok"]:
                md.append(f"| {key} | | **{r.get('note') or '失敗'}** | | | | |")
                continue
            sl = ", ".join(f"{h}:{v}" for h, v in list(r["slack_abs_mw"].items())[:3])
            vm = ", ".join(f"{h}:{v}" for h, v in list(r["vm_min"].items())[:3])
            md.append(f"| {key.split('/')[0]} | {key.split('/')[1]} | {r['mode']} | "
                      f"{r['n_converged']}/{r['n_hours']} | {r['n_ac']}/{r['n_dc_fallback']} | "
                      f"{sl} | {vm} |")
    md += ["", "判定はこの表を根拠に `docs/MODEL_INTERVENTIONS.md` #40 へ追記する（本ファイルは計測記録）。"]
    with open(jp.replace(".json", ".md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(f"-> {jp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
