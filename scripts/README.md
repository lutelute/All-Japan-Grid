# Scripts

データ処理・解析・公開物生成スクリプト集（2026-06-08 全面棚卸し）。

役割別に5系統 + 隔離置き場:

| 系統 | 役割 |
|---|---|
| [1. OSM取得](#1-osm取得-fetch) | Overpass API からの一次データ取得 |
| [2. エンリッチ・監査](#2-エンリッチ監査-enrich--audit) | 欠落属性の自動補完とデータ品質監査 |
| [3. モデル構築・解析](#3-モデル構築解析-build--run) | MATPOWERケース構築、潮流/CPF/N-1/動態/UC 実行 |
| [4. 公開物生成](#4-公開物生成-export--publish) | GitHub Pages・CIM/CGMES・図版データの生成 |
| [5. 図版](#5-図版-figures) | 論文・README 用のワンショット作図 |
| [diagnostics/](#diagnostics--west非収束の診断群) | west島AC非収束の調査スクリプト群（pytest対象外） |
| [deprecated/](#deprecated--隔離済み旧版) | 隔離済み旧版（実行しないこと） |

---

## 1. OSM取得 (fetch)

| Script | 役割 |
|---|---|
| `fetch_subdivided.py` | OSMデータ取得（大規模地域はタイル分割、重複除去込み） |
| `fetch_plants.py` | 発電所（`power=plant`）の Overpass 取得 |
| `osm_fetch_progress.py` | 全地域の取得進捗をリアルタイム表示するモニタ |

## 2. エンリッチ・監査 (enrich / audit)

GeoJSON の欠落属性（名称・事業者・燃料種別）を外部ソースで自動補完する。
**実行順序が重要** — `enrich_all.py` が正しい順序で一括実行するオーケストレーター。

| # | Script | Description | API | Cache |
|---|--------|-------------|-----|-------|
| 1 | `audit_data_quality.py` | ベースライン監査: プレースホルダ件数の計測（最終検証にも使用） | - | - |
| 2 | `enrich_substations_geocode.py` | 変電所名称: Nominatim逆ジオコーディング → `{area}変電所` | Nominatim | - |
| 3 | `enrich_plants_p03.py` | 発電所属性: P03国土数値情報マッチング + 事業者名正規化 | - | - |
| 4 | `enrich_overpass_tags.py` | 発電所属性: OSM IDでOverpass APIバッチ取得 | Overpass | `data/cache/overpass_tags.json` |
| 5 | `enrich_plants_geocode.py` | 発電所名称: Nominatim逆ジオコーディング → `{area}発電所` | Nominatim | `data/cache/plants_geocode.json` |
| 6 | `enrich_lines_endpoints.py` | 送電線名称: 端点変電所マッチング → `{from}~{to}線` | - | - |

```bash
python scripts/enrich_all.py             # 全地域・全ステップ
python scripts/enrich_all.py --region okinawa
python scripts/enrich_all.py --dry-run   # 実行計画のみ
```

**レート制限**: Nominatim 1.1秒/req（全発電所 ~16,000件で約5時間）、Overpass 100 IDs/バッチ・10秒間隔・429/504で指数バックオフ。

> ⚠ **注意**: 現在のエンリッチは `data/*.geojson` を **in-place 更新**する。raw OSM とキュレーション結果が
> 同一ファイルに混在するため、OSM 再取得はエンリッチ結果を失う。DB統一（raw/curated/derived 3層化）で
> 解消予定 — `REVIEW_FINDINGS.md` 参照。

### 監査・補完

| Script | 役割 |
|---|---|
| `audit_substation_plant_overlap.py` | 変電所/発電所の分類混在を4カテゴリで検出（`--fix` でカテゴリC タグ誤りを修正、出力: `data/audit/substation_plant_overlap.json`） |
| `complement_plants.py` | AGJ ↔ JRP（姉妹プロジェクト）発電所データの相互補完 |
| `restore_missing_plants.py` | JRP の kyushu/okinawa plants_lite → AGJ 形式 plants.geojson 再生 |
| `fix_plant_capacity.py` | 容量値の W → MW 単位修正（OSM 単位なし値対応） |
| `cross_validate.py` | AGJ ↔ JRP データ整合性クロスバリデーション |

（`complement_report.md` / `cross_validate_report.md` は過去実行の結果レポート）

## 3. モデル構築・解析 (build / run)

| Script | 役割 |
|---|---|
| `build_alljapan_full.py` | 全10地域 + 全国の MATPOWER ケース構築（→ `output/matpower_alljapan/`） |
| `build_load_timeseries.py` | 時系列負荷乗数の生成（日負荷曲線 + 年間トレンド YAML から） |
| `run_national_powerflow.py` | 全国ゾーン（多島）潮流 |
| `run_cpf.py` | 連続潮流（CPF）— P-V ノーズカーブ・負荷余裕 |
| `run_n1_contingency.py` | N-1 単一線路停止スクリーニング（地域別） |
| `run_dynamics_alljapan.py` | 動態解析スイート（動揺・モーダル・短絡） |
| `run_psdat_powerflow.py` | psdat-python 統合（MATPOWER 形式 + 古典スウィング） |
| `run_uc_full_3state.py` | 全国783機 UC（cold/warm/hot 3状態起動コスト） |
| `diagnose_ybus.py` | Ybus から潮流可解性を診断（`docs/YBUS_SOLVABILITY.md` の実装） |
| `run_pf_1h.m` / `run_pf_24h.m` / `run_pf_8760h.m` / `test_pf_quick.m` | MATLAB/MATPOWER 側での .mat ケース検証 |

## 4. 公開物生成 (export / publish)

| Script | 役割 |
|---|---|
| `export_powerflow_pages.py` | **潮流パイプラインの司令塔**（`build_and_solve`）。Pages 潮流タブ用データ一式を生成 |
| `regen_powerflow_snapped.sh` | 潮流結果の再生成 → ステージング → `--promote` で `docs/data/powerflow/` 差し替え |
| `export_substations_geojson.py` | 詳細ポップアップ用の全属性付き変電所 GeoJSON（`data/` 直読み、電圧推定ロジック込み → `docs/data/substations.geojson`） |
| `export_generators_geojson.py` | P03 GML + `data/reference/generator_defaults.yaml` → `docs/data/generators.geojson`。**⚠ 現在 ImportError**（依存 `src/parser` が git 履歴に一度も収載されておらず起動不可。出力済みの generators.geojson は追跡済みで配信は継続。修理方針は `REVIEW_FINDINGS.md`） |
| `export_cim.py` | CIM/CGMES **Level 1**（EQ+GL カタログ）→ `dist/cim/` |
| `export_cim_level2.py` | CIM/CGMES **Level 2**（EQ/TP/SSH/SV/GL 求解可能ケース）→ `dist/cim_level2/` |
| `build_static_site.py` | Pages 地図レイヤ用の軽量 GeoJSON（`subs_*` / `lines_*` / `plants_*`） |
| `slim_geojson.py` | GeoJSON 軽量化（プロパティ削減） |
| `gen_pf_geojson.py` | 潮流結果 → `pf_buses.geojson` / `pf_branches.geojson` |
| `gen_backbone_ring.py` | 500/275kV バックボーンのリング構造検出（networkx 二重連結成分） |
| `optimize_sld_layout.py` | 単線結線図（SLD）の配置最適化 — Barycenter 反復で交差最小化 |
| `export_eggc_trace.py` | EGGC（証拠ゲート付き系統コンフレーション）の判定を再走し、**過程**（端点スナップ候補・経路ポリライン・main/off-main 内訳・周辺OSM線）を `docs/data/eggc_trace.json` へ。**入力は適用前スナップショット `--built docs/data/built/all.json.pre_route.bak`**（現行正典で走らせると断片が既に main のため証拠ゲートがほぼ閉じる＝冪等性の裏返し） |
| `build_eggc_explainer.py` | 上記トレースを埋め込んだ**自己完結の教材ページ** `docs/eggc_explainer.html`（テンプレは `scripts/templates/eggc_explainer.src.html`）。ブラウザ内で Dijkstra を実走させる |
| `build_eggc_slides.py` | EGGC の発表デッキ `docs/slides/eggc_2026-08-17.html`（図は data URI 埋め込み・テンプレは `scripts/templates/eggc_slides.src.html`）。pptx 版は `docs/slides/eggc_2026-08-17.md` を marp-pptx で変換 |

> Pages のポップアップは2系統のデータを使う: 地図レイヤ用（`build_static_site.py` 生成）と
> 詳細ポップアップ用（`export_substations_geojson.py` / `export_generators_geojson.py` 生成）。
> enrichment 後は**両方の再生成**が必要（片方だけだと「Unnamed」が残る）。

## 5. 図版 (figures)

論文（`papers/figs/`）・README（`docs/assets/figs/`）用のワンショット作図。

| Script | 出力 |
|---|---|
| `gen_national_map.py` | 全国送電網トポロジ図 `fig_national_all.png` |
| `gen_layer_figs.py` / `gen_layer_figs_white.py` | 電圧レイヤ別図（黒背景 / 白背景・論文用） |
| `gen_satellite_v3.py` | 衛星画像突合せ検証図（Web Mercator 投影） |
| `gen_dynamics_fig_v2.py` | 動態応答図（Kundur 2エリアモデル） |
| `gen_swing_waveforms.py` | 動揺波形図 |
| `gen_nx_proper.py` / `gen_nx_500kv_national.py` / `gen_nx_multiregion.py` | N-x カスケード安定度解析図 |
| **`gen_ybus_from_db.py`** | **Ybusタブの全アセット（地域別/大元/Spy/ギャラリー/組立アニメ）を DB更新済み建造モデル `docs/data/built/` から生成（正典・エリア間連系線含む）。`--build` で組立gif** |
| `gen_ybus_national.py` / `gen_ybus_white.py` | Ybus 図（論文/README 用・白背景の `papers/figs` `fig_ybus_*`）。※最近傍近似のため**アプリ表示には使わない**（アプリは `gen_ybus_from_db.py`） |
| `gen_uc_dispatch_profile.py` / `gen_uc_national_overview.py` / `gen_uc_regional.py` | UC ディスパッチ・全国概況・地域別図 |
| `make_readme_gifs.py` | README のデモ GIF（Pages をブラウザで台本どおりに操作して録画・南海トラフ・予告編。`--list` でシーン一覧） |
| `plot_eggc_figs.py` | EGGC のスライド用 3 図（before/after・証拠ゲート散布・判定内訳と線長）→ `docs/reports/figs/eggc_*.png`。入力は `docs/data/eggc_trace.json` |
| `plot_eggc_gallery.py` | EGGC で置換された線の**全数**を画像化（一覧 1 枚・エリア別 4 枚・特徴的な 10 本の before/after）。台帳の累積 replaced が正で、後発ケースは `docs/data/eggc_trace_current.json`（現行正典から `--names` 指定で抽出）で補う。台帳の二重登録（端点数十m差）も検出して図に印を付ける |

> ⚠ 図版スクリプト群にはヘルパー（haversine・色表・フォント設定）の重複が多い。
> 共有モジュール化は Phase C（`REVIEW_FINDINGS.md`）で対応予定。

## db/ — 統一グリッドDB（DB統一 R/C/D 層）

`docs/DB_ARCHITECTURE.md` の実装。raw OSM・キュレーション・派生を分離し、機械的更新を可能にする。

| Script | 役割 |
|---|---|
| `db/ingest.py` | 現 GeoJSON を raw_features（R層）+ enrichments（C層、provenance復元）に分解取込 → `data/grid.db` |
| `db/curate.py` | C層へのキュレーション書き込み（手動上書き `--set f=v --where-name/...`、bulk `--import`）。raw を書き換えず再fetchでも保全される |
| `db/export.py` | DB → GeoJSON 再生成（`--verify` で元ファイルとの golden 比較、`--dump-enrichments` で追跡用 JSONL 出力） |

```bash
python scripts/db/ingest.py                          # 全10地域 → data/grid.db
python scripts/db/curate.py --layer plants --region hokuriku \
    --where-osm-id 62271105 --set 'operator=北陸電力'
python scripts/db/export.py --verify                 # golden 検証
```

> DB本体 `data/grid.db` は gitignore（再構築可能）。追跡する正本は `data/db/enrichments.jsonl`（C層ダンプ）。

## diagnostics/ — west非収束の診断群

`diagnostics/test_west_*.py` / `test_kansai_*.py` は west 島 AC 非収束の根本究明
（`docs/WEST_AC_ANALYSIS.md`）に使った調査スクリプト。**pytest のテストではない**
（`pytest.ini` の `testpaths = tests` で収集対象外）。単体実行する:

```bash
python scripts/diagnostics/test_west_reactive.py
```

## deprecated/ — 隔離済み旧版

後継と同じ出力ファイルを上書きするため隔離した旧版スクリプト。経緯は
`scripts/deprecated/README.md` 参照。**通常運用では実行しないこと。**

---

## 全スクリプト索引（自動生成）

`cog -I . -r scripts/README.md` で作り直す（`scripts/scripts_index.py`）。説明は各ファイルの冒頭の 1 行。

<!-- [[[cog import cog, scripts.scripts_index as si; cog.out(si.table()) ]]] -->
直下 251 本(サブフォルダは上の各節)。🔒 = Snakefile・CI・tests・src・launchd が名前で参照(動かすなら参照元も直す)。


<details><summary><b>取得 / fetch</b>(17 本)</summary>

| スクリプト | 説明 |
|---|---|
| `fetch_area_fuelmix.py` | 各社「エリア需給実績」(燃料別・30分値)の取得 → zone×hour×燃料MW. |
| `fetch_capacity_tables.py` | 一般送配電事業者の「予想潮流・空容量一覧表」を取得する(介入#45 の較正入力). |
| `fetch_denkiyoho.py` | でんき予報(各社 当日需要実績・1時間値)の準リアルタイム取得. |
| `fetch_estat_mesh.py` 🔒 | Fetch 2020-census 1 km mesh population (e-Stat GIS, stats T001140). |
| `fetch_fit.py` | FIT/FIP 事業計画認定情報を47都道府県ぶん取得する。 |
| `fetch_hks.py` | OCCTO「ユニット別発電実績公開システム」(HKS) から30分値の発電実績を取得する。 |
| `fetch_occto_kohyo.py` 🔒 | Fetch OCCTO's public wide-area CSV API (no registration required). |
| `fetch_orphan_supplements.py` | I3: fetch the ways our extracts missed around isolated-fragment tips. |
| `fetch_osm_refresh.py` | OSM再抽出(2026-08 大工事): lines+substations を osm_id+全タグ付きで再取得する。 |
| `fetch_plants.py` 🔒 | Fetch power plant (power=plant) data from OpenStreetMap via Overpass API. |
| `fetch_rei_gridmap.py` | 自然エネルギー財団「洋上風力開発エリア&送電線マップ」のArcGIS層を取得する. |
| `fetch_subdivided.py` | Subdivided OSM fetcher for large regions (Hokkaido, Tokyo, etc.). |
| `fetch_system_disclosure.py` | 系統情報の公表（一般送配電事業者10社）を取得する。 |
| `fetch_transformer_lists.py` | 全国の変電所変圧器台帳(非公開・私的検証用)を各社の「空容量・予想潮流一覧」から作る. |
| `osm_fetch_progress.py` | OSM Fetch Progress Monitor — real-time progress bar for all regions. |
| `osm_node_topology.py` | B路線プロトタイプ: 生OSM(ノード参照)から**正確な**接続トポロジを得る。 |
| `osmnx_ab.py` | osmnx(標準ツール)で OSM node-sharing トポロジを取得し、我々の手法とA/B。 |

</details>

<details><summary><b>エンリッチ・適用 / enrich & apply</b>(20 本)</summary>

| スクリプト | 説明 |
|---|---|
| `apply_capacity_sources.py` 🔒 | 出典必須DB(generator_capacity_sources.jsonl)の容量を発電所geojsonに反映(出典付き)。 |
| `apply_circuit_sources.py` 🔒 | 回線数(並列回線 `par`)の出典補完 — 介入#44 候補(2026-09-02). |
| `apply_connections.py` | E3: 人間が承認した接続を supplement に統合し、島削減をA/B検証する — 2026-06-14。 |
| `apply_disclosure_v2.py` 🔒 | 孤立変電所の実証接続 v2 — 公表線路・分岐タップ・変圧器実証・同一敷地同定。 |
| `apply_mixed_voltage_circuits.py` | 併架線の回線数を電圧クラスごとに正す — 介入#45 候補(2026-09-21). |
| `apply_node_hygiene.py` 🔒 | 介入#35 — 偽断片のノード衛生(跨region二重登録の解消). オーナー承認 2026-08-26. |
| `apply_satellite_connections.py` 🔒 | 介入#36 — 衛星判読クラスの接続適用(1件ずつオーナー承認制). |
| `apply_tepco_connections.py` 🔒 | TEPCO公表で解決した孤立変電所の接続を、正典を壊さず検証・worklist化する。 |
| `complement_plants.py` | AGJ ↔ JRP 発電所データ相互補完スクリプト |
| `enrich_all.py` | Unified enrichment pipeline for all GeoJSON layers. |
| `enrich_lines_endpoints.py` 🔒 | Enrich unnamed transmission lines with endpoint-based names. |
| `enrich_overpass_tags.py` 🔒 | Enrich plant features with missing attributes via Overpass API batch tag queries. |
| `enrich_plants_geocode.py` 🔒 | Enrich unnamed plants with reverse-geocoded area names. |
| `enrich_plants_p03.py` 🔒 | Enrich OSM power plant data with 国土数値情報 P03 (発電施設). |
| `enrich_substations_geocode.py` 🔒 | Enrich unnamed substations with reverse-geocoded area names. |
| `fix_plant_capacity.py` | Fix plant capacity values: convert W -> MW for unitless OSM values. |
| `fix_pptx_math_size.py` | marp-pptx が書いた OMML 数式の文字サイズを PowerPoint に効かせる。 |
| `merge_powerjp_timeseries.py` | 24時刻UC潮流(flows_ts_*.json)を flow_map の flows_*.geojson へ結合する. |
| `migrate_osm_refresh.py` | OSM再抽出の移行(大工事フェーズ2): data/osm_refresh/* を data/ へ、名前資産を引き継いで移す。 |
| `record_osm_snapshot.py` 🔒 | OSM断面時刻(osm3s)の記録 — 国際ベンチマーク劣位「OSM時刻未記録」の解消。 |

</details>

<details><summary><b>監査・検証 / audit & validate</b>(13 本)</summary>

| スクリプト | 説明 |
|---|---|
| `audit_data_quality.py` 🔒 | Audit data quality across all GeoJSON files. |
| `audit_mixed_pref_flip.py` 🔒 | 混在県個別化(介入#42)のドライラン監査 — all.json は変更しない(2026-09-02). |
| `audit_substation_plant_overlap.py` 🔒 | Audit substation/plant classification overlap in OSM-derived GeoJSON data. |
| `compare_observed_derived_impedance.py` | 公表インピーダンス(observed)でAGJの線路パラメータ推定(derived)を答え合わせする。 |
| `compare_station_layers.py` 🔒 | SubSLD(構造 DB)と node-breaker 観測層を、同じ変電所ごとに突き合わせる。 |
| `cross_validate.py` | AGJ ↔ JRP データ整合性クロスバリデーション |
| `match_impedance_to_model.py` | 公表インピーダンス（observed）をAGJ建造モデルの枝に対応付ける。 |
| `reconcile.py` 🔒 | OCCTO-actuals reconciliation report (PLAN_66KV M10-3). |
| `reconcile_isolated_multi.py` | 東京でやった「孤立変電所×TEPCO公表接続の突合」を **関西・北海道・東北** に横展開する。 |
| `reconcile_isolated_tepco.py` | 監査の東京「孤立変電所(A=繋ぐべき)」を、TEPCOの公表接続で突合する。 |
| `validate_cgmes.py` 🔒 | Strict, independent validation of the exported CGMES RDF/XML. |
| `validate_intervention.py` 🔒 | モデルの介入の妥当性を、独立した公表資料と潮流の実績で採点する(介入 #48 を最初の対象に)。 |
| `verify_crosswalk_by_linename.py` | 公表インピーダンスの対応付けを **線名** で検証・修正する（#47）。 |

</details>

<details><summary><b>構築・解析 / build & solve</b>(95 本)</summary>

| スクリプト | 説明 |
|---|---|
| `analyze_transformer_nodes.py` | D3: OSM power=transformer node evidence vs the standard trafo ladder. |
| `build_alljapan_full.py` | Build FULL-SCALE MATPOWER cases for ALL 10 regions + All-Japan. |
| `build_connectivity_audit.py` | 建造モデルの連結性を「目で見える」形に落とす監査。 |
| `build_dashboard_data.py` 🔒 | Pages ダッシュボード(docs/index.html)が読む要約 docs/data/dashboard.json を生成する. |
| `build_editor_data.py` 🔒 | Pre-render the built (snapped) model view to static JSON for the Pages editor. |
| `build_eggc_explainer.py` | EGGC教材ページをビルドする（テンプレ + トレースデータ → 自己完結HTML）。 |
| `build_eggc_slides.py` | EGGC スライドをビルドする（テンプレ + 図 → 自己完結HTML）。 |
| `build_fit_geojson.py` | 座標化したFIT再エネ設備を地図用GeoJSONにする。 |
| `build_flow_geojson.py` | 線路観測（実測潮流＋運用容量＋インピーダンス）を地図用GeoJSONにする。 |
| `build_fragment_worklist.py` | 断片解消キャンペーンのワークリスト生成 — 孤立成分の素性+証拠候補の棚卸し. |
| `build_g_table.py` | G_DB第2弾: 号機単位のG表(動的定数つき)を出荷する(2026-08-17 並列キャンペーン). |
| `build_generation_geojson.py` | OCCTO ユニット別発電実績（30分値）を地図用に整える。 |
| `build_generator_geojson.py` | 発電所マスタ（大規模層）を地図用GeoJSONにする。 |
| `build_generator_master.py` | 発電所マスタDBを組む（observed層）。 |
| `build_impedance_slides.py` | EGGC スライドをビルドする（テンプレ + 図 → 自己完結HTML）。 |
| `build_island_candidates.py` | A島の接続候補worklistを生成 — 「一つずつ」レビュー用(オーナー: 100件くらいなら確認できる)。 |
| `build_line_observations.py` | 事業者公表の3様式を「送電線No.」で結合し、線路ごとの観測レコードを作る。 |
| `build_load_timeseries.py` | Generate time-series load multiplier data for MATPOWER power flow. |
| `build_network_geojson.py` | 送電網・変電所・発電所を地図ビュー用に軽量化して書き出す。 |
| `build_pages_editor.py` 🔒 | GitHub Pages 用エディタ(docs/editor.html)を **単一の正** から派生生成する。 |
| `build_reports_index.py` | docs/reports/ の索引 INDEX.md を作り直す(月ごと・新しい順)。 |
| `build_static_site.py` 🔒 | Build lightweight static GeoJSON files for GitHub Pages. |
| `build_station_db.py` 🔒 | 変電所の構内結線(node-breaker)の観測層を、電力だけに絞った日本の PBF から作る。 |
| `build_structures_batch.py` 🔒 | 変電所内部構造(node-breaker)の地域一括生成 — 構造DBの正典生成器. |
| `build_subsld_batch.py` | SubSLD法の全所展開 — 実証ペア図PNGの地域一括生成(オーナー指示 2026-08-26). |
| `build_substation_properties.py` 🔒 | 変電所プロパティ層 — 電圧階級・回線数・導体数の全国集約(オーナー指示 2026-08-26). |
| `build_substation_structure.py` 🔒 | 変電所内部構造(node-breaker)の実証ビルダー — GridStitch P2 プロトタイプ. |
| `build_topology_dataset.py` | トポロジ接続データ構築: 全点(鉄塔/変電所点/線頂点)をノード、共有OSMノードを辺として |
| `gen_agc_24h_profile.py` | 周波数セキュリティの24時間断面 — 慣性・N-1・nadirの日内プロファイル. |
| `gen_agc_map_anim.py` | 事故→UFLS→復帰 を地図の上で見せるアニメGIF(苫東厚真トリップ・北海道). |
| `gen_agc_story_fig.py` | AGCの「事故→復帰」ドラマを1枚で見せる注釈付き波形図(全史デッキ用). |
| `gen_all_ac_buses.py` | Rebuild the live map's national bus layer from the current model (D7). |
| `gen_backbone_ring.py` | 500/275kV バックボーンのリング構造を検出し、GeoJSONとして出力する。 |
| `gen_banner.py` | Generate the project hero banner (docs/assets/banner.png). |
| `gen_cim_national_pf.py` | Generate the national power-flow map (fig_cim_national_pf.png). |
| `gen_dynamics_fig_v2.py` | Publication-quality dynamics figure for IEEJ paper. |
| `gen_east_incident_anim.py` | 東全域の大擾乱アニメGIF — N-3→UFLS→回復、2幕構成(2026-08-30 v3). |
| `gen_eastwest_swing_anim.py` | 東西動揺GIF — 50Hz東系統(183機)と60Hz西系統(298機)、各最大機N-1(2026-08-30). |
| `gen_grand_trailer.py` | All-Japan-Grid 全史トレーラーGIF — 組み上げ→UC→AC点灯→西の夜→擾乱→24/24 (2026-08-30). |
| `gen_grid_hero.py` | 全国系統のヒーロー画像(暗背景・電圧クラス発光) — 全史デッキの「掴み」用. |
| `gen_grid_strength_map.py` | 系統強度(短絡容量)マップ — IBR安定性検討のPhase 0(オーナー指示2026-08-17「実施」)。 |
| `gen_interarea_anim.py` | 逆位相動揺(inter-areaモード)GIF — 九州側と関西側の綱引き(2026-08-30 v3). |
| `gen_layer_figs.py` | 3-layer visualization for IEEJ paper: |
| `gen_layer_figs_white.py` | Layer figures with WHITE background for IEEJ paper. |
| `gen_loading_map.py` | ピーク断面ローディングマップPNG — 東西フル網のAC潮流で線路負荷率を地図に(2026-08-30). |
| `gen_national_map.py` | 全国送電網トポロジ図 (fig_national_all.png) |
| `gen_national_overview_from_full.py` 🔒 | 全国基幹概観(電圧帯別)を **正典 powerflow_full** から再生成する (idempotent)。 |
| `gen_national_swing_anim.py` | 全系統動揺GIF — 4島541機、各島の最大機N-1を同時刻表示(2026-08-30). |
| `gen_nx_500kv_national.py` | 全国500kV送電網の実GeoJSONトポロジからYbusを構築し、N-1/N-2過渡安定解析を実施する。 |
| `gen_nx_multiregion.py` | N-1 and N-2 transient stability analysis for multiple regions. |
| `gen_nx_proper.py` 🔒 | 全国500kV+275kV送電網の実GeoJSONトポロジからYbusを構築し、 |
| `gen_paper_figs.py` | Validation-section figures for the papers (PLAN_NEXT P2, ledger 62). |
| `gen_pf_geojson.py` | 潮流計算結果を pf_buses.geojson / pf_branches.geojson として出力. |
| `gen_pipeline_buildup_anim.py` | OSM→系統モデルの組み上げアニメGIF — 「手順が見える」デッキ素材(2026-08-30). |
| `gen_recovery_anim.py` | 周波数が戻るさまGIF — 北海道トリップ→UFLS→LFC/EDCで50.00Hzへ(2026-08-30). |
| `gen_recovery_arc_east_anim.py` | 周波数が戻るさま(東N-3・900秒)GIF — 回復の物語を1本のチャートで(2026-08-30). |
| `gen_regional_networks.py` | 10地域別送電網トポロジ図 (fig_regional_networks.png) |
| `gen_route_tiers.py` | Rebuild the live map's national route tiers from the current model (D7). |
| `gen_satellite_v3.py` | Satellite validation figure v3 – proper contextily with Web Mercator. |
| `gen_scr_map.py` | 系統の強さの地図 — 全バス短絡容量(SCC)マップ(2026-08-30). |
| `gen_sld_from_built.py` 🔒 | SLD(単線結線図 force-graph)データを **正典 built + powerflow_full** から生成 (idempotent)。 |
| `gen_subsld_flipbook.py` | SubSLDフリップブックGIF — 読み方ガイド+全国機械生成の流し(2026-08-30). |
| `gen_swing_map.py` | 運転点込みモーダル: 収束ACのV∠δから機械内部電圧E∠δを構成し、 |
| `gen_swing_modes.py` | 電気機械モード帯の全島推定(G_DB第一歩の検証器・2026-08-17). |
| `gen_swing_wave_anim.py` | 動揺の波が系統を走るアニメGIF — 実インピーダンスの見せ所(2026-08-29). |
| `gen_swing_waveforms.py` | 3地域 最悪N-1 動揺波形比較 (fig_swing_waveforms.png) |
| `gen_uc_dispatch_json.py` | fy2023 UC を解いて 地域×燃料×24h のディスパッチをビューア用JSONに書き出す。 |
| `gen_uc_dispatch_profile.py` | 全国UC 24時間日間プロファイル図 |
| `gen_uc_national_overview.py` | UC national overview figure: all-10-region generation mix as stacked bars + interconnection flows. |
| `gen_uc_regional.py` 🔒 | 10地域別UC 24時間日間プロファイル (fig_uc_regional.png) |
| `gen_uc_stack_anim.py` | UC 24時間ディスパッチ積み上げGIF — 燃料別発電の一日(2026-08-30). |
| `gen_west_ac_map.py` | 西日本フルAC初成立の記念図 — vm熱地図 + 誤帰属検挙マップ(2026-08-30). |
| `gen_west_ac_onset_anim.py` | 第6幕アニメ: 発散が育つ(#38前) → 収束する(#38後) — NR反復の可視化GIF. |
| `gen_ybus_from_db.py` 🔒 | Ybus 可視化を **DB更新済みの建造モデル** から生成する(正典ソース)。 |
| `gen_ybus_national.py` | Generate fig_ybus_national.png: all-Japan combined Ybus sparsity + block structure. |
| `gen_ybus_numeric.py` 🔒 | 数値 Ybus の正典生成器 — built 正典から検証済みアドミタンス行列を出荷する. |
| `gen_ybus_white.py` | Regenerate fig_ybus_all.png with WHITE background. |
| `hunt_fragment_osm_bridges.py` 🔒 | 断片解消キャンペーン第一波 — OSM実線ブリッジの検出と回収. |
| `hunt_fragment_osm_chains.py` 🔒 | 断片解消キャンペーン第二波 — OSM way連鎖の追跡回収. |
| `hunt_fragment_third_wave.py` 🔒 | 断片解消キャンペーン第三波 — 継ぎ目緩和の OSM way 連鎖回収 + 同一敷地同定の提案(ドライラン専用). |
| `rebuild_ab.py` | geojson再生成のA/B: 現行lines vs 再生成lines(電圧伝播+鉄塔fetch由来)で |
| `rebuild_geojson.py` | geojson再生成(②): node-ref生OSMから lines geojson を作り直す。 |
| `route_disclosure_edges.py` 🔒 | 実証接続(直線コード)をOSM実線形へ吸着する — 断片=公表線そのもの の場合のみ。 |
| `run_agc_from_uc.py` | UC → 潮流 → AGC の運用チェーンを1コマンドで通す（論文実証・2026-08-29）. |
| `run_cpf.py` 🔒 | Continuation Power Flow (CPF) — voltage-stability / PV-curve analysis. |
| `run_dynamics_alljapan.py` | All-Japan-Grid 電力系統動態解析スイート |
| `run_full_powerflow_from_db.py` 🔒 | Full-scale national power flow from the canonical built DB (docs/data/built). |
| `run_multimachine_national.py` | 全島・全機動揺つき共シミュレーション — AGC30 → AGC-N を系統全体へ(2026-08-29). |
| `run_n1_contingency.py` | N-1 single-line outage contingency screening per region. |
| `run_national_powerflow.py` 🔒 | National zonal power flow: solve each synchronous AC island as ONE network |
| `run_pf_1h.m` | % run_pf_1h.m — 1時間スナップショット潮流計算 |
| `run_pf_24h.m` | % run_pf_24h.m — 24時間潮流計算（1h間隔 / 30min間隔の2ケース） |
| `run_pf_8760h.m` | % run_pf_8760h.m — 年間8760時間潮流計算 |
| `run_psdat_powerflow.py` | All-Japan-Grid × psdat-python 統合: MATPOWER形式電力フロー + 古典スウィングモデル. |
| `run_uc_full_3state.py` | 全国783機UC（cold/warm/hot 3状態起動コスト）を実行して |

</details>

<details><summary><b>UC / unit commitment</b>(9 本)</summary>

| スクリプト | 説明 |
|---|---|
| `uc_annual.py` 🔒 | 年間 rolling UC — fy2023シナリオ × 合成8760h時系列（ROADMAP P5）。 |
| `uc_annual_merge.py` 🔒 | チャンク並列 uc_annual の結果JSONをマージして年間レポートを作る。 |
| `uc_benchmark.py` 🔒 | UCベンチマーク — データ品質・求解性能・ディスパッチ妥当性のKPI計測。 |
| `uc_island_gap.py` | UC側の島需給恒等式ダンプ — PF島slackの「島間融通」成分を定量化する. |
| `uc_pv_compare.py` | PV有無×UC: 両シナリオの24h UCを解き、(region,fuel,hour)の起動容量とdispatchを保存。 |
| `uc_to_pf.py` 🔒 | UC→潮流 連携検証 — UCディスパッチ断面が送電網で流せるかを確認する。 |
| `uc_to_pf_built.py` 🔒 | UC 24h → built正典(v4銘板)全規模潮流 — 時間別ディスパッチの通年断面検証. |
| `uc_to_pf_national.py` 🔒 | UC→全国ゾーナル潮流 — UC断面を同期島ネットへ地域別注入して検証する。 |
| `uc_validate.py` 🔒 | UC検証 Phase A-1 — 代表日のUC解を発電実績（nas03）と地域×燃料で突合する。 |

</details>

<details><summary><b>書き出し・公開 / export & publish</b>(24 本)</summary>

| スクリプト | 説明 |
|---|---|
| `export_cim.py` 🔒 | Export All-Japan-Grid GeoJSON to CIM/CGMES RDF/XML (EQ + GL profiles). |
| `export_cim_level2.py` 🔒 | Export Level-2 CGMES (a solvable power-flow case) per region. |
| `export_day_flows.py` 🔒 | 指定日の実績需要(でんき予報)で24時刻の全ノーダル潮流を計算し日付別断面を出力. |
| `export_eggc_trace.py` | EGGC(証拠ゲート付き系統コンフレーション)の適用過程を、教材用に**実データで**書き出す。 |
| `export_flow_map_data.py` 🔒 | 潮流方向・発電稼働率マップ(docs/flow_map.html)のデータをエクスポートする. |
| `export_generators_geojson.py` | Export generator data from P03 GML to GeoJSON with enriched attributes. |
| `export_loops.py` 🔒 | ループ(閉路)構造の抽出 — 運用ビュー用(オーナー指示 2026-08-28「ループとかも見れるの?」). |
| `export_map_tiers_from_built.py` 🔒 | 系統図/エリアタブの地図タイルを **DB更新済み建造モデル** から再生成する (idempotent)。 |
| `export_matpower_canonical.py` | 正典系譜のMATPOWERケース出力 — built正典+標準注入で4島(+west_reduced). |
| `export_national_matpower.py` 🔒 | Export the national model as MATPOWER cases — .mat + CSV tables (N4). |
| `export_obs_compare.py` 🔒 | 観測潮流(公表実績の年統計)とモデルの潮流を、線ごとに突き合わせる(潮流マップの「観測と比べる」)。 |
| `export_obs_local.py` | 線クリック用の観測実績オーバーレイ(年統計=集計値)を生成する. |
| `export_other_freq_layer.py` | Export the OTHER-frequency equipment of each region as a reference layer. |
| `export_powerflow_pages.py` 🔒 | Export power flow results as GeoJSON for GitHub Pages visualization. |
| `export_subsld_pages.py` 🔒 | SubSLD の Pages 機能化 — 全所コンパクトJSONの書き出し(オーナー指示 2026-08-27). |
| `export_subsld_ways.py` 🔒 | SubSLD Pages ビューア用の実線形エクスポート(オーナーFB 2026-08-27). |
| `export_substations_geojson.py` | Export enriched substation data from OSM GeoJSON with voltage inference. |
| `make_dataset_bundle.py` | All-Japan-Grid — 配布用データセットバンドル (.zip) を生成する。 |
| `make_readme_gifs.py` | README のデモ GIF を、Pages のページをブラウザで操作して撮り直す。 |
| `realtime_cycle.sh` 🔒 | でんき予報リアルタイムサイクル: 取得 → NOW断面PF → Pages更新(realtime_publish.sh が main へ公開) |
| `realtime_publish.sh` | リアルタイム断面を、作業ツリーのブランチに関係なく origin/main へ公開する。 |
| `regenerate_all.py` 🔒 | 全出力を単一モデルから一括再生成 + MODEL_VERSION 刻印(全面改修 Phase 4)。 |
| `slim_flow_map.py` 🔒 | flow_map配信データの軽量化(数値整数化+実線形パスのRDP簡略化20m許容). |
| `slim_geojson.py` | GeoJSON 軽量化スクリプト |

</details>

<details><summary><b>診断・調査 / diagnostics</b>(11 本)</summary>

| スクリプト | 説明 |
|---|---|
| `diag_west_ac_epicenter.py` | 西AC非収束の震源地診断 — 失敗NRの最終ミスマッチ上位バスを地図に落とす. |
| `diag_west_ac_onset.py` | 西AC発散の初動診断 — 反復k=1..6でVが最初に暴れるバスを特定. |
| `diag_west_ac_onset_full.py` | 第6波: westフルスケールAC発散の初動診断 — 66/77kV層の残存キラー特定. |
| `diagnose_pf_frontier.py` 🔒 | 潮流計算の「どこまで計算できるか」を成分構造から診断する。 |
| `diagnose_slack.py` | slack吸収の解剖 — 「どの成分・どの理由でスラックが電力を供給しているか」を定量化する. |
| `diagnose_ybus.py` | Diagnose Ybus conditioning per region — reveal why AC power flow struggles. |
| `diagnose_zone_contamination.py` | zone汚染診断 — 幻tie「kyushu↔shikoku」の解剖と、bbox重なり汚染の全量計測. |
| `probe_west_ac.py` | 西日本フルAC正典化キャンペーン 第1波 — 介入候補のプローブ行列(2026-08-29). |
| `probe_west_ac_infeed.py` | 西AC第5波 — 「都心給電の必然接続(仮)」プローブ(2026-08-30・正典不変更). |
| `screen_capacity_gaps.py` | 発電量・容量が「上手く入っていない」発電所をスクリーニングし収集worklistを出す。 |
| `screen_false_fragments.py` | 偽断片スクリーニング — 跨island同座標双子による「断片=登録人工物」候補の機械列挙. |

</details>

<details><summary><b>図・動画 / figures</b>(21 本)</summary>

| スクリプト | 説明 |
|---|---|
| `animate_powerflow_gif.py` | UC 24h × 潮流のGIFアニメーション — 全系統(4島)・全電圧階級(66kV+)の時系列可視化. |
| `plot_bundle_scaling.py` | 束導体の本数を変えたとき、抵抗とリアクタンスが「同じようには」変わらない理由。 |
| `plot_calibration_before_after.py` | 線種標準値の較正（介入#46）が系統全体に与える影響を before/after で示す。 |
| `plot_conductor_hypothesis.py` | 観測リアクタンスから導体構成の仮説を検定する（原因の究明）。 |
| `plot_effective_bundle_dist.py` | 線 1 本ごとに「実効的な導体本数」を逆算し、その分布を見る。 |
| `plot_effective_bundle_scatter.py` | 線ごとに逆算した「実効導体本数」を、抵抗基準 × リアクタンス基準の散布図で見る。 |
| `plot_eggc_figs.py` | EGGC のスライド用図を、教材と同じトレースデータから描く。 |
| `plot_eggc_gallery.py` | EGGC で実線形に置き換わった線を **全数** 画像化する。 |
| `plot_evidence_ladder.py` | 同じデータから複数の答えが出る理由と、主張ごとの確からしさを一枚で示す。 |
| `plot_impedance_routed_map.py` | 公表インピーダンスの検証を **実線形** で地図に描く（直線ではなく）。 |
| `plot_impedance_validation.py` | 公表インピーダンス X_公表 / X_モデル を 3 つの視点で見る。 |
| `plot_leadin_gap.py` | 「変電所に入っていく線」を使わずに代表点へ直線を引いている箇所を可視化する。 |
| `plot_leadin_overrun.py` | 距離上限を破った leadin / namebind を全国地図に出す（#46 の可視化）。 |
| `plot_linename_fixable.py` | 線名照合と変電所名照合が食い違った線（fixable）を並べて描く（#47）。 |
| `plot_ratio_chord_vs_route.py` | X_モデルの長さ基準を「弦距離」から「実線形長」に変えると比がどう動くか。 |
| `plot_synthetic_edges.py` | 「直線で無理やり繋いでいる」箇所を全国地図に出す。 |
| `plot_tower_scale.py` | 「線間距離 42 m が必要」がどれほど非現実的かを、鉄塔の実寸で示す。 |
| `plot_why42m.py` | 「2 導体と仮定すると鉄塔に 42 m が要る」を、段を追って読める図にする。 |
| `plot_ybus.py` | 数値 Ybus の可視化 — dist/ybus/ の出荷物から図一式を dist/ybus/figs/ に生成. |
| `plot_zone_reattribution_figs.py` | zone再属性(A案)のbefore/after図 — 事例記録(case_study_phantom_tie)の図を決定的に再生成. |
| `render_grid_figure.py` | Render the built grid as a single-image 系統図 (for LINE delivery). |

</details>

<details><summary><b>その他 / other</b>(41 本)</summary>

| スクリプト | 説明 |
|---|---|
| `archive_to_nas.sh` | 電力系データの NAS(nas03) 退避 — リリース版のスナップショットを残す。 |
| `b_overnight.py` | B路線 夜間ドライバ: 全国を node参照つきで取得 → node-topology連結性を測定 → 現モデルと比較。 |
| `b_phase2_analyze.py` | B Phase2 分析: node-topology(共有ノード=正確な線接続)+ 変電所束縛(point-in-polygon)で |
| `calibrate_islands.py` | (c) 島変電所のデータ校正 — region/voltage の誤タグを OSM 実タグで精緻化する。 |
| `capacity_provenance.py` 🔒 | 発電所の発電量・容量を **出典必須(provenance-first)** で記録する DB。 |
| `classify_isolated_subs.py` | 連結性監査で出た「孤立変電所」を A/繋ぐべき・B/除外・?/不明 に振り分ける。 |
| `connection_candidates.py` | 接続候補ジェネレータ (接続編集ツールのバックエンド) — I6-5新方向 2026-06-14。 |
| `convert_chubu_flow.py` | 中部PGの潮流実績Excel(xlsm/xlsx)を標準4行ヘッダCSV(cp932)へ変換する。 |
| `coverage_report.py` 🔒 | Provenance & validation coverage report for the unified grid DB. |
| `d4_island_audit.py` | D4 island audit — 小規模islandを物理接続の観点で判定する(計測のみ・本番不変)。 |
| `d4_island_classify.py` | I6-5 island classifier — build後の実態(degree・近傍build後ノード)で島を分類する。 |
| `eval_pop_tilt_matrix.py` | 介入#40(人口メッシュ傾斜)の再判定行列 — 全国メッシュ整備後の ON/OFF 比較. |
| `geocode_generators.py` | 発電所マスタに座標を付ける（国土地理院ジオコーディングAPI）。 |
| `interconnector_provenance.py` 🔒 | 連系線の運用容量を **出典必須(provenance-first)** で記録する DB。 |
| `island_classify.py` 🔒 | 島の分類器 — 島変電所を「なぜ繋がらないか」で仕分け、編集ツール/OSM還元に渡す。 |
| `island_substations.py` | 島の実変電所(名前つき・本系統に未接続)を全国で census する。 |
| `n1_screening.py` 🔒 | National N-1 screening — top-corridor outages on the island models (S1). |
| `optimize_sld_layout.py` | SLD 配置最適化 — Barycenter反復法による交差最小化. |
| `parse_impedance.py` | 事業者公表の「様式5 インピーダンス」xlsx を正規化CSVに変換する。 |
| `parse_point_demand.py` | L_DB第一歩: 変圧器(バンク)潮流実績→地点需要の正規化テーブル(2026-08-17 オーナー「両方並列で」). |
| `parse_tepco_plans.py` | TEPCO 流通設備建設計画表(設備計画表)から地中/架空フラグ付き線路レコードを抽出する. |
| `plant_switchyard_gaps.py` | 発電所の連系変電所(switchyard)がOSMに欠落しているケースを検出する。 |
| `pool_kyushu_kuyoryo.py` | 九州31地区「予想潮流・空容量一覧表」の全面プール化。 |
| `provenance.py` 🔒 | 出典必須(provenance-first)レコードの **汎用バリデータ** — 捏造防止規約の単一実装. |
| `prune_pages_days.py` 🔒 | Pages に上げる前に、潮流マップの日別断面を直近 N 日だけにする(deploy-pages 用)。 |
| `prune_pages_slides.py` 🔒 | Pages に上げる前に、docs/slides の pptx・pdf を各デッキの最新版だけにする(deploy-pages 用)。 |
| `pv_dynamics_compare.py` | PV有無×UC → 動的比較: ①24h系統慣性カーブ ②正午の動揺モード ③正午のS_sc(66-77kV)。 |
| `readme_numbers.py` | README に埋め込む数字を、データから作る(cog から呼ぶ)。 |
| `regen_powerflow_snapped.sh` | --------------------------------------------------------------------------- |
| `report_kv66_quality.py` | Per-region 66 kV-band quality ledger (M4-4 of docs/archive/plans/PLAN_66KV.md). |
| `restore_missing_plants.py` | JRP の kyushu/okinawa_plants_lite → AGJ 形式の plants.geojson を生成 |
| `score_road_reconnection.py` | Score fragment-reconnection candidates by road-path plausibility (M9). |
| `score_transformer_topology.py` 🔒 | 変電所内の変圧器の結び方(梯子 / 介入 #48)が正しいかを、各社の公表一覧(全国の変圧器台帳)で採点する。 |
| `scripts_index.py` | scripts/ 直下の全スクリプト索引を作る(scripts/README.md の cog から呼ぶ)。 |
| `stepdown_gap_census.py` | 介入#43(降圧点欠損)の census と静的ゲート — 島ごとに OFF / #43a / #43a+#43b を比べる. |
| `substation_scope.py` 🔒 | SubScope — GridStitch 変電所構造ビューア. |
| `sync_realtime_to_nas.sh` | ローカル蓄積(data/realtime/)を pws-nas03 のAGJ領域へ退避する。 |
| `test_pf_quick.m` | % Quick PF convergence test for all regions + All-Japan |
| `today_loop.sh` | 今日だけの1時間毎更新ループ(プレゼン用・2026-08-18限定) |
| `tower_connectivity.py` | 全鉄塔(power=tower)をプロットし、接続されていない鉄塔を検証する(geojson再生成の第一歩)。 |
| `transformer_provenance.py` 🔒 | 変電所の変圧器(容量・台数・タップ)を **出典必須** で記録する DB — Phase B 本命. |

</details>
<!-- [[[end]]] -->
