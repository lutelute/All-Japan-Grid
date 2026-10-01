# データセットの詳細 / Dataset details

README を入口に絞ったとき(2026-10)、README にあった詳しい節をここへ**原文のまま**移した。
数字や記述はそれぞれの節を書いた時点のもので、最新の規模はダッシュボード
(https://lutelute.github.io/All-Japan-Grid/)と README の「規模」を見ること。

The detailed sections that used to live in the README were moved here verbatim when the README was
trimmed to an entry page (2026-10). Figures reflect when each section was written; see the dashboard
for current numbers.

- [全国トポロジと検証 / National topology & validation](#national-topology--validation--全国トポロジと検証)
- [データセット / Dataset](#dataset--データセット)(ファイル形式・CIM/CGMES・データソース・エンリッチメント)
- [本データの限界 / Limitations](#limitations--what-this-data-is-not--本データの限界)(教訓・既知の品質問題・66kV の到達点)
- [本データの活用法 / What this data IS good for](#what-this-data-is-good-for--本データの活用法)
- [解析ツール / Analysis tools](#analysis-tools--解析ツール)
- [今後の展望 / Future work](#future-work--complementary-data-sources--今後の展望--補完データソース)

---

## National Topology & Validation / 全国トポロジと検証

The national transmission network extracted from OSM (coloured by voltage class), confirmed against satellite imagery (Kashima / Anan FC / Reinan), and scored against TEPCO's per-line flows — corridor-usage rank correlation (a capacity/topology proxy) reaches **interior Spearman ρ = 0.721**, while the AC flow solved on synthetic loads correlates at **ρ ≈ 0.46 (interior) / 0.60 (trunk)** (details in [Highlights](#highlights--ハイライト)).

OSM から抽出した全国送電網（電圧クラス別色分け）。衛星画像との位置照合で実在インフラ上に乗ることを確認（鹿島・阿南FC・嶺南）。東京電力の線路別潮流と突合せ検証。回廊使用率の順位相関（容量・トポロジの代理指標）は **内部 Spearman ρ = 0.721**、合成負荷で解いた AC 潮流の相関は **ρ ≈ 0.46（内部）/ 0.60（基幹）**（詳細は下記 Highlights）。

<p align="center">
  <img src="https://raw.githubusercontent.com/lutelute/All-Japan-Grid/main/docs/assets/figs/fig_national_all.png" alt="National transmission topology" width="100%">
</p>
<p align="center">
  <img src="https://raw.githubusercontent.com/lutelute/All-Japan-Grid/main/docs/assets/figs/fig_satellite_validation.png" alt="Satellite validation (Kashima / Anan FC / Reinan)" width="100%">
</p>

**24-hour power flow.** The UC dispatch solved on the reconstructed grid, animated hour by hour — line width/shade = |P|, generation bubbles, FC / Kita-Hon interconnector transfers, with the west island shown in DC (honest labelling) and the intervention-registry caveat on every frame. Reproduce with `scripts/animate_powerflow_gif.py`.

24時間の潮流。再構築した系統上で解いた UC ディスパッチを時間ごとにアニメーション表示（線幅・濃淡 = |P|、発電バブル、FC・北本連系の融通、西側は DC 表示で正直にラベル、各フレームに介入台帳の注記）。`scripts/animate_powerflow_gif.py` で再現できます。

<p align="center">
  <img src="https://raw.githubusercontent.com/lutelute/All-Japan-Grid/main/docs/assets/gif/national_pf_24h.gif" alt="24-hour national power-flow animation" width="72%">
</p>

> Detailed methodology figures (validation ρ progression, recall tiers, regional networks, Ybus, unit commitment, transient stability) live in the manuscript under [`papers/`](../papers/).
> 詳細な方法論の図（検証ρの推移・recall・地域別ネットワーク・Ybus・UC・過渡安定）は [`papers/`](../papers/) の論文に収録。

---


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
- Full specification: **[docs/CIM_MAPPING.md](CIM_MAPPING.md)**

**Level 2 — solvable power-flow case (EQ/TP/SSH/SV/GL):** `scripts/export_cim_level2.py`
exports the *connected, solved* network with shared `ConnectivityNode`s,
`TopologicalNode`s, `PowerTransformer`s, `EnergyConsumer` loads, PV
`SynchronousMachine`s and a slack `ExternalNetworkInjection`. The round-trip
through pandapower `cim2pp` is **electrically identical** to the solved
network (parallel circuits, switching states and km lengths preserved;
regression-tested) and **`runpp` converges in all 10 regions** (v1.4.0
assets: 6 natively, 4 as x0.8 balanced demand-scaled cases — see
[docs/CIM_MAPPING.md](CIM_MAPPING.md); the in-repo model itself now
solves all 10 regions natively, see the figure below).

**Level 2 — 求解可能な潮流ケース:** `scripts/export_cim_level2.py` が接続済み・
求解済みネットワークを EQ/TP/SSH/SV/GL で出力します。エクスポートは並列回線・開閉状態・
km長を保持し、pandapower `cim2pp` での往復後も**元のネットワークと電気的に同一**
（回帰テスト済み）。**全10地域で潮流が収束**します（v1.4.0資産: 6地域はそのまま、
4地域は x0.8 の需給整合済みケース。リポジトリ内モデル自体は下図のとおり全10地域が無補正収束）。

<p align="center">
  <img src="https://raw.githubusercontent.com/lutelute/All-Japan-Grid/main/docs/assets/figs/fig_cim_national_pf.png" alt="CIM/CGMES Level 2 national power-flow" width="62%">
</p>

> **14,647 buses across all 10 regions, every region solved natively in AC —
> no demand scaling** (since 2026-06: multi-voltage substations, generator
> Q-limits, voltage propagation, frequency-aware slice membership and boundary
> imports retired the former kansai ×0.4 expedient). Bus colour = AC-solved
> voltage (pu). Parameters remain synthetic per-class typicals, so this is a
> topological/electrical consistency result, not an operational study.
> Regenerate with `python scripts/gen_cim_national_pf.py`. /
> 全10地域 14,647 母線を AC 電圧(pu)で色分け。**全地域が需要スケール無しで収束**
> （2026-06 の累積改善で旧 kansai ×0.4 便宜を撤廃）。パラメータは合成典型値のため、
> 運用値ではなく整合性の結果。

Both levels ship as zipped [GitHub Release v1.3.0](https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.3.0) assets
(`all_japan_grid_cim_L1.zip` ≈31 MB, `all_japan_grid_cim_L2.zip` ≈13 MB),
regenerable via the two scripts above.

**Import it in ~1 line / 1行で取り込み:** load any region into pandapower (CGMES or
MATPOWER), with PyPSA / MATLAB / PSS-E recipes, in **[docs/INTEROP.md](INTEROP.md)** —
runnable demo [`examples/import_quickstart.py`](../examples/import_quickstart.py).

### Data Source / データソース

All data is extracted from [OpenStreetMap](https://www.openstreetmap.org/) using the Overpass API.
全データは Overpass API を用いて [OpenStreetMap](https://www.openstreetmap.org/) から抽出しています。

- `power=substation` — Substations, switching stations / 変電所、開閉所
- `power=line` / `power=cable` — Transmission lines / 送電線
- `power=plant` — Power plants / 発電所

License / ライセンス: [ODbL](https://opendatacommons.org/licenses/odbl/) (OpenStreetMap)

**Authoritative overlay / 権威データの重ね合わせ:** power-plant identity, capacity and
operator are corroborated against **国土数値情報 発電所データ（P03）**（出典: 国土交通省
[国土数値情報](https://nlftp.mlit.go.jp/ksj/)）where an OSM plant matches a P03 record
within 2 km. Matched attributes are tagged `source=p03_db` with a `_p03_distance_km`
provenance and kept distinct from synthetic values. As of v1.3.x this corroborates
**16.2 % of plants** — see **[docs/COVERAGE.md](COVERAGE.md)** for the full
validated-vs-synthetic snapshot, or run `ajgrid coverage` for the live figure. The raw P03 GML is
**not redistributed** here — fetch it from the source above; only the derived,
attributed overlay lives in the DB.

**Independent topology cross-check / 独立トポロジ突合:** connectivity is cross-checked
against **[open-keitouzu](https://github.com/ibarapascal/open-keitouzu)** — a logical
topology of the trunk + 154 kV grid extracted from the ten utilities' official system
diagram PDFs (CC BY 4.0). Its crosswalk maps 657 stations directly onto this dataset's
node IDs (641 kept after our geographic adjudication of same-name mismatches);
88.1 % of mappable diagram edges are reproduced by our built model, and the divergent
remainder (92 edges, 30 in a disconnected component) is kept as a human-review
adjudication queue with links to the original diagrams — see `scripts/keitouzu/` and
`docs/reports/keitouzu_*.md`. Many thanks to the open-keitouzu author for publishing
this dataset **with an AGJ crosswalk included**.

**独立トポロジ突合:** 接続関係は **[open-keitouzu](https://github.com/ibarapascal/open-keitouzu)**
（十社の公式系統図PDFから抽出された基幹＋154kV の論理トポロジ、CC BY 4.0）と突合しています。
先方の crosswalk は本データセットのノードIDへの対応657件を同梱しており（同名異地の
誤マッチを地理裁定で除外し641件を採用）、突合可能な系統図辺の 88.1% が本モデルで再現、
残る食い違い92本（うち断絶30本）は原図リンク付きの人間裁定キューとして保持しています
（`scripts/keitouzu/`・`docs/reports/keitouzu_*.md`）。**AGJ への crosswalk を
同梱した形で公開してくださった** open-keitouzu 作者に感謝します。

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

See [WHITEPAPER.md](../WHITEPAPER.md) Section 4 for detailed methodology.
詳細な方法論は [WHITEPAPER.md](../WHITEPAPER.md) セクション4を参照。

> **Note / 注意:** Pages上のポップアップ表示には2系統のデータが使われます:
> 1. **地図レイヤー用** (`subs_*.geojson`, `lines_*.geojson`, `plants_*.geojson`) — `build_static_site.py` が `data/` から生成。`_display_name` で表示。
> 2. **詳細ポップアップ用** (`substations.geojson`, `generators.geojson`) — 各 export スクリプトが生成。座標マッチングで紐付け。
>
> enrichment後は**両方を再生成**しないと「Unnamed」が残ります:
> ```bash
> python scripts/export_substations_geojson.py   # 詳細ポップアップ用
> python scripts/build_static_site.py            # 地図レイヤー用
> ```


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
7. **AC power flow on OSM topology is a consistency tool, not an operational study / OSMトポロジの交流潮流は整合性検証の道具であり運用解析ではない** — With synthetic per-class impedances, CF-based dispatch and allocated demand, the solved flows now rank-correlate with utility measurements (interior Spearman ρ≈0.46 vs TEPCO across 419 corridors incl. the 66 kV layer, 2026-06-11; trunk-only ρ≈0.60) — useful for topology/consistency work and teaching, but absolute MW/voltage values are NOT operational results until authoritative parameters (Pillar 3) replace the typicals.

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

### 66 kV Programme — Verdict & Ceiling / 66kV級プログラムの到達点と天井（2026-06-11）

A measured campaign (ledger ㉛–㊺, `docs/PLAN_66KV.md`) pushed the model to solve **meaningfully down to 66 kV** and instrumented it against TEPCO's per-line disclosure. Where it landed, honestly:

| Layer / 層 | Attachment recall / 接続再現 | Flow rank-corr ρ / 流れ順位相関 | Gate / 目標 |
|---|---|---|---|
| Trunk (275 kV+) | 60.8% (n=286) | **0.60** (n=74) | — |
| 154 kV | 61.3% (n=137) | 0.11 (n=36, n.s.) | 0.40 — **not reached / 未達** |
| 66 kV | 53.1% (n=634) | **0.14** (n=307, p=0.017) | 0.30 — **not reached / 未達** |
| All interior / 全体 | 56.3% (n=1,057) | **0.46** (p≈1e-23) | 0.50 — not reached / 未達 |

**What works / 達成**: full-model AC converges in all 10 regions with the 66 kV layer in; a measured demand map (1,222 substations / 19 GW from disclosure busbar columns) and per-corridor flow statistics live in the DB (`measured_bus_loads` / `measured_line_stats`, `scripts/db/calibrate.py`) and recalibrate with one command; the validation instruments (3-layer ρ, banded attachment recall with graph-adjacency tier) ship in the standard sweep.

**Why the gates were not reached — a data-bound ceiling, each point evidenced in `docs/reports/IMPROVEMENT_LOG.md` / 未達の理由は手法でなくデータの天井**:

1. **OSM lacks the urban underground network** — 20 of 65 pure-154 kV corridors (central-Tokyo cables) are unmapped, capping the 154 kV instrument at n≈36–45 (ledger ㉝). / 都心地中ケーブル網がOSM未収載
2. **A corridor's flow aggregates several downstream yards** — the line/busbar metering points are linkable (44% of 66 kV corridors connect to a measured destination yard by the eponym rule, 塚田線→塚田; ledger ㊼ correcting ㊲'s overstated 'disjoint yards'), but the corridor typically carries ~2.6× its destination's own demand, so single-yard demand knowledge orders flows only weakly (truth-side ρ≈0.25). / 回廊流量は複数下流ヤードの合算（行先1件の需要では順序づけ困難）
3. **Normally-open switch states are not public** — the 66 kV mesh is operated radially; an impedance-MST proxy measurably did not help (ledger ㊷). / 常開点非公開（プロキシ実験は無効果と実証）

Sub-transmission flows where demand WAS measured reach ρ≈0.19 (vs 0.11 without) — demand knowledge helps, but the structural ceiling sits below the gates until the data above exists (ledger ㊵).

**Regional expansion / 他地域への展開**: the per-line flow validation is Tokyo-only (TEPCO is the only utility publishing per-line hourly series found so far). East-Japan regions (Hokkaido/Tohoku) carry 95–98% voltage-tagged 66 kV layers and are structurally ready; Chubu/Kansai/Kyushu's 66 kV layers are heavily fragmented (largest-component cover 12–17%, ledger ㊶) and need connectivity curation before sub-transmission flows can mean anything there. Attachment-recall validation generalises wherever a utility publishes line names; flow-ρ validation needs per-line series.

## What This Data IS Good For / 本データの活用法

- **Visualization / 可視化**: Interactive maps of Japan's transmission infrastructure by voltage class and region / 電圧階級・地域別の送電インフラ インタラクティブマップ
- **Topology research / トポロジ研究**: Graph-theoretic analysis of network connectivity, redundancy, vulnerability / ネットワーク接続性・冗長性・脆弱性のグラフ理論的分析
- **Geographic reference / 地理的参照**: Substation locations and transmission corridors for spatial analysis / 空間分析のための変電所位置・送電回廊
- **Starting point for synthetic models / 合成モデルの出発点**: Geographic skeleton to be enriched with electrical parameters from other sources / 他ソースの電気パラメータで補完可能な地理的骨格
- **Education / 教育**: Understanding the structure of Japan's 10 regional grids and the 50/60 Hz boundary / 日本の10地域系統と50/60Hz境界の構造理解

## Analysis Tools / 解析ツール

`src/` の潮流・UC・動態のコードは、生の OSM トポロジではなく**正典 built モデル**（`docs/data/built/`）の上で動きます。
線路定数・需要・発電機諸元の多くは合成値で、置いた仮定はすべて [介入台帳](MODEL_INTERVENTIONS.md) に
根拠・帳簿・無効化の方法つきで登録しています。結果は整合性の確認とスクリーニングのためのもので、
接続可否・運用可否・安定度の判定には使えません。

The solvers in `src/` run on the **canonical built model**, not on raw OSM topology. Most line constants, loads and
machine data are synthetic; every assumption is registered in the [intervention registry](MODEL_INTERVENTIONS.md)
with its evidence, its ledger and a switch to turn it off. Results are for consistency checks and screening —
not for connection, operation or stability studies.

### Local Server / ローカルサーバー

```bash
pip install -r requirements.txt
PYTHONPATH=. uvicorn src.server.app:app --host 127.0.0.1 --port 8088
open http://localhost:8088          # / = ダッシュボード, /editor = 接続エディタ, /tools = ツール実行
```

### Included Tools / 収録ツール

| Module / モジュール | Purpose / 目的 | Status / 状態 |
|--------|---------|--------|
| `src/server/` | FastAPI web server, interactive map / FastAPI ウェブサーバー、インタラクティブマップ | Works / 動作可 |
| `src/powerflow/` | DC/AC power flow via pandapower / pandapower による DC/AC 潮流計算 | Requires electrical parameters / 電気パラメータが必要 |
| `src/ac_powerflow/` | Advanced AC methods / 高度な AC 手法 | Requires electrical parameters / 電気パラメータが必要 |
| `src/uc/` | Unit Commitment (MILP, PuLP + HiGHS) with inter-regional transmission constraints / 地域間連系線制約付き UC ソルバ | Verified: 646 generators × 24h × 9 interconnections → Optimal in ~38s / 実証済み |
| `src/converter/` | pandapower / MATPOWER export / エクスポート | Works / 動作可 |

### Screening CLIs / スクリーニング解析 CLI *(2026-09-02)*

All run on the canonical built model (`docs/data/built/all.json`; every modelling assumption is registered in
[`docs/MODEL_INTERVENTIONS.md`](MODEL_INTERVENTIONS.md)). **Screening only** — not connection, operation or
stability studies; synthetic impedances and typical machine constants throughout.
正典 built モデル上のスクリーニングです（仮定はすべて介入台帳に登録）。接続可否・運用可否・安定度の判定ではありません。

- **N-1 line-outage screening / N-1 全枝スクリーニング** —
  `PYTHONPATH=. python3 scripts/sensitivity/n1_screening.py --islands east west --ac-verify 5`
  LODF evaluates every single-circuit outage at once (west 6,681 branches in ~2 s); bridges are booked separately
  with the islanded load; only real branches (OSM geometry, disclosed connections, nameplate transformers) rank in the
  main table, outages whose worst branch carries a synthetic rating are disclosed apart; the top outages are re-solved
  with the production AC solver. → `docs/reports/n1_screening_<date>.md`
- **IBR hosting capacity by short-circuit ratio / 系統強度（SCR）による IBR 連系可能量** —
  `PYTHONPATH=. python3 scripts/sensitivity/ibr_hosting_scr.py --islands west --scr-min 3`
  Thevenin short-circuit MVA at every bus (sparse LU; machine xd″ from `src/dynamics/machine_agg`), SCR = S_sc/P_ibr,
  P_max = S_sc/SCR_min − existing IBR, cross-checked against pandapower `calc_sc` (exact match); combined with the
  thermal PTDF hosting capacity to show which limit binds. → `docs/reports/ibr_hosting_scr_<date>.md`
- **Multi-machine swing at the AC operating point / 多機動揺モデルの AC 運転点化** —
  `PYTHONPATH=. python3 scripts/gen_swing_modes.py --solve-west net.pkl` then `--ac-op west --net-pickle net.pkl`
  Classical machines initialised from the converged AC solution (E∠δ, equilibrium Pe = Pm to machine precision),
  electromechanical modes with participation factors, N-1 generator disconnection transients.
  → `docs/reports/swing_modes_west_ac_<date>.md`
- **Line-capacity calibration / 線路容量の運用容量較正** *(opt-in)* — `--cap-calib` on the power-flow driver, `scripts/sensitivity/n1_screening.py` and `hosting_capacity.py`: multiplies each line rating by the published operating-limit ratio for its area and voltage class (`config/line_capacity_calibration.yaml`; ratios only, no redistributed capacity values). Off by default — 154 kV agrees across utilities (0.679 / 0.678) but 500 kV spans 0.37–0.95. → `docs/reports/line_capacity_calibration_<date>.md`

## Future Work — Complementary Data Sources / 今後の展望 — 補完データソース

> **📐 戦略計画 / Strategic plan:** All-Japan-Grid を日本の電力業界の
> 継続的資産へ育てる5本柱の計画は **[docs/VISION.md](VISION.md)** を参照。

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
| **open-keitouzu** (十社系統図の論理トポロジ) | Official-diagram connectivity cross-check — **integrated**, see Data Source / 公式系統図の接続関係との突合 — **統合済み**（Data Source 節参照） | [github.com/ibarapascal/open-keitouzu](https://github.com/ibarapascal/open-keitouzu) |

Contributions and collaborations welcome. If you have access to additional data sources or are working on Japanese grid modeling, please open an issue.

コントリビューションや共同研究を歓迎します。追加のデータソースをお持ちの方、日本の系統モデリングに取り組んでいる方は、ぜひ Issue を作成してください。
