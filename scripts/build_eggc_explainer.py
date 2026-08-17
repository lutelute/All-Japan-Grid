#!/usr/bin/env python3
"""EGGC教材ページをビルドする（テンプレ + トレースデータ → 自己完結HTML）。

出力は**単一ファイルで完結**させる。理由: 教材はスライドと一緒に配ったり、
ローカルでダブルクリックして開いたりされる。fetch 前提だと file:// で落ちる。

  scripts/templates/eggc_explainer.src.html   ← 編集する正本
  docs/data/eggc_trace.json                   ← export_eggc_trace.py の出力
  docs/eggc_explainer.html                    ← 生成物（データ埋め込み済み）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMPL = ROOT / "scripts/templates/eggc_explainer.src.html"
DATA = ROOT / "docs/data/eggc_trace.json"
OUT = ROOT / "docs/eggc_explainer.html"
MARK = "/*__EGGC_TRACE__*/ null"


def main() -> int:
    if not DATA.exists():
        print(f"データが無い: {DATA}\n  先に scripts/export_eggc_trace.py を実行", file=sys.stderr)
        return 1
    html = TMPL.read_text(encoding="utf-8")
    if MARK not in html:
        print(f"テンプレに差込点 {MARK} が無い", file=sys.stderr)
        return 1
    trace = json.loads(DATA.read_text(encoding="utf-8"))
    blob = json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
    # </script> がデータに紛れるとHTMLが壊れる（今は無いが将来の名前で起きうる）
    blob = blob.replace("</", "<\\/")
    OUT.write_text(html.replace(MARK, blob), encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"出力: {OUT.relative_to(ROOT)} ({kb:.0f} KB) "
          f"ケース {trace['stats']['n_cases']} / 対象 {trace['stats']['n_targets']} 本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
