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
    # 実証接続の再適用（介入#28/#29） — build_editor_data が all.json を基底から
    # 再構築するため、in-place 適用した公表接続worklistは build のたびに消える
    # （2026-08-15 に実害: regen が v1(13本)+v2(83本) を黙って落とし、PF が 8/11 の
    # pre-apply 数値に戻った）。apply_capacity_sources と同じ「再構築後に必ず再適用」
    # パターンでパイプラインに組み込む。両スクリプトとも冪等（既存 disclosure 枝は skip）。
    ("apply_disclosure_v1", [sys.executable, "scripts/apply_tepco_connections.py", "--write"], False),
    ("apply_disclosure_v2", [sys.executable, "scripts/apply_disclosure_v2.py",
                             "--from-worklist", "--write"], False),
    # 実証コードのOSM実線形吸着（断片=公表線そのもの の12本のみ・オーナー指示 2026-08-16
    # 「ちゃんと線があるものにおいては地形的に線を辿ってほしい」）。冪等・直線維持分は台帳に理由記録
    ("route_disclosure", [sys.executable, "scripts/route_disclosure_edges.py", "--write"], False),
    # 介入#34: OSM実線ブリッジの抽出回収(fragment campaign 第一波 2026-08-20)。
    # 実在OSM線が断片と本系統の両方に接触(≤80m・電圧整合ゲート)する場合のみ
    # 実線形ごと回収。冪等(既存ペアはskip)。regenで消えないようSTEPSに組込
    ("fragment_recovery", [sys.executable, "scripts/hunt_fragment_osm_bridges.py",
                           "--write"], False),
    ("fragment_recovery_chains", [sys.executable,
                                  "scripts/hunt_fragment_osm_chains.py",
                                  "--write"], False),
    # 介入#35: 偽断片のノード衛生(跨region二重登録の解消・オーナー承認 2026-08-26)。
    # 衛星判読パイロットc1で発見した「断片=登録人工物」を機械判定して双子側へ寄せる
    # (完全双子=削除/近傍双子≤150m・kv一致=リマップ/残余junction=再帰属)。
    # 名前つき未解決が残る断片はスキップ(部分手術しない)。冪等(適用後は対象が消える)
    ("node_hygiene", [sys.executable, "scripts/apply_node_hygiene.py",
                      "--write"], False),
    ("export_map_tiers", [sys.executable, "scripts/export_map_tiers_from_built.py"], False),          # ① 系統図tier+属性
    ("gen_sld", [sys.executable, "scripts/gen_sld_from_built.py"], False),                            # ③ SLD
    ("run_full_powerflow", [sys.executable, "scripts/run_full_powerflow_from_db.py", "--max-ac-buses", "20000"], True),  # 全規模AC(②前提・サーバ)。既定6000ではwest10193/east6205がDC-only=summary再現不能のため明示(2026-06-27, west_ac_convergence #7)
    ("gen_national_overview", [sys.executable, "scripts/gen_national_overview_from_full.py"], False),  # ② 全国概観
    ("export_national_matpower", [sys.executable, "scripts/export_national_matpower.py"], True),
    ("export_cim", [sys.executable, "scripts/export_cim.py"], True),
    ("build_static_site", [sys.executable, "scripts/build_static_site.py"], False),
    # ④ 出典容量反映 — build_static_site が plants_utility/ipp/all を作り直すため、必ずその後に再適用。
    # 順序を誤ると live/regen で capacity_mw_sourced・出典リンクが消える(2026-06-26 修正)。
    ("apply_capacity_sources", [sys.executable, "scripts/apply_capacity_sources.py"], False),
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
