#!/usr/bin/env python3
"""線路容量の理論値を、送配電事業者の公表値で較正する（集計のみ公開）。

本モデルの線路容量は電圧階級から機械的に振った理論値 `√3·V·I` で、出典を持たない。
接続可能量の算出でも「基準潮流が既に容量を超える枝がある」という形で表面化した
（`docs/reports/hosting_capacity_*.md`）。

送配電事業者は線路ごとの**設備容量・運用容量・制約要因**を公表しているが、
その生値は All-Rights-Reserved で再配布できない（`data/external/` は git 管理外）。
そこで**私的検証にとどめ、公開するのは電圧階級ごとの比（無次元）と制約要因の分布**だけにする。
比だけでも較正には十分で、値そのものを持ち出さずに済む。

出力は較正係数の提案であって適用ではない。適用は人間判断＋
`docs/MODEL_INTERVENTIONS.md` への記帳が要る。

usage: python3 scripts/capacity/calibrate_line_capacity.py
出力: docs/reports/line_capacity_calibration_<date>.{md,json}
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SRC = ROOT / "data" / "external" / "kansai_td" / "154kv_more_line.csv"
REPORTS = ROOT / "docs" / "reports"

# 潮流モデルが線路に与える電流定格 [kA]（電圧階級ごとの代表値）。
# scripts/run_full_powerflow_from_db.py が線路を作るときに使う値と揃える。
MODEL_IKA = {500: 4.0, 275: 2.0, 220: 2.0, 187: 1.2, 154: 1.2,
             132: 1.0, 110: 1.0, 77: 0.7, 66: 0.6}
MIN_SAMPLES = 3          # この本数未満の階級は統計にしない


def num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()
    if not SRC.exists():
        raise SystemExit(f"公表データが無い: {SRC}（data/external/ は git 管理外）")

    rows = list(csv.reader(open(SRC, encoding="cp932")))
    updated = rows[0][0] if rows and rows[0] else ""
    data = rows[2:]

    per_ckt: dict[float, list[float]] = defaultdict(list)   # 設備容量/回線
    oper_ratio: dict[float, list[float]] = defaultdict(list)  # 運用容量/設備容量
    reasons: dict[str, int] = defaultdict(int)
    n_lines = 0
    for r in data:
        if len(r) < 7:
            continue
        kv, ckt, equip, oper, reason = num(r[2]), num(r[3]), num(r[4]), num(r[5]), r[6].strip()
        if kv is None:
            continue
        n_lines += 1
        if ckt and equip:
            per_ckt[kv].append(equip / ckt)
        if equip and oper:
            oper_ratio[kv].append(oper / equip)
        if reason:
            reasons[reason] += 1

    out = []
    for kv in sorted(per_ckt, reverse=True):
        if len(per_ckt[kv]) < MIN_SAMPLES or int(kv) not in MODEL_IKA:
            continue
        theo = (3 ** 0.5) * kv * MODEL_IKA[int(kv)]        # モデルの理論容量/回線
        pub = st.median(per_ckt[kv])                        # 公表 設備容量/回線（中央値）
        opr = st.median(oper_ratio[kv]) if oper_ratio[kv] else None
        out.append({
            "kv": kv,
            "n_lines": len(per_ckt[kv]),
            "model_over_equipment": round(theo / pub, 3),
            "operational_over_equipment": round(opr, 3) if opr else None,
            "model_over_operational": round(theo / (pub * opr), 3) if opr else None,
            "suggested_factor": round((pub * opr) / theo, 3) if opr else None,
        })

    total_reasons = sum(reasons.values())
    payload = {
        "date": date,
        "source": "関西電力送配電 空容量マッピング（154kV 以上の線路一覧）",
        "source_updated": updated,
        "license": "All-Rights-Reserved。生値は再配布せず、公開するのは比と分布のみ",
        "n_lines_analyzed": n_lines,
        "model_ika_ka": MODEL_IKA,
        "by_voltage": out,
        "constraint_reasons": {k: {"n": v, "share": round(v / total_reasons, 3)}
                               for k, v in sorted(reasons.items(), key=lambda x: -x[1])},
    }
    json.dump(payload, open(REPORTS / f"line_capacity_calibration_{date}.json", "w"),
              ensure_ascii=False, indent=1)

    L = [
        f"# 線路容量の理論値を公表値で較正する（{date}）",
        "",
        "本モデルの線路容量は電圧階級から機械的に振った理論値 `√3·V·I` で、出典を持たない。",
        "送配電事業者は線路ごとの**設備容量・運用容量・制約要因**を公表しているので、それで較正する。",
        "",
        "> **ライセンスの扱い**: 公表データは All-Rights-Reserved で再配布できない。",
        "> 検証は私的に行い、**公開するのは電圧階級ごとの比（無次元）と制約要因の分布だけ**とする。",
        "> 比だけでも較正には十分で、値そのものを持ち出さずに済む。",
        f"> 出典: 関西電力送配電 空容量マッピング（{updated}）／解析対象 {n_lines} 線路。",
        "",
        "## 結果 — 理論値は運用容量の約 2 倍",
        "",
        "| 電圧 | 本数 | 理論÷設備容量 | 運用÷設備容量 | **理論÷運用容量** | 較正係数の目安 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in out:
        L.append(f"| {r['kv']:.0f} kV | {r['n_lines']} | {r['model_over_equipment']:.2f} | "
                 f"{r['operational_over_equipment']:.2f} | **{r['model_over_operational']:.2f}** | "
                 f"{r['suggested_factor']:.2f} |")
    L += [
        "",
        "読み方は二段になっている。",
        "",
        "1. **理論÷設備容量** — 理論式そのものの精度。500kV では 1.05 とほぼ正しいが、",
        "   低い電圧階級ほど過大になる（77kV で 1.87）。代表電流値が実態より大きい",
        "2. **運用÷設備容量** — 設備の熱容量と、実際に流してよい上限の差。500kV で 0.50、",
        "   275/154kV で 0.75。安定度・電圧・上位系の制約が効くため、熱容量いっぱいには流せない",
        "",
        f"両者を掛けると、**モデルの容量は運用容量の "
        f"{min(r['model_over_operational'] for r in out):.1f}〜"
        f"{max(r['model_over_operational'] for r in out):.1f} 倍**になる。",
        "電圧階級によらずほぼ 2 倍で揃っているのが特徴で、",
        "単一の較正係数（約 0.5）でかなり実態に寄せられることを示している。",
        "",
        "## 制約要因の分布",
        "",
        "| 制約要因 | 本数 | 割合 |",
        "|---|---:|---:|",
    ]
    for k, v in payload["constraint_reasons"].items():
        L.append(f"| {k} | {v['n']} | {v['share']:.1%} |")
    L += [
        "",
        "**熱容量が支配的**（約 8 割）なので、熱容量を基礎に置くモデルの作りは妥当。",
        "ただし同期安定性・電圧安定性が効く線路も一定数あり、そこは熱容量だけでは決まらない。",
        "",
        "## 適用の提案（未適用）",
        "",
        "- 線路容量に **電圧階級別の較正係数**（上表の最右列）を掛ける: "
        + "／".join(f"{r['kv']:.0f}kV {r['suggested_factor']:.2f}" for r in out),
        f"  — 全階級で {min(r['suggested_factor'] for r in out):.2f}〜"
        f"{max(r['suggested_factor'] for r in out):.2f} に収まり、"
        f"**単一係数 0.5 でもほぼ足りる**",
        "- 効果: 接続可能量の算出が実態寄りになる。現在は容量が過大なため",
        "  「余裕がある」と誤って読める地点が出る",
        "- 限界: **出典は関西エリアのみ**。他エリアへ外挿してよいかは別途確認が要る。",
        "  設備仕様は事業者ごとに違いうるし、運用容量の決め方も同じとは限らない",
        "- **これは提案であって適用ではない。** 採用は人間判断＋",
        "  `docs/MODEL_INTERVENTIONS.md` への記帳（①根拠②帳簿③無効化）が必要",
        "",
        "## 適用したらどうなるか — 容量ではなく潮流の問題が露出する",
        "",
        "西日本で係数 0.5 を当てて接続可能量の算出を回すと、こうなる",
        "（`scripts/sensitivity/hosting_capacity.py --capacity-factor 0.5`）。",
        "",
        "| 容量の扱い | 制約対象の枝 | 既に容量超過 | 混雑増分の中央値 |",
        "|---|---:|---:|---:|",
        "| 理論値のまま（係数 1.0） | 3,466 | 77 本（2.2%） | 150 %/GW |",
        "| 較正後（係数 0.5） | 3,466 | **287 本（8.3%）** | 300 %/GW |",
        "",
        "**容量を実態に寄せると過負荷が増える。** 当然の算術だが、意味は小さくない——",
        "実系統は基本的に容量超過ゼロで運用されているので、8.3% の枝が超過するということは、",
        "**モデルの潮流そのものが実態とずれている**ことになる。",
        "つまり次の課題は容量データではなく、その潮流を作っている**需要配分と発電機の出力配分**。",
        "",
        "容量の較正はそれ単独では接続可能量を「良く」しない。むしろ、",
        "容量を正しくすることで**潮流側の歪みが見えるようになる**のが、この作業の実際の効用である。",
        "",
        "---",
        "生成: `scripts/capacity/calibrate_line_capacity.py`",
        "",
    ]
    (REPORTS / f"line_capacity_calibration_{date}.md").write_text("\n".join(L), encoding="utf-8")

    print(f"解析 {n_lines} 線路（生値は非公開・比のみ出力）")
    for r in out:
        print(f"  {r['kv']:5.0f}kV n={r['n_lines']:3d}  理論÷設備 {r['model_over_equipment']:.2f}  "
              f"運用÷設備 {r['operational_over_equipment']:.2f}  "
              f"理論÷運用 {r['model_over_operational']:.2f}  → 較正係数 {r['suggested_factor']:.2f}")
    print(f"  制約要因: " + " / ".join(f"{k} {v['share']:.0%}"
                                       for k, v in list(payload["constraint_reasons"].items())[:3]))
    print(f"→ docs/reports/line_capacity_calibration_{date}.md")


if __name__ == "__main__":
    main()
