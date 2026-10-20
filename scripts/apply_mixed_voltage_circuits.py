#!/usr/bin/env python3
"""併架線の回線数を電圧クラスごとに正す — 介入#45 候補(2026-09-21).

背景: OSM は同じ鉄塔に別電圧の回線が乗る線路(併架)を 1 本の way にまとめ、
電圧と回線数を併記する(``voltage=275000;66000`` ``circuits=6`` = 275 kV 2 回線
+ 66 kV 4 回線)。ビルダーは長らく **合計を最大電圧のクラスに全部付け、展開した
下位クラスは 1 回線**としていたため、上位電圧の容量が最大 4 倍に膨らみ、下位電圧は
過小になっていた(`docs/reports/mixed_voltage_circuits_builder_2026-09-21.md`)。

ビルダー(`src/powerflow/snapped_topology.py`)は 2026-09-21 に直したが、正典
`docs/data/built/all.json` は OSM からの一発再生成ができず(介入 #21/#23/#31/#38/#44
などをその場で積み上げている)、ビルダーから作り直すとそれらを壊す。そこで本スクリプトは
**同じ補正を正典の枝へ直接当てる**。

介入#44(回線数の出典補完)との関係: #44 は公表資料をもとに **増やす方向にしか**
変えない。本介入はその裏返しで、OSM が数え過ぎた上位電圧を減らし、1 回線に潰れていた
下位電圧を戻す。**公表値の方が強い**ので、本介入を当てたあとに #44 を再実行すると、
公表資料が本介入より多い回線数を示す枝は自動的に戻る(増やす方向しか動かないため)。
その差分が「OSM 推定が公表値を下回った枝」の一覧になる。

証拠: 同じ線路の**単一電圧・単一名・circuits タグつき**の way(``data/{region}_lines.geojson``)。
2 本以上の way が支持することを要求し、値が割れたら **最大値** を採る(線路の回線数は
区間の最大であって多数決ではない。2 回線の線路でも端部の引込が 1 回線の way として
分かれて登録されるため)。実名の無い線に付けた合成名(``東北電力ネットワーク 66.0kV線``・
``A変電所~B変電所線``)は別々の線路が同名になるので証拠にしない。
本当に併架(名前の別の線が別電圧に属する)の枝だけを対象にする。推測はしない。

使い方:
    python3 scripts/apply_mixed_voltage_circuits.py             # ドライラン(既定)
    python3 scripts/apply_mixed_voltage_circuits.py --write     # 正典を書き換え(.bak を取る)
    python3 scripts/apply_mixed_voltage_circuits.py --json out.json

①根拠 = 各行の evidence(線路名・電圧・支持 way 数)②帳簿 = `--json` の出力と
`all.json.pre_mixedcirc.bak` ③無効化 = .bak を戻す。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from powerflow.snapped_topology import (  # noqa: E402
    _circuit_evidence, _is_synthetic_line_name, _line_name_list,
    _voltage_class_list,
)

BUILT = os.path.join(ROOT, "docs", "data", "built", "all.json")
BAK = BUILT + ".pre_mixedcirc.bak"
REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai",
           "chugoku", "shikoku", "kyushu", "okinawa"]


def load_evidence(min_support=2):
    """全地域の lines geojson から証拠表と、線路名→電圧クラスの対応を作る。

    Returns: ({(線路名, kv): (回線数, 支持 way 数)}, {線路名: {kv, ...}})
    """
    props, support = [], collections.Counter()
    name_kv = collections.defaultdict(set)
    for r in REGIONS:
        path = os.path.join(ROOT, "data", f"{r}_lines.geojson")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            gj = json.load(fh)
        for feat in gj.get("features", []):
            p = feat.get("properties") or {}
            props.append(p)
            cls = _voltage_class_list(p.get("voltage"))
            names = _line_name_list(p.get("name"))
            if len(cls) == 1 and len(names) == 1 and not _is_synthetic_line_name(names[0]):
                name_kv[names[0]].add(cls[0])
                if p.get("circuits") not in (None, ""):
                    support[(names[0], cls[0])] += 1
    ev = _circuit_evidence(props, min_support=min_support)
    return {k: (v, support[k]) for k, v in ev.items()}, dict(name_kv)


def proposals(edges, ev, name_kv):
    """本当に併架(名前の別の線が別電圧)の枝だけ、その電圧の線路の回線数を当てる。"""
    out = []
    for i, e in enumerate(edges):
        names = [n for n in _line_name_list(e.get("name"))
                 if not _is_synthetic_line_name(n)]
        if len(names) < 2:
            continue                      # 併架名でない/合成名だけの枝は触らない
        kv = float(e.get("kv") or 0)
        if kv <= 0:
            continue                      # 電圧不明の枝は触らない
        # 名前のうち少なくとも 1 つが別の電圧クラスに属する = 本当の併架
        other_kv = {v for n in names for v in name_kv.get(n, ()) if v != kv}
        if not other_kv:
            continue                      # 同電圧の線が並んでいるだけ(数え上げは正しい)
        hit = [(n, ev[(n, kv)]) for n in names if (n, kv) in ev]
        if len(hit) != 1:
            continue                      # 証拠が無い/複数名に当たる = 曖昧なので触らない
        name, (n_circ, sup) = hit[0]
        par = int(e.get("par") or 1)
        if n_circ == par:
            continue
        out.append({"idx": i, "edge_name": e.get("name"), "line": name, "kv": kv,
                    "par_before": par, "par_after": int(n_circ), "support_ways": sup,
                    "direction": "down" if n_circ < par else "up"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="正典を書き換える(.bak を取る)")
    ap.add_argument("--json", default="", help="帳簿の出力先")
    ap.add_argument("--min-support", type=int, default=2)
    ap.add_argument("--limit", type=int, default=25, help="画面に出す件数")
    a = ap.parse_args()

    ev, name_kv = load_evidence(a.min_support)
    with open(BUILT, encoding="utf-8") as fh:
        built = json.load(fh)
    edges = built["edges"]
    props = proposals(edges, ev, name_kv)

    down = [p for p in props if p["direction"] == "down"]
    up = [p for p in props if p["direction"] == "up"]
    kv_delta = collections.Counter()
    for p in props:
        kv_delta[p["kv"]] += p["par_after"] - p["par_before"]
    print(f"証拠 {len(ev)} 組(線路名×電圧・{a.min_support} 本以上の way が支持)")
    print(f"枝 {len(edges)} 本のうち併架名の枝への提案 {len(props)} 件"
          f"(減らす {len(down)}・増やす {len(up)})")
    for kv in sorted(kv_delta, reverse=True):
        print(f"  {kv:g} kV: 回線数 合計 {kv_delta[kv]:+d}")
    print()
    for p in sorted(props, key=lambda x: -abs(x["par_after"] - x["par_before"]))[:a.limit]:
        print(f"  {str(p['edge_name'])[:26]:26} {p['line']:14} {p['kv']:>5g}kV  "
              f"par {p['par_before']} -> {p['par_after']}  (支持 {p['support_ways']} way)")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"min_support": a.min_support, "n_edges": len(edges),
                       "proposals": props}, fh, ensure_ascii=False, indent=1)
        print(f"\n帳簿: {a.json}")

    if a.write:
        if not os.path.exists(BAK):
            with open(BAK, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(built, ensure_ascii=False))
            print(f"バックアップ: {BAK}")
        for p in props:
            edges[p["idx"]]["par"] = p["par_after"]
        with open(BUILT, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(built, ensure_ascii=False))
        print(f"書き換えた: {BUILT}({len(props)} 枝)")
    else:
        print("\n(ドライラン。書き換えるには --write)")


if __name__ == "__main__":
    main()
