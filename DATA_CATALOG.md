# DATA_CATALOG — All-Japan-Grid データカタログ

「どのファイルに何が入っているか」を実ファイルから数えた**実測件数つき**で一覧化したカタログ。
件数はすべて GeoJSON の `features` 配列長を直接カウントした実測値（測定日: 2026-06-03）。

> **件数の正本はこのカタログ（=実測値）**
> **正: 変電所 6,962 / 送電線 40,077 / 発電所 19,138**
> （2026-08-11 に再カウントして同値を確認。`docs/data/{subs,lines,plants}_all.geojson` の `features` 長）
>
> **決着済み**: かつて README 冒頭の地域別表の Total 行だけが「7,962」と誤記されていた
> （地域別の各行 471+901+…+59 を足すと 6,962 になるので、合計欄の単純な書き間違いだった）。
> **2026-08-11 時点で README・WHITEPAPER に 7,962 は1箇所も残っておらず、全資料が 6,962 で一致している。**

---

## 1. ソースデータ — `data/{region}_{substations,lines,plants}.geojson`（地域別・10地域）

OSM 由来の地域別 GeoJSON。これがパイプライン全体の**一次ソース**。
ファイル命名は `data/{region}_{substations|lines|plants}.geojson`。

| 地域 / Region | 周波数 | 変電所 substations | 送電線 lines | 発電所 plants |
|---|---:|---:|---:|---:|
| 北海道 / hokkaido | 50 Hz | 471 | 4,136 | 436 |
| 東北 / tohoku | 50 Hz | 901 | 6,628 | 1,311 |
| 東京 / tokyo | 50 Hz | 1,726 | 8,295 | 7,207 |
| 中部 / chubu | 60 Hz | 1,163 | 6,589 | 3,792 |
| 北陸 / hokuriku | 60 Hz | 267 | 2,296 | 432 |
| 関西 / kansai | 60 Hz | 902 | 3,994 | 1,518 |
| 中国 / chugoku | 60 Hz | 531 | 3,176 | 1,173 |
| 四国 / shikoku | 60 Hz | 258 | 1,532 | 688 |
| 九州 / kyushu | 60 Hz | 684 | 3,314 | 2,549 |
| 沖縄 / okinawa | 60 Hz | 59 | 117 | 32 |
| **合計 / Total** | — | **6,962** | **40,077** | **19,138** |

ジオメトリ種別:
- `*_substations.geojson` — Point / Polygon（`power=substation`、開閉所含む）
- `*_lines.geojson` — LineString（`power=line` / `power=cable`）
- `*_plants.geojson` — Point（`power=plant`）

主なプロパティ: 変電所・送電線は `name` / `name:ja` / `voltage` / `operator` / `power`、発電所は `name` / `plant:source`(燃料) / `plant:output:electricity`(容量) / `operator`。

> この10地域の集計は `docs/data/regions.json` のメタ（`substations`/`lines`/`plants`/`bounding_box`/`frequency_hz`）と完全一致する（regions.json が正本メタ）。

---

## 2. 配布派生 — `docs/data/`（GitHub Pages 配信用、生成物だが Git 追跡対象）

ソースを集約・分割・整形した**ビューア / 配布用**の派生 GeoJSON。

### 2.1 集約・電圧分割レイヤ

| ファイル | features | 役割（1行） |
|---|---:|---|
| `subs_all.geojson` | 6,962 | 全地域の変電所を結合した配信用レイヤ（軽量プロパティ `_region`/`_display_name`/`_voltage_kv`）|
| `subs_275kv.geojson` | 366 | 275kV 以上の変電所のみ抽出（高圧フィルタビュー）|
| `subs_154kv.geojson` | 965 | 154kV 級の変電所のみ抽出 |
| `substations.geojson` | 6,962 | 詳細ポップアップ用の変電所（`name_en`/`operator`/`voltage_kv`/`frequency_hz` 等のリッチ属性）|
| `lines_all.geojson` | 40,077 | 全地域の送電線を結合した配信用レイヤ |
| `lines_275kv.geojson` | 4,963 | 275kV 級の送電線のみ抽出 |
| `lines_154kv.geojson` | 12,332 | 154kV 級の送電線のみ抽出 |
| `plants_all.geojson` | 19,138 | 全地域の発電所を結合した配信用レイヤ |
| `plants_utility.geojson` | 3,125 | 一般電気事業者（電力会社）系の発電所のみ |
| `plants_ipp.geojson` | 16,013 | IPP / その他（電力会社以外）の発電所のみ |
| `generators.geojson` | 688 | 燃料種別デフォルト（`data/reference/generator_defaults.yaml`）を付与した UC/解析用の発電機（≥10MW、`capacity_mw`/`ramp_*`/`startup_cost_jpy`/`co2_intensity` 等の電力モデル属性つき）|

### 2.2 潮流計算結果 — `docs/data/powerflow/`（地域別・スナップ済みトポロジ）

地域別に AC/DC 潮流を解いた結果（pandapower、`topology="snapped"`）。バス/ブランチをノードグラフ化しスナップ＆再接続した版。

| ファイル群 | 役割（1行） |
|---|---|
| `{region}_ac_buses.geojson` / `{region}_ac_lines.geojson` | 地域別 AC 潮流の母線・線路（電圧 vm、潮流結果つき）×10地域 |
| `{region}_dc_buses.geojson` / `{region}_dc_lines.geojson` | 地域別 DC 潮流の母線・線路（位相角 va、loading）×10地域 |
| `all_ac_buses.geojson`（2,344）/ `all_ac_lines.geojson`（2,645）| 全地域 AC 結果を結合した全国バックボーン母線・線路 |
| `pf_buses.geojson`（1,975）/ `pf_branches.geojson`（2,645）| 潮流モデルの母線・ブランチ（解析用トポロジ）|
| `backbone_ring.geojson`（2,306）| 全国基幹送電網（バックボーンリング）の抽出ジオメトリ |
| `routes_{500,275,154,110,77,66}kv.geojson` | 電圧階級ごとに分けた送電ルート・ジオメトリ（6階級）|
| `sld_data.json` | 単線結線図（SLD）描画用データ |
| `summary.json` | 地域別の収束サマリ（`ac/dc_converged`・`vm_min/max`・`n_buses`・`n_lines`・`n_gens`・`total_load_mw`/`total_gen_mw`・`max_loading` 等）|

### 2.3 全国ゾーン潮流 — `docs/data/powerflow_national/`（多島モデル）

地域を**3島系統（east / west / hokkaido / okinawa）**に束ねて解いた全国版（`topology="national_zonal"`、multi_slack + 5km 再接続）。

| ファイル群 | 役割（1行） |
|---|---|
| `{region}_ac_buses/lines.geojson` | AC 結果。**実体は系統島で共有**（同一島の地域は同じ結果を参照）|
| `{region}_dc_buses/lines.geojson` | DC 結果（地域別）|
| `summary.json` | 島ごとの収束状況（`island`・`ac_converged`・`vm_min/max`・`n_components`・`n_synthetic_lines`）|

島の割り当て（summary.json 実測）:
- **hokkaido 島**: hokkaido（AC 収束 ✅）
- **east 島**（50Hz）: tohoku / tokyo（AC 収束 ✅）
- **west 島**（60Hz）: chubu / hokuriku / kansai / chugoku / shikoku / kyushu（AC **未収束** ❌）
- **okinawa 島**: okinawa（AC 収束 ✅）
- 実 GeoJSON が存在するのは AC 収束した島の代表（hokkaido / tohoku / tokyo / okinawa）の `*_ac_*` のみ。DC は全地域分あり。

### 2.4 N-1 解析 — `docs/data/n1/`

各地域で送電線 1 回線停止（N-1 contingency）を回したワーストケース集計。

| ファイル | 役割（1行） |
|---|---|
| `{region}_n1.csv` | 地域別 N-1 結果（停止線ごとの最大線路 loading 等）。hokkaido/tohoku/tokyo/chubu/hokuriku/chugoku/shikoku/kyushu/okinawa の 9 ファイル |
| `n1_summary.csv` | 全地域横断サマリ（`base_max_load`・`worst_max_load`・`worst_delta`・`worst_ac_fail`・`worst_line`）。tokyo / kyushu は最悪ケースで AC 発散（`AC_FAIL`）|
| `n1_worst_top.png` | ワースト N-1 を可視化した図 |

### 2.5 その他 `docs/data/` 直下

| ファイル | 役割（1行） |
|---|---|
| `regions.json` | 10地域のメタ（id・和英名・周波数・bounding_box・件数）。**地域件数の正本** |
| `powerflow_before/` | スナップ前（旧トポロジ）の潮流結果。スナップ改善の before/after 比較用（40 ファイル）|
| `powerflow_snapped/` | スナップ版の作業用ステージング（41 ファイル）。**`.gitignore` 対象**（`docs/data/powerflow_snapped/`）→ 配布本体は `powerflow/` |

---

## 3. リファレンスデータ — `data/reference/`（手動整備のマスター）

外部ソース・文献値をもとに**手動整備**する系統モデル構築用マスター。OSM 由来ではない。

| ファイル | 中身・役割 | 出典 |
|---|---|---|
| `voltage_hierarchy.yaml` | 地域別の電圧階級体系（500/275/154/110/77/66kV 等の階層定義）| OCCTO 系統マスタ |
| `generator_defaults.yaml` | 燃料種別ごとの発電機デフォルト（ramp rate・最小起動停止時間・起動停止費用・燃料費・熱効率・CO2 原単位・利用率・耐用年数 等）。`generators.geojson` 生成の入力 | OCCTO 供給計画 / 発電コスト検証委員会(2021) / IEEE Japan |
| `interconnections.yaml` | 地域間連系線の定義と潮流容量（FC・連系線）| OCCTO 公開データ |
| `load_profiles.yaml` | 地域別・時間帯別の負荷プロファイル | 各電力会社公開データ |
| `README.md` | 上記 YAML の構造説明と更新手順 | — |

---

## 4. 監査データ — `data/audit/`（品質監査の出力、Git 非追跡）

> **`.gitignore` 対象**（`data/audit/`）。再生成は `scripts/audit_substation_plant_overlap.py`。

| ファイル | 中身・役割 |
|---|---|
| `substation_plant_overlap.json` | 変電所(`power=substation`)と発電所(`power=plant`)の OSM 分類混在を監査した結果。下記カテゴリ別リスト + `summary` を格納 |

`substation_plant_overlap.json` の構造（実測）:

| キー | 件数 | 内容 |
|---|---:|---|
| `category_a_substations_named_as_plants` | 45 | 名称に「発電所」を含む変電所（正規の開閉所と誤分類が混在）|
| `category_b_substation_generation` | 41 | `substation=generation`（昇圧用。誤りではないが発電所と重複しうる）|
| `category_c_tag_value_errors` | 0 | `substation` フィールドに型でなく施設名が入る入力ミス（現データでは 0 件）|
| `category_d_plants_named_as_substations` | 5 | 名称に「変電所」を含む発電所（多くは変電所併設の蓄電池）|
| `colocated_name_mismatches` | 262 | 近接する変電所/発電所で名称が食い違うペア |
| `summary` | — | 上記の件数サマリ（a=45, b=41, c=0, d=5, colocated=262）|

---

## 5. 生成物 — `output/`（再生成可能、Git 非追跡）

> **`.gitignore` 対象**（`output/`）。解析スクリプトの出力先。図・CSV・.mat 等の派生物で、ソースから再生成可能。
> 論文用の重要図は別途 `docs/assets/` と `papers/figs/` に保持。

| サブディレクトリ | 中身・役割 |
|---|---|
| `output/cpf/` | 連続潮流(CPF)= PV カーブ / 電圧安定性。`{region}_pv.json`（hokkaido/kansai/okinawa/tokyo 等）|
| `output/dynamics/` | 動的解析の図（固有値・参加係数・過渡安定・短絡・故障除去）`fig_*.png` / `{region}_modal.png` 等 |
| `output/matpower/` | スナップ版の MATPOWER ケース（`{region}_snapped.mat`）|
| `output/matpower_alljapan/` | 全国 + 地域別 MATPOWER ケース（`alljapan.mat` + 各地域 `.mat`）|
| `output/powerflow_regional/` | 地域別潮流の収束レポート（`ac_convergence_report.md`）とダッシュボード図 |
| `output/psdat/` | psdat-python 連携の固有値 / 故障シミュ図 |
| `output/uc/` | ユニットコミットメント(UC)結果（`uc_result.csv` + dispatch/cost/heatmap 図）|
| `output/uc_national/` | 全国 UC 結果（dispatch stack / fleet capacity / dashboard 図）|
| `output/uc_national_interconnection_result.txt` | 連系線を考慮した全国 UC のテキスト結果 |

---

## 6. その他のデータ資産

| パス | 役割 | Git |
|---|---|---|
| `data/wri_global_power_plants.csv` | WRI Global Power Plant Database（全世界。`capacity_mw`/`primary_fuel`/`commissioning_year`/`generation_gwh_*` 等）。発電所の容量・燃料の外部照合用 | 追跡 |
| `data/cache/*.pkl` | GridNetwork のピクルキャッシュ（高速化用、ハッシュ名）| **非追跡**（`*.pkl` / `data/cache/`）|
| `data/external/` | 外部ダウンロード置き場 | **非追跡**（`data/external/`）|

---

## 付録 A — 件数の食い違い整理（**解決済み**）

| 指標 | 実測（本カタログ正本）| README | WHITEPAPER |
|---|---:|---:|---:|
| 変電所 | **6,962** | 6,962 ✅ | 6,962 ✅ |
| 送電線 | **40,077** | 40,077 ✅ | 40,077 ✅ |
| 発電所 | **19,138** | 19,138 ✅ | 19,138 ✅ |

README 冒頭表の Total 行「7,962」誤記は **v1.2.0 で修正済み**（CHANGELOG の Fixed 項参照）。
2026-06-08 時点で全資料の件数は実測と一致。今後数値を更新する際は、本カタログの実測値を正本として
README・WHITEPAPER・papers/ を揃えること。
