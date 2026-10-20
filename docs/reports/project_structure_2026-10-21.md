# プロジェクトの全体構造と「クソ機能」の候補 2026-10-21

オーナー指示「クソ機能とか rag とか graphRAG とかでプロジェクトの全体構造をもっと見ていくべき」。io（Pages）の一新を、ページを 1 枚ずつ直すのではなく、プロジェクトの本当の構造に合わせて進めるための台帳。分析は AI（Claude Opus 5.5 のサブエージェント）で、リポジトリには書き込まずに行った。

- 方法: コードの関係グラフ（graphify、`--code-only`・LLM 不使用・外部送信なし）を作り直した（10,815 ノード / 26,069 エッジ、11 秒）。これに利用の痕跡を重ねた。痕跡として見たのは、git の最終更新、Snakefile・regenerate_all・CI・launchd・テスト・カタログ・README からの参照と、AST で解決した import。
- 根拠の表（このフォルダ `project_structure_2026-10-21/`）:
  - `candidates.csv` … 候補 28 件。項目は何か・なぜか・根拠・影響範囲・推奨。
  - `pillars_table.csv` … 柱ごとのファイル数・テスト・最終更新・30 日のコミット数・健康状態。
  - `signals.csv` … 全 513 ファイルの柱・日付・`graphify affected` の件数・参照数。
- **推奨はすべて「消さずに、導線から外す・退役と明記する」**（オーナー方針「資産はちゃんと崩さずに残しておくこと」）。

## 全体の地図（12 の柱 ＋ 旧系譜）

| 柱 | 主なもの | 状態 |
|---|---|---|
| 1 取得・エンリッチ | fetch_*・enrich_*（06-17 に封鎖済み） | 止まっている |
| 2 正典 DB・出典台帳 | src/db・scripts/db・capacity_sources | 止まっている（安定・テストが厚い） |
| 3 建造（built）と接続の修理・介入 | build_editor_data・apply_*（#28〜#51） | 生きている。再現の穴あり（B7） |
| 4 変電所の構造 | src/stations・SubSLD | 生きている（いちばん活発） |
| 5 潮流・Ybus（計算の核） | run_full_powerflow_from_db（build_island_net）・gen_ybus_* | 生きている。核が scripts/ にある（E1） |
| 6 解析ツール | sensitivity・capacity・CPF・diagnostics | 止まっている。一部は旧系譜 |
| 7 UC | src/uc・uc_to_pf_built | 核は生きている |
| 8 動態・周波数 | swing_solver・agc・DAE 枠組み | 止まっている（8 月末で一段落） |
| 9 観測との照合 | 公表インピーダンス・keitouzu・toporag | 断続的に生きている |
| 10 リアルタイム | でんき予報・日別断面・pulse（launchd で毎時） | 生きている |
| 11 配布・相互運用 | export_matpower_canonical・dataset・CIM | 生きているが入口がねじれている |
| 12 Pages・ローカル | build_static_site・dashboard・src/server | 作り直し中 |
| X 旧系譜（snapped / legacy） | build_and_solve・run_national_powerflow・src/reconstruction・src/ac_powerflow | 退役のはずが、CLI・README・:8088 の入口に残っている |

テストは退役した側に厚く付いている。例えば ReconstructionConfig へのテストからの辺は 58 本ある。一方、正典の核である build_island_net へのテストからの辺は 4 本しかない（E2）。

## いちばん効いたもの

**D1 地図は正典ではなく、介入前の基底 OSM を出していた**（この日に確認・修正）

- `docs/data/lines_*`・`subs_*` を、2 本のスクリプトが同じ名前で書いていた。
  - `export_map_tiers_from_built.py`：正典から書く。
  - `build_static_site.py`：基底 OSM から書く。deploy でも regenerate_all でも、こちらが後に走って上書きしていた。
- 証拠：
  - 地図の線は 40,087 本で、基底の OSM と一致した。正典の枝は 19,944 本。
  - 西島根〜三隅の線は、正典では 220 kV（介入#51）なのに、地図には 275 kV で出ていた。
- 修正（PR `feat/map-from-canon`）：正典の層を `docs/data/map/` に分けて書き、地図はそこを読むようにした。基底 OSM の層は、編集と CSV のためにそのまま残した。deploy にも正典の層を書く段を足し、再発を防ぐ検査 `tests/test_map_tiers_canon.py` を付けた。

## すぐ直せるもの（io 一新の中で進める）

| id | 何か | 直し方 |
|---|---|---|
| D2 | ダッシュボードの規模の数字（17,841 ノード・成分 962）は built/index.json の古い値。all.json 本体は 17,738 ノード・19,944 枝 | **済（PR #83）** 数字を all.json から数え直す |
| B1・A1 | 「MATPOWER ケースを書き出す」カードが、比較用になった export_national_matpower と psdat の説明文書を指している。説明の「GENCOST つきで runopf にそのまま」も誤り（配布物に gencost は無い） | **済** カードを正本の export_matpower_canonical と dataset/01 の README へ。説明を直した |
| B5・A1 | 「Ybus の健全性診断」「連続潮流」のカードが snapped 系譜 | **済** カードに「旧系譜」の札と注記。CIM・取り込みデモ（snapped）、データ品質の監査（介入前の OSM）、再生成（B7）にも注記 |
| C6 | docs/js/powerflow.js はどのページも読んでいない | アーカイブとして残す（済み） |
| — | カタログに `lineage`（built / snapped / legacy / base_osm）・`data_as_of`・`pillar` を足す | **lineage は済**（built / stations / snapped / base_osm / frozen / mixed / text）。built 以外は注記が無いと落ち、ソースが旧系譜の網を組む関数を import していたら built と名乗れない検査（tests/test_pages_dashboard.py）。`data_as_of`・`pillar` は残り |

## オーナーの判断が要るもの

| id | 何か | 選択肢 |
|---|---|---|
| B7 | 正典 all.json と再生成の手順（Snakefile・regenerate_all）がずれている。正典に当てた apply_mixed_voltage_circuits（#47）が STEPS に入っておらず、今 regenerate_all を回すと正典が変わる（推測・未実行） | **済（10-21・実測）** #47 を STEPS・Snakefile に入れ、抜けを落とす検査を足した。ただし今の再生成は #47 を足しても正典を一発では再現しない（ノード +9・枝 −37・par 107 枝）。原因は正典に当て直していないバグ修正と順序の経路依存で、差の向きはまちまち → 正典は置き換えず、差を `docs/reports/regenerate_reproducibility_2026-10-21.md` に記録 |
| A7 | 週次の遅いテストが落ち続けている。**訂正（10-21 実測）**: 「4 週連続」ではなく 06-14 の初回から 19 回すべて赤。09-27 は pulp 4.0 で conftest の import が落ちたもの（10-02 に修正済み）で、ほかは sweep の東京 99 > 25。閾値 25 は導入時（06-10）の基準値でも四国 35 で成り立っていなかった。測っているのは地域別のスナップ済みの網（builder=snapped と build_and_solve）| **済（10-21・オーナー委任）** sweep は地域ごとの実測を記録として固定（帯 ±20%）。正典の 4 島を全規模の AC で解く週次ジョブ canonical-islands を足した（それまで正典を解く pytest は 0 本） |
| E1 | 正典の網づくり build_island_net が scripts/run_full_powerflow_from_db.py（1,782 行）にあり、50 ファイルが import している。src から scripts への逆向きの import が 3 か所ある | **済（10-21・オーナー委任）** 実体を `src/powerflow/full_from_built.py` へ移し、`scripts/run_full_powerflow_from_db.py` は入口として残した（import すると同じモジュールが返るので 50 本の import と monkeypatch はそのまま）。パスで読み込む 11 か所とソースを読むテストは新しい置き場所へ。src から scripts への逆向きの import は tools_dashboard の 1 か所を直した |
| A1・B2・B3 | CLI（`ajgrid solve`・`uc to-pf`・`cim`）・README の Quickstart・:8088 の潮流 API が旧系譜を向いている。潮流を解くファイルは 84 本ある | **済（10-21・オーナー委任）** `ajgrid pf`・`ajgrid matpower` を足し、`uc to-pf` を正典版へ（旧版は `to-pf-snapped`）。`solve`・`cim`・:8088 の /api/powerflow・/api/matpower は旧系譜と明記（:8088 の 2 つはどこからも呼ばれていなかった）。README の Quickstart・地図の説明（8 タブ→4 タブ）・GIF を今の io に |
| D3・D4 | powerflow_full（08-28）・N-1（06-03）・CIM（Level1 は基底、Level2 は snapped）の出力が古い | **一部済（10-21）** powerflow_full（全規模の潮流・4 島とも AC 収束、西は 08-28 版で不収束だった）と N-1（正典の 4 島）を手元で作り直した（それぞれ 3 分弱・4 分弱でサーバー不要）。地図の Ybus タブの N-1 は正典の結果に替え、旧系譜の表は記録として折りたたんだ。正典と出力の規模がずれたら落ちる検査を付けた。CIM（旧系譜）は残り |
| D5 | README の南海トラフの節と hero.gif が残っている（ハザードは 10-09 に非公開へ移管済み） | **済（10-21）** 節は残して見出しに「別リポジトリ・非公開」。hero.gif の最後の場面は動揺に差し替え（このリポジトリで回せるもの） |

## Pages の柱の見せ方（提案）

今の 8 分類を、プロジェクトの柱に合わせて 6 つとアーカイブに組み替える案。**済（10-21・オーナー委任）**: 下の表どおりに組み替えた（`docs/data/tools_catalog.json` の categories）。

| カテゴリ | 入れるもの | 柱 |
|---|---|---|
| 見る（いまの系統） | 系統図・潮流マップ・pulse（正典の版バッジつき） | 3・10・12 |
| 変電所の中 | SubSLD・変電所の結線の変更箇所 | 4 |
| 計算する | Ybus・N-1（正典で作り直す）・全規模の潮流・SCR・CPF・動揺・UC | 5〜8 |
| つくり方と根拠 | 取得 → 正典 DB → 介入台帳・EGGC・エディタ → 観測との照合 | 1〜3・9 |
| 持ち帰る | ダウンロード・MATPOWER（正本）・CIM（注記つき）・ローカル版 | 11 |
| 学ぶ | EGGC の教材・スライド・解説動画 | 横断 |
| 記録（アーカイブ） | compare・uc_map・review・codex のまとめ・旧系譜の説明 | X |
