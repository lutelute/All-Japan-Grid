#!/usr/bin/env python3
"""太陽光の既定容量を下げると過負荷はどう動くか（what-if・未適用）。

`docs/reports/generation_fleet_audit_2026-08-09.md` で分かったこと:
太陽光の既定値 10MW に対し、実容量が付いた OSM レコード 600 件の中央値は **0.10MW**。
100 倍の乖離で、モデルの太陽光は 180GW＝実績ピーク 56.7GW の 318% に膨らんでいる。

なぜそれが潮流を歪めるか — `balance_by_zone` は

    scale = min(zone需要 * (1+予備率) / zone容量合計, 1.0)
    gen.p_mw = gen.max_p_mw * scale

とゾーン内を**一律スケール**する。つまり **ゾーン内の発電の空間配分は容量に完全比例**する。
太陽光ノードに一律 10MW を与えると、OSM に太陽光ポリゴンが多い場所へ注入が集まり、
実際に火力・原子力が建っている場所からは離れる。総量はゾーン需要にアンカーされるので
「合っている」ように見えるが、**潮流の形は別物になる**。

本スクリプトは既定値を梯子状に振って（10.0 → 1.0 → 0.10 MW）、

  - ゾーン内の発電がどれだけ太陽光ノードに乗っているか
  - 線路の過負荷（>100%）の本数・最大・超過量

がどう動くかを測る。**潮流本体のコードをそのまま呼ぶ**（診断と本番の実装が食い違って
二度誤った経緯があるため、パラメタだけ差し替えて同じ関数を通す）。

採用は人間判断。採るなら `docs/MODEL_INTERVENTIONS.md` に①根拠②帳簿③無効化を登録する。

usage:
    python3 scripts/capacity/whatif_solar_default.py --islands hokkaido okinawa
    python3 scripts/capacity/whatif_solar_default.py            # 全4島（DC・約4分）
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

# 振る既定値の梯子。10.0 が現行、0.10 が OSM 実容量の中央値。
LADDER = [10.0, 1.0, 0.10]


def load_pf():
    """潮流本体をモジュールとして読み込む（scripts/ は package ではないので spec 経由）。"""
    path = ROOT / "scripts" / "run_full_powerflow_from_db.py"
    spec = importlib.util.spec_from_file_location("pf_full", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pf_full"] = mod
    spec.loader.exec_module(mod)
    return mod


def solar_share_by_zone(net) -> dict[str, dict]:
    """ゾーンごとに「発電のうち太陽光ノードに乗っている割合」を返す。

    balance_by_zone 後の p_mw で見る＝実際に潮流へ入る注入の配分。
    """
    out: dict[str, dict] = defaultdict(lambda: {"total_mw": 0.0, "solar_mw": 0.0,
                                                "n_gen": 0, "n_solar": 0})
    for gi, r in net.gen.iterrows():
        z = str(net.bus.at[int(r["bus"]), "zone"])
        p = float(r["p_mw"])
        rec = out[z]
        rec["total_mw"] += p
        rec["n_gen"] += 1
        if "solar" in str(r.get("type") or "").lower():
            rec["solar_mw"] += p
            rec["n_solar"] += 1
    for z, rec in out.items():
        rec["solar_share"] = round(rec["solar_mw"] / rec["total_mw"], 4) if rec["total_mw"] else 0.0
        rec["total_mw"] = round(rec["total_mw"], 1)
        rec["solar_mw"] = round(rec["solar_mw"], 1)
    return dict(out)


def overload_stats(net) -> dict:
    """過負荷の指標。件数だけでなく**超過量**も見る（1本が桁違いに超えている場合を捉える）。"""
    if not len(net.res_line):
        return {"n_line": 0, "n_over": 0, "max_pct": None, "excess_mw": 0.0,
                "over_share": 0.0, "p95_pct": None}
    df = net.res_line.join(net.line[["max_i_ka", "in_service"]], rsuffix="_l")
    df = df[df["in_service"].fillna(False)]
    lp = df["loading_percent"].dropna()
    if not len(lp):
        return {"n_line": 0, "n_over": 0, "max_pct": None, "excess_mw": 0.0,
                "over_share": 0.0, "p95_pct": None}
    over = lp[lp > 100.0]
    # 超過量: 定格を超えた分の潮流(MW)。loading% と実潮流から逆算する
    pf_mw = df.loc[over.index, "p_from_mw"].abs()
    excess = float((pf_mw * (1.0 - 100.0 / over)).sum()) if len(over) else 0.0
    return {"n_line": int(len(lp)), "n_over": int(len(over)),
            "max_pct": round(float(lp.max()), 1),
            "p95_pct": round(float(lp.quantile(0.95)), 1),
            "excess_mw": round(excess, 1),
            "over_share": round(len(over) / len(lp), 4)}


def run_variant(pf, island: str, nodes, edges, cfg, pref_gwh, solar_cap: float) -> dict:
    """既定値だけ差し替えて潮流本体を通す。DC のみ（島間で比較可能な唯一のモード）。"""
    pf._DEFAULT_CAP["solar"] = solar_cap
    t0 = time.time()
    geom: dict = {}
    net, bus_of, bstats = pf.build_island_net(
        island, nodes, edges, pf.ISLAND_FREQ[island], geom,
        dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
    n_gen = pf.attach_generators(net, bus_of, nodes, island)
    total_load = pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    pf.add_per_component_slacks(net)
    pf.balance_by_zone(net, cfg)
    zones = solar_share_by_zone(net)
    cap_by_zone = {}
    for gi, r in net.gen.iterrows():
        z = str(net.bus.at[int(r["bus"]), "zone"])
        cap_by_zone[z] = cap_by_zone.get(z, 0.0) + float(r["max_p_mw"])
    net_dc, dc, _net_ac, _ac = pf.solve_island(net, max_ac_buses=0)   # DC のみ
    return {
        "island": island, "solar_default_mw": solar_cap,
        "n_gen": n_gen, "total_load_mw": round(total_load, 1),
        "zone_capacity_mw": {z: round(v, 1) for z, v in sorted(cap_by_zone.items())},
        "zones": zones,
        "dc_converged": bool(dc.get("converged")),
        "overload": overload_stats(net_dc),
        "seconds": round(time.time() - t0, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*",
                    default=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--ladder", nargs="*", type=float, default=LADDER)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    pf = load_pf()
    baseline_solar = pf._DEFAULT_CAP["solar"]
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    runs = []
    try:
        for island in args.islands:
            for cap in args.ladder:
                r = run_variant(pf, island, nodes, edges, cfg, pref_gwh, cap)
                o = r["overload"]
                print(f"[{island:9s}] solar_default={cap:6.2f}MW  gen={r['n_gen']:5d}  "
                      f"過負荷 {o['n_over']:4d}/{o['n_line']:5d} ({o['over_share']:6.2%})  "
                      f"最大 {o['max_pct']}%  超過 {o['excess_mw']:,.0f}MW  "
                      f"{r['seconds']:.0f}s", flush=True)
                runs.append(r)
    finally:
        pf._DEFAULT_CAP["solar"] = baseline_solar     # 副作用を残さない

    payload = {"date": date, "baseline_solar_default_mw": baseline_solar,
               "ladder": args.ladder, "runs": runs}
    (REPORTS / f"whatif_solar_default_{date}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── レポート ────────────────────────────────────────────────
    by_isl: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by_isl[r["island"]].append(r)

    L = [f"# 太陽光の既定容量を下げると過負荷はどう動くか（what-if・{date}）", "",
         "`generation_fleet_audit` で、太陽光の既定値 **10MW** が OSM 実容量の中央値 "
         "**0.10MW** の 100 倍だと分かった。",
         "潮流本体の `balance_by_zone` はゾーン内を容量に比例して一律スケールするので、",
         "**既定値はそのままゾーン内の空間配分になる**。実際に振って測った。", "",
         "**未適用**。採否は人間判断で、採るなら `docs/MODEL_INTERVENTIONS.md` に登録する。", "",
         "## 過負荷の動き", "",
         "| 島 | 太陽光既定値 | 発電機 | 過負荷本数 | 過負荷率 | 最大負荷率 | 超過潮流 |",
         "|---|---:|---:|---:|---:|---:|---:|"]
    for isl in args.islands:
        for r in by_isl.get(isl, []):
            o = r["overload"]
            L.append(f"| {isl} | {r['solar_default_mw']:.2f} MW | {r['n_gen']:,} | "
                     f"{o['n_over']:,} / {o['n_line']:,} | {o['over_share']:.2%} | "
                     f"{o['max_pct']}% | {o['excess_mw']:,.0f} MW |")
    L += ["", "## ゾーン内で太陽光ノードに乗っている発電の割合", "",
          "「その場所に太陽光があるという理由だけで置かれた注入」がどれだけ潮流を動かしているか。", "",
          "| ゾーン | 既定 10MW | 1MW | 0.10MW |", "|---|---:|---:|---:|"]
    zones_seen: set[str] = set()
    for r in runs:
        zones_seen |= set(r["zones"])
    for z in sorted(zones_seen):
        cells = []
        for cap in args.ladder:
            v = next((r["zones"].get(z, {}).get("solar_share")
                      for r in runs if r["solar_default_mw"] == cap and z in r["zones"]), None)
            cells.append(f"{v:.1%}" if v is not None else "—")
        L.append(f"| {z} | " + " | ".join(cells) + " |")
    L += ["", "---",
          "生成: `scripts/capacity/whatif_solar_default.py`（DC・介入#19/#20/#21 既定ON相当）", ""]
    (REPORTS / f"whatif_solar_default_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/whatif_solar_default_{date}.md")


if __name__ == "__main__":
    main()
