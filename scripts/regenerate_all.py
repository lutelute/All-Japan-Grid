#!/usr/bin/env python3
"""全出力を単一モデルから一括再生成 + MODEL_VERSION 刻印(全面改修 Phase 4)。

各出力(Pages編集ビュー / 全国潮流 / MATPOWER / CIM / Pages OSM地図)が**別パイプライン・
別タイミング**で生成され鮮度がずれていた(調査: OSM地図4/23 vs built6/16 = 7週間差)。本スクリプトは
それらを**1コマンドで順に再生成**し、`docs/data/MODEL_VERSION.json` に git HEAD と各段の生成時刻を
刻んで**skewを可視化**する。重い段は --skip-* で選べる。

順序(下流依存): build_editor_data → run_national_powerflow → export_matpower_canonical
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
    # 変電所の構造 DB(data/structures・git の外)を、追跡している基底の OSM から作る(約 5 秒・決定的)。
    # 2026-10-24 まで手順に無く、本体の構造 DB は 08-28 に作ったままだった。10-07〜08 の直し(敷地の多角形で
    # 母線・ベイを帰属させる・#48〜#50)が、変電所の属性・SubSLD・潮流に入っていなかった。clone した人も同じものを作る
    ("build_structures", [sys.executable, "scripts/build_structures_batch.py", "--all"], False),
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
    # 介入#34 追補3: 第三波(継ぎ目 60m→200m の OSM way 連鎖・2026-09-02)。
    # **hokkaido/west のみ**適用する — 全 68 本(east 17 本込み)を入れると east ピーク AC が
    # dc_fallback に退行することを実測済み(却下記録 uc_pf_built_east_sel_frag3_rejected_*.json)。
    # 電圧整合・迂回係数 ≤1.5・跨島双子の3ゲート。跨ぎ枝が増える候補が混ざると自動中止。冪等
    ("fragment_recovery_third_wave", [sys.executable,
                                      "scripts/hunt_fragment_third_wave.py",
                                      "--seam-m", "200",
                                      "--islands", "hokkaido", "west",
                                      "--write"], False),
    # 介入#35: 偽断片のノード衛生(跨region二重登録の解消・オーナー承認 2026-08-26)。
    # 衛星判読パイロットc1で発見した「断片=登録人工物」を機械判定して双子側へ寄せる
    # (完全双子=削除/近傍双子≤150m・kv一致=リマップ/残余junction=再帰属)。
    # 名前つき未解決が残る断片はスキップ(部分手術しない)。冪等(適用後は対象が消える)
    # 介入#42: 混在県個別化(2026-09-02)も同経路(--mixed-pref)。境界資産+切断ガードで
    # 長野/新潟/静岡の跨ぎ候補を再帰属(帳簿=fragments/mixed_pref_ledger.json)。冪等
    ("node_hygiene", [sys.executable, "scripts/apply_node_hygiene.py",
                      "--mixed-pref", "--write"], False),
    # 介入#47: 併架線の回線数を電圧クラスへ配分(2026-09-22 正典適用・929f640)。2026-10-21 まで
    # STEPS に無く、regen すると #47 が消えた(B7・docs/reports/regenerate_reproducibility_2026-10-21.md)。
    # ビルダー(mixed_voltage_circuits_by_name)で拾えない併架名の枝を、同じ線路名の単一電圧 way の
    # circuits で正す。必ず #44 の前に置く(#44 の後に回すと #44 が上げた 4 枝を下げ直す=実測)。
    # #44 は増やす方向のみなので公表値が勝つ。冪等
    ("mixed_voltage_circuits", [sys.executable, "scripts/apply_mixed_voltage_circuits.py",
                                "--write"], False),
    # 介入#44: 回線数(par)の出典補完(2026-09-02)。公表資料の回線数を台帳
    # data/reference/circuit_counts.jsonl から引き当てて **増やす方向のみ** 適用。
    # build_editor_data が基底から作り直すと par は OSM circuits タグ由来へ戻るため、
    # 再適用が要る(#28/#29 と同じ「再構築後に必ず再適用」パターン)。冪等
    ("apply_circuit_sources", [sys.executable, "scripts/apply_circuit_sources.py",
                               "--write"], False),
    # 介入#36: 衛星判読クラスの接続(オーナー承認制・スクリプト内CONNECTIONS表が
    # 承認台帳)。approved のみ適用・冪等。第1号=小千谷66kV(衛星のみ証拠)
    ("satellite_connections", [sys.executable,
                               "scripts/apply_satellite_connections.py",
                               "--write"], False),
    # 介入#51: 一次資料(各社の空容量・予想潮流一覧)で誤りと分かった OSM の電圧タグを直す
    # (スクリプト内 CORRECTIONS 表が承認台帳)。approved のみ適用・冪等。第1号=西島根 275→220 kV
    ("voltage_corrections", [sys.executable,
                             "scripts/apply_voltage_corrections.py",
                             "--write"], False),
    # 地域とノード衛生の仕上げ(2026-10-21)。#35・#42・#38 は node_hygiene で一度当てるが、後の段
    # (回線数・衛星接続・電圧の訂正)でつながりが変わると、二重登録の断片が新しくでき、#42 の付け替え
    # 条件もそろう(静岡の富士川以東の 2 変電所が chubu のまま残った=手順の経路依存)。正典は増分で
    # 当てていたので偶然そろっていた。ここで同じスクリプトをもう一度流す。冪等なので 2 回目は何もしない
    ("node_hygiene_final", [sys.executable, "scripts/apply_node_hygiene.py",
                            "--mixed-pref", "--write"], False),
    # 変電所プロパティ層(オーナー指示 2026-08-26「導体数・回線数を変電所の
    # プロパティに」): 構造DB terminal × OSM線タグ(circuits/wires/cables)を
    # 変電所ごとに集約し、built の sub ノードへ sub_props を付与。冪等
    ("substation_properties", [sys.executable,
                               "scripts/build_substation_properties.py",
                               "--attach"], False),
    # SubSLD Pages機能(docs/subsld.html)のデータ書き出し(オーナー指示 2026-08-27)。
    # 構造DB+方向推定→compact JSON(≈2.4MB)。ブラウザ側でSLDPaneをSVG描画
    ("subsld_pages", [sys.executable,
                      "scripts/export_subsld_pages.py"], False),
    ("subsld_ways", [sys.executable,
                     "scripts/export_subsld_ways.py"], False),
    # ループ(閉路)構造(オーナー指示 2026-08-28「ループとかも見れるの?」)。
    # circuit_rank=E-V+C と橋判定。開閉操作の意味(迂回できるか)を読むのに使う
    ("loops", [sys.executable, "scripts/export_loops.py"], False),
    ("export_map_tiers", [sys.executable, "scripts/export_map_tiers_from_built.py"], False),          # ① 系統図tier+属性
    ("run_full_powerflow", [sys.executable, "scripts/run_full_powerflow_from_db.py", "--max-ac-buses", "20000"], True),  # 全規模AC(②前提・サーバ)。既定6000ではwest10193/east6205がDC-only=summary再現不能のため明示(2026-06-27, west_ac_convergence #7)
    # ③ SLD。枝の負荷率に潮流の結果(powerflow_full)を使うので、潮流の後に置く(2026-10-24。それまで前にあり、
    # いつも 1 回前の潮流で書いていた。--light では潮流を飛ばし、コミットしてある潮流の結果から書く)
    ("gen_sld", [sys.executable, "scripts/gen_sld_from_built.py"], False),
    ("gen_national_overview", [sys.executable, "scripts/gen_national_overview_from_full.py"], False),  # ② 全国概観
    # N-1 全枝スクリーニング(正典の 4 島・上位 5 件は AC で解き直す・約 4 分)と、地図の Ybus / N-1 タブが
    # 読む要約(2026-10-21 から。それまでタブは旧系譜の地域別 N-1 を出していた)
    ("n1_screening", [sys.executable, "scripts/sensitivity/n1_screening.py",
                      "--islands", "hokkaido", "okinawa", "east", "west", "--ac-verify", "5"], True),
    ("export_n1_pages", [sys.executable, "scripts/export_n1_pages.py"], False),
    # 配布する MATPOWER ケース(dist/matpower_national)。2026-10-20 から正典系譜で書く
    ("export_matpower_canonical", [sys.executable, "scripts/export_matpower_canonical.py"], True),
    ("export_cim", [sys.executable, "scripts/export_cim.py"], True),
    # 正典の 4 島から CIM/CGMES Level 2(dist/cim_canonical・2026-10-21)。cim2pp で読み戻して解けるかも確かめる。
    # 上の export_cim は介入前の OSM から地理情報だけを書く Level 1(比較用)
    ("export_cim_canonical", [sys.executable, "scripts/export_cim_level2.py",
                              "--topology", "canonical", "--verify"], True),
    ("build_static_site", [sys.executable, "scripts/build_static_site.py"], False),
    # ④ 出典容量反映 — build_static_site が plants_utility/ipp/all を作り直すため、必ずその後に再適用。
    # 順序を誤ると live/regen で capacity_mw_sourced・出典リンクが消える(2026-06-26 修正)。
    ("apply_capacity_sources", [sys.executable, "scripts/apply_capacity_sources.py"], False),
    # 全面改修Phase5フル統合: Pagesエディタを単一の正(templates/editor.html)から再生成。
    # 静的shimでフル:8088エディタがPages上で動く(drift防止・最後にdocs/editor.htmlへ書く)。
    ("build_pages_editor",
     [sys.executable, "scripts/build_pages_editor.py", "--out", "docs/editor.html"], False),
]


# 正典に増分で当てるときは追記でまとめる帳簿(apply_node_hygiene の _merge_ledger)。基底から作り直すときは
# 前の版の行が古くなる(消えたノードの付け替えが残り、帳簿とマーカーの数が合わなくなった・2026-10-21)ので、
# build_editor_data から流すときは最初に空にする。中身はこの回の作り直しで当てた分だけになる(git に前の版は残る)
LEDGERS_RESET_ON_REBUILD = [
    os.path.join(ROOT, "docs", "data", "fragments", "node_hygiene_ledger.json"),
    os.path.join(ROOT, "docs", "data", "fragments", "mixed_pref_ledger.json"),
    os.path.join(ROOT, "docs", "data", "fragments", "uniform_freq_ledger.json"),
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
    if not args.stamp_only and not getattr(args, "skip_build_editor_data", False):
        for p in LEDGERS_RESET_ON_REBUILD:
            if os.path.exists(p):
                os.remove(p)
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
    # 自分の欄だけを更新する(2026-10-21)。上書きすると、別のスクリプトが刻んだ欄
    # (record_osm_snapshot.py の osm_snapshot など)が消えていた
    prev = {}
    if os.path.exists(MODEL_VERSION_PATH):
        try:
            with open(MODEL_VERSION_PATH, encoding="utf-8") as f:
                prev = json.load(f)
        except (OSError, json.JSONDecodeError):
            prev = {}
    stamp = {**prev, **stamp}
    with open(MODEL_VERSION_PATH, "w", encoding="utf-8") as f:
        json.dump(stamp, f, ensure_ascii=False, indent=2)
    print(f"\nMODEL_VERSION: {head}{' (dirty)' if dirty else ''} → {MODEL_VERSION_PATH}")
    print(f"  steps: {[(k, v['status']) for k, v in results.items()]}")


if __name__ == "__main__":
    main()
