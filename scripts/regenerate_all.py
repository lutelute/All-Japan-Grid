#!/usr/bin/env python3
"""全出力を単一モデルから一括再生成 + MODEL_VERSION 刻印(全面改修 Phase 4)。

各出力(Pages編集ビュー / 全国潮流 / MATPOWER / CIM / Pages OSM地図)が**別パイプライン・
別タイミング**で生成され鮮度がずれていた(調査: OSM地図4/23 vs built6/16 = 7週間差)。本スクリプトは
それらを**1コマンドで順に再生成**し、`docs/data/MODEL_VERSION.json` に git HEAD と各段の生成時刻を
刻んで**skewを可視化**する。重い段は --skip-* で選べる。

順序(下流依存): build_editor_data → run_national_powerflow → export_national_matpower
→ export_cim → build_static_site。

不変条件: 物理接続=真・計算は検証器・捏造禁止・基底extract不変・committedスコアカード不可触。
本スクリプトは派生物だけを再生成し、基底 data/*.geojson(=DB export)・supplement・cuts は変えない。

Usage:
  PYTHONPATH=. python scripts/regenerate_all.py                 # 全段(重い)
  PYTHONPATH=. python scripts/regenerate_all.py --light         # editor+static のみ(pandapower不要)
  PYTHONPATH=. python scripts/regenerate_all.py --skip-powerflow --skip-matpower --skip-cim
  PYTHONPATH=. python scripts/regenerate_all.py --stamp-only    # MODEL_VERSION のみ更新
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_VERSION_PATH = os.path.join(ROOT, "docs", "data", "MODEL_VERSION.json")

# (name, argv, heavy?) — heavy 段は pandapower 等が要る・遅い
STEPS = [
    ("build_editor_data", [sys.executable, "scripts/build_editor_data.py"], False),
    ("run_national_powerflow", [sys.executable, "scripts/run_national_powerflow.py"], True),
    ("export_national_matpower", [sys.executable, "scripts/export_national_matpower.py"], True),
    ("export_cim", [sys.executable, "scripts/export_cim.py"], True),
    ("build_static_site", [sys.executable, "scripts/build_static_site.py"], False),
    # 全面改修Phase5フル統合: Pagesエディタを単一の正(templates/editor.html)から再生成。
    # 静的shimでフル:8088エディタがPages上で動く(drift防止・最後にdocs/editor.htmlへ書く)。
    ("build_pages_editor",
     [sys.executable, "scripts/build_pages_editor.py", "--out", "docs/editor.html"], False),
]


def _git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:   # noqa: BLE001
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--light", action="store_true",
                    help="pandapower不要の段のみ(editor+static)")
    ap.add_argument("--stamp-only", action="store_true", help="MODEL_VERSION のみ更新")
    for name, _argv, _heavy in STEPS:
        ap.add_argument(f"--skip-{name.replace('_', '-')}", action="store_true")
    args = ap.parse_args()

    head = _git("rev-parse", "--short", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    results = {}
    if not args.stamp_only:
        for name, argv, heavy in STEPS:
            if getattr(args, f"skip_{name}", False) or (args.light and heavy):
                results[name] = {"status": "skipped"}
                print(f"  {name:<24s} skipped")
                continue
            print(f"  {name:<24s} running…")
            t0 = time.time()
            rc = subprocess.call(argv, cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT})
            dt = round(time.time() - t0, 1)
            results[name] = {"status": "ok" if rc == 0 else f"rc={rc}", "elapsed_s": dt}
            print(f"  {name:<24s} {results[name]['status']} ({dt}s)")
            if rc != 0:
                print(f"  ! {name} 失敗(rc={rc})— 後続を続行(部分再生成)")

    stamp = {
        "model_version": head or "unknown",
        "git_dirty": dirty,
        "generated_at": now,
        "steps": results,
        "note": "全出力を単一モデルから一括再生成した版(全面改修Phase4)。"
                "git_dirty=true は未コミット変更がある状態での再生成(=コミット推奨)。",
    }
    os.makedirs(os.path.dirname(MODEL_VERSION_PATH), exist_ok=True)
    with open(MODEL_VERSION_PATH, "w", encoding="utf-8") as f:
        json.dump(stamp, f, ensure_ascii=False, indent=2)
    print(f"\nMODEL_VERSION: {head}{' (dirty)' if dirty else ''} → {MODEL_VERSION_PATH}")
    print(f"  steps: {[(k, v['status']) for k, v in results.items()]}")


if __name__ == "__main__":
    main()
