#!/usr/bin/env python3
"""OCCTO「ユニット別発電実績公開システム」(HKS) から30分値の発電実績を取得する。

    https://hatsuden-kokai.occto.or.jp/hks-web-public/

得られるもの: 発電所コード / エリア / 発電所名 / ユニット名 / 発電方式・燃種 /
              対象日 / 00:30〜24:00 の30分値[kWh] / 日量。全10エリア・約470ユニット。

**利用条件**（免責事項同意画面より・オーナー承認のうえ同意 2026-08-12）:
  コンテンツは出典を記載すれば自由に利用できる。編集・加工した場合はその旨も記載する。
  公開値は速報値でありデータ欠落がありうる。正確性の保証はない。
  → 生CSVは data/external/（gitignore）に置き再配布しない。集計値は出典明記で利用する。

このサイトは免責同意→検索→CSV保存という画面遷移が要るため、HTTPだけでは取れず
ブラウザ自動化（playwright）を使う。免責同意はオーナーの明示的承認に基づく。

使い方:
    python scripts/fetch_hks.py 2026/08/10                # 1日
    python scripts/fetch_hks.py 2026/08/01 2026/08/10     # 期間
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external" / "occto" / "hks"
PROVENANCE = OUT / "provenance.jsonl"
BASE = "https://hatsuden-kokai.occto.or.jp/hks-web-public"


def fetch(date_from: str, date_to: str) -> Path | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright が要る: pip install playwright && playwright install chromium")
        return None

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"hks_{date_from.replace('/', '')}_{date_to.replace('/', '')}.csv"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 1500, "height": 1050}, accept_downloads=True)
        pg.goto(f"{BASE}/", wait_until="networkidle", timeout=60000)

        # 免責事項への同意（オーナー承認済み。内容は本ファイル冒頭に明記）
        pg.check("#agreed")
        pg.click("#next")
        pg.wait_for_load_state("networkidle", timeout=60000)

        pg.goto(f"{BASE}/info/hks", wait_until="networkidle", timeout=90000)

        # 対象日。id が振られていないので「日付が入っている text 入力」で拾う
        inputs = [e for e in pg.query_selector_all("input[type='text']")
                  if (e.get_attribute("value") or "").count("/") == 2]
        if len(inputs) < 2:
            print("! 日付入力が見つからない（画面構成が変わった可能性）")
            browser.close()
            return None
        inputs[0].fill(date_from)
        inputs[1].fill(date_to)

        pg.click("text=検索")
        pg.wait_for_load_state("networkidle", timeout=180000)
        with pg.expect_download(timeout=300000) as dl:
            pg.click("text=CSV保存")
        dl.value.save_as(str(dest))
        browser.close()

    blob = dest.read_bytes()
    PROVENANCE.parent.mkdir(parents=True, exist_ok=True)
    with PROVENANCE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "source": "OCCTO ユニット別発電実績公開システム",
            "url": f"{BASE}/info/hks",
            "date_from": date_from, "date_to": date_to,
            "file": str(dest.relative_to(ROOT)),
            "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
            "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "layer": "observed",
            "note": "速報値。出典明記で利用可、生CSVは再配布しない",
        }, ensure_ascii=False) + "\n")
    print(f"OK {dest.name}  {len(blob):,}B")
    return dest


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    frm = sys.argv[1]
    to = sys.argv[2] if len(sys.argv) > 2 else frm
    return 0 if fetch(frm, to) else 1


if __name__ == "__main__":
    raise SystemExit(main())
