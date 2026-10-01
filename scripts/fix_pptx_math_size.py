#!/usr/bin/env python3
"""marp-pptx が書いた OMML 数式の文字サイズを PowerPoint に効かせる。

marp-pptx 0.5.0 は数式ランのサイズを Word 流の <w:rPr><w:sz/></w:rPr> で書く。
PowerPoint はこれを読まず、既定の小さいサイズで描く（LibreOffice は読む）。
同じ値を PowerPoint が読む <a:rPr sz=...> に置き換える。

使い方: python3 scripts/fix_pptx_math_size.py deck.pptx   （上書き）
"""
from __future__ import annotations

import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

W_RPR = re.compile(
    r'<(\w+):rPr xmlns:\1="http://schemas\.openxmlformats\.org/wordprocessingml/2006/main">'
    r'<\1:sz \1:val="(\d+)"/>(?:<\1:szCs \1:val="\d+"/>)?</\1:rPr>'
)


def fix(xml: str) -> tuple[str, int]:
    # w:sz は半ポイント、a:rPr の sz は 1/100 ポイント
    return W_RPR.subn(
        lambda m: f'<a:rPr lang="en-US" sz="{int(m.group(2)) * 50}">'
                  f'<a:latin typeface="Cambria Math"/></a:rPr>',
        xml,
    )


def main(path: str) -> int:
    src = Path(path)
    total = 0
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if re.match(r"ppt/slides/slide\d+\.xml$", item.filename):
                text, n = fix(data.decode("utf-8"))
                if n:
                    data = text.encode("utf-8")
                    total += n
            zout.writestr(item, data)
    shutil.move(tmp_path, src)
    print(f"{src.name}: 数式ラン {total} 箇所のサイズを PowerPoint 形式に変換")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
