#!/usr/bin/env python3
"""Pages に上げる前に、docs/slides の pptx・pdf を各デッキの最新版だけにする(deploy-pages 用)。

    python scripts/prune_pages_slides.py --dry-run   # 何を外すかだけ表示
    python scripts/prune_pages_slides.py             # CI の作業コピーから削除する

なぜ要るか(2026-10): Pages は docs/ を丸ごと上げるが、スライドは「版と日付を上げた別名で保存し、
前の版は残す」運用なので旧版が積もる。南海トラフの統合で docs/ は 826MB になり、Pages の上限 1GB に
近づいた。どの Pages のページも pptx・pdf にはリンクしていない(2026-10-02 確認)ので、旧版は
サイトに載せず git にだけ残す。git の履歴・GitHub 上の閲覧はそのまま。

同じデッキの判定: ファイル名から `_v<N>` と `_YYYY-MM-DD` を取り除いた名前(フォルダ・拡張子ごと)。
最新の判定: (日付, 版) の大きい方。日付も版も無いファイルはそれ自体が 1 デッキ。
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SLIDES = ROOT / "docs" / "slides"
PAT_V = re.compile(r"_v(\d+)(?=_|$)")
PAT_D = re.compile(r"_(\d{4}-\d{2}-\d{2})(?=_|$)")


def deck_key(p: Path) -> tuple[str, str, str]:
    stem = PAT_D.sub("", PAT_V.sub("", p.stem))
    return (str(p.parent), stem, p.suffix.lower())


def rank(p: Path) -> tuple[str, int]:
    d = PAT_D.search(p.stem)
    v = PAT_V.search(p.stem)
    return (d.group(1) if d else "", int(v.group(1)) if v else -1)


def plan() -> tuple[list[Path], list[Path]]:
    groups: dict[tuple, list[Path]] = defaultdict(list)
    for p in SLIDES.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".pptx", ".pdf"):
            groups[deck_key(p)].append(p)
    keep, drop = [], []
    for files in groups.values():
        files.sort(key=rank)
        keep.append(files[-1])
        drop.extend(files[:-1])
    return sorted(keep), sorted(drop)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    keep, drop = plan()
    mb = sum(p.stat().st_size for p in drop) / 1e6
    for p in drop:
        print(("would drop " if a.dry_run else "drop ") + str(p.relative_to(ROOT)))
        if not a.dry_run:
            p.unlink()
    print(f"keep {len(keep)} / drop {len(drop)} files ({mb:.0f} MB)")


if __name__ == "__main__":
    main()
