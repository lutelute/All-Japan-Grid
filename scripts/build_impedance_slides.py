#!/usr/bin/env python3
"""EGGC スライドをビルドする（テンプレ + 図 → 自己完結HTML）。

既存デッキ（agj_dynamics_*.html）と同じく、図は data URI で埋め込んで
1 ファイルで配れる形にする。テンプレ中の {{FIG:name.png}} を差し替える。
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMPL = ROOT / "scripts/templates/impedance_slides.src.html"
FIGS = ROOT / "docs/reports/figs"
OUT = ROOT / "docs/slides/impedance_calibration_2026-08-20.html"


def main() -> int:
    html = TMPL.read_text(encoding="utf-8")
    missing = []

    def sub(m):
        name = m.group(1)
        p = FIGS / name
        if not p.exists():
            missing.append(name)
            return ""
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    html = re.sub(r"\{\{FIG:([^}]+)\}\}", sub, html)
    if missing:
        print(f"図が無い: {missing}\n  先に scripts/plot_eggc_figs.py を実行", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    n = html.count('<section class="slide')
    print(f"出力: {OUT.relative_to(ROOT)} ({OUT.stat().st_size/1024:.0f} KB) {n} 枚")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
