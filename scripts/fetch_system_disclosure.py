#!/usr/bin/env python3
"""系統情報の公表（一般送配電事業者10社）を取得する。

制度的根拠: 資源エネルギー庁「系統情報の公表の考え方」（令和3年5月改定）が
全一般送配電事業者に様式を定めた公表を求めている。台帳は config/system_disclosure.yaml。

ファイル名に年月が入る（impedance_kikan01_2025_08.xlsx 等）ため、URL直書きではなく
**一覧ページを取得して link_pattern にマッチするリンクを拾う**。更新に自動追従する。

取得物は observed（事業者公表値）層であり、AGJの解析出力（derived）とは別に置く。
生ファイルは data/external/system_disclosure/ （gitignore・再配布しない）。

2026-10-21: 中身が前回と同じファイルは書き直さず記録もしない(新規・更新だけを数える)。置き場は
環境変数 AGJ_SYSTEM_DISCLOSURE で変えられる(毎時の処理の worktree から本体の置き場へ書くため)。
--changed-file に変わったファイルの一覧を書く(scripts/realtime_cycle.sh が観測の表の作り直しに使う)。

使い方:
    python -m scripts.fetch_system_disclosure --dry-run          # 何が取れるか一覧
    python -m scripts.fetch_system_disclosure --kind impedance   # 全社のインピーダンス
    python -m scripts.fetch_system_disclosure --utility shikoku  # 四国の全種別
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "system_disclosure.yaml"
OUTDIR = Path(os.environ.get("AGJ_SYSTEM_DISCLOSURE") or ROOT / "data" / "external" / "system_disclosure")
# 出所の記録は追跡しているファイル。毎時の処理は本体の作業ツリーを汚さないよう AGJ_SD_PROVENANCE で
# git の外(data/realtime/)へ書く(scripts/realtime_cycle.sh)
PROVENANCE = Path(os.environ.get("AGJ_SD_PROVENANCE") or OUTDIR / "provenance.jsonl")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TIMEOUT = 60


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def find_links(index_url: str, pattern: str) -> list[str]:
    """一覧ページから pattern にマッチするリンクを絶対URLで返す。"""
    html = get(index_url).decode("utf-8", errors="replace")
    rx = re.compile(pattern, re.IGNORECASE)
    found: list[str] = []
    for m in re.finditer(r'href="([^"]+)"', html, re.IGNORECASE):
        href = m.group(1)
        if rx.search(href):
            absolute = urljoin(index_url, href)
            if absolute not in found:
                found.append(absolute)
    return found


def record(entry: dict) -> None:
    PROVENANCE.parent.mkdir(parents=True, exist_ok=True)
    with PROVENANCE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def unzip_cp932(path: Path) -> int:
    """ZIPを展開する。

    日本の事業者ZIPはファイル名が CP932 で、UTF-8フラグが立っていない。
    そのまま展開すると macOS の unzip が "Illegal byte sequence" で失敗するので、
    cp437 経由で復号する（zipfile が格納名を cp437 として渡してくるため）。
    """
    out = path.with_suffix("")
    out.mkdir(exist_ok=True)
    n = 0
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            name = info.filename
            if not (info.flag_bits & 0x800):
                name = name.encode("cp437", errors="replace").decode("cp932", errors="replace")
            name = name.replace("\\", "/")
            dst = out / name
            if info.is_dir() or name.endswith("/"):
                dst.mkdir(parents=True, exist_ok=True)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(zf.read(info))
            n += 1
    return n


def fetch_one(utility: str, kind: str, url: str, dry_run: bool) -> dict | None:
    name = url.split("/")[-1].split("?")[0]
    dest = OUTDIR / utility / kind / name
    if dry_run:
        print(f"  [dry-run] {utility}/{kind}/{name}  <- {url}")
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        blob = get(url)
    except Exception as exc:  # noqa: BLE001 — 取得失敗は握らず記録して続行
        print(f"  ! FAIL {utility}/{kind}/{name}: {exc}")
        return None
    sha = hashlib.sha256(blob).hexdigest()
    status = "new"
    if dest.exists():
        if hashlib.sha256(dest.read_bytes()).hexdigest() == sha:
            print(f"  = 同じ {utility}/{kind}/{name}")
            return {"status": "unchanged", "file": name}
        status = "updated"
    dest.write_bytes(blob)
    if dest.suffix.lower() == ".zip":
        try:
            n = unzip_cp932(dest)
            print(f"    展開 {n} ファイル")
        except Exception as exc:  # noqa: BLE001
            print(f"    ! 展開失敗 {name}: {exc}")
    entry = {
        "utility": utility,
        "kind": kind,
        "file": f"data/external/system_disclosure/{utility}/{kind}/{name}",
        "source_url": url,
        "bytes": len(blob),
        "sha256": sha,
        "status": status,
        "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "layer": "observed",
    }
    record(entry)
    print(f"  OK({status}) {utility}/{kind}/{name}  {len(blob):,}B")
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--utility", help="事業者キー（hokkaido/tohoku/.../okinawa）")
    ap.add_argument("--kind", help="種別（impedance/capacity/flow_actual/outage_plan）")
    ap.add_argument("--dry-run", action="store_true", help="取得せず対象URLだけ表示")
    ap.add_argument("--changed-file", help="新規・更新のファイルを 1 行ずつ書く(無ければ空ファイル)")
    args = ap.parse_args()
    changed: list[str] = []

    def done(entry) -> bool:
        if entry and entry.get("status") in ("new", "updated"):
            changed.append(entry["file"])
        return bool(entry)

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    utilities = cfg["utilities"]
    ok = fail = 0

    for ukey, u in utilities.items():
        if args.utility and ukey != args.utility:
            continue
        for kkey, k in (u.get("kinds") or {}).items():
            if args.kind and kkey != args.kind:
                continue
            print(f"[{ukey}/{kkey}] {u['name']}")

            # direct_url(1 本)と direct_urls(一覧)の両方を読む。中部は一覧で書いてあり、
            # 単数形しか読まなかったので一度も自動では取られていなかった(2026-10-21)
            directs = list(k.get("direct_urls") or []) + ([k["direct_url"]] if k.get("direct_url") else [])
            if directs:
                for url in directs:
                    if done(fetch_one(ukey, kkey, url, args.dry_run)) or args.dry_run:
                        ok += 1
                    else:
                        fail += 1
                continue

            pattern = k.get("link_pattern")
            if not pattern:
                print("  (link_pattern 未定義 — スキップ)")
                continue
            index_url = k.get("index_url") or u.get("index_url")
            try:
                links = find_links(index_url, pattern)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! 一覧取得失敗 {index_url}: {exc}")
                fail += 1
                continue
            if not links:
                # verified: false の社はここに来る。嘘をつかず「未発見」と出す。
                print(f"  — 該当リンクなし（pattern={pattern}） 要追加調査")
                fail += 1
                continue
            for url in links:
                if done(fetch_one(ukey, kkey, url, args.dry_run)) or args.dry_run:
                    ok += 1
                else:
                    fail += 1

    print(f"\n完了: 成功 {ok} / 失敗・未発見 {fail} / 新規・更新 {len(changed)}")
    if not args.dry_run:
        print(f"出所記録: {PROVENANCE}")
    if args.changed_file:
        Path(args.changed_file).write_text("".join(f"{c}\n" for c in changed), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
