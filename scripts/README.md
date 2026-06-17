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
| `capture_combined_gif.py` / `capture_ybus_gif.py` / `capture_network_gifs.mjs` | README 用アニメーション GIF（Network+Ybus ツアー等） |

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
