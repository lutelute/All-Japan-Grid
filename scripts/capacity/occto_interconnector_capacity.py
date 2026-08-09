#!/usr/bin/env python3
"""連系線の運用容量を OCCTO 公表データから出典付きで抽出する。

本モデルの弱点は**容量が出典を持たないこと**だった。線路の熱容量は電圧階級から
機械的に振った理論値（√3·V·I）で、感度行列による接続可能量の算出でも
「基準潮流が既に容量を超える枝がある」という形で表面化した
（`docs/reports/hosting_capacity_*.md`）。

連系線については OCCTO が**運用容量そのもの**を 30 分値で公表しており、
利用条件も「出典明記で自由利用」なので、ここだけは出典付きの実値に置き換えられる。

出力は `data/transformer_sources.jsonl` / `generator_capacity_sources.jsonl` と
同じ規約（値・出典URL・原文引用・確信度・取得日）に揃える。

**運用容量は季節・系統状態で変動する**ため、単一値には期間中の最大値を採り、
分布（最小・中央値・最大と観測数）を note に残す。運用容量は「その時点で流せる上限」
なので、最大値は設備能力の下限保証として読める。

usage: python3 scripts/capacity/occto_interconnector_capacity.py
出力:
  data/interconnector_capacity_sources.jsonl   出典付きレコード（値の正本）
  docs/reports/occto_interconnector_capacity_<date>.md   要約と分布
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OCCTO = ROOT / "data" / "external" / "occto"
OUT_JSONL = ROOT / "data" / "interconnector_capacity_sources.jsonl"
REPORTS = ROOT / "docs" / "reports"

SOURCE_URL = "https://web-kohyo.occto.or.jp/kks-web-public/"
SOURCE_TITLE = ("OCCTO 系統情報公表システム 連系線関連情報（種別04・30分値CSV。"
                "登録不要でダウンロード可）")
LICENSE_NOTE = "OCCTO 利用条件: 出典を明記すれば自由利用可"

# CSV の列（2行目がヘッダ、1行目は UPDATE 時刻）
COL_DATE, COL_TIME, COL_NAME = 0, 1, 2
COL_FWD_CAP, COL_REV_CAP = 3, 4


def scan() -> tuple[dict, dict]:
    """kohyo_04 を走査して連系線×方向の運用容量の分布と、最大値の出典行を返す。"""
    vals: dict[tuple[str, str], list[float]] = defaultdict(list)
    peak: dict[tuple[str, str], tuple[float, str, str, str]] = {}
    files = sorted(OCCTO.glob("kohyo_04_*.csv"))
    if not files:
        raise SystemExit(f"OCCTO データが無い: {OCCTO}/kohyo_04_*.csv")

    for path in files:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            r = csv.reader(fh)
            next(r, None)          # UPDATE 行
            next(r, None)          # ヘッダ行
            for row in r:
                if len(row) <= COL_REV_CAP:
                    continue
                name = row[COL_NAME].strip()
                if not name:
                    continue
                for direction, col in (("順方向", COL_FWD_CAP), ("逆方向", COL_REV_CAP)):
                    try:
                        v = float(row[col])
                    except (ValueError, IndexError):
                        continue
                    k = (name, direction)
                    vals[k].append(v)
                    if k not in peak or v > peak[k][0]:
                        peak[k] = (v, row[COL_DATE], row[COL_TIME], path.name)
    return vals, peak


def records(vals: dict, peak: dict, date: str) -> list[dict]:
    out = []
    for (name, direction), series in sorted(vals.items()):
        s = sorted(series)
        n = len(s)
        vmax = s[-1]
        vmin = s[0]
        vmed = s[n // 2]
        pk = peak[(name, direction)]
        # 原文引用: 最大値が観測された行の実際の値をそのまま引く
        quote = (f'"{pk[1]}","{pk[2]}","{name}",…,'
                 f'{direction}運用容量(MW)="{pk[0]:g}"')
        out.append({
            "link_key": f"occto:{name}:{direction}",
            "name": name,
            "direction": direction,
            "field": "operational_capacity_mw",
            "value": vmax,
            "unit": "MW",
            "source_type": "official",
            "source_url": SOURCE_URL,
            "source_title": SOURCE_TITLE,
            "quote": quote,
            "retrieved_at": date,
            "confidence": "high",
            "collected_by": "Claude Fable 5",
            "license_note": LICENSE_NOTE,
            "note": (f"期間中の最大運用容量。運用容量は季節・系統状態で変動するため"
                     f"分布も併記: 最小 {vmin:g} / 中央値 {vmed:g} / 最大 {vmax:g} MW、"
                     f"観測 {n:,} 断面（30分値）。出典ファイル {pk[3]}。"
                     f"運用容量はその時点で流せる上限なので、最大値は設備能力の下限として読む。"),
            "observations": n,
            "min_mw": vmin, "median_mw": vmed, "max_mw": vmax,
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    vals, peak = scan()
    recs = records(vals, peak, date)

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    links = sorted({r["name"] for r in recs})
    by = {(r["name"], r["direction"]): r for r in recs}
    L = [
        f"# 連系線の運用容量 — OCCTO 公表データからの出典付き抽出（{date}）",
        "",
        "本モデルの容量は電圧階級から機械的に振った理論値で、出典を持たなかった。",
        "連系線については OCCTO が**運用容量そのもの**を 30 分値で公表しており、",
        "利用条件も出典明記で自由利用のため、ここだけは出典付きの実値に置き換えられる。",
        "",
        f"- 出典: [{SOURCE_TITLE}]({SOURCE_URL})",
        f"- ライセンス: {LICENSE_NOTE}",
        f"- 対象: 連系線 **{len(links)} 本** × 2 方向 = {len(recs)} レコード",
        f"- 期間: `data/external/occto/kohyo_04_*.csv`（30 分値）",
        "",
        "**運用容量は季節・系統状態で変動する。** 単一値には期間中の最大値を採り、",
        "分布を併記した。運用容量は「その時点で流せる上限」なので、最大値は設備能力の",
        "下限として読める（設備は少なくともこれだけは流せる）。",
        "",
        "| 連系線 | 順方向 最大 | 同 中央値 | 逆方向 最大 | 同 中央値 | 観測断面 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for nm in links:
        f_ = by.get((nm, "順方向"))
        b_ = by.get((nm, "逆方向"))
        L.append(
            f"| {nm} | "
            f"{f_['max_mw']:,.0f} MW | {f_['median_mw']:,.0f} MW | "
            f"{b_['max_mw']:,.0f} MW | {b_['median_mw']:,.0f} MW | "
            f"{f_['observations']:,} |" if f_ and b_ else f"| {nm} | — | — | — | — | — |")
    L += [
        "",
        "## 使い方と限界",
        "",
        "- 値の正本は `data/interconnector_capacity_sources.jsonl`（1 レコード = 連系線 × 方向）。",
        "  既存の `transformer_sources.jsonl` / `generator_capacity_sources.jsonl` と同じ規約",
        "  （値・出典URL・原文引用・確信度・取得日）",
        "- **これは連系線のみ。** 島内の線路容量は依然として理論値のままで、",
        "  そちらが接続可能量算出の律速になっている（`docs/reports/hosting_capacity_*.md`）",
        "- 運用容量には熱容量だけでなく安定度・電圧制約も織り込まれているため、",
        "  熱容量（√3·V·I）とは意味が違う。**運用容量の方が実態に近い**が、",
        "  モデルの枝と 1:1 に対応するとは限らない（連系線は複数回線の束であることが多い）",
        "- モデルへの適用は人間判断＋`docs/MODEL_INTERVENTIONS.md` 記帳が必要",
        "",
        "---",
        "生成: `scripts/capacity/occto_interconnector_capacity.py`",
        "",
    ]
    (REPORTS / f"occto_interconnector_capacity_{date}.md").write_text("\n".join(L), encoding="utf-8")

    print(f"連系線 {len(links)} 本 × 2 方向 = {len(recs)} レコードを抽出")
    for nm in links:
        f_, b_ = by.get((nm, "順方向")), by.get((nm, "逆方向"))
        if f_ and b_:
            print(f"  {nm:34s} 順 {f_['max_mw']:6,.0f} / 逆 {b_['max_mw']:6,.0f} MW "
                  f"({f_['observations']:,}断面)")
    print(f"→ {OUT_JSONL.relative_to(ROOT)}")
    print(f"→ docs/reports/occto_interconnector_capacity_{date}.md")


if __name__ == "__main__":
    main()
