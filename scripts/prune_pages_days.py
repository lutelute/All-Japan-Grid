#!/usr/bin/env python3
"""Pages に上げる前に、潮流マップの日別断面を直近 N 日だけにする(deploy-pages 用)。

    python scripts/prune_pages_days.py --dry-run      # 何を外すかだけ表示
    python scripts/prune_pages_days.py --keep 30      # CI の作業コピーから削除し、目次も書き換える

なぜ要るか(2026-10-04): 日別断面(docs/data/flow_map/days/YYYYMMDD.json)は 4 島そろうと 1 日 約 2.2 MB。
Pages は docs/ を丸ごと上げる(上限 1 GB)ので、全日を載せ続けると 1 年で上限に届く。オーナー判断で
「公開は直近 30 日・git には全日を残す」。地図は manifest.json の dates だけを選択肢に出すので、
外した日は目次からも消す(リンク切れにしない)。git の履歴・GitHub 上の閲覧はそのまま。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAYS = ROOT / "docs" / "data" / "flow_map" / "days"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep", type=int, default=30, help="残す日数(新しい順)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    files = sorted(p for p in DAYS.glob("2*.json") if p.stem.isdigit())
    keep, drop = files[-a.keep:], files[:-a.keep] if len(files) > a.keep else []
    mb = sum(p.stat().st_size for p in drop) / 1e6
    for p in drop:
        print(("would drop " if a.dry_run else "drop ") + p.name)
        if not a.dry_run:
            p.unlink()
    mf = DAYS / "manifest.json"
    if mf.exists() and not a.dry_run:
        d = json.loads(mf.read_text(encoding="utf-8"))
        kept = {p.stem for p in keep}
        d["dates"] = [x for x in d.get("dates", []) if x in kept]
        mf.write_text(json.dumps(d, ensure_ascii=False))
    print(f"keep {len(keep)} / drop {len(drop)} days ({mb:.0f} MB)")


if __name__ == "__main__":
    main()
