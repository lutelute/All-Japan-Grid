# DB統一アーキテクチャ設計 — Data Layer Unification

- **方針**（オーナー指示 2026-06-08）: 「DBは基本統一の方向にしたい。いろんなデータがあるのはいいし、使い方によってそのデータを編集したり別のデータと組み合わせるのはわかるが、**基本的にはDBで機械的に更新できる仕組みにしておくのが強い筋**」
- **状態**: 設計案 v1（2026-06-08）— 実装前のレビュー用
- **関連**: `REVIEW_FINDINGS.md`（全体レビュー）、`DATA_CATALOG.md`（現データ資産の正本）

---

## 1. 現状の問題（実測ベース）

### 1.1 raw と curated の混在（in-place 変異）

エンリッチパイプライン（Nominatim / P03 / Overpass / audit `--fix`）はすべて
`data/{region}_{layer}.geojson` を **その場で書き換える**。

```
OSM再取得 ──────────────┐
                         ▼ 上書き
data/{region}_*.geojson ←── enrich 6段が in-place 変異（5時間分のAPI成果もここに直書き）
                         ▲
                         └── audit --fix / 手動修正 もここ
```

帰結:
- **OSM 再取得 = エンリッチ成果の全喪失**。「機械的更新」が構造的に不可能
- エンリッチ結果の在処が GeoJSON 内のみ（キャッシュ `data/cache/overpass_tags.json` は
  1f78a28 で削除済みで、**再実行には再び数時間の API 呼び出しが必要**）
- 何が raw で何が補完値か、ファイルを見ても完全には分離できない

### 1.2 安定キーの欠如（実測 2026-06-08）

| レイヤ | OSM id | 実態 |
|---|---|---|
| plants | ✅ `osm_id` + `osm_type` プロパティ有り | エンリッチ（Overpass バッチ）が必要として付与した |
| substations | ❌ **0/59 件**（okinawa 実測。top-level keys = type/properties/geometry のみ） | fetch 時に Overpass の element id が捨てられている |
| lines | ❌ **0/117 件**（同上） | 同上 |

ローダは配列 index で id を合成している（`src/server/geojson_parser.py:110`
`{region}_osm_sub_{osm_id}` の `osm_id` は実質 index、`examples/run_powerflow_all.py:197`
は明示的に `{region}_sub_{i}`）。**再取得で1件でも増減すると以降の全 id がシフト**し、
`load_attributes.bus_id` 等の外部参照が全部無効になる。

### 1.3 既にある土台（活かす）

- `src/db/`（2026-03-06、889 LOC、参照はテストのみ）= SQLite + SQLAlchemy 2.0 +
  upsert 部分更新 + 自前軽量 migration（`MIGRATIONS` タプル追記方式）。
  docstring 自体が「GIS トポロジから独立に更新できる属性オーバーレイ」と宣言しており、
  **設計思想は最初からDB統一方針と一致**。テーブル: `generator_attributes`（UCコスト/蓄電）/
  `substation_attributes`（tap/電圧設定/zone）/ `load_attributes` / `schema_version`
- エンリッチは provenance マーカーを既に書いている: `_enriched_by`・`_name_source`・
  `_display_name`・`_p03_distance_km` 等（`_` 接頭辞 = 派生メタの規約）
  → **ingest 時の raw / curated 分解が機械的に可能**

---

## 2. 設計原則

1. **raw は不変** — fetch だけが書く。再 fetch = スナップショット差し替え
2. **curated は raw に触らない** — osm キー（暫定は幾何キー）で別テーブルに upsert。
   OSM 再取得後も自動で再適用される
3. **derived は全て生成物** — `raw ⟕ curated` から GeoJSON / docs/data / CIM / MATPOWER を再生成。
   手で編集しない
4. **既存パイプライン互換** — D層が現行 `data/{region}_{layer}.geojson` と意味等価のファイルを
   吐けることを golden test で保証してから切り替える（直読みする ~20 スクリプトは当面無改修）
5. **漸進移行** — 各ステップでテストスイート緑（ベースライン: 824 passed）を維持

## 3. スキーマ（SQLite `data/grid.db`・既存 migration 機構で v2 として追加）

```sql
-- ============ R層: raw（fetch だけが書く） ============
CREATE TABLE snapshots (
  snapshot_id   TEXT PRIMARY KEY,      -- 例: '2026-06-08T12:00Z_okinawa'
  region        TEXT NOT NULL,
  layer         TEXT NOT NULL,         -- substations | lines | plants
  fetched_at    TEXT NOT NULL,
  source        TEXT NOT NULL,         -- 'overpass' | 'ingest-legacy'（既存GeoJSON取込）
  feature_count INTEGER
);

CREATE TABLE raw_features (
  feature_key TEXT NOT NULL,           -- 後述 3.1
  layer       TEXT NOT NULL,
  region      TEXT NOT NULL,
  osm_type    TEXT,                    -- node|way|relation（取れ次第埋める）
  osm_id      INTEGER,
  tags        TEXT NOT NULL,           -- OSM タグ JSON（rawのまま、補完値を混ぜない）
  geometry    TEXT NOT NULL,           -- GeoJSON geometry JSON
  first_seen  TEXT NOT NULL,
  last_seen   TEXT NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1,  -- 最新スナップショットに存在するか
  seq         INTEGER,                     -- 元ファイル内の出現順（export の安定順序用）
  PRIMARY KEY (layer, region, feature_key)
  -- region を PK に含める: 現行ファイルは境界重複要素を両 region に持ち得るため、
  -- per-region ファイルの忠実な往復を優先（osm キー移行後に重複の同定・解析が可能になる）
);

-- ============ C層: curated（enrich/audit/手動/外部照合が書く） ============
CREATE TABLE enrichments (
  layer       TEXT NOT NULL,
  feature_key TEXT NOT NULL,
  field       TEXT NOT NULL,           -- 'name' | 'operator' | 'fuel_type' | 'capacity_mw' | ...
  value       TEXT,                    -- JSON値
  source      TEXT NOT NULL,           -- 'manual'|'audit_fix'|'p03'|'overpass_tags'|'jrp'|
                                       -- 'nominatim'|'endpoint_match'
  confidence  REAL,
  run_id      TEXT,
  updated_at  TEXT NOT NULL,
  PRIMARY KEY (layer, region, feature_key, field, source)
);
-- source は既存マーカーの値を verbatim 採用（情報無損失）:
--   legacy: 'endpoint_matching'|'nominatim'|'geocode_promotion'|'p03'|'overpass'|'jrp_lite'|'legacy_marker'
--   新規:   'manual'|'audit_fix'
-- 解決優先順位（D層で適用）:
--   manual > audit_fix > p03 > overpass > jrp_lite > endpoint_matching > geocode_promotion > nominatim > raw値

-- 既存3テーブル（電気属性オーバーレイ）は維持。
-- id を feature_key 体系に揃える（generator_attributes.id 等）
```

### 3.1 feature_key — 安定キー戦略（設計の核心）

| フェーズ | キー | 備考 |
|---|---|---|
| 恒久 | `n{osm_id}` / `w{osm_id}` / `r{osm_id}` | OSM 要素 id。plants は今すぐ可 |
| 暫定（subs/lines の現データ） | `g:{geohash}` = 正規化ジオメトリの SHA1 先頭12桁 | 現 GeoJSON に id が無いため。決定的・再現可能 |

移行手順:
1. ingest 時、id の無い substations/lines は幾何キーで登録
2. `fetch_subdivided.py` を **OSM element id を保存する形に修正**（Overpass は常に id を返す。
   現状は変換時に捨てているだけ）
3. 次回 fetch の ingest で、新 raw（osm id 付き）と既存 curated（幾何キー）を
   ジオメトリ近接で 1:1 照合 → enrichments の feature_key を osm キーへ**一括付け替え**
   （migration スクリプト、照合できない残渣はレポートして手動確認）
4. 以後は osm キーが恒久キー。OSM 側のジオメトリ編集に耐える

> 幾何キーは OSM 上で形状が編集されると変わる。**暫定期間を短くする**こと
>（= fetch 修正と次回 fetch を早期に実施）。

## 4. 機械的更新フロー（目標形）

```
scripts/db/fetch.py    : Overpass → スナップショット登録（osm id 保存）
scripts/db/ingest.py   : raw_features 差し替え + 差分レポート（added/removed/changed/moved）
scripts/db/enrich.py   : 解決後も欠落のフィールドだけ API 呼び出し → enrichments へ upsert
                         （DB自体が「既知」を持つため、消失したJSONキャッシュの代替になる）
scripts/db/export.py   : D層生成 — data/*.geojson（互換形）/ docs/data/* / generators.geojson
```

- すべて再実行可能（idempotent）。cron / CI に載せられる
- 差分レポートが「OSMで何が変わったか」を毎回機械的に出す（現状は不可能）
- JRP 連携（`complement_plants.py` / `cross_validate.py`）は `source='jrp'` の enrichments として表現

## 5. 既存資産との関係

| 資産 | 扱い |
|---|---|
| `data/{region}_*.geojson` | **D層の生成物に降格**（互換形を出力し続けるので下流 ~20 スクリプトは無改修） |
| `data/cache/*.json`（消失済み） | 廃止 — DB が永続キャッシュを兼ねる |
| `data/reference/*.yaml`（手動マスター） | **DB外のまま**（人が編集する正本は YAML が適切。D層生成時の入力） |
| `config/regions.yaml` | 対象外（設定であってデータではない） |
| `src/db` 既存3テーブル | 電気属性オーバーレイとして接続（UC/PF ビルダが参照） |
| P03 GML | 新設 ingest で取り込み → **壊れている `export_generators_geojson.py`
  （src/parser 欠落）の機能をここで吸収・修理** |

## 6. git 追跡方針（推奨 = b案）

| 対象 | 追跡 | 理由 |
|---|---|---|
| `data/grid.db`（SQLite 本体） | ❌ gitignore | バイナリ diff 不可。追跡物から完全再構築可能にする |
| `data/db/enrichments.jsonl`（C層のテキストダンプ、export 時に自動更新） | ✅ | **キュレーション成果が本当の資産**。diff 可読・レビュー可能・復元可能 |
| `data/{region}_*.geojson`（D層出力） | ✅ 当面 | 現互換・Pages とユーザーが直接使う配布形。将来 Release asset 化を検討 |
| raw スナップショット | ❌（メタのみ DB 内） | Overpass から再取得可能。必要なら Release asset |

→ **DB は「`git clone` 後に `make db` で再構築できる」状態を保つ**
（ingest: tracked GeoJSON + enrichments.jsonl → grid.db）。履歴肥大も起きない。

## 7. 漸進移行ステップ（各ステップで全 tests 緑を維持）

| Step | 内容 | 状態 |
|---|---|---|
| 0 | スキーマ migration v2 + feature_key 実装（`src/db/` 拡張） | ✅ `9943f7f`（snapshots/raw_features/enrichments） |
| 0.5 | `fetch_subdivided.py` の osm id 保存修正 | ✅ `e8fcf09`（osm_type/osm_id を tile merge 越しに保持） |
| 1 | `scripts/db/ingest.py` — 現 GeoJSON を raw / enrichments に分解取込 | ✅ `9943f7f`（66,177 features・232,139 curated rows、件数一致） |
| 2 | `scripts/db/export.py` — DB → GeoJSON golden | ✅ `9943f7f`（全30 region/layer roundtrip equivalent） |
| 3 | C層書き込み経路（`apply_enrichments` + `scripts/db/curate.py`）+ ingest が manual を保全 | ✅ `c3f889b`（curate→export 反映を実データ実証、再ingest耐性テスト済み） |
| 3b | enrich 6段の書き込み先を GeoJSON→DB に切替（1本ずつ） | 🔶 **1/6 完了** `494a70d`: `enrich_lines_endpoints`(オフライン)を `src/db/enrich.py` + `scripts/db/enrich.py` でDB化。命名ロジックは `assign_line_name` に抽出し両版で共有。残5段(geocode×2/overpass/p03/audit)は Nominatim/Overpass/P03依存で**要サーバー実行** |
| 4 | P03 ingest 新設（generators.geojson も D層出力へ = `export_generators_geojson.py` 修理） | ⏳ **ブロック中**: `data/generators/P03/*.xml`（P03 GML）がリポジトリに未取得。要 DL → パーサ移植（`src/parser` 喪失分の再実装） |
| 5（任意） | ローダの DB 直読み・audit の SQL 化・差分レポート CI | ⏳ 未着手 |

**Step 3/3b で「機械的に更新できる仕組み」が実エンリッチャでも成立**: `ingest → enrich(DB) → export` が回り、DB-nativeエンリッチャ出力は再ingest・将来の再fetchで保全される。
**設計上の要点(Step 3bで確定)**: DB-nativeエンリッチャは ingest が所有する legacy source(`endpoint_matching`等、`LEGACY_SOURCES`)とは**別のsourceラベル**(`enrich_lines_endpoints`)で書く。さもないと再ingestが「自分の所有物」として消す。`_enriched_by`の**値**だけ legacy と同じ(`endpoint_matching`)にしてGeoJSON互換を保つ。残り5エンリッチャ(geocode×2/overpass/p03/audit)も同パターンで、それぞれ専用sourceラベルを使う。
Step 3b残り・Step 4 はサーバー実行・外部データ取得が前提のため、ローカルセッションでは未着手（着手時は pws-160core 等で）。

Step 0–2 だけでも「キュレーション成果の救出」と「機械的更新の土台」が成立する。
Step 3 以降は通常作業の合間に1本ずつ。

## 8. リスクと未決事項

- **暫定幾何キーの寿命**: OSM 側のジオメトリ編集で変わる → Step 0.5 と次回 fetch を早期に
- **地域境界の重複**: 同一 OSM 要素が隣接 region の bbox 両方に入る可能性
  → ingest で (layer, feature_key) 衝突を検出し region 帰属規則を決める（要実測）
- **並行アクター**: SQLite WAL で読み書き耐性はあるが、パイプラインは単一実行を前提とする
  （ロックファイル or `make` 直列化）
- **DBエンジン**: SQLite 続行（既存 migration 機構を流用）。サーバー常駐・多人数書き込みが
  要件化したら PostgreSQL + PostGIS を再検討（スキーマは ORM なので移行容易）
- 表示用派生値（`_fuel_color`・`_category` 等）を enrichments に入れるか export 時計算にするか
  → **export 時計算に倒す**（純粋な派生はC層に保存しない）方向で実装時に確定
