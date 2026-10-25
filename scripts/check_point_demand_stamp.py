#!/usr/bin/env python3
"""手元の地点需要の表が、正典の版(MODEL_VERSION.json)に記録した表と同じかを確かめる(2026-10-26).

潮流・N-1・MATPOWER・CIM の公開値は、git の外にある地点需要の表(介入#30)から作る。
表は各社の公表から各自で作るので、作り直した人や毎時の処理が「公開値と同じ表か」をここで見る。
違えば、どの事業者の行が違うか(行数と sha256 だけ。地点ごとの値は出さない)を示す。

    PYTHONPATH=. python3 -m scripts.check_point_demand_stamp     # rc: 0 同じ / 1 違う・記録なし
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.powerflow.point_demand import fingerprint  # noqa: E402

MODEL_VERSION = ROOT / "docs/data/MODEL_VERSION.json"


def compare(now: dict, rec: dict | None) -> list[str]:
    """違いの説明(同じなら空)。"""
    if not rec:
        return ["正典の版に地点需要の表の記録が無い(重い段を回した regenerate_all が記録する)"]
    if not now.get("present"):
        return ["手元に地点需要の表が無い(ピン留めなしで組むので公開値と違う)"]
    if now.get("sha256") == rec.get("sha256"):
        return []
    out = [f"表が違う: 手元 {now['sha256'][:12]}({now['rows']} 行)/ 正典 {rec.get('sha256', '?')[:12]}"
           f"({rec.get('rows', '?')} 行)"]
    a, b = now.get("by_utility", {}), rec.get("by_utility", {})
    for u in sorted(set(a) | set(b)):
        if a.get(u, {}).get("sha256") != b.get(u, {}).get("sha256"):
            out.append(f"  {u}: 手元 {a.get(u, {}).get('rows', 0)} 行 / 正典 {b.get(u, {}).get('rows', 0)} 行")
    return out


def main() -> int:
    rec = None
    if MODEL_VERSION.exists():
        rec = (json.loads(MODEL_VERSION.read_text(encoding="utf-8")).get("external_inputs") or {}).get("point_demand")
    diff = compare(fingerprint(), rec)
    if not diff:
        print("地点需要の表: 正典の版と同じ")
        return 0
    print("地点需要の表: " + "\n".join(diff))
    print("  公開値と同じにするには正典の版の表を、新しい表で作り直すなら regenerate_all(重い段)を回す")
    return 1


if __name__ == "__main__":
    sys.exit(main())
