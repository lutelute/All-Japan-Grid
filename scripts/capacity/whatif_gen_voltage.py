#!/usr/bin/env python3
"""発電機の接続先を電圧階級に見合わせたら過負荷はどうなるか（what-if・未適用）。

`docs/reports/overload_vs_topology_2026-08-09.md` で分かった真因:

    attach_generators は発電所を **電圧を見ずに最寄りの変電所バス**へ繋いでいる
    （`best = min(sub_bus, key=距離)`）。66kV 変電所は数が桁違いに多いので、
    最寄りはほぼ 66kV になる。結果 east は発電容量の 53.2%（99GW）が 66kV バスに載り、
    姉崎火力 3,600MW も 66kV 接続。66kV 線が 1,000MW 超を流す潮流が立ち、
    east の過負荷 602 本のうち 521 本（87%）が 66kV、500kV は 0 本になる。

ここでは繋ぎ方を変えて効果を測る。**外部の接続電圧表を持ち込まない**のが要点で、
判定基準はモデル自身のデータだけから作る（出典の無い数値表を作ると捏造になる）:

  base   現行。最寄りの変電所バス（20km 以内）。
  site   **同一サイトの最高電圧**。半径 --site-km（既定 1.5km）以内に複数階級が
         あれば最も高い階級へ繋ぐ。発電所は自前の開閉所を持ち、そこにある最高電圧の
         ヤードへ引き込まれる、という実系統の形をなぞる。座標が同じ多階層変電所は
         `src/topology/coords.py` が扱っている構造そのもの。
  cap    **受電容量で選ぶ**。バスに集まる枝の合計容量（線: max_i_ka×kV×√3×並列数、
         変圧器: sn_mva×並列数）がその発電所の出力以上になる最寄りのバスへ繋ぐ。
         「1,144MW が 66kV 引込線 1 本の先にぶら下がる」という物理的に不可能な形を
         構造的に禁じる。閾値はモデル自身の枝容量なので外部出典を要さない。
  kvfit  **階級で選ぶ**。各電圧階級の 1 回線あたり容量の中央値を**モデル自身の導体定数から
         測り**（66kV 137MVA / 77kV 187 / 110kV 343 / 154kV 533 / 187kV 972 /
         220kV 1,372 / 275kV 1,905 / 500kV 6,928 MVA）、その発電所の出力を 1 回線で
         運べる最下位の階級を必要階級とする。半径 --kvfit-km（既定 25km）以内で
         必要階級以上の最寄りバスへ繋ぐ。大型機ほど遠くの高電圧を探すことになるが、
         これは実系統の姿と一致する — 姉崎火力(3,600MW)の 500kV バスはモデル内で
         5km、横浜火力(2,800MW)は 20km、川崎火力(3,420MW)は 10km 先にある。
         接続電圧表を外から持ち込まないので捏造にならない。

採用は人間判断。採るなら `docs/MODEL_INTERVENTIONS.md` に①根拠②帳簿③無効化を登録する。

usage:
    python3 scripts/capacity/whatif_gen_voltage.py --islands okinawa hokkaido
    python3 scripts/capacity/whatif_gen_voltage.py          # 全4島（DC・約10分）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "docs" / "reports"

MODES = ["base", "site", "cap", "kvfit"]


def load_pf():
    path = ROOT / "scripts" / "run_full_powerflow_from_db.py"
    spec = importlib.util.spec_from_file_location("pf_full", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pf_full"] = mod
    spec.loader.exec_module(mod)
    return mod


def bus_incident_mva(net) -> dict[int, float]:
    """各バスに集まる枝の合計容量（MVA）。これがそのバスの受電能力の上限を決める。"""
    cap: dict[int, float] = defaultdict(float)
    for _li, r in net.line.iterrows():
        if not r["in_service"]:
            continue
        kv = float(net.bus.at[int(r["from_bus"]), "vn_kv"])
        mva = float(r["max_i_ka"]) * kv * math.sqrt(3.0) * max(1, int(r.get("parallel") or 1))
        cap[int(r["from_bus"])] += mva
        cap[int(r["to_bus"])] += mva
    for _ti, r in net.trafo.iterrows():
        if not r["in_service"]:
            continue
        s = float(r["sn_mva"]) * max(1, int(r.get("parallel") or 1))
        cap[int(r["hv_bus"])] += s
        cap[int(r["lv_bus"])] += s
    return cap


def class_branch_mva(net) -> dict[float, float]:
    """電圧階級ごとの「1 回線あたり容量の中央値」をモデル自身の導体定数から測る。

    外部の接続電圧表を持ち込まずに「この出力はこの階級では運べない」を言うための基準。
    並列回線は 1 回線あたりに戻して数える（`parallel` で割る）。
    """
    per: dict[float, list[float]] = defaultdict(list)
    for _li, r in net.line.iterrows():
        if not r["in_service"]:
            continue
        kv = round(float(net.bus.at[int(r["from_bus"]), "vn_kv"]), 1)
        per[kv].append(float(r["max_i_ka"]) * kv * math.sqrt(3.0))
    out = {}
    for kv, v in per.items():
        v.sort()
        out[kv] = v[len(v) // 2]
    return out


def required_kv(p_mw: float, ladder: list[tuple[float, float]]) -> float:
    """その出力を 1 回線で運べる最下位の電圧階級。無ければ最上位。"""
    for kv, mva in ladder:
        if mva >= p_mw:
            return kv
    return ladder[-1][0] if ladder else 0.0


def attach_generators_variant(pf, net, bus_of, nodes, island, mode: str,
                              site_km: float = 1.5, max_km: float = 20.0,
                              kvfit_km: float = 25.0) -> dict:
    """`pf.attach_generators` の繋ぎ先だけを差し替えた版。

    発電所の集め方・重複除去（領土地域優先）は本番と同じ手順を踏む。ここを自前で
    書き直すと本番と診断が食い違うので、**本番の関数から手順をなぞる**。
    """
    import pandapower as pp
    from src.powerflow.region_attribution import area_of_coord

    sub_bus = [(i, bus_of[i], nodes[i]["lat"], nodes[i]["lon"])
               for i in bus_of if nodes[i].get("sub") == 1]
    if not sub_bus:
        return {"n_gen": 0}
    regions = [r for r, (isl, _f) in pf.ISLAND_OF.items() if isl == island]
    feats = []
    for region in regions:
        path = os.path.join(pf.ROOT, "data", f"{region}_plants.geojson")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for feat in json.load(f).get("features", []):
                feats.append((region, feat))
    chosen, extra = {}, []
    for region, feat in feats:
        g = feat.get("geometry") or {}
        oid = (feat.get("properties") or {}).get("osm_id")
        if oid is None or g.get("type") != "Point":
            extra.append((region, feat))
            continue
        cur = chosen.get(oid)
        if cur is None:
            chosen[oid] = (region, feat)
        else:
            lon, lat = g["coordinates"][0], g["coordinates"][1]
            home = area_of_coord(lat, lon)
            if region == home and cur[0] != home:
                chosen[oid] = (region, feat)
    feats = list(chosen.values()) + extra

    incident = bus_incident_mva(net) if mode == "cap" else {}
    ladder: list[tuple[float, float]] = []
    if mode == "kvfit":
        ladder = sorted(class_branch_mva(net).items())
        max_km = max(max_km, kvfit_km)
    n_gen = 0
    n_moved = 0
    moved_mw = 0.0
    kv_hist: dict[float, float] = defaultdict(float)
    for k, (region, feat) in enumerate(feats):
        g = feat.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        lon, lat = g["coordinates"][0], g["coordinates"][1]
        props = feat.get("properties", {})
        try:
            cap_mw = float(props.get("capacity_mw"))
        except (TypeError, ValueError):
            cap_mw = None
        fuel = props.get("fuel_type") or props.get("plant:source") or "unknown"
        if not isinstance(fuel, str) or fuel.startswith("http"):
            fuel = "unknown"
        if cap_mw is None or cap_mw <= 0:
            cap_mw = pf._DEFAULT_CAP.get(fuel, pf._CAP_FALLBACK)

        cands = [(pf._haversine_km(lat, lon, s[2], s[3]), s) for s in sub_bus]
        cands.sort(key=lambda t: t[0])
        near = [(d, s) for d, s in cands if d <= max_km]
        if not near:
            continue
        # 現行の繋ぎ先は 20km 以内の最寄り（kvfit で半径を伸ばしても比較の基準は動かさない）
        base_near = [(d, s) for d, s in near if d <= 20.0]
        if not base_near:
            continue
        base_pick = base_near[0][1][1]
        pick = base_pick
        if mode == "site":
            same_site = [(d, s) for d, s in near if d <= site_km]
            if same_site:
                # 同一サイト内で最高電圧、同点なら近い方
                pick = max(same_site,
                           key=lambda t: (float(net.bus.at[t[1][1], "vn_kv"]), -t[0]))[1][1]
        elif mode == "cap":
            ok = next((s for d, s in near if incident.get(s[1], 0.0) >= cap_mw), None)
            if ok is not None:
                pick = ok[1]
            else:
                # どこも受けきれない → 20km 内で最も受電容量の大きいバス
                pick = max(near, key=lambda t: incident.get(t[1][1], 0.0))[1][1]
        elif mode == "kvfit":
            need = required_kv(cap_mw, ladder)
            ok = next((s for d, s in near
                       if float(net.bus.at[s[1], "vn_kv"]) >= need - 0.5), None)
            if ok is not None:
                pick = ok[1]
            else:
                # 必要階級が半径内に無い → 半径内で最も高い階級（同点なら近い方）
                pick = max(near,
                           key=lambda t: (float(net.bus.at[t[1][1], "vn_kv"]), -t[0]))[1][1]
        if pick != base_pick:
            n_moved += 1
            moved_mw += cap_mw
        kv_hist[round(float(net.bus.at[pick, "vn_kv"]), 1)] += cap_mw
        try:
            pp.create_gen(net, bus=int(pick), p_mw=cap_mw, vm_pu=1.0,
                          name=str(props.get("name") or f"{region}_gen_{k}"),
                          type=fuel, max_p_mw=cap_mw, min_p_mw=0.0,
                          max_q_mvar=0.5 * cap_mw, min_q_mvar=-0.3 * cap_mw)
            n_gen += 1
        except (ValueError, TypeError):
            pass
    tot = sum(kv_hist.values()) or 1.0
    return {"n_gen": n_gen, "n_moved": n_moved, "moved_mw": round(moved_mw, 1),
            "ladder_note": (" / ".join(f"{kv:.0f}kV {mva:,.0f}MVA" for kv, mva in ladder)
                            if ladder else None),
            "kv_share": {str(k): round(v / tot, 4) for k, v in sorted(kv_hist.items())},
            "share_at_or_below_110kv": round(
                sum(v for k, v in kv_hist.items() if k <= 110.0) / tot, 4)}


def overload_stats(net) -> dict:
    if not len(net.res_line):
        return {"n_line": 0, "n_over": 0, "max_pct": None, "excess_mw": 0.0,
                "over_share": 0.0, "over_hv": 0, "over_lv": 0}
    df = net.res_line.join(net.line[["in_service", "from_bus"]], rsuffix="_l")
    df = df[df["in_service"].fillna(False)]
    lp = df["loading_percent"].dropna()
    if not len(lp):
        return {"n_line": 0, "n_over": 0, "max_pct": None, "excess_mw": 0.0,
                "over_share": 0.0, "over_hv": 0, "over_lv": 0}
    over_idx = lp[lp > 100.0].index
    pf_mw = df.loc[over_idx, "p_from_mw"].abs()
    excess = float((pf_mw * (1.0 - 100.0 / lp[over_idx])).sum()) if len(over_idx) else 0.0
    kv = df.loc[over_idx, "from_bus"].map(lambda b: float(net.bus.at[int(b), "vn_kv"]))
    return {"n_line": int(len(lp)), "n_over": int(len(over_idx)),
            "max_pct": round(float(lp.max()), 1),
            "excess_mw": round(excess, 1),
            "over_share": round(len(over_idx) / len(lp), 4),
            "over_lv": int((kv <= 110.0).sum()), "over_hv": int((kv >= 154.0).sum())}


def run(pf, island, nodes, edges, cfg, pref_gwh, mode, site_km, kvfit_km) -> dict:
    t0 = time.time()
    net, bus_of, bstats = pf.build_island_net(
        island, nodes, edges, pf.ISLAND_FREQ[island], {},
        dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
    if mode == "base":
        n = pf.attach_generators(net, bus_of, nodes, island)
        info = {"n_gen": n, "n_moved": 0, "moved_mw": 0.0}
        kvh: dict[float, float] = defaultdict(float)
        for _gi, gr in net.gen.iterrows():
            kvh[round(float(net.bus.at[int(gr["bus"]), "vn_kv"]), 1)] += float(gr["max_p_mw"])
        tot = sum(kvh.values()) or 1.0
        info["kv_share"] = {str(k): round(v / tot, 4) for k, v in sorted(kvh.items())}
        info["share_at_or_below_110kv"] = round(
            sum(v for k, v in kvh.items() if k <= 110.0) / tot, 4)
    else:
        info = attach_generators_variant(pf, net, bus_of, nodes, island, mode,
                                         site_km=site_km, kvfit_km=kvfit_km)
    pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    pf.add_per_component_slacks(net)
    pf.balance_by_zone(net, cfg)
    net_dc, dc, _a, _b = pf.solve_island(net, max_ac_buses=0)
    return {"island": island, "mode": mode, **info,
            "dc_converged": bool(dc.get("converged")),
            "overload": overload_stats(net_dc), "seconds": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*",
                    default=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--modes", nargs="*", default=MODES)
    ap.add_argument("--site-km", type=float, default=1.5,
                    help="site モードで「同一サイト」とみなす半径")
    ap.add_argument("--kvfit-km", type=float, default=25.0,
                    help="kvfit モードで必要階級のバスを探す半径（大型機の引込線に相当）")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    pf = load_pf()
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    res = []
    for island in args.islands:
        for mode in args.modes:
            r = run(pf, island, nodes, edges, cfg, pref_gwh, mode,
                    args.site_km, args.kvfit_km)
            o = r["overload"]
            print(f"[{island:9s}] {mode:5s} 繋ぎ替え {r['n_moved']:5,}台/"
                  f"{r['moved_mw']:9,.0f}MW  110kV以下 {r['share_at_or_below_110kv']:5.1%}  "
                  f"過負荷 {o['n_over']:4,}/{o['n_line']:,} ({o['over_share']:5.2%}) "
                  f"低圧側 {o['over_lv']:4,} 高圧側 {o['over_hv']:3,}  "
                  f"最大 {o['max_pct']}%  超過 {o['excess_mw']:,.0f}MW  {r['seconds']:.0f}s",
                  flush=True)
            res.append(r)

    (REPORTS / f"whatif_gen_voltage_{date}.json").write_text(
        json.dumps({"date": date, "site_km": args.site_km, "runs": res},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    ladder_note = next((r.get("ladder_note") for r in res if r.get("ladder_note")), "")
    L = [f"# 発電機の接続先を電圧に見合わせたら過負荷はどうなるか（what-if・{date}）", "",
         "真因は `attach_generators` が発電所を**電圧を見ずに最寄りの変電所バス**へ繋いでいること",
         "（`docs/reports/overload_vs_topology_{d}.md`）。繋ぎ方だけを変えて効果を測った。".format(d=date),
         "",
         "**外部の接続電圧表は持ち込んでいない** — 判定基準はモデル自身のデータだけから作る。", "",
         "| モード | 繋ぎ先の選び方 |", "|---|---|",
         "| base | 現行。最寄りの変電所バス（20km 以内） |",
         f"| site | 半径 {args.site_km}km 以内に複数階級があれば**最高電圧**へ（発電所は自前の"
         "開閉所の最高電圧ヤードに引き込まれる、という実系統の形） |",
         "| cap | バスに集まる枝の合計容量（線 max_i_ka×kV×√3×並列数、変圧器 sn_mva×並列数）が"
         "**その発電所の出力以上**になる最寄りのバスへ |",
         f"| kvfit | 各階級の 1 回線容量の中央値を**モデル自身の導体定数から測り**、その出力を"
         f"1 回線で運べる最下位の階級を必要階級として、半径 {args.kvfit_km}km 以内の"
         "必要階級以上の最寄りバスへ |", "",
         (f"階級の梯子（モデル実測）: {ladder_note}" if ladder_note else ""), "",
         "## 結果", "",
         "| 島 | モード | 繋ぎ替え | 110kV以下に載る容量 | 過負荷 | 低圧側(≤110kV) | 高圧側(≥154kV) | 最大負荷率 | 超過潮流 |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in res:
        o = r["overload"]
        L.append(f"| {r['island']} | {r['mode']} | {r['n_moved']:,} 台 / "
                 f"{r['moved_mw']:,.0f} MW | {r['share_at_or_below_110kv']:.1%} | "
                 f"{o['n_over']:,} ({o['over_share']:.2%}) | {o['over_lv']:,} | "
                 f"{o['over_hv']:,} | {o['max_pct']}% | {o['excess_mw']:,.0f} MW |")
    L += ["", "## 接続電圧の分布（容量ベース）", "",
          "| 島 | モード | " + " | ".join(str(k) + " kV" for k in
                                        sorted({float(k) for r in res
                                                for k in r["kv_share"]})) + " |"]
    kvs = sorted({float(k) for r in res for k in r["kv_share"]})
    L.append("|---|---|" + "---:|" * len(kvs))
    for r in res:
        L.append(f"| {r['island']} | {r['mode']} | " +
                 " | ".join(f"{r['kv_share'].get(str(k), 0):.1%}" for k in kvs) + " |")
    L += ["", "---",
          "**未適用**。採否は人間判断で、採るなら `docs/MODEL_INTERVENTIONS.md` に",
          "①根拠②帳簿③無効化を登録する。", "",
          "生成: `scripts/capacity/whatif_gen_voltage.py`（DC・介入#19/#20/#21 既定ON相当）", ""]
    (REPORTS / f"whatif_gen_voltage_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/whatif_gen_voltage_{date}.md")


if __name__ == "__main__":
    main()
