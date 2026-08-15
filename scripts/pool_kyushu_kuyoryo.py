#!/usr/bin/env python3
"""九州31地区「予想潮流・空容量一覧表」の全面プール化。

pdftotext -layout 済みの kuyoryo/*.txt から送電線行を抽出する。
行の錨は「潮流方向」列の矢印(→)。1行 = No/送電線名/kV/回線数/…/from → to。

出力は二層:
  - data/external/.../kuyoryo/pool_full.json  … 全列(容量含む・転載禁止・untracked)
  - docs/reports/kyushu_kuyoryo_pool_<date>.json … 接続事実のみ(district/line/kv/circuits/frm/to)

接続事実(どの局とどの局が繋がっているか)は系統図にも描かれる公知のトポロジであり、
生値(設備容量・運用容量・空容量)はレポートに含めない(reference_utility_data_licensing)。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KUYORYO = ROOT / "data/external/system_disclosure/kyushu/keitouzu/kuyoryo"
REPORT = ROOT / "docs/reports/kyushu_kuyoryo_pool_2026-08-16.json"
FULL = KUYORYO / "pool_full.json"

# 例: "  1  熊本日田線  220  2  612  383  熱容量  熊本  →  日田  -768 ..."
# 錨=矢印。名前列は空白を含まない(PDF由来)。回線数は1-9。
ROW = re.compile(
    r"^\s*(?P<no>\d{1,3})\s+(?P<line>\S+)\s+(?P<kv>\d{2,3})\s+(?P<ckt>\d)\s+"
    r"(?P<mid>.*?)(?P<frm>\S+)\s+→\s+(?P<to>\S+)"
)
# 矢印はあるが No/kV が同一行にない折返し行の救済用
ARROW = re.compile(r"(?P<frm>\S+)\s+→\s+(?P<to>\S+)")


def parse_district(txt: Path) -> list[dict]:
    district = txt.stem.replace("td_", "").replace("_260730", "")
    rows: list[dict] = []
    section = None
    for raw in txt.read_text(encoding="utf-8").splitlines():
        if "送電線" in raw and "電圧" in raw:
            section = "line"
            continue
        if re.search(r"変圧器|変電所\s*$", raw) and "No" in raw:
            section = "trafo"
            continue
        m = ROW.match(raw)
        if not m:
            continue
        frm, to = m.group("frm"), m.group("to")
        # 方向列の値が数値や記号なら折返し行の誤検知
        if re.fullmatch(r"[-\d.,％%※#＃◇()]+", frm) or re.fullmatch(r"[-\d.,％%※#＃◇()]+", to):
            continue
        rows.append(
            {
                "district": district,
                "no": int(m.group("no")),
                "line": m.group("line"),
                "kv": int(m.group("kv")),
                "circuits": int(m.group("ckt")),
                "frm": frm,
                "to": to,
                "raw_mid": m.group("mid").strip(),
                "section": section or "line",
            }
        )
    return rows


def main() -> None:
    all_rows: list[dict] = []
    per_district: dict[str, int] = {}
    for txt in sorted(KUYORYO.glob("td_*_260730.txt")):
        rows = parse_district(txt)
        per_district[txt.stem] = len(rows)
        all_rows.extend(rows)

    FULL.write_text(json.dumps(all_rows, ensure_ascii=False, indent=1), encoding="utf-8")

    facts = [
        {k: r[k] for k in ("district", "no", "line", "kv", "circuits", "frm", "to")}
        for r in all_rows
    ]
    REPORT.write_text(
        json.dumps(
            {
                "source": "九州電力送配電 予想潮流・空容量一覧表(2026-07-30版・31地区)",
                "note": "接続事実のみ。容量・潮流の生値は data/external/ に保持(転載禁止)",
                "rows": facts,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    print(f"総行数 {len(all_rows)} / 地区 {len(per_district)}")
    for k, v in sorted(per_district.items()):
        print(f"  {k}: {v}")
    zero = [k for k, v in per_district.items() if v == 0]
    if zero:
        print(f"! 0行の地区: {zero}", file=sys.stderr)


if __name__ == "__main__":
    main()
