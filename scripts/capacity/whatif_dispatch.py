#!/usr/bin/env python3
"""給電の置き方を変えたら過負荷はどうなるか（what-if・未適用）。

これまでの過負荷診断はすべて `balance_by_zone` を前提にしている:

    scale = min(zone需要 × (1+予備率) / zone容量合計, 1.0)
    gen.p_mw = gen.max_p_mw × scale

つまり **ゾーン内の発電の空間配分は銘板容量に完全比例**する。実系統はそうではない —
経済給電で安い基幹電源が焚かれ、ピーカーは止まり、太陽光は日射に従う。
**注入の地理が根本から違う**可能性がある。

この仮定は診断の結論を左右してきた。太陽光の既定値 10MW が潮流を歪めるのは、
まさに「銘板がそのまま空間配分になる」からで（`whatif_solar_default_2026-08-09.md`）、
給電を UC 解から与えれば**燃料別の総量が外から固定される**ため、水増し銘板の影響は
燃料内の配分だけに縮む。残っている east の 853% がこの仮定の産物なのかを測る。

  nameplate  現行。`balance_by_zone`（ゾーン内を銘板比例で一律スケール）
  uc         UC 解の時刻断面を `inject_dispatch_by_zone` で注入
             （地域×燃料の合計MWを、同燃料のPF側発電機へ容量比例で配分）

接続規則は本番の既定（介入#24 = cap）で固定し、**給電だけを差し替える**。

採用は人間判断。採るなら `docs/MODEL_INTERVENTIONS.md` に①根拠②帳簿③無効化を登録する。

usage:
    python3 scripts/capacity/whatif_dispatch.py --islands east
    python3 scripts/capacity/whatif_dispatch.py --islands east west --scenario fy2023r2
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "docs" / "reports"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_modules():
    """測る器は本番の関数をそのまま通す（診断と本番の食い違いを作らない）。"""
    pf = _load(ROOT / "scripts" / "run_full_powerflow_from_db.py", "pf_full")
    rs = _load(ROOT / "scripts" / "capacity" / "repair_search.py", "rs_disp")
    return pf, rs


def injection_shape(net) -> dict:
    """注入がどこに載っているか。太陽光ノードへの偏りを測る。"""
    tot = sol = 0.0
    n_on = 0
    by_fuel: dict[str, float] = defaultdict(float)
    for _i, r in net.gen.iterrows():
        p = float(r["p_mw"])
        if p <= 0:
            continue
        n_on += 1
        tot += p
        f = str(r.get("type") or "unknown").lower()
        by_fuel[f] += p
        if "solar" in f:
            sol += p
    return {"total_mw": round(tot, 1), "n_gen_on": n_on,
            "solar_mw": round(sol, 1),
            "solar_share": round(sol / tot, 4) if tot else 0.0,
            "top_fuel": {k: round(v, 1) for k, v in
                         sorted(by_fuel.items(), key=lambda x: -x[1])[:6]}}


def run(pf, rs, island, nodes, edges, cfg, pref_gwh, mode, uc_ctx) -> dict:
    t0 = time.time()
    net, bus_of, _ = pf.build_island_net(
        island, nodes, edges, pf.ISLAND_FREQ[island], {},
        dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
    pf.attach_generators(net, bus_of, nodes, island,
                         attach_mode=pf.GEN_ATTACH_DEFAULT)
    pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    n_comp, _ns, n_synth = pf.add_per_component_slacks(net)

    note = ""
    if mode == "nameplate":
        pf.balance_by_zone(net, cfg)
    else:
        from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
        uc, scn, t = uc_ctx["uc"], uc_ctx["scn"], uc_ctx["t"]
        regions = [r for r, (isl, _f) in pf.ISLAND_OF.items() if isl == island]
        fuel_by_zone = {r: uc_snapshot(uc, scn.generators, t, region=r)
                        for r in regions}
        demand = {r: float(scn.net_demand_r[r][t]) for r in regions
                  if r in scn.net_demand_r}
        load_before = net.load["p_mw"].copy()
        inject_dispatch_by_zone(net, fuel_by_zone, demand)
        note = f"t={t} scenario={uc_ctx['scenario']}"
        if mode == "uc_norm":
            # 対照条件: UC は需要も自前の断面へスケールし、しかも注入が需要に満たない
            # （west で 13.3% がスラック持ち）。そのままでは需要水準と不足分が交絡して
            # 「注入の置き場所」の効果を取り出せない。**需要を元に戻し、総注入を
            # 銘板比例と同じ 1.05×需要へ揃えて**、燃料・空間の配分だけを変数にする。
            net.load["p_mw"] = load_before
            want = float(net.load[net.load["in_service"]]["p_mw"].sum()) * 1.05
            got = float(net.gen["p_mw"].sum())
            if got > 0:
                net.gen["p_mw"] = net.gen["p_mw"] * (want / got)
            note += " normalized(需要復元・総注入=1.05×需要)"

    net_dc, dc, _a, _b = pf.solve_island(net, max_ac_buses=0)
    load_mw = float(net.load[net.load["in_service"]]["p_mw"].sum())
    return {"island": island, "mode": mode, "note": note,
            "n_components": n_comp, "n_synth_slack": int(n_synth),
            "load_mw": round(load_mw, 1),
            "injection": injection_shape(net),
            "dc_converged": bool(dc.get("converged")),
            "overload": rs.overload_stats(net_dc),
            "overload_power_basis": rs.overload_stats_power(net_dc),
            "seconds": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=["east", "west"])
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--hour", type=int, default=None,
                    help="既定=全国純需要が最大の時刻（銘板比例はピークを模すので揃える）")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    pf, rs = load_modules()
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    print(f"UC求解中... ({args.scenario})", flush=True)
    from src.uc.scenario import build_national_scenario
    from src.uc.solver import solve_uc
    t_uc = time.time()
    scn = build_national_scenario(scenario=args.scenario)
    uc = solve_uc(scn.to_uc_parameters())
    # 銘板比例はゾーン需要ピークを模した断面なので、比較はピーク時刻で揃える
    nat = [sum(scn.net_demand_r[r][t] for r in scn.net_demand_r)
           for t in range(len(next(iter(scn.net_demand_r.values()))))]
    t = args.hour if args.hour is not None else int(max(range(len(nat)),
                                                        key=lambda i: nat[i]))
    print(f"UC求解 {time.time() - t_uc:.0f}s / 断面 t={t} "
          f"（全国純需要 {nat[t]:,.0f} MW = 最大）", flush=True)
    uc_ctx = {"uc": uc, "scn": scn, "t": t, "scenario": args.scenario}

    res = []
    for island in args.islands:
        for mode in ("nameplate", "uc", "uc_norm"):
            r = run(pf, rs, island, nodes, edges, cfg, pref_gwh, mode, uc_ctx)
            o, inj = r["overload"], r["injection"]
            print(f"[{island:9s}] {mode:9s} | 過負荷 {o['n_over']:4,}/{o['n_line']:,} "
                  f"({o['over_share']:6.2%}) 最大 {o['max_pct']:>8}% "
                  f"超過 {o['excess_mw']:>10,.0f}MW | 注入 {inj['total_mw']:>9,.0f}MW "
                  f"稼働 {inj['n_gen_on']:>5,}機 太陽光 {inj['solar_share']:6.1%} "
                  f"| 偽電源 {r['n_synth_slack']:4,}  {r['seconds']:.0f}s", flush=True)
            res.append(r)

    (REPORTS / f"whatif_dispatch_{date}.json").write_text(
        json.dumps({"date": date, "scenario": args.scenario, "hour": t,
                    "gen_attach": pf.GEN_ATTACH_DEFAULT, "runs": res},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    L = [f"# 給電の置き方を変えたら過負荷はどうなるか（what-if・{date}）", "",
         "これまでの過負荷診断はすべて `balance_by_zone`＝**ゾーン内を銘板容量に比例して",
         "一律スケール**を前提にしていた。実系統は経済給電なので、注入の地理が根本から違う。",
         f"接続規則は本番既定（介入#24 = {pf.GEN_ATTACH_DEFAULT}）で固定し、給電だけ差し替えた。",
         f"UC シナリオ `{args.scenario}`・断面 t={t}（全国純需要が最大の時刻）。", "",
         "**`uc` は交絡している。** `inject_dispatch_by_zone` は需要側も UC 純需要へ",
         "スケールし、しかも注入が需要に届かない（west は 13.3% がスラック持ち）。",
         "そのままでは需要水準・不足分・配分の3つが同時に動く。**`uc_norm` が対照条件**で、",
         "需要を PF 側の値に戻し総注入を銘板比例と同じ 1.05×需要に揃えてある — ",
         "変数は**注入の燃料・空間配分だけ**。結論は `uc_norm` で読むこと。", "",
         "| 島 | 給電 | 過負荷 | 最大負荷率 | 超過潮流 | 注入合計 | 稼働機数 | 太陽光シェア | 偽電源 |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in res:
        o, inj = r["overload"], r["injection"]
        L.append(f"| {r['island']} | {r['mode']} | {o['n_over']:,} ({o['over_share']:.2%}) | "
                 f"{o['max_pct']}% | {o['excess_mw']:,.0f} MW | {inj['total_mw']:,.0f} MW | "
                 f"{inj['n_gen_on']:,} | {inj['solar_share']:.1%} | {r['n_synth_slack']:,} |")
    L += ["", "## 注入の燃料構成", "", "| 島 | 給電 | 上位燃料 |", "|---|---|---|"]
    for r in res:
        L.append(f"| {r['island']} | {r['mode']} | " +
                 " / ".join(f"{k} {v:,.0f}MW" for k, v in r["injection"]["top_fuel"].items())
                 + " |")
    L += ["", "---",
          "**未適用**。採否は人間判断。生成: `scripts/capacity/whatif_dispatch.py`（DC）", ""]
    (REPORTS / f"whatif_dispatch_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/whatif_dispatch_{date}.md")


if __name__ == "__main__":
    main()
