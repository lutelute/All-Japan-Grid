#!/usr/bin/env python3
"""中部PGの潮流実績Excel(xlsm/xlsx)を標準4行ヘッダCSV(cp932)へ変換する。

中部は他社(CSV公表)と違いExcel公表・シート分割・先頭に空行パディングがある。
build_line_observations の read_flow は「先頭8行に 送電線No./送電線名 がある
cp932 CSV」を前提とするため、①先頭の空行を落とし ②シートごとに分割して
既存パイプラインの命名規約(jisseki_<scope>_line_<年度>_04.csv)で書き出す。

入力: data/external/system_disclosure/chubu/flow_actual/jisseki_{kikan|local}_{line|tr}_<FY>.{xlsm,xlsx}
出力: 同ディレクトリに jisseki_{kikan01|local01|local02}_{line|tr}_<FY>_04.csv
      (local01=154kV・local02=77kV以下。kikanは単一シート=kikan01)

実行: python3 scripts/convert_chubu_flow.py   (冪等・既存CSVは上書き)
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/external/system_disclosure/chubu/flow_actual"


def sheet_scope(base_scope: str, idx: int, n_sheets: int) -> str:
    if base_scope == "kikan":
        return "kikan01"
    return f"local{idx + 1:02d}"


def convert(path: Path) -> None:
    m = re.match(r"jisseki_(kikan|local)_(line|tr)_(\d{4})\.(xlsx|xlsm)", path.name)
    if not m:
        return
    base_scope, kind, fy = m.group(1), m.group(2), m.group(3)
    x = pd.ExcelFile(path)
    for i, sheet in enumerate(x.sheet_names):
        df = x.parse(sheet, header=None, dtype=object)
        # 先頭の全空行を除去(ローカル系は5行パディング → 送電線名が8行スキャン外に出る)
        first = 0
        while first < len(df) and df.iloc[first].isna().all():
            first += 1
        df = df.iloc[first:].reset_index(drop=True)
        scope = sheet_scope(base_scope, i, len(x.sheet_names))
        out = SRC / f"jisseki_{scope}_{kind}_{fy}_04.csv"
        df.to_csv(out, index=False, header=False, encoding="cp932", errors="replace")
        print(f"{path.name}[{sheet}] → {out.name}  ({df.shape[0]}行×{df.shape[1]}列)")


def main() -> None:
    for path in sorted(SRC.glob("jisseki_*.xls[mx]")):
        convert(path)


if __name__ == "__main__":
    main()
