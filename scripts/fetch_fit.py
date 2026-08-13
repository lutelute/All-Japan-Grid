#!/usr/bin/env python3
"""FIT/FIP 事業計画認定情報を47都道府県ぶん取得する。

    https://www.fit-portal.go.jp/PublicInfo （資源エネルギー庁）

得られるもの: 設備ID / 発電設備区分（太陽光/風力/水力/地熱/バイオマス）/
              発電出力(kW) / 発電設備の所在地。20kW以上の再エネを網羅（月次更新）。

**利用条件**: 事業計画認定情報の公表制度に基づく公開データ。出典明記で利用可。
  ただし事業者の氏名・住所・電話を含むため、**マスタ化時に個人情報は落とす**
  （build_generator_master.py が施設情報のみ残す）。生xlsxは data/external/fit/
  （gitignore）に置き再配布しない。

JSアプリ（Salesforce）で都道府県ごとにダウンロードボタンがあるため、
HTTPだけでは取れず playwright を使う。

使い方:
    python scripts/fetch_fit.py            # 47県すべて
    python scripts/fetch_fit.py 東京都      # 指定県のみ
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external" / "fit"
PROVENANCE = OUT / "provenance.jsonl"
URL = "https://www.fit-portal.go.jp/PublicInfo"

PREFS = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]


def record(entry: dict) -> None:
    PROVENANCE.parent.mkdir(parents=True, exist_ok=True)
    with PROVENANCE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright が要る: pip install playwright && playwright install chromium")
        return 1

    wanted = sys.argv[1:] or PREFS
    OUT.mkdir(parents=True, exist_ok=True)
    ok = fail = 0

    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(accept_downloads=True, viewport={"width": 1400, "height": 1000})
        pg.goto(URL, wait_until="networkidle", timeout=90000)
        pg.wait_for_timeout(3000)

        for pref in wanted:
            try:
                with pg.expect_download(timeout=120000) as dl:
                    pg.click(f"text={pref}")
                d = dl.value
                dest = OUT / (d.suggested_filename or f"fit_{pref}.xlsx")
                d.save_as(str(dest))
                blob = dest.read_bytes()
                record({
                    "source": "FIT/FIP 事業計画認定情報",
                    "url": URL, "pref": pref,
                    "file": str(dest.relative_to(ROOT)),
                    "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                    "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "layer": "observed",
                    "note": "公表制度に基づく公開データ。個人情報はマスタ化時に除去",
                })
                print(f"  OK {pref}  {dest.name}  {len(blob):,}B")
                ok += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  ! FAIL {pref}: {str(exc)[:60]}")
                fail += 1

        browser.close()

    print(f"\n完了: 成功 {ok} / 失敗 {fail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
