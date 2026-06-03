# データ辞書 / Data Dictionary

All-Japan-Grid 配布データセットの列定義（データ辞書）。各フィーチャの **プロパティ列名 / 型 / 単位 / 必須・任意 / 取得源 / 説明 / 例** を種別ごとにまとめる。

This document defines every column (property) in the All-Japan-Grid distributed dataset, grouped by feature kind: substations / lines / plants. The internal Python data model (`Substation` / `TransmissionLine` / `Generator` dataclasses) is documented separately in [§5](#5-内部データモデル--internal-data-model-dataclasses).

> 関連ドキュメント / See also: [`README.md`](README.md)（概要・地域別件数）, [`WHITEPAPER.md`](WHITEPAPER.md)（方法論）, [`config/line_types.yaml`](config/line_types.yaml)（電気パラメータの典型値）。

---

## 0. 全体仕様 / Conventions

| 項目 / Item | 値 / Value |
|---|---|
| フォーマット / Format | GeoJSON `FeatureCollection`（地域別 1 ファイル / one file per region） |
| 座標系 / CRS | **WGS-84 (EPSG:4326)**。座標は `[経度 longitude, 緯度 latitude]` 順（GeoJSON 標準） |
| 地域 / Regions | `hokkaido, tohoku, tokyo`（50 Hz）/ `chubu, hokuriku, kansai, chugoku, shikoku, kyushu, okinawa`（60 Hz） |
| ファイル命名 / File naming | `data/{region}_substations.geojson` / `_lines.geojson` / `_plants.geojson` |
| 一次取得源 / Primary source | **OpenStreetMap (OSM)** via Overpass API（ライセンス: ODbL） |
| エンリッチ源 / Enrichment | Nominatim（逆ジオコーディング）, 国土数値情報 **P03**（発電所）, `jrp_lite`（合成）, 内部アルゴリズム（端点マッチング・電圧推定・電気パラメータ合成） |

### 取得源コード / Source codes

各列の「取得源」欄で使う略号。

| コード / Code | 意味 / Meaning |
|---|---|
| **OSM** | OpenStreetMap の生タグをそのまま転記 / verbatim OSM tag |
| **Nominatim** | OSM Nominatim 逆ジオコーディングで補完（地名→施設名）/ reverse-geocoded |
| **P03** | 国土数値情報「発電施設データ P03」との空間マッチで補完 / matched to MLIT P03 dataset |
| **算出 / Derived** | 座標・他列から計算（距離・端点マッチ等）/ computed from geometry or other fields |
| **合成 / Synthetic** | 電圧クラス別の典型値・規則ベースで生成（実測値ではない）/ rule-based typical values, **not measured** |
| **内部 / Internal** | パイプラインが付与する管理用メタ（`_`接頭辞が多い）/ pipeline bookkeeping metadata |

### データ件数（実測 / measured from `data/`）

| 種別 / Kind | フィーチャ数 / Features | ジオメトリ / Geometry |
|---|---:|---|
| Substations / 変電所 | 6,962 | `Point`, `Polygon`, `MultiPolygon` |
| Lines / 送電線 | 40,077 | `LineString` |
| Plants / 発電所 | 19,138 | `Point` |

> 地域別内訳は [`README.md` の Dataset 表](README.md#dataset--データセット) を参照。

### 値の規約（重要 / IMPORTANT conventions）

- **電圧 `voltage` の単位は「ボルト (V)」**（OSM 原データ準拠）。例 `"275000"` = 275 kV。**文字列型**で、複数値は `;` 区切り（例 `"154000;66000"`）、未設定は `null`。kV 換算は `voltage / 1000`。
- **`capacity_mw` の欠損は `-1.0`（センチネル値）**。`0` ではない。さらに、フィーチャによっては列自体が `null`／非数値の場合があり、これも「容量不明」を意味する。**正の値のみを有効容量として扱うこと**（`capacity_mw > 0`）。
- 電気パラメータ（`r_ohm_per_km`, `x_ohm_per_km`, `c_nf_per_km`, `max_i_ka`）は**配布 GeoJSON には含まれない**。これらは内部データモデル（[§5](#5-内部データモデル--internal-data-model-dataclasses)）で電圧クラス別の**典型値（合成値）**として付与される。実測の線路定数ではない。
- 多数の OSM タグ列は値が `null` のまま保持される（スキーマを揃えるため）。「任意」列の大半は実体が空。

---

## 1. 変電所 / Substations (`data/{region}_substations.geojson`)

ジオメトリ: `Point`（多くの開閉所・変換所）/ `Polygon`・`MultiPolygon`（敷地ポリゴンの場合）。`power=substation` のフィーチャ。

### 1.1 主要列 / Core columns

| 列名 / Column | 型 / Type | 単位 / Unit | 必須/任意 | 取得源 / Source | 説明 / Description | 例 / Example |
|---|---|---|---|---|---|---|
| `power` | string | — | 必須 | OSM | フィーチャ種別。常に `"substation"` | `"substation"` |
| `name` | string | — | 任意 | OSM / Nominatim | 施設名（日本語）。OSM 欠損時は Nominatim 由来の `{地名}変電所` で補完 | `"東京電力 岡田変電所"` |
| `name:ja` | string\|null | — | 任意 | OSM | 日本語名タグ | `null` |
| `name:en` | string\|null | — | 任意 | OSM | 英語名タグ | `"Okada Substation"` |
| `operator` | string\|null | — | 任意 | OSM | 運用事業者名（**所有者の保証なし**, README 注記参照） | `"東京電力パワーグリッド"` |
| `operator:en` | string\|null | — | 任意 | OSM | 事業者名（英語） | `"TEPCO Power Grid"` |
| `operator:ja` | string\|null | — | 任意 | OSM | 事業者名（日本語） | `"東京電力パワーグリッド"` |
| `voltage` | string\|null | **ボルト V** | 任意 | OSM | 公称電圧（V 単位、`;` 区切り複数可）。非 null は全体の約 57% | `"275000"` / `"154000;66000"` |
| `substation` | string\|null | — | 任意 | OSM | 変電所の機能種別 | `"distribution"`, `"transmission"`, `"traction"`, `"industrial"` |
| `ref` | string\|null | — | 任意 | OSM | 参照記号・略称 | `"岡田"` |
| `frequency` | string\|null | Hz | 任意 | OSM | 周波数タグ（多くは null） | `"50"` |
| `gas_insulated` | string\|null | — | 任意 | OSM | GIS（ガス絶縁開閉装置）か | `"yes"` |
| `location` | string\|null | — | 任意 | OSM | 設置形態 | `"outdoor"`, `"underground"` |
| `wikidata` / `operator:wikidata` | string\|null | — | 任意 | OSM | Wikidata Q-ID | `"Q21032324"` |
| `description` | string\|null | — | 任意 | OSM | 備考 | `null` |

### 1.2 内部メタ列 / Internal metadata（`_` 接頭辞）

| 列名 / Column | 型 / Type | 取得源 / Source | 説明 / Description | 例 / Example |
|---|---|---|---|---|
| `_display_name` | string | 内部 / Internal | 地図ポップアップ表示用に解決した最終名称 | `"岡田変電所"` |
| `_enriched_by` | string\|null | 内部 / Internal | 補完手段。`geocode_promotion`（Nominatim 由来）/ `null`（OSM のみ） | `"geocode_promotion"` |
| `_name_source` | string\|null | 内部 / Internal | 名称の出所。`geocoded` / `name:en` / `null` | `"geocoded"` |

### 1.3 その他 OSM 補助タグ / Additional OSM tags

スキーマ統一のため保持される任意タグ群（大半は `null`）。住所・建物・調査メタなど:
`addr:city`, `addr:province`, `addr:postcode`, `addr:suburb`, `addr:neighbourhood`, `addr:block_number`, `addr:housenumber`, `addr:quarter`, `building`, `building:levels`, `building:material`, `building:part`, `barrier`, `fence_type`, `landuse`, `area`, `height`, `ele`, `layer`, `cables`, `circuits`, `frequency_conversion`, `note`, `fixme`, `start_date`, `survey:date`, `mapillary`, `source`, `source:name`, `source_ref`, `wikipedia`, `operator:short`, `operator:short:en`, `operator:short:ja`, `operator:wikipedia`, `not:operator:wikidata`, `name:ja-Hira`, `name:ja-Latn`, `name:ja_rm`, `name:ko`, `name:es`, `alt_name`, `designation`, `disused`, `industrial`, `utility`, `plant:output:electricity`, `branch`, `type`, `gas_insulated` ほか。

> 型はすべて `string|null`、単位なし、すべて**任意**、取得源は **OSM**。意味は OSM Wiki の各キー定義に準拠。

---

## 2. 送電線 / Lines (`data/{region}_lines.geojson`)

ジオメトリ: `LineString`。`power=line`（架空線, 約 97%）または `power=cable`（地中線・海底ケーブル, 約 3%）。

### 2.1 主要列 / Core columns

| 列名 / Column | 型 / Type | 単位 / Unit | 必須/任意 | 取得源 / Source | 説明 / Description | 例 / Example |
|---|---|---|---|---|---|---|
| `power` | string | — | 必須 | OSM | `"line"`（架空）/ `"cable"`（地中・海底） | `"line"` |
| `name` | string\|null | — | 任意 | OSM / 算出 | 線路名。OSM 欠損時は `{事業者} {電圧}kV線` 等の合成名 | `"高井戸線"` |
| `name:ja` | string\|null | — | 任意 | OSM | 日本語名タグ | `null` |
| `voltage` | string\|null | **ボルト V** | 任意 | OSM | 公称電圧（V 単位）。`;` 区切りで多回線・併架の複数電圧を表す。非 null は約 85% | `"66000"`, `"275000;154000"` |
| `cables` | string\|null | 本 / count | 任意 | OSM | ケーブル（導体）条数 | `"6"` |
| `circuits` | string\|null | 回線 / count | 任意 | OSM | 回線数 | `"2"` |
| `wires` | string\|null | — | 任意 | OSM | 1 相あたり素導体構成 | `"single"`, `"double"`, `"quad"` |
| `operator` | string\|null | — | 任意 | OSM | 運用事業者（**所有者保証なし**） | `"東北電力"` |
| `operator:en` / `operator:ja` | string\|null | — | 任意 | OSM | 事業者名（英/日） | `"Tohoku EPCO"` |
| `frequency` | string\|null | Hz | 任意 | OSM | 周波数 | `"60"` |
| `material` | string\|null | — | 任意 | OSM | 導体材質 | `"aluminium"` |
| `structure` | string\|null | — | 任意 | OSM | 支持構造 | `"tower"` |
| `ref` | string\|null | — | 任意 | OSM | 線路記号 | `null` |
| `from` / `to` | string\|null | — | 任意 | OSM | 起点・終点（OSM タグ。算出端点とは別） | `null` |
| `voltage:primary` / `voltage:secondary` / `voltage:design` | string\|null | ボルト V | 任意 | OSM | 一次/二次/設計電圧 | `null` |
| `description` | string\|null | — | 任意 | OSM | 備考 | `null` |

### 2.2 内部メタ列 / Internal metadata（`_` 接頭辞）

| 列名 / Column | 型 / Type | 取得源 / Source | 説明 / Description | 例 / Example |
|---|---|---|---|---|
| `_display_name` | string | 内部 / Internal | 地図表示用に解決した最終線路名 | `"磯谷線"` |
| `_region` | string | 内部 / Internal | 所属地域 ID | `"hokkaido"` |
| `_region_ja` | string | 内部 / Internal | 地域名（日本語） | `"北海道"` |
| `_voltage_kv` | number\|null | 内部 / 算出 (Derived) | **kV 単位**に正規化した代表電圧。OSM `voltage`(V) を 1000 で除し、非標準値（22/25/33 kV 等）を JP 標準クラスにスナップした値 | `22.0`, `275.0` |
| `_enriched_by` | string\|null | 内部 / Internal | 補完手段。`endpoint_matching`（端点を最近傍変電所に紐付け ≤50 km）/ `null` | `"endpoint_matching"` |
| `_name_source` | string\|null | 内部 / Internal | 名称の出所。`operator_voltage` / `endpoints` / `regional_fallback` / `null` | `"operator_voltage"` |

> 注: 地図レイヤー用に軽量化した `docs/data/lines_all.geojson` は、`_region`・`_region_ja`・`_display_name`・`_voltage_kv` の 4 列のみを持つ。

### 2.3 その他 OSM 補助タグ / Additional OSM tags

`telecom`, `line`, `circuit`, `branch`, `layer`, `tunnel`, `bridge`, `man_made`, `landuse`, `maxheight`, `ground_conductors`, `gas_insulated`, `abandoned`, `disused`, `proposed:voltage`, `name:up`, `name:down`, `name:en`, `name:ja-Hira`, `name:ja-Latn`, `name:ja_rm`, `name:fr`, `name:es`, `alt_name`, `note`, `fixme`, `FIXME`, `start_date`, `source`, `source:ja`, `wikidata`, `wikipedia`, `operator:short(:en/:ja)`, `operator:wikidata`, `operator:wikipedia`, `not:operator:wikidata` ほか（型 `string|null`、任意、OSM 由来）。

---

## 3. 発電所 / Plants (`data/{region}_plants.geojson`)

ジオメトリ: `Point`。OSM `power=plant` 由来に、国土数値情報 P03 と逆ジオコーディングで属性を補完。

### 3.1 主要列 / Core columns

| 列名 / Column | 型 / Type | 単位 / Unit | 必須/任意 | 取得源 / Source | 説明 / Description | 例 / Example |
|---|---|---|---|---|---|---|
| `name` | string | — | 必須 | OSM / Nominatim / P03 | 発電所名（日本語）。欠損時は `{地名}発電所` で補完 | `"群馬県日向見発電所"` |
| `name:ja` | string | — | 任意 | OSM | 日本語名（空文字あり） | `""` |
| `name:en` | string\|null | — | 任意 | OSM / 算出 | 英語名 | `"Gunma Prefecture Hinatami Power Plant"` |
| `operator` | string\|null | — | 任意 | OSM / P03 | 事業者名 | `"群馬県企業局"` |
| `fuel_type` | string | — | 必須 | OSM / P03 / 算出 | 正規化燃料種別（下表参照）。不明は `"unknown"` | `"hydro"`, `"solar"` |
| `capacity_mw` | number | **MW** | 任意 | P03 / OSM | 定格出力。**欠損は `-1.0`**（または列欠落・非数値）。正値のみ有効 | `120.0` / `-1.0`（不明） |
| `voltage` | string | ボルト V | 任意 | OSM | 連系電圧（多くは空文字） | `""` |
| `plant:source` | string | — | 任意 | OSM | OSM 原データのソースタグ（≒燃料の元値） | `"hydro"`, `"solar"` |
| `osm_id` | integer | — | 任意 | OSM | OSM 要素 ID | `5744947416` |
| `osm_type` | string\|null | — | 任意 | OSM | OSM 要素種別 | `"way"`, `"relation"`, `"node"` |

### 3.2 内部メタ列 / Internal metadata（`_` 接頭辞）

| 列名 / Column | 型 / Type | 単位 / Unit | 取得源 / Source | 説明 / Description | 例 / Example |
|---|---|---|---|---|---|
| `_region` | string | — | 内部 / Internal | 所属地域 ID | `"tokyo"` |
| `_display_name` | string | — | 内部 / Internal | 地図表示用の最終名称 | `"群馬県日向見発電所"` |
| `_category` | string | — | 内部 / Internal | 区分。`ipp`（独立系）/ `utility`（一般電気事業者）/ `unknown` | `"ipp"` |
| `_fuel_color` | string | — | 内部 / Internal | 地図表示用 HEX カラー | `"#999999"` |
| `_enriched_by` | string\|null | — | 内部 / Internal | 補完手段。`nominatim` / `p03` / `jrp_lite`（合成）/ `overpass` / `null` | `"p03"` |
| `_name_source` | string\|null | — | 内部 / Internal | 名称の出所。`geocoded` / `fallback` / `null` | `"geocoded"` |
| `_p03_distance_km` | number\|null | **km** | 内部 / P03 | P03 マッチ点までの距離（小さいほど高信頼） | `0.044` |

### 3.3 `fuel_type` の取り得る値 / Allowed values

正規化後の主な値（[§5](#5-内部データモデル--internal-data-model-dataclasses) の `FuelType` enum に対応）:
`solar`, `hydro`, `coal`, `gas`(≈LNG/天然ガス), `oil`, `nuclear`, `wind`, `geothermal`, `biomass`, `waste`, `battery`, `unknown`。

> 注意: ごく一部のフィーチャで `fuel_type` に URL 等の異常値が残存（OSM 原データの `source` タグ混入）。下流利用時は上記既知値以外を `unknown` として扱うのが安全。

---

## 4. 欠損・センチネル値の早見表 / Missing-value cheat sheet

| 列 / Column | 欠損表現 / Missing representation | 有効判定 / Valid test |
|---|---|---|
| `voltage`（subs/lines/plants） | `null` または空文字 `""` | `voltage not in (None, "")` |
| `capacity_mw`（plants） | **`-1.0`**（センチネル）／ `null` ／ 非数値 | `float(capacity_mw) > 0` |
| `_voltage_kv`（lines） | `null`（電圧推定不可） | `_voltage_kv and _voltage_kv > 0` |
| `name` 系 | `null` または空文字 | 補完後はほぼ全件充足（README: subs/plants 100%, lines 99.99%） |
| その他 OSM タグ | `null` | — |

---

## 5. 内部データモデル / Internal data model (dataclasses)

配布 GeoJSON を読み込み、潮流計算（pandapower / MATPOWER）に渡すための内部表現。`src/model/*.py` の dataclass で定義される。**GeoJSON の列名とは異なる**点に注意（GeoJSON= OSM 生スキーマ、dataclass= 解析用正規化スキーマ）。電気パラメータはここで初めて付与される。

ファイル: [`src/model/substation.py`](src/model/substation.py), [`src/model/transmission_line.py`](src/model/transmission_line.py), [`src/model/generator.py`](src/model/generator.py)。

### 5.1 `Substation`（変電所＝バス）

| フィールド / Field | 型 / Type | 単位 / Unit | 必須/任意 | 取得源 / Source | 説明 / Description | 例 / Example |
|---|---|---|---|---|---|---|
| `id` | str | — | 必須 | 算出 / Derived | 一意 ID `{region}_sub_{seq}`（OSM 経由は `{region}_osm_sub_{osm_id}`） | `"tokyo_sub_0042"` |
| `name` | str | — | 必須 | OSM / Nominatim | 施設名 | `"岡田変電所"` |
| `region` | str | — | 必須 | 内部 / Internal | 地域 ID | `"tokyo"` |
| `latitude` | float | **度 (WGS-84)** | 必須 | OSM | 緯度 | `35.7` |
| `longitude` | float | **度 (WGS-84)** | 必須 | OSM | 経度 | `139.4` |
| `voltage_kv` | float | **kV** | 必須 | OSM / 算出 | 公称電圧（kV）。OSM `voltage`(V) を 1000 で除した値。不明は `0.0` | `275.0` |
| `bus_type` | int | — | 任意 (既定 1) | 算出 / Derived | MATPOWER バス種別: `1`=PQ / `2`=PV / `3`=Slack | `1` |
| `voltage_class` | enum\|null | — | 任意 | 算出 / Derived | `VoltageClass`。`voltage_kv` から自動導出 | `KV_275` |
| `source_map` | str | — | 任意 | 内部 / Internal | 出所ファイル名 | `""` |
| `grid_class` | str | — | 任意 | 合成 / Synthetic | 系統階層（`backbone` / `regional` / `sub_transmission`） | `"backbone"` |
| `description` | str | — | 任意 | OSM | 備考 | `""` |

### 5.2 `TransmissionLine`（送電線＝ブランチ）

| フィールド / Field | 型 / Type | 単位 / Unit | 必須/任意 | 取得源 / Source | 説明 / Description | 例 / Example |
|---|---|---|---|---|---|---|
| `id` | str | — | 必須 | 算出 / Derived | 一意 ID `{region}_line_{seq}` | `"tokyo_line_0123"` |
| `name` | str | — | 必須 | OSM / 算出 | 線路名 | `"高井戸線"` |
| `from_substation_id` | str | — | 必須 | 算出 / Derived | 起点バス ID（端点最近傍マッチ ≤50 km） | `"tokyo_sub_0042"` |
| `to_substation_id` | str | — | 必須 | 算出 / Derived | 終点バス ID | `"tokyo_sub_0051"` |
| `voltage_kv` | float | **kV** | 必須 | OSM / 算出 | 公称電圧（kV） | `275.0` |
| `length_km` | float | **km** | 必須 | 算出 / Derived | 線路長。座標列から Haversine（折れ線）で計算。最小フォールバック 1.0 km | `12.4` |
| `r_ohm_per_km` | float | **Ω/km** | 任意 (既定 0.0) | **合成 / Synthetic** | 単位長あたり抵抗。**電圧クラス別の典型値**（実測ではない） | `0.028` |
| `x_ohm_per_km` | float | **Ω/km** | 任意 (既定 0.0) | **合成 / Synthetic** | 単位長あたりリアクタンス。**電圧クラス別の典型値** | `0.325` |
| `c_nf_per_km` | float | **nF/km** | 任意 (既定 0.0) | **合成 / Synthetic** | 単位長あたり静電容量。サセプタンス `b_s_per_km`(S/km) から周波数依存で換算: `c_nf = b/(2πf)·1e9`（50 Hz 東 / 60 Hz 西）。**典型値ベース** | `12.25` |
| `max_i_ka` | float | **kA** | 任意 (既定 0.0) | **合成 / Synthetic** | 許容電流（熱容量）。**電圧クラス別の典型値** | `2.0` |
| `capacity_status` | enum | — | 任意 | 内部 / Internal | `CapacityStatus`（空き容量区分。本データでは既定 `UNKNOWN`） | `UNKNOWN` |
| `voltage_class` | enum\|null | — | 任意 | 算出 / Derived | `voltage_kv` から自動導出 | `KV_275` |
| `n1_eligible` | bool | — | 任意 (既定 False) | 算出 / Derived | N-1 適格性（`capacity_status` から導出） | `false` |
| `grid_class` | str | — | 任意 | 合成 / Synthetic | 系統階層 | `"backbone"` |
| `coordinates` | list[(lat,lon)] | **度** | 任意 | OSM | 折れ線の経路点列（緯度, 経度 順） | `[(35.7,139.4), …]` |
| `source_map` | str | — | 任意 | 内部 / Internal | 出所ファイル名 | `""` |
| `description` | str | — | 任意 | OSM | 備考 | `""` |

> **電気パラメータは合成値 / Electrical parameters are synthetic:** `r_ohm_per_km` / `x_ohm_per_km` / `c_nf_per_km` / `max_i_ka` は実線路の測定値ではなく、[`config/line_types.yaml`](config/line_types.yaml) に定義された**電圧クラス別の標準的な典型値**（OCCTO 広域系統計画資料・各社設計標準に基づく代表値）を `src/converter/line_parameters.py` が付与したもの。同一電圧クラスの全線路に同じ単位長定数が割り当てられ、線路長 `length_km` を乗じて総インピーダンスを得る。実系統の個別線路定数とは一致しない。

#### 電圧クラス別の典型値（合成値の出典）/ Synthetic per-km values by voltage class

`config/line_types.yaml` より（`c_nf_per_km` は周波数依存のため `b_s_per_km` から実行時換算）:

| 電圧クラス / kV | `r_ohm_per_km` (Ω/km) | `x_ohm_per_km` (Ω/km) | `b_s_per_km` (S/km) | `max_i_ka` (kA) | grid_class |
|---:|---:|---:|---:|---:|---|
| 500 | 0.012 | 0.290 | 4.1e-6 | 4.0 | backbone |
| 275 | 0.028 | 0.325 | 3.85e-6 | 2.0 | backbone |
| 220 | 0.032 | 0.335 | 3.75e-6 | 1.8 | backbone |
| 187 | 0.038 | 0.350 | 3.65e-6 | 1.5 | backbone |
| 154 | 0.050 | 0.380 | 3.5e-6 | 1.0 | regional |
| 132 | 0.045 | 0.370 | 3.55e-6 | 1.2 | backbone (Okinawa) |
| 110 | 0.055 | 0.385 | 3.45e-6 | 0.9 | regional |
| 77 | 0.100 | 0.395 | 3.3e-6 | 0.7 | sub_transmission |
| 66 | 0.120 | 0.400 | 3.2e-6 | 0.6 | sub_transmission |

### 5.3 `Generator`（発電所）

主要フィールドのみ抜粋（潮流・UC 用フィールドは多数。全定義は [`src/model/generator.py`](src/model/generator.py) の docstring 参照）。

| フィールド / Field | 型 / Type | 単位 / Unit | 必須/任意 | 取得源 / Source | 説明 / Description | 例 / Example |
|---|---|---|---|---|---|---|
| `id` | str | — | 必須 | 算出 / Derived | 一意 ID `{region}_gen_{seq}` | `"kyushu_gen_0917"` |
| `name` | str | — | 必須 | OSM / P03 / Nominatim | 発電所名 | `"川内川第一水力発電所"` |
| `capacity_mw` | float | **MW** | 必須 | P03 / OSM | 定格出力。GeoJSON 段階の欠損 `-1.0` はモデル化時に解決/除外 | `120.0` |
| `fuel_type` | str→enum | — | 必須 | OSM / P03 | 燃料種別（`FuelType` に解決） | `"hydro"` |
| `connected_bus_id` | str | — | 任意 | 算出 / Derived | 連系バス ID（最近傍変電所マッチ） | `"kyushu_sub_0044"` |
| `region` | str | — | 任意 | 内部 / Internal | 地域 ID | `"kyushu"` |
| `latitude` / `longitude` | float | **度 (WGS-84)** | 任意 (既定 0.0) | OSM / P03 | 緯度・経度 | `31.8 / 130.3` |
| `operator` | str | — | 任意 | OSM / P03 | 事業者名 | `"電源開発株式会社"` |
| `status` | str | — | 任意 (既定 `active`) | 内部 / Internal | 稼働状態 | `"active"` |
| `vm_pu` | float | **p.u.** | 任意 (既定 1.0) | 合成 / Synthetic | PV バス電圧設定値 | `1.0` |
| `p_min_mw` | float | **MW** | 任意 (既定 0.0) | 合成 / Synthetic | 最低出力 | `12.0` |
| `source` | str | — | 任意 | 内部 / Internal | データ出所識別子 | `"p03"` |

#### UC / 経済性・運用パラメータ（合成値 / Synthetic）

ユニットコミットメント（UC）・経済負荷配分用のフィールドは、燃料種別ごとの**標準値（合成値）**で付与される（[`data/reference/generator_defaults.yaml`](data/reference/generator_defaults.yaml) 由来）。実プラント固有値ではない。

| フィールド / Field | 型 | 単位 | 既定 | 説明 |
|---|---|---|---|---|
| `startup_cost` / `shutdown_cost` | float | ¥ | 0.0 | 起動/停止コスト |
| `hot_/warm_/cold_start_cost` | float | ¥ | 0.0 | 3 状態（熱/温/冷）起動コスト |
| `warm_start_h` / `cold_start_h` | int | h | 0 | 状態遷移しきい時間 |
| `min_up_time_h` / `min_down_time_h` | int | h | 1 | 最小連続運転/停止時間 |
| `ramp_up_mw_per_h` / `ramp_down_mw_per_h` | float\|null | MW/h | null=無制限 | ランプ率 |
| `fuel_cost_per_mwh` | float | ¥/MWh | 0.0 | 燃料費 |
| `labor_cost_per_h` | float | ¥/h | 0.0 | 人件費 |
| `no_load_cost` | float | ¥ | 0.0 | 無負荷固定費 |
| `maintenance_windows` | list[(int,int)] | h | [] | 計画停止期間 (start,end) |
| `construction_date` / `rebuild_planned_date` | str\|null | ISO 8601 | null | 建設/改修予定日 |
| `disaster_risk_score` | float | — | 0.0 | 災害脆弱性スコア（0=なし） |

#### 蓄電（ストレージ）パラメータ / Storage（合成 / Synthetic）

| フィールド / Field | 型 | 単位 | 既定 | 説明 |
|---|---|---|---|---|
| `storage_capacity_mwh` | float | MWh | 0.0 | 蓄電容量（>0 で蓄電設備扱い） |
| `charge_rate_mw` / `discharge_rate_mw` | float\|null | MW | null=容量と同値 | 充放電上限 |
| `charge_efficiency` / `discharge_efficiency` | float | 比率 (0,1] | 0.90 | 充放電効率 |
| `initial_soc_fraction` | float | 比率 [0,1] | 0.5 | 初期 SOC |
| `min_terminal_soc_fraction` | float | 比率 [0,1] | 0.5 | 終端最小 SOC |

> なお、UC 向けの拡張 GeoJSON（[`docs/data/generators.geojson`](docs/data/generators.geojson)）は、上記モデルを書き出した派生レイヤーで、`startup_cost_jpy`, `fuel_cost_per_mwh_jpy`, `co2_intensity_kg_per_mwh`, `forced_outage_rate`, `capacity_factor` などの**合成された経済・信頼度パラメータ**を列として含む。これらも燃料種別ベースの典型値であり実測値ではない。

---

## 6. 列挙型 / Enumerations

| Enum | 定義 / Members |
|---|---|
| `VoltageClass` | `KV_500, KV_275, KV_220, KV_187, KV_154, KV_132, KV_110, KV_77, KV_66, REGIONAL(0)` |
| `CapacityStatus` | `ZERO_N1_INELIGIBLE, ZERO_N1_ELIGIBLE, AVAILABLE, UNKNOWN` |
| `FuelType` | `COAL, LNG, OIL, NUCLEAR, HYDRO, PUMPED_HYDRO, GEOTHERMAL, WIND, SOLAR, BIOMASS, MIXED, UNKNOWN` |
| `BusType` | `PQ(1), PV(2), SLACK(3)`（MATPOWER 慣例） |

---

## 7. 注意事項 / Caveats

1. **本データは「地理トポロジ」であり、すぐ使える電力系統モデルではない。** 電気パラメータ（R/X/C/許容電流）は電圧クラス別の合成典型値。個別線路の実定数とは一致しない。
2. **`operator` は所有者を保証しない。** OSM の `operator` タグは実所有者と異なりうる（README の免責参照）。
3. **`voltage` の単位はボルト (V)**、`voltage_kv` / `_voltage_kv` はキロボルト (kV)。混同しないこと。
4. **`capacity_mw = -1.0` は「容量不明」のセンチネル**。`0` ではない。集計時は正値のみを対象に。
5. 一部 `fuel_type` に OSM 由来の異常値（URL 等）が残存。既知値以外は `unknown` 扱い推奨。
6. GeoJSON のプロパティ列名（OSM スキーマ）と dataclass のフィールド名（解析用スキーマ）は**一致しない**。マッピングは `src/server/geojson_parser.py` を参照。
7. 件数の出典: 本辞書の件数は `data/*.geojson` を実測した値（subs 6,962 / lines 40,077 / plants 19,138）。README の地域別表と整合。
</content>
</invoke>
