```
 █████╗ ██╗     ██╗             ██╗██████╗         ██████╗ ██████╗ ██╗██████╗
██╔══██╗██║     ██║             ██║██╔══██╗       ██╔════╝ ██╔══██╗██║██╔══██╗
███████║██║     ██║             ██║██████╔╝█████╗ ██║  ███╗██████╔╝██║██║  ██║
██╔══██║██║     ██║        ██   ██║██╔═══╝ ╚════╝ ██║   ██║██╔══██╗██║██║  ██║
██║  ██║███████╗███████╗   ╚█████╔╝██║            ╚██████╔╝██║  ██║██║██████╔╝
╚═╝  ╚═╝╚══════╝╚══════╝    ╚════╝ ╚═╝             ╚═════╝ ╚═╝  ╚═╝╚═╝╚═════╝
```

# All-Japan-Grid

Open Japanese power grid **geographic topology** dataset built from OpenStreetMap.
10 regions, 40,000+ transmission lines, 7,000+ substations, 19,000+ power plants.

OpenStreetMap から機械的に抽出した、日本全国の送電網 **地理トポロジ** データセットです。
10 地域、送電線 40,000 本超、変電所 7,000 箇所超、発電所 19,000 箇所超。

**Live Map / ライブマップ:** https://lutelute.github.io/All-Japan-Grid/

---

## Disclaimer / 免責事項

> **English:**
> This dataset is generated **automatically by machine processing** of publicly available [OpenStreetMap](https://www.openstreetmap.org/) data. It does **not** reflect official information from any electric power company, transmission operator, or government agency. The data may contain errors, omissions, or inaccuracies inherent to crowdsourced mapping and automated extraction. **Use at your own risk.** The authors assume no liability for any damages, losses, or consequences arising from the use of this data. This dataset is provided "as is" without warranty of any kind, express or implied.

> **日本語:**
> 本データセットは、公開されている [OpenStreetMap](https://www.openstreetmap.org/) のデータを **機械的に自動処理** して生成したものです。各電力会社・送電事業者・政府機関等の公式情報を正確に反映したものでは **ありません**。クラウドソーシングによる地図データおよび自動抽出処理に起因する誤り・欠落・不正確さが含まれる可能性があります。**本データの利用は自己責任** でお願いいたします。本データの利用により生じたいかなる損害・損失・結果についても、作成者は一切の責任を負いません。本データセットは明示・黙示を問わず、いかなる種類の保証もなく「現状のまま」提供されます。

> **⚠ Operator / Ownership Attribution / 事業者・所有者情報について:**
> This dataset is **not** derived from official data published by General Electricity Transmission and Distribution Operators (一般送配電事業者). In OpenStreetMap, the `operator` tag on transmission/distribution lines does not always reflect the actual asset owner. Since all features are extracted automatically from open data **without authoritative ownership information**, the operator attribution of individual lines and substations is **not guaranteed** to be correct. Lines that cross utility service area boundaries, shared facilities, and assets transferred between operators may be particularly inaccurate.
>
> 本データセットは一般送配電事業者が公開する公式データから作成したものでは **ありません**。OpenStreetMap 上の送配電線の `operator` タグは、実際の設備所有者と異なる場合があります。所有者情報を持たないオープンデータから自動的に抽出した処理であるため、個々の送電線・変電所の事業者帰属は **保証されません**。特に、事業者の供給区域をまたぐ線路、共用設備、事業者間で移管された設備などは不正確な可能性が高くなります。

---

### Network Preview / ネットワーク プレビュー

<p align="center">
  <img src="https://raw.githubusercontent.com/lutelute/All-Japan-Grid/main/docs/assets/gif/network_ybus_tour.gif" alt="Network + Ybus Tour" width="100%">
</p>

### Satellite Validation / 衛星画像との突合せ検証

OSM由来のトポロジが実在の送電インフラと一致することを衛星画像で検証しています（鹿島・阿南FC・嶺南など主要変電所）。

<p align="center">
  <img src="https://raw.githubusercontent.com/lutelute/All-Japan-Grid/main/docs/assets/figs/fig_satellite_validation.png" alt="Satellite Validation" width="100%">
</p>

### Pipeline / パイプライン全体図

7段階の自動エンリッチパイプライン: OSM取得 → 属性補完 → トポロジ再構築 → 電気パラメータ付与 → Ybus構築 → 潮流解析 → 可視化。

<p align="center">
  <img src="https://raw.githubusercontent.com/lutelute/All-Japan-Grid/main/docs/assets/figs/fig_pipeline_flow.png" alt="Pipeline Flow" width="100%">
</p>

### v1.3.0 Highlights

- ✅ **CIM / CGMES Level 2 — electrically faithful & more native solves.** Corrected parallel-circuit counting and unified voltage parsing make the cim2pp round-trip electrically identical to the solved network, and lift **chubu & kyushu to native convergence**: **8 of 10 regions now solve natively** (hokuriku x0.8, kansai x0.3 as balanced demand-scaled cases). All 10 verify OK.
- 🔧 **Power-flow pipeline promoted into `src/powerflow/`** — the reconstruction → solve pipeline (`build_and_solve`, topology builders, net transforms, solver) moved out of `examples/`/`scripts/` so the dependency flows the right way and the model is testable in CI.
- 📦 [Release v1.3.0](https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.3.0): `all_japan_grid_cim_L1.zip` (31 MB) + `all_japan_grid_cim_L2.zip` (13 MB)

### v1.2.0 Highlights

- 🆕 **CIM / CGMES standardization** — the whole dataset re-expressed as IEC 61970 CIM (CGMES 2.4.15 RDF/XML). **Level 1** catalogue (6,962 `Substation` / 40,077 `ACLineSegment` / 19,138 fuel-specific `GeneratingUnit`) + **Level 2** solvable power-flow case (EQ/TP/SSH/SV/GL), validated via pandapower `cim2pp`.
- 📄 Full mapping spec: [docs/CIM_MAPPING.md](docs/CIM_MAPPING.md)

### v1.1.0 Highlights

- 🆕 [N-1 contingency analysis](https://github.com/lutelute/All-Japan-Grid/blob/main/scripts/run_n1_contingency.py) — 914 backbone lines tripped one-by-one across 9 regions, identifying pivotal lines whose loss breaks AC convergence in Tokyo / Kyushu.
- 🔧 Voltage standardization (`_clean_voltage`) — non-standard 22/25/30/33/100 kV snap to JP standard classes. **Hokkaido `vm_min` 0.30 → 0.81 pu**.
- ⚡ National-zonal power flow — east/Hokkaido/Okinawa AC + west DC, with **auto-DC mode** on the live map.
- 🗺 New compare tab with Ybus visualization (national / per-region / spy plot).
- 📄 [Release notes](https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.1.0) / [Root-cause analysis](https://github.com/lutelute/All-Japan-Grid/blob/main/docs/WEST_AC_ANALYSIS.md)

> **Important / 重要:** This dataset provides the **geographic layout** of Japan's transmission infrastructure — where substations and lines are physically located and how they connect spatially. It is **not** a ready-to-use electrical model. See [Limitations](#limitations--what-this-data-is-not--本データの限界) below.
>
> 本データセットは日本の送電インフラの **地理的配置** — 変電所や送電線の物理的な位置と空間的な接続関係 — を提供するものです。そのまま使える電力系統モデルでは **ありません**。詳しくは下記 [Limitations（本データの限界）](#limitations--what-this-data-is-not--本データの限界) を参照してください。

## Dataset / データセット

| Region / 地域 | Substations / 変電所 | Lines / 送電線 | Plants / 発電所 | Frequency / 周波数 |
|--------|------------|-------|--------|-----------|
| Hokkaido / 北海道 | 471 | 4,136 | 436 | 50 Hz |
| Tohoku / 東北 | 901 | 6,628 | 1,311 | 50 Hz |
| Tokyo / 東京 | 1,726 | 8,295 | 7,207 | 50 Hz |
| Chubu / 中部 | 1,163 | 6,589 | 3,792 | 60 Hz |
| Hokuriku / 北陸 | 267 | 2,296 | 432 | 60 Hz |
| Kansai / 関西 | 902 | 3,994 | 1,518 | 60 Hz |
| Chugoku / 中国 | 531 | 3,176 | 1,173 | 60 Hz |
| Shikoku / 四国 | 258 | 1,532 | 688 | 60 Hz |
| Kyushu / 九州 | 684 | 3,314 | 2,549 | 60 Hz |
| Okinawa / 沖縄 | 59 | 117 | 32 | 60 Hz |
| **Total / 合計** | **6,962** | **40,077** | **19,138** | — |

### File Format / ファイル形式

GeoJSON FeatureCollection per region / 地域ごとの GeoJSON:
```
data/{region}_substations.geojson   # Point/Polygon features（変電所）
data/{region}_lines.geojson         # LineString features（送電線）
data/{region}_plants.geojson        # Point features（発電所）
```

Key properties (substations & lines) / 主なプロパティ（変電所・送電線）:
- `voltage` — OSM voltage in volts / 電圧（ボルト単位、例: `"275000"`）
- `name` / `name:ja` — Facility name / 施設名
- `operator` — Operating utility / 運用事業者
- `cables`, `circuits` — Line specifications / 線路仕様

Key properties (plants) / 主なプロパティ（発電所）:
- `fuel_type` — Normalized: solar, hydro, coal, gas, nuclear, wind, etc. / 燃料種別
- `capacity_mw` — Output capacity in MW (when available) / 発電容量（MW）
- `plant:source` — Raw OSM source tag / OSM 原データのソースタグ
- `name` / `name:ja` — Plant name / 発電所名

### CIM / CGMES Export / CIM・CGMES エクスポート

In addition to GeoJSON, the dataset is published as **IEC 61970 CIM
(CGMES 2.4.15) RDF/XML** — the international standard for power-system model
exchange. Every substation, line and plant becomes a standards-conformant CIM
object with a deterministic mRID and a WGS84 geographic location.

GeoJSON に加え、本データセットを電力系統モデル交換の国際標準 **IEC 61970 CIM
(CGMES 2.4.15) RDF/XML** としても提供します。全変電所・送電線・発電所が、決定的な
mRID と WGS84 座標を持つ規格準拠の CIM オブジェクトになります。

```bash
python scripts/export_cim.py          # -> dist/cim/<region>_{EQ,GL}.xml
```

- **Profiles:** EQ (Equipment) + GL (Geographical Location)
- **Mapping:** substation → `cim:Substation`+`VoltageLevel`+`BaseVoltage`, line → `cim:ACLineSegment`+`Terminal`+`ConnectivityNode`, plant → fuel-specific `cim:{Thermal,Hydro,Wind,Solar,Nuclear}GeneratingUnit` (+`SynchronousMachine`), coordinates → `cim:Location`+`PositionPoint`
- **6,962** Substations · **40,077** ACLineSegments · **19,138** GeneratingUnits (all 10 regions, 0 dangling references)
- **Validated** against pandapower `cim2pp` (an independent CGMES parser)
- Full specification: **[docs/CIM_MAPPING.md](docs/CIM_MAPPING.md)**

**Level 2 — solvable power-flow case (EQ/TP/SSH/SV/GL):** `scripts/export_cim_level2.py`
exports the *connected, solved* network with shared `ConnectivityNode`s,
`TopologicalNode`s, `PowerTransformer`s, `EnergyConsumer` loads, PV
`SynchronousMachine`s and a slack `ExternalNetworkInjection`. The round-trip
through pandapower `cim2pp` is **electrically identical** to the solved
network (parallel circuits, switching states and km lengths preserved;
regression-tested) and **`runpp` converges in all 10 regions** — 8 natively,
with the two ill-conditioned regions shipped as balanced demand-scaled cases
(hokuriku x0.8, kansai x0.3 — generation redispatched to match; see
[docs/CIM_MAPPING.md](docs/CIM_MAPPING.md)).

**Level 2 — 求解可能な潮流ケース:** `scripts/export_cim_level2.py` が接続済み・
求解済みネットワークを EQ/TP/SSH/SV/GL で出力します。エクスポートは並列回線・開閉状態・
km長を保持し、pandapower `cim2pp` での往復後も**元のネットワークと電気的に同一**
（回帰テスト済み）。**全10地域で潮流が収束**します（8地域はそのまま、悪条件の
hokuriku は x0.8、kansai は x0.3 の需給整合済み需要スケールケースとして提供）。

<p align="center">
  <img src="https://raw.githubusercontent.com/lutelute/All-Japan-Grid/main/docs/assets/figs/fig_cim_national_pf.png" alt="CIM/CGMES Level 2 national power-flow" width="62%">
</p>

> 13,731 buses across 10 regions, exported as CGMES and re-solved through
> pandapower `cim2pp` → `runpp`. The map shows the native solve (kansai grey);
> the Level-2 CGMES then solves **all 10** via demand-scaling. /
> 図は無補正の解（kansai 灰色）。Level 2 CGMES は需要スケールで **全10地域** 収束。

Both levels ship as zipped [GitHub Release v1.2.1](https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.3.0) assets
(`all_japan_grid_cim_L1.zip` ≈31 MB, `all_japan_grid_cim_L2.zip` ≈13 MB),
regenerable via the two scripts above.

### Data Source / データソース

All data is extracted from [OpenStreetMap](https://www.openstreetmap.org/) using the Overpass API.
全データは Overpass API を用いて [OpenStreetMap](https://www.openstreetmap.org/) から抽出しています。

- `power=substation` — Substations, switching stations / 変電所、開閉所
- `power=line` / `power=cable` — Transmission lines / 送電線
- `power=plant` — Power plants / 発電所

License / ライセンス: [ODbL](https://opendatacommons.org/licenses/odbl/) (OpenStreetMap)

### Data Enrichment Pipeline / データエンリッチメント パイプライン

Raw OSM data contains many features with missing attributes (name, operator, fuel type). A 6-stage enrichment pipeline fills these gaps programmatically.

OSM の生データには属性（名称、事業者、燃料種別）が欠落したフィーチャが多数存在します。6段階のエンリッチメントパイプラインでこれらを自動補完します。

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Enrichment Pipeline Flow                        │
│                                                                     │
│  [1] audit_data_quality.py ──── Baseline audit (107,383 placeholders)│
│       │                                                             │
│  [2] enrich_substations_geocode.py --promote-names                  │
│       │   Nominatim reverse geocoding → {area}変電所                 │
│       │   Dedup suffixes (_2, _3) for same-name conflicts           │
│       │                                                             │
│  [3] enrich_plants_p03.py                                           │
│       │   P03 national dataset spatial matching                     │
│       │   + operator name normalization                             │
│       │                                                             │
│  [4] enrich_overpass_tags.py                                        │
│       │   Batch Overpass API queries (100 IDs/batch)                │
│       │   name, operator, fuel_type from OSM tags                   │
│       │   Cache: data/cache/overpass_tags.json                      │
│       │                                                             │
│  [5] enrich_plants_geocode.py                                       │
│       │   Nominatim reverse geocoding → {area}発電所                 │
│       │   1.1s rate limit, cache: data/cache/plants_geocode.json    │
│       │                                                             │
│  [6] enrich_lines_endpoints.py                                      │
│       │   Match line start/end to nearest substation (≤50km)        │
│       │   Name format: {from}~{to}線 / {operator} {voltage}kV線     │
│       │                                                             │
│  [7] audit_data_quality.py ──── Final validation                    │
└─────────────────────────────────────────────────────────────────────┘
```

**Results / 結果:**

| Layer | Total | Before | After | Resolution |
|-------|-------|--------|-------|------------|
| Substations / 変電所 | 6,962 | 3,114 unnamed | **0** | 100% |
| Plants / 発電所 | 19,138 | 16,102 unnamed | **0** | 100% |
| Lines / 送電線 | 40,077 | 30,168 unnamed | **2** | 99.99% |

```bash
# Run full pipeline / パイプライン全体を実行
python scripts/enrich_all.py

# Single region / 特定地域のみ
python scripts/enrich_all.py --region hokuriku

# Dry run (show execution plan) / ドライラン
python scripts/enrich_all.py --dry-run
```

See [WHITEPAPER.md](WHITEPAPER.md) Section 4 for detailed methodology.
詳細な方法論は [WHITEPAPER.md](WHITEPAPER.md) セクション4を参照。

> **Note / 注意:** Pages上のポップアップ表示には2系統のデータが使われます:
> 1. **地図レイヤー用** (`subs_*.geojson`, `lines_*.geojson`, `plants_*.geojson`) — `build_static_site.py` が `data/` から生成。`_display_name` で表示。
> 2. **詳細ポップアップ用** (`substations.geojson`, `generators.geojson`) — 各 export スクリプトが生成。座標マッチングで紐付け。
>
> enrichment後は**両方を再生成**しないと「Unnamed」が残ります:
> ```bash
> python scripts/export_substations_geojson.py   # 詳細ポップアップ用
> python scripts/build_static_site.py            # 地図レイヤー用
> ```

## Interactive Map (GitHub Pages) / インタラクティブマップ

The static site at `docs/` renders all regions on a Leaflet.js dark map with voltage-based coloring.
`docs/` 以下の静的サイトで、全地域を Leaflet.js ダークマップ上に電圧別の色分けで表示します。

Voltage filter presets / 電圧フィルタ: 500 kV, 275 kV+, 154 kV+, 110 kV+, 66 kV+, All

```bash
# Local preview / ローカルプレビュー
python -m http.server -d docs 8080
open http://localhost:8080
```

## Limitations — What This Data Is NOT / 本データの限界

OSM provides the **geographic** skeleton of the transmission grid. To build a functioning electrical model (power flow, OPF, UC), the following are required but **missing** from this dataset.

OSM が提供するのは送電網の **地理的** 骨格です。実用的な電力系統モデル（潮流計算、OPF、UC）を構築するには、以下のデータが必要ですが本データセットには **含まれていません**。

| Missing / 不足データ | Why it matters / 重要な理由 | Potential source / 補完候補 |
|---------|---------------|-----------------|
| **Line impedance (R, X, B)** / 線路インピーダンス | Required for any power flow calculation / 潮流計算に必須 | Typical values by voltage class, OCCTO published parameters |
| **From/to bus connectivity** / 母線接続関係 | OSM lines are geographic traces, not bus-bus connections / OSM の線は地理的経路であり母線間接続ではない | Manual verification, OCCTO topology data |
| **Generator details** / 発電機詳細 | Lacks cost curves, min/max output, ramp rates / コストカーブ・出力範囲・ランプレート等が欠如 | OCCTO supply plan, 国土数値情報 P03, JEPX data |
| **Load / demand** / 負荷・需要 | No demand allocation at buses / 母線への需要配分なし | OCCTO area demand, prefecture-level statistics |
| **Transformer data** / 変圧器データ | No tap ratios, impedance, winding configuration / タップ比・インピーダンス・巻線構成なし | Synthetic estimation or utility disclosure |
| **Switching topology** / 開閉器トポロジ | Bus-section / breaker-level detail unavailable / 母線区分・遮断器レベルの詳細なし | Not publicly available in Japan |

### Lessons Learned / 教訓

1. **"地図があるからデータがある" は誤り** — A map showing transmission lines does not imply that the underlying electrical parameters exist. Geographic data and electrical data are fundamentally different.
2. **容量データ ≠ 系統モデル** — Knowing a line is "275 kV" tells you the voltage class but nothing about impedance, thermal rating, or actual connectivity.
3. **Endpoint matching is fragile / 端点マッチングは脆弱** — Heuristic from/to bus estimation from geographic proximity produces many mismatches. A 50 km threshold catches most connections but also creates false links.
4. **Japanese name normalization / 日本語名称の正規化** — `変電所`, `発電所`, `開閉所` have multiple orthographies (kanji/kana/abbreviation). Fuzzy matching is essential.
5. **Null diversity / Null値の多様性** — OSM features may have `voltage=null`, `voltage=""`, `voltage="yes"`, or no voltage tag at all. Robust parsing must handle all cases.
6. **Regional scope & name resolution / 地域スコープと名称解決** — The same substation name can appear in multiple regions. Name-based matching must be scoped to the correct region.
7. **AC power flow on OSM topology produces physically meaningless results / OSMトポロジでの交流潮流計算は物理的に無意味** — Without proper impedance data, generator dispatch, and demand allocation, power flow output is numerical noise, not engineering insight.

### Known Data Quality Issues — Substation / Plant Classification / データ品質の既知の問題 — 変電所・発電所の分類混在

OSM data contains systematic misclassifications between substations (`power=substation`) and power plants (`power=plant`). An automated audit (`scripts/audit_substation_plant_overlap.py`) identified 4 categories of issues:

OSM データには変電所（`power=substation`）と発電所（`power=plant`）の間で体系的な分類の混在があります。自動監査スクリプト（`scripts/audit_substation_plant_overlap.py`）で 4 カテゴリの問題を特定しました。

| Category / カテゴリ | Count / 件数 | Severity / 深刻度 | Description / 概要 |
|---|---|---|---|
| **A. Substations named as plants** / 発電所名の変電所 | ~45 | Medium / 中 | `power=substation` with name containing `発電所`. Mix of legitimate switchyards (e.g. `葛野川発電所屋外開閉設備`) and likely misclassified plants (e.g. `川内発電所` 500kV). |
| **B. `substation=generation`** / 発電用変電所 | ~41 | Low / 低 | Intentional OSM tag for step-up substations at generation sites. Not an error per se, but these features may overlap with nearby plant entries. |
| **C. Tag value errors** / タグ値の誤り | ~17 | **High / 高** | `substation` field contains another facility name instead of a valid type (e.g. `substation=東京電力パワーグリッド（株）堰原変電所`). Clearly an OSM input error. |
| **D. Plants named as substations** / 変電所名の発電所 | ~5 | Low / 低 | `power=plant` with name containing `変電所`. Mostly battery storage at substations (e.g. `豊前蓄電池変電所`). |

**Examples of Category A — Misclassified major facilities / カテゴリA 事例:**

```
[hokkaido] 石狩湾新港発電所   substation=generation  voltage=275000   ← LNG火力がsubstationとして登録
[chugoku]  川内発電所         substation=transmission voltage=500000;187000  ← 原子力発電所
[kansai]   阿南発電所         substation=transmission voltage=187000;66000   ← 火力発電所
[tohoku]   田子倉発電所       substation=transmission voltage=275000   ← 水力発電所(只見川)
[chubu]    大井水力発電所     substation=transmission voltage=154000   ← 水力発電所
```

**Examples of Category C — Tag value errors / カテゴリC 事例:**

```
[tokyo]    桜堤一丁目変電所    substation=東京電力パワーグリッド（株）堰原変電所  ← 別の変電所名が混入
[chubu]    市場変電所          substation=SGET富山メガソーラー発電所             ← 発電所名が混入
[kansai]   諏訪町変電所        substation=関西電力株式会社八鹿変電所             ← 別の変電所名が混入
```

**Colocated but differently named / 近接するが名称が異なる変電所・発電所ペア:**

200m以内に変電所と発電所が共存するが名前が一致しないペアが約260件。多くは水力発電所の昇圧変電所（例: `岩清水変電所` ↔ `下新冠発電所` 10m）。これは発電所に併設される変電設備が独立した名前を持つ実態を反映しており、必ずしもデータ誤りではない。

```bash
# Run the full audit / 監査スクリプトを実行
python scripts/audit_substation_plant_overlap.py

# Apply reproducible fixes (Category C tag errors) / 再現可能な修正を適用
python scripts/audit_substation_plant_overlap.py --fix
```

> **Note / 注意:** Category A and B are **upstream OSM data issues**. Fixing them in our dataset would diverge from the source. Category C tag errors are corrected by `--fix` because they are unambiguous input mistakes. The audit results are saved to `data/audit/substation_plant_overlap.json` for downstream consumers.
>
> カテゴリ A・B は **OSM 上流のデータ問題** です。本データセットで修正するとソースとの乖離が生じます。カテゴリ C のタグ誤りは明確な入力ミスであるため `--fix` で修正します。監査結果は `data/audit/substation_plant_overlap.json` に保存され、下流で参照可能です。

## What This Data IS Good For / 本データの活用法

- **Visualization / 可視化**: Interactive maps of Japan's transmission infrastructure by voltage class and region / 電圧階級・地域別の送電インフラ インタラクティブマップ
- **Topology research / トポロジ研究**: Graph-theoretic analysis of network connectivity, redundancy, vulnerability / ネットワーク接続性・冗長性・脆弱性のグラフ理論的分析
- **Geographic reference / 地理的参照**: Substation locations and transmission corridors for spatial analysis / 空間分析のための変電所位置・送電回廊
- **Starting point for synthetic models / 合成モデルの出発点**: Geographic skeleton to be enriched with electrical parameters from other sources / 他ソースの電気パラメータで補完可能な地理的骨格
- **Education / 教育**: Understanding the structure of Japan's 10 regional grids and the 50/60 Hz boundary / 日本の10地域系統と50/60Hz境界の構造理解

## Analysis Tools (Experimental) / 解析ツール（実験的）

The `src/` directory contains power flow and UC solver code. These tools work correctly on **complete** electrical models (e.g. MATPOWER test cases) but produce unreliable results on raw OSM topology due to the missing data described above.

`src/` ディレクトリには潮流計算および UC ソルバのコードが含まれています。これらのツールは **完備された** 電力系統モデル（例: MATPOWER テストケース）では正しく動作しますが、上述の不足データにより、生の OSM トポロジに対しては信頼できない結果を出力します。

They are included as reference implementations for future use when combined with complementary data sources.
補完データソースとの組み合わせを想定した参照実装として収録しています。

### Local Server / ローカルサーバー

```bash
pip install -r requirements.txt
uvicorn src.server.app:app --reload
open http://localhost:8000
```

### Included Tools / 収録ツール

| Module / モジュール | Purpose / 目的 | Status / 状態 |
|--------|---------|--------|
| `src/server/` | FastAPI web server, interactive map / FastAPI ウェブサーバー、インタラクティブマップ | Works / 動作可 |
| `src/powerflow/` | DC/AC power flow via pandapower / pandapower による DC/AC 潮流計算 | Requires electrical parameters / 電気パラメータが必要 |
| `src/ac_powerflow/` | Advanced AC methods / 高度な AC 手法 | Requires electrical parameters / 電気パラメータが必要 |
| `src/uc/` | Unit Commitment (MILP, PuLP + HiGHS) with inter-regional transmission constraints / 地域間連系線制約付き UC ソルバ | Verified: 646 generators × 24h × 9 interconnections → Optimal in ~38s / 実証済み |
| `src/converter/` | pandapower / MATPOWER export / エクスポート | Works / 動作可 |

## Future Work — Complementary Data Sources / 今後の展望 — 補完データソース

> **📐 戦略計画 / Strategic plan:** All-Japan-Grid を日本の電力業界の
> 継続的資産へ育てる5本柱の計画は **[docs/VISION.md](docs/VISION.md)** を参照。

To build a usable electrical model, this geographic topology needs to be combined with:
実用的な電力系統モデルを構築するには、本地理トポロジを以下のデータと組み合わせる必要があります:

| Data source / データソース | What it provides / 提供内容 | Access / アクセス |
|-------------|-----------------|--------|
| **OCCTO** (電力広域的運営推進機関) | Interconnection capacity, area demand, supply-demand plans / 連系線容量、地域需要、需給計画 | [occto.or.jp](https://www.occto.or.jp/) |
| **国土数値情報 P03** | Power plant locations, capacity, fuel type / 発電所位置、容量、燃料種別 | [nlftp.mlit.go.jp](https://nlftp.mlit.go.jp/ksj/) |
| **JEPX** (日本卸電力取引所) | Spot market prices, area price signals / スポット市場価格、エリアプライス | [jepx.jp](http://www.jepx.jp/) |
| **PyPSA-Earth / atlite** | Renewable resource data, synthetic grid enrichment / 再エネ資源データ、合成系統補完 | [pypsa-earth.readthedocs.io](https://pypsa-earth.readthedocs.io/) |
| **MATPOWER test cases** | Validated IEEE/PGLIB models for benchmarking / 検証済みベンチマークモデル | [matpower.org](https://matpower.org/) |
| **Synthetic line parameters** / 合成線路パラメータ | R/X/B estimation by voltage class and conductor type / 電圧階級・導体種別による推定値 | Literature values (e.g. Glover, Sarma & Overbye) |

Contributions and collaborations welcome. If you have access to additional data sources or are working on Japanese grid modeling, please open an issue.

コントリビューションや共同研究を歓迎します。追加のデータソースをお持ちの方、日本の系統モデリングに取り組んでいる方は、ぜひ Issue を作成してください。

## Project Structure / プロジェクト構成

```
data/                  GeoJSON network data (10 regions) / 地域別 GeoJSON（一次ソース）
config/                Region metadata, schemas, UC config / 地域メタデータ・スキーマ・UC設定
src/
  model/               Data models / データモデル（Substation, TransmissionLine, Generator）
  converter/           pandapower conversion / pandapower 変換
  matpower/            MATPOWER .mat export with GENCOST / MATPOWER エクスポート
  cim/                 IEC 61970 CIM / CGMES export (L1 + L2) / CIM・CGMES エクスポート
  reconstruction/      Isolated-element reconnection & synthesis / 孤立要素の再接続・合成
  powerflow/           DC/AC power flow runner (experimental) / 潮流計算（実験的）
  ac_powerflow/        Advanced AC power flow, ~20 methods (experimental) / 高度 AC 潮流（実験的）
  dynamics/            Swing equation, CPF, short-circuit, modal / 動態・電圧安定性・短絡
  uc/                  Unit Commitment solver (experimental) / UC ソルバ（実験的）
  db/                  SQLite attribute overlay (DB unification base) / 属性DB（DB統一の土台）
  server/              FastAPI web server + GeoJSON loader / ウェブサーバー
  utils/               Geographic utilities / 地理ユーティリティ
examples/              Demo scripts (incl. national UC with 757 generators) / デモスクリプト（757台全国UC含む）
docs/                  GitHub Pages static site / 静的サイト
scripts/               Pipeline, analysis, export & figure scripts — see scripts/README.md / 用途別5系統
schemas/               XML schema definitions / XML スキーマ定義
tests/                 pytest test suite / テストスイート
papers/                IEEJ (和文) & IEEE Access manuscripts / 論文原稿
dist/                  CIM/CGMES distribution (samples tracked, full sets via Releases) / CIM 配布物
```

## Requirements / 必要環境

Python 3.10+

```bash
pip install -r requirements.txt
```

Key dependencies / 主な依存パッケージ: pandapower, fastapi, pulp, highspy, pyyaml, geopandas

## Contributing / 貢献

データギャップ（権威ある R/X/B・実需要・発電機諸元・第三者検証）と、再取得後も失われない
貢献経路（OSM 上流 / DB キュレーション / コード）は **[CONTRIBUTING.md](CONTRIBUTING.md)** に
まとめています。事業者・OCCTO・研究機関との連携設計は [docs/ENGAGEMENT.md](docs/ENGAGEMENT.md)、
全体構想は [docs/VISION.md](docs/VISION.md) を参照。

> Data gaps and contribution paths that survive an OSM re-fetch are documented in
> **[CONTRIBUTING.md](CONTRIBUTING.md)**. **Please never submit confidential / NDA data to this
> public repository** — only publicly-derived values or validated `confidence` tags.

## License / ライセンス

- Network data / ネットワークデータ: [ODbL](https://opendatacommons.org/licenses/odbl/) (OpenStreetMap)
- Code / コード: MIT
