#!/usr/bin/env python3
"""モデル検証行列(軽量)のゲート — uc_to_pf_built.py の結果 JSON を閾値で合否判定する。

`.github/workflows/verify.yml` から呼ばれる。pytest(ci.yml)が守るのは単体のピンで、
「正典 all.json からフル AC 潮流が実際に解けるか」は誰も見ていなかった
(2026-06-27〜09-01 の CI 2か月赤の教訓: 劣化はデータ側から入る)。ここは
okinawa と hokkaido のピーク断面 1 本ずつだけを解き(合計数分)、

  - 収束(converged=True・solver=="ac"、dc_fallback を許さない)
  - vm_min / slack_abs_mw / served_frac の閾値

で fail させる。北海道は発電機の無効電力の上限を守る解で解けること・66 kV 以上の網の最低電圧も見る。
閾値は committed の実測(docs/reports/uc_pf_built_*_sel_2026-11-15.json)に
余裕を持たせた値(下記 THRESHOLDS に出典と実測を併記)。east/west フルは重いので載せない。

使い方:
    PYTHONPATH=. python3 scripts/uc_to_pf_built.py --islands hokkaido okinawa --out out/verify.json
    PYTHONPATH=. python3 scripts/ci/verify_matrix.py --report out/verify.json [--summary out/summary.md]

終了コード: 0=全合格 / 1=閾値違反または非収束 / 2=入力不正。
GITHUB_STEP_SUMMARY が環境にあれば Markdown 表を追記する。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# 島 → 閾値。実測(2026-11-15・git 3409965d・fy2023r2・built_full_v4_nameplate、
# docs/reports/uc_pf_built_{hokkaido,okinawa}_sel_2026-11-15.json):
#   hokkaido h18: 上限を守る解・vm_min 0.680(浜益 22 kV)・66 kV 以上 0.7144 / slack 797.1 MW / served 1.0 / n_bus 860
#   okinawa  h11: 上限を外した解・vm_min 0.961 / slack 56.3 MW / served 1.0 / n_bus 100
# 余裕: vm_min は実測 −0.02〜0.03、slack は実測の約 1.5 倍、served は 0.99。
# CI には銘板(data/structures・gitignore)が無いので hokkaido は n_trafo_nameplate=0 で
# 解ける(1 基の銘板がヒューリスティック容量へ戻る)。その差も余裕の内。
#
# 2026-11-15 に北海道の下限を決め直した(先生「1 でいい」)。それまでの下限 0.83 は 09-02 の実測 0.8555 から
# 決めたが、その解は発電機の無効電力の上限を外した NR の解だった(上限 0.05 Mvar の 0.1 MW の太陽光が
# 27 Mvar を出していた)。介入#64(22・33 kV の級)のあと北海道は上限を守る NR で解けるようになり、北の
# 宗谷・名寄と石狩の 22 kV で電圧が下がる。下限はその解で測り直し、北海道は「上限を守る解で解けること」
# (require_q_lims)も見る。上限を外した解に戻ったら、電圧が高く出ても落とす。
# 66 kV 以上の網の最低(vm_min_66kv_up)も別に見る(22・33 kV の鎖に隠れて上の網が下がるのを捕まえる)。
# 沖縄は上限を外した解のまま(上限を守る解では解けない。docs/reports/low_kv_classes_2026-11-15.md)。
THRESHOLDS = {
    "hokkaido": {"vm_min": 0.65, "vm_min_66kv_up": 0.69, "require_q_lims": True,
                 "slack_abs_mw": 1200.0, "served_frac": 0.99, "n_bus_min": 700},
    "okinawa": {"vm_min": 0.94, "slack_abs_mw": 200.0, "served_frac": 0.99,
                "n_bus_min": 80},
}


def check_island(name: str, rep: dict, thr: dict) -> list[tuple[str, bool, str]]:
    """(項目, 合否, 詳細) の列。"""
    rows: list[tuple[str, bool, str]] = []
    rows.append(("all_converged", bool(rep.get("all_converged")),
                 f"n_converged={rep.get('n_converged')}/{rep.get('n_hours')}"))
    n_bus = int(rep.get("n_bus") or 0)
    rows.append(("n_bus", n_bus >= thr["n_bus_min"], f"{n_bus} (>= {thr['n_bus_min']})"))
    hours = rep.get("hours") or {}
    if not hours:
        rows.append(("hours", False, "no hours solved"))
        return rows
    for h, hr in sorted(hours.items(), key=lambda kv: int(kv[0])):
        tag = f"h{h}"
        rows.append((f"{tag}.solver", hr.get("solver") == "ac" and bool(hr.get("converged")),
                     f"solver={hr.get('solver')} converged={hr.get('converged')}"))
        vm = hr.get("vm_min")
        # 合否は vm_min だけで決める。詳細には、どの解き方で解けたか(発電機の無効電力の上限を守ったか)・
        # 66 kV 以上の最低・いちばん低い母線を添える(2026-11-15。前の実測 0.8555 は上限を外した解だった)
        how = {True: "上限を守る解", False: "上限を外した解"}.get(hr.get("q_lims_enforced"), "解き方は記録なし")
        extra = f" {how}"
        if hr.get("vm_min_66kv_up") is not None:
            extra += f"・66 kV 以上 {hr['vm_min_66kv_up']}"
        if hr.get("vm_min_bus"):
            extra += f"・最低 {hr['vm_min_bus'].get('name')} {hr['vm_min_bus'].get('vn_kv')} kV"
        rows.append((f"{tag}.vm_min", vm is not None and float(vm) >= thr["vm_min"],
                     f"{vm} (>= {thr['vm_min']}){extra}"))
        if thr.get("require_q_lims"):
            ql = hr.get("q_lims_enforced")
            rows.append((f"{tag}.q_lims", ql is True,
                         f"{how}(発電機の無効電力の上限を守る解で解けること)"))
        if "vm_min_66kv_up" in thr:
            vh = hr.get("vm_min_66kv_up")
            rows.append((f"{tag}.vm_min_66kv_up", vh is not None and float(vh) >= thr["vm_min_66kv_up"],
                         f"{vh} (>= {thr['vm_min_66kv_up']})"))
        sl = hr.get("slack_abs_mw")
        rows.append((f"{tag}.slack_abs_mw", sl is not None and abs(float(sl)) <= thr["slack_abs_mw"],
                     f"{sl} (<= {thr['slack_abs_mw']})"))
        sf = hr.get("served_frac")
        rows.append((f"{tag}.served_frac", sf is not None and float(sf) >= thr["served_frac"],
                     f"{sf} (>= {thr['served_frac']})"))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", required=True, help="uc_to_pf_built.py の出力 JSON")
    ap.add_argument("--islands", nargs="*", default=None,
                    help="判定する島(省略時=THRESHOLDS にある島すべてが report に要る)")
    ap.add_argument("--summary", default=None, help="Markdown 要約の出力先(任意)")
    args = ap.parse_args(argv)
    try:
        with open(args.report, encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"report を読めない: {e}", file=sys.stderr)
        return 2
    islands = args.islands or list(THRESHOLDS)
    meta = rep.get("meta", {})
    lines = [f"## verify-matrix — {meta.get('date')} @ {meta.get('git_head')} "
             f"({meta.get('scenario')} / {meta.get('model')})", "",
             "| island | check | ok | detail |", "|---|---|---|---|"]
    ok_all = True
    for isl in islands:
        thr = THRESHOLDS.get(isl)
        if thr is None:
            print(f"閾値未定義の島: {isl}", file=sys.stderr)
            return 2
        r = (rep.get("islands") or {}).get(isl)
        if r is None:
            ok_all = False
            lines.append(f"| {isl} | present | ❌ | report に無い |")
            continue
        for item, ok, detail in check_island(isl, r, thr):
            ok_all &= ok
            lines.append(f"| {isl} | {item} | {'✅' if ok else '❌'} | {detail} |")
    lines.append("")
    lines.append(f"**{'PASS' if ok_all else 'FAIL'}**")
    text = "\n".join(lines) + "\n"
    print(text)
    if args.summary:
        with open(args.summary, "w", encoding="utf-8") as f:
            f.write(text)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as f:
            f.write(text)
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
