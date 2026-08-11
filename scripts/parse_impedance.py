#!/usr/bin/env python3
"""事業者公表の「様式5 インピーダンス」xlsx を正規化CSVに変換する。

入力: data/external/system_disclosure/{utility}/impedance/*.xlsx
出力: data/external/system_disclosure/normalized/impedance_{lines,transformers}.csv
      （生値相当のため gitignore 下に置く。再配布しない。集計のみ docs/reports/ へ）

様式は10社で共通だがシート名に方言がある（実測 2026-08-11）:
    「様式5(送電線インピーダンス)」 中国・北陸・四国
    「インピーダンス（ループ系統）」 北海道
    「インピーダンス」               九州
列レイアウトは5社とも一致するが、位置決め打ちはせず**ヘッダ行を検出して列を同定**する。

単位: 全社 1000MVAベースの % （実測で確認済み）。pu換算は R_pu = R_pct/100。
      系統ベース100MVAへ移す場合は ×(100/1000) = ÷10。

注意（正直に記録すべき事実）:
  九州は設備名の一部が匿名化されている（□□□□線１Ｌ / 6発電所 等）。
  anonymized 列で機械的に印を付ける。名前照合の母数から除外するために使う。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "external" / "system_disclosure"
OUT = SRC / "normalized"

# ヘッダ行の目印。この語を含む行をヘッダとみなす。
LINE_HEADER_KEY = "送電線No"
TR_HEADER_KEY = "変電所No"
ANON_RX = re.compile(r"[□■○×]{2,}")


def _norm(v: object) -> str:
    return re.sub(r"\s+", "", str(v)) if pd.notna(v) else ""


def _find_sections(df: pd.DataFrame) -> list[tuple[int, bool]]:
    """(ヘッダ行, 変圧器か) のリストを返す。

    北海道・九州は1シートに送電線セクションと変圧器セクションを縦に連結している
    （実測: 北海道は行110、九州は行121から変圧器）。シート名だけで判別すると
    変圧器を丸ごと取りこぼすため、シート全体からヘッダ行を全部拾う。
    """
    sections: list[tuple[int, bool]] = []
    for i in range(len(df)):
        cells = [_norm(v) for v in df.iloc[i]]
        if any(LINE_HEADER_KEY in c for c in cells):
            sections.append((i, False))
        elif any(TR_HEADER_KEY in c for c in cells):
            sections.append((i, True))
    return sections


def _cols(df: pd.DataFrame, hrow: int) -> dict[str, int]:
    """ヘッダ行のセル値から列インデックスを同定する。"""
    found: dict[str, int] = {}
    for j, v in enumerate(df.iloc[hrow]):
        s = _norm(v)
        if not s:
            continue
        if "送電線No" in s or "変電所No" in s:
            found.setdefault("no", j)
        elif s.startswith("電圧"):
            found.setdefault("kv", j)
        elif "送電線名" in s or "変圧器名" in s:
            found.setdefault("name", j)
        elif s == "区間":
            found.setdefault("from", j)
            found.setdefault("to", j + 1)  # 区間は2セル（結合セル）
        elif s.startswith("R(%"):
            found.setdefault("r", j)
        elif s.startswith("X(%"):
            found.setdefault("x", j)
        elif s.startswith("Y/2(%"):
            found.setdefault("b2", j)
        elif s.startswith("Xps(%"):
            found.setdefault("xps", j)
        elif "備" in s and "考" in s:
            found.setdefault("note", j)
    return found


def _num(v: object) -> float | None:
    if pd.isna(v):
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def parse_file(path: Path, utility: str) -> tuple[list[dict], list[dict]]:
    scope = "kikan" if "kikan" in path.name else "local"
    lines: list[dict] = []
    trs: list[dict] = []
    for sheet in pd.ExcelFile(path).sheet_names:
        df = pd.read_excel(path, sheet_name=sheet, header=None)
        sections = _find_sections(df)
        for si, (hrow, is_tr) in enumerate(sections):
            # セクションの終端は次のヘッダ行の手前
            end = sections[si + 1][0] if si + 1 < len(sections) else len(df)
            c = _cols(df, hrow)
            for i in range(hrow + 1, end):
                row = df.iloc[i]
                name = _norm(row[c["name"]]) if "name" in c else ""
                if not name:
                    continue
                base = {
                    "utility": utility,
                    "scope": scope,
                    "equipment_no": _norm(row[c["no"]]) if "no" in c else "",
                    "name": name,
                    "voltage_kv": _num(row[c["kv"]]) if "kv" in c else None,
                    "note": _norm(row[c["note"]]) if "note" in c else "",
                    "base_mva": 1000,
                    "source_file": str(path.relative_to(ROOT)),
                    "layer": "observed",
                }
                if is_tr and "xps" in c:
                    xps = _num(row[c["xps"]])
                    if xps is None:
                        continue
                    trs.append({**base, "Xps_pct": xps})
                elif not is_tr and "x" in c:
                    x = _num(row[c["x"]])
                    if x is None:
                        continue
                    frm = _norm(row[c["from"]]) if "from" in c else ""
                    to = _norm(row[c["to"]]) if "to" in c else ""
                    lines.append(
                        {
                            **base,
                            "from_node": frm,
                            "to_node": to,
                            "R_pct": _num(row[c["r"]]) if "r" in c else None,
                            "X_pct": x,
                            "B_half_pct": _num(row[c["b2"]]) if "b2" in c else None,
                            "anonymized": bool(
                                ANON_RX.search(name)
                                or ANON_RX.search(frm)
                                or ANON_RX.search(to)
                            ),
                        }
                    )
    return lines, trs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", default=str(OUT))
    args = ap.parse_args()

    all_lines: list[dict] = []
    all_trs: list[dict] = []
    for path in sorted(SRC.glob("*/impedance/*.xlsx")):
        utility = path.parts[len(SRC.parts)]
        try:
            ln, tr = parse_file(path, utility)
        except Exception as exc:  # noqa: BLE001
            print(f"! {path.name}: {exc}")
            continue
        all_lines += ln
        all_trs += tr
        print(f"{utility:9s} {path.name:36s} lines={len(ln):4d} trafos={len(tr):3d}")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    dl = pd.DataFrame(all_lines)
    dt = pd.DataFrame(all_trs)
    dl.to_csv(outdir / "impedance_lines.csv", index=False, encoding="utf-8")
    dt.to_csv(outdir / "impedance_transformers.csv", index=False, encoding="utf-8")

    summary = {
        "lines_total": int(len(dl)),
        "transformers_total": int(len(dt)),
        "utilities": sorted(dl["utility"].unique().tolist()) if len(dl) else [],
        "by_utility": (
            dl.groupby("utility").size().to_dict() if len(dl) else {}
        ),
        "by_voltage_kv": (
            dl["voltage_kv"].value_counts().sort_index().to_dict() if len(dl) else {}
        ),
        "anonymized": int(dl["anonymized"].sum()) if len(dl) else 0,
        "base_mva": 1000,
        "layer": "observed",
    }
    (outdir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n送電線 {len(dl)} / 変圧器 {len(dt)} → {outdir.relative_to(ROOT)}")
    print(f"匿名化を含む行: {summary['anonymized']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
