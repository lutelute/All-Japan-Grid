#!/usr/bin/env python3
"""正典系譜のMATPOWERケース出力 — built正典+標準注入で4島(+west_reduced).

未解決課題#2(2026-08-20): 従来の配布ケース(export_national_matpower)は
snapped系譜で、eastが素朴ACで解けなかった。正典系譜(build_island_net+標準
注入)なら east は素朴NRで収束することを試験で確認済み。west は全部入りだと
tol10MVA緩解のみのため、**west_reduced**(アンテナ集約・需要保存・帳簿つき)を
併せて出力する — これは素朴runpfで解ける。

    PYTHONPATH=. python3 scripts/export_matpower_canonical.py \
        [--out dist/matpower_canonical] [--islands east west ...]
        [--line-impedance]   # 様式5実測R/X(直結線のみ)を適用(既定OFF)

出力: <out>/<island>.mat + CSV + 名前サイドカー + meta.json
(書き出し部は export_national_matpower.export_net を共用)。
生成物はコミットしない(スクリプトが再現レシピ)。
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ISLANDS = ("hokkaido", "east", "west", "okinawa")


def build_canonical_net(island, nodes, edges, freq):
    """試験(trial_*)と同一の標準セットアップで島ネットを組む。"""
    import src.powerflow.point_demand as pdm
    from scripts.run_full_powerflow_from_db import (
        add_per_component_slacks, allocate_loads, attach_generators,
        balance_by_zone, build_island_net, load_demand_config)
    from src.powerflow.pref_demand import pref_zone_gwh
    from src.powerflow.pipeline import add_reactive_compensation

    cfg = load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)
    demand_pd = pdm.load_point_demand()
    net, bus_of, _ = build_island_net(island, nodes, edges, freq, {})
    attach_generators(net, bus_of, nodes, island, attach_mode="cap", stats=True)
    pinned, _ = pdm.match_buses(net, demand_pd)
    allocate_loads(net, cfg, pref_gwh=pref_gwh, point_demand=pinned)
    add_reactive_compensation(net, factor=cfg.get(
        "reactive_compensation_factor", 0.6))
    add_per_component_slacks(net)
    balance_by_zone(net, cfg, use_zone_src=True)
    return net


def try_ac(net):
    """素朴NR(既定tol・フラット→DC初期化の2トライ)。緩tolは使わない=真解のみ。"""
    import pandapower as pp
    for init in ("dc", "flat"):
        n = copy.deepcopy(net)
        try:
            pp.runpp(n, init=init, calculate_voltage_angles=True,
                     enforce_q_lims=False, numba=False, max_iteration=60)
            return n, True, init
        except Exception:  # noqa: BLE001
            continue
    n = copy.deepcopy(net)
    pp.rundcpp(n)
    return n, False, "dc-only"


def main() -> int:
    from scripts.export_national_matpower import export_net
    from scripts.run_full_powerflow_from_db import ISLAND_FREQ
    from src.powerflow.reduce_antenna import aggregate_antennas

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="dist/matpower_canonical")
    ap.add_argument("--islands", nargs="*", default=list(ISLANDS))
    ap.add_argument("--line-impedance", action="store_true",
                    help="様式5実測R/X(crosswalk直結線)を適用")
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    built = json.load(open("docs/data/built/all.json"))
    nodes, edges = built["nodes"], built["edges"]

    meta = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(
                timespec="seconds"),
            "head": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                   capture_output=True, text=True,
                                   check=False).stdout.strip(),
            "lineage": "canonical (built + build_island_net + 標準注入)",
            "demand": "fy2023既定断面",
            "note": ("素朴NR(既定許容誤差)で解けた島のみ ac_converged=true。"
                     "west(全部入り)は真解が無いため dc-only で出力し、"
                     "west_reduced(アンテナ集約・需要保存)を素朴AC可の"
                     "ケースとして併載する。緩い許容誤差の解は焼き込まない。"),
            "islands": []}
    for island in args.islands:
        freq = ISLAND_FREQ[island]
        t0 = time.monotonic()
        print(f"... build {island}", file=sys.stderr, flush=True)
        net0 = build_canonical_net(island, nodes, edges, freq)
        if args.line_impedance:
            from src.powerflow.line_impedance import (
                apply_disclosed_line_impedance)
            li_ledger = apply_disclosed_line_impedance(net0, freq_hz=freq)
            print(f"    line-impedance: {li_ledger['n_applied']}本適用",
                  file=sys.stderr)
        variants = [(island, net0, None)]
        if island == "west":
            netr = copy.deepcopy(net0)
            red = aggregate_antennas(netr)
            variants.append((f"{island}_reduced", netr, red))
        for name, net, red in variants:
            n, ac_ok, how = try_ac(net)
            rec = export_net(name, n, ac_ok, args.out,
                             validate=not args.no_validate,
                             regions=[island], frequency=freq)
            rec["solve"] = how
            rec["build_s"] = round(time.monotonic() - t0, 1)
            if red:
                rec["reduction"] = red
            if args.line_impedance:
                rec["line_impedance"] = li_ledger["n_applied"]
            meta["islands"].append(rec)
            print(f"    {name}: ac={ac_ok}({how}) bus={rec['n_bus']} "
                  f"rt={rec.get('validation', {}).get('roundtrip')}",
                  file=sys.stderr, flush=True)
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
    print(f"-> {args.out}/ (meta.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
