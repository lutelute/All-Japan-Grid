#!/usr/bin/env python3
"""一般送配電事業者の「予想潮流・空容量一覧表」を取得する(介入#45 の較正入力).

線路容量の較正(`scripts/capacity/calibrate_line_capacity.py`)は各社が公表する
**設備容量・運用容量・運用容量制約要因**を必要とする。2026-09-02 時点で手元にあったのは
kansai / shikoku / kyushu / tokyo の 4 社だけで、残り 6 社は「全国中央値へフォールバック」
していた(`config/line_capacity_calibration.yaml`)。本スクリプトはその 6 社を取りに行く。

**ライセンス**: 取得物は各社 All-Rights-Reserved(転載禁止)。保存先 `data/external/` は
git 管理外で、コミットしてよいのは来歴(URL・sha256・バイト数・取得日)と、較正が出す
**無次元の比**だけ。線路別の生値はレポートにも書かない。

様式は 10 社でほぼ共通(「送電線No / 送電線名 / 電圧(kV) / 回線数 / 設備容量(100%×回線数) /
運用容量値 / 運用容量制約要因 / …」)だが、配布形態が違う:

  hokkaido  ZIP(sys_capa_kikan.zip・sys_capa_local01..24.zip)  → 中に CSV
  tohoku    CSV 直リンク(ファイル名に年月が入るので索引ページから拾う)
  chubu     gridmap の pass.json が指す ZIP(geo_data/KRSIH010..016)
  hokuriku  CSV 直リンク(同上・索引ページから拾う)
  chugoku   ZIP(zip/csv_220kv.zip ほか県別)
  okinawa   **PDF のみ**(operating_capacity.pdf)。判読は別途 — 取得だけして記録する

使い方:
    PYTHONPATH=. python3 scripts/fetch_capacity_tables.py                # 6社ぶん取得
    PYTHONPATH=. python3 scripts/fetch_capacity_tables.py --utilities hokkaido tohoku
    PYTHONPATH=. python3 scripts/fetch_capacity_tables.py --dry-run      # URLの解決だけ
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "data" / "external" / "system_disclosure"
PROV = EXT / "provenance.jsonl"
UA = "Mozilla/5.0 (compatible; All-Japan-Grid/1.7 research; +https://github.com/lutelute/All-Japan-Grid)"
SLEEP = 1.0                      # 礼儀: 1 リクエスト/秒

# 索引ページから拾う社は (index_url, href の正規表現)、直リンクの社は URL のリスト。
DISCOVER = {
    "tohoku": ("https://nw.tohoku-epco.co.jp/consignment/system/announcement/",
               r'href="(\./data/sys_capa_[^"]+\.csv)"'),
    "hokuriku": ("https://www.rikuden.co.jp/nw_notification/U_154seiyaku.html",
                 r'href="(/nw_notification/attach/sys_capa_[^"]+\.csv)"'),
}

STATIC = {
    "hokkaido": ["https://www.hepco.co.jp/network/con_service/public_document/zip/sys_capa_kikan.zip"]
    + [f"https://www.hepco.co.jp/network/con_service/public_document/zip/sys_capa_local{i:02d}.zip"
       for i in range(1, 25)],
    "chubu": [f"https://gridmap.powergrid.chuden.co.jp/geo_data/KRSIH{n:03d}"
              for n in range(10, 17)],          # 運用容量等一覧表 CSV(本店＋6地域・中身は ZIP)
    "chugoku": [f"https://www.energia.co.jp/nw/service/retailer/keitou/access/zip/csv_{s}.zip"
                for s in ("220kv", "tori", "shima", "oka", "hiro", "yama")],
    # PDF のみ(判読は本スクリプトのスコープ外・取得と記録だけ行う)
    "okinawa": ["https://www.okiden.co.jp/shared/pdf/business/free/rule02/operating_capacity.pdf"],
}

PDF_ONLY = {"okinawa"}


def get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def discover(utility: str) -> list[str]:
    """索引ページから当月ぶんのファイル URL を拾う(ファイル名に年月が入るため)。"""
    index_url, pat = DISCOVER[utility]
    html = get(index_url).decode("utf-8", errors="replace")
    out = []
    for m in re.finditer(pat, html):
        out.append(urllib.parse.urljoin(index_url, m.group(1)))
    # 同名の重複を落とし、順序は保つ
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def save_blob(utility: str, url: str, blob: bytes) -> list[tuple[Path, str]]:
    """保存する。ZIP なら中の CSV も展開する。→ [(path, source_url)]。

    ZIP 内のファイル名は cp932 で書かれていることがあり、zipfile が cp437 として
    読むと化ける(中部の実測)。読める名前に直せないものは連番にする。
    """
    d = EXT / utility / "capacity"
    d.mkdir(parents=True, exist_ok=True)
    base = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name) or "download"
    written: list[tuple[Path, str]] = []

    if blob[:2] == b"PK":
        zpath = d / (base if base.lower().endswith(".zip") else base + ".zip")
        zpath.write_bytes(blob)
        written.append((zpath, url))
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for i, info in enumerate(z.infolist()):
                if info.is_dir():
                    continue
                name = info.filename
                if not info.flag_bits & 0x800:      # UTF-8 フラグ無し = cp437 で読まれている
                    try:
                        name = name.encode("cp437").decode("cp932")
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        name = f"{zpath.stem}_{i}{Path(name).suffix or '.csv'}"
                if not name.lower().endswith((".csv", ".xlsx", ".xls")):
                    continue
                safe = re.sub(r"[^\w\-.()（）　 ぁ-んァ-ヶ一-龠ａ-ｚＡ-Ｚ０-９]", "_", name)
                p = d / f"{zpath.stem}__{safe}"
                p.write_bytes(z.read(info))
                written.append((p, url))
    else:
        p = d / base
        p.write_bytes(blob)
        written.append((p, url))
    return written


def append_provenance(entries: list[dict]) -> None:
    if not entries:
        return
    with open(PROV, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--utilities", nargs="*",
                    default=["hokkaido", "tohoku", "chubu", "hokuriku", "chugoku", "okinawa"])
    ap.add_argument("--dry-run", action="store_true", help="URL の解決だけ(取得しない)")
    args = ap.parse_args(argv)

    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    summary: dict[str, dict] = {}
    prov: list[dict] = []

    for u in args.utilities:
        urls = discover(u) if u in DISCOVER else list(STATIC.get(u, []))
        if u in DISCOVER:
            time.sleep(SLEEP)
        summary[u] = {"urls": len(urls), "ok": 0, "files": 0, "failed": [],
                      "pdf_only": u in PDF_ONLY}
        print(f"[{u}] 候補 {len(urls)} URL" + ("  ※PDFのみ(判読は別途)" if u in PDF_ONLY else ""))
        if args.dry_run:
            for x in urls[:4]:
                print("   ", x)
            continue
        for url in urls:
            try:
                blob = get(url)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
                summary[u]["failed"].append({"url": url, "reason": str(e)[:120]})
                print(f"   × {url.rsplit('/', 1)[-1]}: {e}")
                time.sleep(SLEEP)
                continue
            for path, src in save_blob(u, url, blob):
                prov.append({
                    "utility": u, "kind": "capacity",
                    "file": str(path.relative_to(ROOT)),
                    "source_url": src,
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "retrieved": now,
                    "layer": "observed",
                })
                summary[u]["files"] += 1
            summary[u]["ok"] += 1
            time.sleep(SLEEP)
        print(f"   → 取得 {summary[u]['ok']}/{len(urls)} URL・保存 {summary[u]['files']} ファイル"
              + (f"・失敗 {len(summary[u]['failed'])}" if summary[u]["failed"] else ""))

    if not args.dry_run:
        append_provenance(prov)
        print(f"来歴 {len(prov)} 行を {PROV.relative_to(ROOT)} に追記")
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
