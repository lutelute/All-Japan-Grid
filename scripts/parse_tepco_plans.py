#!/usr/bin/env python3
"""TEPCO 流通設備建設計画表(設備計画表)から地中/架空フラグ付き線路レコードを抽出する.

入力: data/external/system_disclosure/tokyo/plans/*.pdf (転載禁止・untracked)
出力: data/external/system_disclosure/normalized/tepco_planned_lines.csv (untracked)

判別規則(external_grid_resources_2026-08-17.md):
  電線種別 CV/CVT/POF/OF = 地中ケーブル、ACSR/TACSR/AC/GTACSR等 = 架空。
  1レコードに両方あれば混在(部分地中)。

抽出方式: pdftotext -layout の行から「〜～〜」の区間パターンをアンカーに、
レコード近傍(次アンカーまで)の電線種別トークン・電圧・こう長を回収する。
表セルの折返しでレイアウトが崩れるため厳密なセル復元はせず、
**名称・区間・電圧・こう長・種別・地中/架空**のみを保証対象とする。
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/external/system_disclosure/tokyo/plans"
OUT = ROOT / "data/external/system_disclosure/normalized/tepco_planned_lines.csv"

UG_PAT = re.compile(r"(CVT?|POF|OF)\s*\d{2,4}")
OH_PAT = re.compile(r"((?:G?T?ACSR|HDCC|ACFR|TAL|ZTACIR|OE|OC)(?:/\w+)?)\s*\d{2,4}")
# 区間: 「A～B」のAとB(変電所名・鉄塔No.区間・立坑・MHなど何でも)。~の前後の連続トークン
SECTION = re.compile(r"([一-龥ぁ-んァ-ヶA-Za-z0-9・()（）.\-]+)\s*[～〜~]\s*"
                     r"([一-龥ぁ-んァ-ヶA-Za-z0-9・()（）.\-]+)")
NAME_PAT = re.compile(r"([一-龥ァ-ヶA-Za-z0-9・]+?(?:線|幹線|連系線)(?:引替|増強|新設)?)\s")
KV_PAT = re.compile(r"\b(500|275|154|66)\b")
LEN_PAT = re.compile(r"\b(\d{1,3}(?:\.\d)?)\s*(?:km)?\b")
CAT_PAT = re.compile(r"(工事中|計画|その他|着工準備)")


def records_from_pdf(pdf: Path) -> list[dict]:
    txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                         capture_output=True, text=True, check=True).stdout
    # 全角英数(ＣＶＴ・６６等)を半角へ。表は全角で組まれている(66kV表で実測)
    txt = unicodedata.normalize("NFKC", txt)
    lines = txt.splitlines()
    # アンカー行(区間パターン)の位置
    anchors = [i for i, ln in enumerate(lines)
               if SECTION.search(ln) and "整備計画" not in ln
               and "例:" not in ln and "区間" not in ln.replace(" ", "")[:6]]
    recs = []
    for j, i in enumerate(anchors):
        lo = i - 6 if j == 0 else max(i - 6, (anchors[j - 1] + i) // 2)
        hi = ((anchors[j + 1] + i) // 2 + 1) if j + 1 < len(anchors) else min(
            i + 8, len(lines))
        blob = "\n".join(lines[lo:hi])
        m = SECTION.search(lines[i])
        frm, to = m.group(1), m.group(2)
        nm = NAME_PAT.search(lines[i]) or NAME_PAT.search(blob)
        kvm = KV_PAT.search(lines[i]) or KV_PAT.search(blob)
        cat = CAT_PAT.search(blob)
        ug = sorted(set(x.group(0).replace(" ", "") for x in UG_PAT.finditer(blob)))
        oh = sorted(set(x.group(0).replace(" ", "") for x in OH_PAT.finditer(blob)))
        # こう長: 区間行のkV直後の数値を優先(なければ空欄=正直に)
        length = ""
        if kvm:
            after = lines[i][lines[i].find(kvm.group(1)) + len(kvm.group(1)):]
            lm = LEN_PAT.search(after)
            if lm:
                length = lm.group(1)
        recs.append({
            "file": pdf.name,
            "category": cat.group(1) if cat else "",
            "name": nm.group(1) if nm else "",
            "from_sub": frm, "to_sub": to,
            "kv": kvm.group(1) if kvm else "",
            "length_km": length,
            "cable_types_ug": ";".join(ug),
            "cable_types_oh": ";".join(oh),
            "underground": bool(ug), "overhead": bool(oh),
        })
    return recs


def main() -> int:
    pdfs = sorted(SRC.glob("*.pdf"))
    pdfs = [p for p in pdfs if "setubikeikaku" in p.name or "tepco_500" in p.name]
    if not pdfs:
        print("入力PDFなし(plans/)"); return 1
    allr = []
    for p in pdfs:
        rs = records_from_pdf(p)
        n_ug = sum(1 for r in rs if r["underground"] and not r["overhead"])
        n_mix = sum(1 for r in rs if r["underground"] and r["overhead"])
        print(f"{p.name}: {len(rs)}区間 (純地中{n_ug}・混在{n_mix})")
        allr.extend(rs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(allr[0].keys()))
        w.writeheader()
        w.writerows(allr)
    print(f"saved {len(allr)} rows -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
