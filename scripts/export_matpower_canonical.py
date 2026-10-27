#!/usr/bin/env python3
"""配布する MATPOWER ケースの出力 — built 正典+標準注入で 4 島.

未解決課題#2(2026-08-20): 従来の配布ケース(export_national_matpower)は
snapped系譜で、eastが素朴ACで解けなかった。正典系譜(build_island_net+標準
注入)なら east は素朴NRで収束する。

2026-10-20 からこれを配布物(dist/matpower_national)の正本にした。素朴 NR
(既定の許容誤差)で解けない島は、電圧降下の見積もりが大きいアンテナの木から
順に畳み(reduce_antenna.fold_until)、解けた最小の縮約を出す。west は
線路容量を超える負荷が配られた 66kV の放射状の木 2 本(17 バス)を畳めば
解ける。畳んだ木は meta.json の reduction に全部残す。緩い許容誤差の解は
焼き込まない。

    PYTHONPATH=. python3 scripts/export_matpower_canonical.py \
        [--out dist/matpower_national] [--islands east west ...]
        [--line-impedance]   # 様式5実測R/X(直結線のみ)を適用(既定OFF)
        [--no-fold]          # 解けない島も畳まずに DC で出す(介入#52 の無効化)

出力: <out>/<island>.mat + CSV + 名前サイドカー + meta.json
(書き出し部は src/converter/matpower_case.py の export_net)。
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


def build_canonical_net(island, nodes, edges, freq, point_demand=True, connected=None,
                        attach_mode=None):
    """試験(trial_*)と同一の標準セットアップで島ネットを組む。

    point_demand=False は地点需要(data/external の CSV・git の外)を使わない。CI はこれで組む
    (2026-10-21 実測: 配布値との差は損失 0.05pt・vm 0.003pu 以内、バス数と畳む数は同じ)。
    connected: 介入#54(出力の目標 = 同じ成分・同じエリアの負荷・予備率なし)。None はモデル既定。
    attach_mode: 発電機の繋ぎ先の規則(介入#24・#41)。None はモデル既定 = 島別の `attach_default_for`。
      2026-10-28 まではここだけ `"cap"` を書き込んでいて、#41(西・北海道は `capkv`)に追随して
      いなかった(西で知多・東海の 6 発電所 6,985 MW が 1 個の 154 kV バスに載っていた)。
    """
    import src.powerflow.point_demand as pdm
    from scripts.run_full_powerflow_from_db import (
        CONNECTED_DISPATCH, add_per_component_slacks, allocate_loads, attach_default_for,
        attach_generators, balance_by_zone, build_island_net, load_demand_config)
    from src.powerflow.pref_demand import pref_zone_gwh
    from src.powerflow.compensation import add_reactive_compensation

    cfg = load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)
    net, bus_of, _ = build_island_net(island, nodes, edges, freq, {})
    attach_generators(net, bus_of, nodes, island, stats=True,
                      attach_mode=attach_mode or attach_default_for(island))
    pinned = pdm.match_buses(net, pdm.load_point_demand())[0] if point_demand else None
    allocate_loads(net, cfg, pref_gwh=pref_gwh, point_demand=pinned)
    add_reactive_compensation(net, factor=cfg.get(
        "reactive_compensation_factor", 0.6))
    add_per_component_slacks(net)
    balance_by_zone(net, cfg, use_zone_src=True,
                    connected=CONNECTED_DISPATCH if connected is None else connected)
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


def solve_canonical(net0, fold=True, spread=None):
    """正典の解き方: 素朴 NR → 解けなければ降下の大きいアンテナの木から畳む(介入#52) →
    最大の成分のスラックに残った損失を発電機へ配って解き直す(介入#54②)。

    配布ケース・CIM・ゾーンの書き出し・正典の島の試験が同じ手順で解くように、ここに 1 つだけ置く。
    返り値 (解いたネット, 収束したか, 始動, 畳みの帳簿 or None, 配りの帳簿 or None)。
    """
    from scripts.run_full_powerflow_from_db import CONNECTED_DISPATCH, spread_slack
    from src.powerflow.reduce_antenna import fold_until

    base, red = net0, None
    n, ok, how = try_ac(net0)
    if not ok and fold:
        folded, red = fold_until(net0, lambda nt: try_ac(nt)[1])
        if folded is not None:
            base = folded
            n, ok, how = try_ac(folded)
    sp = None
    if ok and (CONNECTED_DISPATCH if spread is None else spread):
        last = {}

        def resolve(nt):
            s, good, h = try_ac(nt)
            last["how"] = h
            return s, good
        n, sp = spread_slack(base, n, resolve)
        how = last.get("how", how) if sp.get("applied") else how
    return n, ok, how, red, sp


def main() -> int:
    from src.converter.matpower_case import export_net
    from scripts.run_full_powerflow_from_db import ISLAND_FREQ

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="dist/matpower_national")
    ap.add_argument("--islands", nargs="*", default=list(ISLANDS))
    ap.add_argument("--line-impedance", action="store_true",
                    help="様式5実測R/X(crosswalk直結線)を適用")
    ap.add_argument("--no-fold", action="store_true",
                    help="解けない島もアンテナを畳まずに DC で出す(介入#52 の無効化)")
    ap.add_argument("--no-connected-dispatch", action="store_true",
                    help="出力の目標をエリアの負荷全体×(1+予備率)に戻し、損失も配らない(介入#54 の無効化)")
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
            # 地点需要の表(git の外・再配布不可)の指紋。作り直した人が同じ表か確かめる(2026-10-26)
            "point_demand": __import__("src.powerflow.point_demand",
                                       fromlist=["fingerprint"]).fingerprint(),
            "note": ("素朴NR(既定許容誤差・dc→flat 始動)で解けた島のみ "
                     "ac_converged=true。解けない島は電圧降下の見積もりが大きい"
                     "アンテナの木(<100kV の行き止まり)から順に親バスへ畳み"
                     "(負荷は保存)、解けた最小の縮約を出す。畳んだ木は "
                     "reduction.trees に根・バス名・負荷・降下つきで全部残す。"
                     "緩い許容誤差の解は焼き込まない。"),
            "islands": []}
    for island in args.islands:
        freq = ISLAND_FREQ[island]
        t0 = time.monotonic()
        print(f"... build {island}", file=sys.stderr, flush=True)
        net0 = build_canonical_net(island, nodes, edges, freq,
                                   connected=False if args.no_connected_dispatch else None)
        if args.line_impedance:
            from src.powerflow.line_impedance import (
                apply_disclosed_line_impedance)
            li_ledger = apply_disclosed_line_impedance(net0, freq_hz=freq)
            print(f"    line-impedance: {li_ledger['n_applied']}本適用",
                  file=sys.stderr)
        n, ac_ok, how, red, spread = solve_canonical(
            net0, fold=not args.no_fold, spread=False if args.no_connected_dispatch else None)
        if red:
            print("    素朴NRで解けない → 降下の大きいアンテナの木から畳んだ",
                  file=sys.stderr, flush=True)
        rec = export_net(island, n, ac_ok, args.out,
                         validate=not args.no_validate,
                         regions=[island], frequency=freq)
        rec["solve"] = how
        rec["build_s"] = round(time.monotonic() - t0, 1)
        if red:
            rec["reduction"] = red
        if spread:
            rec["slack_spread"] = spread
        if args.line_impedance:
            rec["line_impedance"] = li_ledger["n_applied"]
        meta["islands"].append(rec)
        print(f"    {island}: ac={ac_ok}({how}) bus={rec['n_bus']} "
              f"folded={red['n_removed'] if red and 'n_removed' in red else 0} "
              f"rt={rec.get('validation', {}).get('roundtrip')}",
              file=sys.stderr, flush=True)
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
    print(f"-> {args.out}/ (meta.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
