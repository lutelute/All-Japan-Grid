#!/usr/bin/env python3
"""open-keitouzu（十社系統図の論理トポロジ, CC BY 4.0）をピン留めコミットから取得する。

取得先: data/external/keitouzu/  （data/external/ は untracked — 家訓どおり
外部データは源泉に留め、必要断面をスクリプトで再物質化する）

上流: https://github.com/ibarapascal/open-keitouzu
ライセンス: CC BY 4.0（CSVとその編成）。原典の系統図PDFは各社著作物で上流にも含まれない。
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

PINNED_COMMIT = "db1c6c6597e7210195b692a15fff4ad7de32a6db"  # v1 (2026-08)
RAW_BASE = f"https://raw.githubusercontent.com/ibarapascal/open-keitouzu/{PINNED_COMMIT}"
DEST = Path(__file__).resolve().parents[2] / "data" / "external" / "keitouzu"

# ピン留めコミット時点の sha256（改版検知用）
FILES = {
    "data/substations.csv": ("substations.csv", "15be47d18a95d1e8ac056b2ff62fb8fa0e938a46a108be5de0b376debbe62284"),
    "data/routes.csv": ("routes.csv", "bf6b31972f43ec96ab9be1f7eab431a6e0c6e983321c522402ffd54385bdfbc3"),
    "data/aliases.csv": ("aliases.csv", "50d21ba049c4e3b278362bafe734c68111b21db56106dc3d81ecd78c5cc13916"),
    "data/crosswalk.csv": ("crosswalk.csv", "9e8b586eeb5db274e30f377784566613e9f5effb382f2858b6b4f7571a29a24d"),
    "data/sources.csv": ("sources.csv", "912926caa0ad36f994a91c1367ef037b083100ae060d2d84d569ceed7697f0ea"),
    "sources/manifest.csv": ("manifest.csv", "29ebff05f3033c8652021b373c243795aa244a0cf55d2c08e3fcb70d11d46a90"),
    "LICENSE": ("LICENSE.upstream", None),
}


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    failed = False
    for remote, (local, expect) in FILES.items():
        dest = DEST / local
        url = f"{RAW_BASE}/{remote}"
        data = urllib.request.urlopen(url, timeout=60).read()
        actual = hashlib.sha256(data).hexdigest()
        if expect is not None and actual != expect:
            print(f"NG  {local}: sha256 mismatch (expected {expect[:12]}…, got {actual[:12]}…)")
            failed = True
            continue
        dest.write_bytes(data)
        print(f"OK  {local}  {len(data):>8} bytes  {actual[:12]}…")
    if failed:
        print("checksum不一致あり。ピン留めコミット指定のURLで不一致は異常 — 上流かネットワークを疑うこと。")
        return 1
    print(f"\n→ {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
