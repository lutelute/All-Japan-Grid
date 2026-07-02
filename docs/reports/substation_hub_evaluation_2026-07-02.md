# 評価: 「変電所=接続ハブ」前提でのプロジェクト現状評価

- 日付: 2026-07-02
- 評価実施: Claude Fable 5（オーナー指示による全体評価）
- オーナー前提（本評価の基準）: **「線は基本変電所に入る。変電所で電圧階級・タップ・回線・導体を接続する。なぜならそこから負荷に分配供給されるからである。」** OSMは点と線だけで接続を表現できておらず、明らかに接続されているものが構造的に接続されていない — これを系統として接続するようにDB化する。

---

## 0. 総評

この前提は新しい方針ではなく、**プロジェクト自身が 2026-06-14 に立てた GRIDSTITCH_PLAN（`docs/GRIDSTITCH_PLAN.md`）の3本柱そのもの**である（③「変電所の bus/bay/busbar + 1次2次を一級市民化」）。しかし実装は P1（busbar/bay の吸収）で止まり、**本丸の P2「変電所内部データモデルの永続化」以降が未実装**のまま、直近1ヶ月は CIM 検証・データ論文準備に注力していた。

現状を一言で言うと: **「変電所ハブ」の骨格（線→変電所束縛・電圧階級別バス・変圧器挿入・回線数）は build 時の計算として実装済みだが、それが構造（データ）として存在しない。** 接続は毎回のビルドで座標幾何から再推論され、「なぜ繋がるのか」はどこにも記録されない。タップ・導体・負荷分配・CIMの物理変電所は欠落している。

---

## 1. 前提4要素+接続構造の現状評価

| 要素 | データ源（実測充足率） | モデルでの扱い | DB化 | 評価 |
|---|---|---|---|---|
| **電圧階級** | 線 voltage 85.1% (34,093/40,077) / 変電所 56.7% (3,944/6,962) | 変電所を階級別バス `{sid}@500/@275/…` に分解（`multi_voltage=True` 既定）+ 回廊伝播補完（`prop`/`prop2` provenance） | built JSON に kv として出るのみ。**VoltageLevel は非永続** | ◑ 骨格あり。変電所側 43.3% が電圧不明（built で kv=0 変電所 780） |
| **タップ** | OSM `transformer` タグ **0%** (0/6,962) | **TapChanger はコード・CIM出力とも皆無**。変圧器は電圧階級ペアの合成典型値（`_TRAFO_PARAMS`） | `substation_attributes`（tap_ratio/tap_min/tap_max/tap_step_percent）が**スキーマだけ存在し 0 行** | ✗ 完全欠落。ただし受け皿スキーマは 2026-03 から用意済み |
| **回線** | `circuits` 58.7% + `cables` 67.4% | `_parse_circuits`: circuits タグ→cables/3→幾何1 の優先順で `par` 化。枝マージで加算。pandapower `parallel`・CIM `R/par`・MATPOWER・変圧器バンク数まで**一気通貫** | `edges.par`（数値） | ◯ 4要素中で最も健全。ただし「回線」は本数の数値であり、1号線/2号線という**回線オブジェクトではない**（`ref` タグ 11.7% は未活用） |
| **導体** | `wires` 12.6% (5,045) | パース済み（single/double/quad→`n_bundle`）だが **ampacity スケール（0.5–2.5x）のみ**。R/X/B は電圧階級固定テーブル `config/line_types.yaml`（導体名は記述用） | line_types.yaml（階級9値） | ◑ 意図的限定（ledger 66）。導体からの電気定数計算は不存在 |
| **負荷分配** | 実測負荷 `measured_bus_loads` **1,222 バス分が DB に存在するが未接続** | OCCTO地域ピーク×0.85 を電圧クラス重み（66kV=0.50 … 500kV=0.05）で**送電バスに直付け按分**。配電用変電所の二次側・フィーダは不存在 | measured_bus_loads（未使用） | ✗ 「変電所から負荷へ分配」の構造なし。合成按分のみ |

## 2. 既にできていること（前提と合致する資産）

1. **線→変電所の束縛はポリゴン内包が最優先**（`src/powerflow/snapped_topology.py:610-643` `_bind_vertex`）: shapely `covers` → 境界 0.15/0.6km → フォールバック半径 0.4km。「線は変電所に入る」の幾何面は実装済み。旧「50km最近傍で線を捨てる」は撤廃済み。
2. **変電所は電圧階級ごとにバス分解**: 実測 hokuriku で物理変電所約260 → 353バス（2バス59・3バス14・4バス2）。無タグは `@u` で最高位にぶら下げ。
3. **電圧階級間は変圧器が唯一のジョイント**: `xfmr_stubs`（50m スタブ）→ `insert_transformers`（pandapower 正式 trafo、MATPOWER は tap 比付き branch、CIM は PowerTransformer+End×2）。
4. **電圧の回廊伝播**（オーナー方針「無タグでも接続先の既知電圧から辿って埋める」）: `snapped_topology.py:764-809` Pass A.5 実装済み・反復20回・曖昧なら不明のまま・provenance 付き。
5. **端点補完の証拠ベース戦略群**: mid-span tap / tip joint / 線名根拠束縛（「X〜Y線」5km）/ lead-in 1.5km / T-tap。全て provenance 付き。
6. **DB 3層（R/C/D）は稼働中**: enrichments 243,093行・機械的更新ループ（fetch→ingest→enrich→export）は閉じている。**受け皿はある**。

## 3. 核心ギャップ（前提と乖離する7点）

1. **変電所内部構造（node-breaker）が存在しない**: `BusbarSection`/`Bay`/`Terminal` はモデル・DB・CIM のどこにも無い（grep 全滅）。busbar/bay 線は「保持→ポリゴン束縛で自己ループ化→消滅」= 暗黙に畳まれ、構造として残らない。`src/model/substation.py:145` は「Each substation maps to a single bus」のまま。
2. **接続が「構造」でなく「毎回の幾何再計算」**: どの線がどの変電所のどの母線に、どの根拠（内包/lead-in/線名/stitch/tie）で繋がったかは build 中の中間値であり、**捨てられる**。連結性の単一権威 `connectivity.py` に至っては座標5桁キー（**電圧無視**）の縮退で「同一地点=接続」。接続の機序が最低5種（座標一致/kv無視縮退/越境stitch 110m/OCCTOタイ名寄せ/端点スナップ）混在し、どれもDBレコードでない。
3. **タップ完全欠落**（表のとおり。スキーマ枠 0 行）。
4. **変圧器が全て合成**: OSM transformer タグ 0% → 実在の変圧器（台数・容量・結線・タップ範囲）は一切データ化されていない。`VISION.md:35` 自身が「変圧器・母線接続の実態」を核心的欠落の筆頭に明記。
5. **CIM L2 に物理変電所が存在しない**: **Substation = 地域全体で1個**（"okinawa grid"）、VoltageLevel はバス毎の抽象。okinawa 実測: 91バスに Substation 1・Bay 0・BusbarSection 0・TapChanger 0。「変電所ハブ」構造が出荷物に全く出ていない。
6. **負荷が送電バス直付けの合成按分**（実測1,222バスは DB で眠っている）。
7. **地域境界の変電所二重記録**: 同一物理変電所が2地域データに別実体で存在（下北・東通村・吉岡ほか、同名同座標ペア多数）。越境 stitch で「繋がる」が実体は2つ = 物理サイトの同一性がモデル化されていない（GRIDSTITCH_PLAN §9 の懸念の現物）。

## 4. 「明らかに接続されているのに構造的に接続されていない」の内訳（重要な文脈）

built 全国は連結成分 1,096・島ノード 2,161。ただし島分類診断（2026-06-24、全10地域）の内訳は:

| 分類 | 件数 | 意味 | 対処 |
|---|---|---|---|
| osm_gap | 451 | OSM に連系線が描かれていない | 出典付き充填・OSM還元（幾何操作では救えない） |
| isolated | 309 | 線が1本も付かない孤立変電所 | 同上 |
| railway | 74 | 鉄道・別事業者網 | **繋がない**（正当な分離） |
| reachable | 17 | 線は届くのに未束縛 | 束縛ロジックで救える残り |
| phantom | 0 | 幽霊ノード | 解消済み |

つまり**幾何・束縛のバグはほぼ潰し切っており（reachable 全国17）、非連結の主因は OSM データ自体の欠落（760件）**。「接続の修正」を幾何アルゴリズムでさらに攻めても伸び代は小さい。攻めるべきは (a) 接続を第一級データとして DB 化し、人間の編集・外部出典・OSM還元で欠落を埋められる器を完成させること（GridStitch 路線）、(b) 変電所内部の構造化。本評価の修正計画はこの認識に立つ。

## 5. 修正ロードマップ（提案）

GRIDSTITCH_PLAN P2 を核に再起動し、オーナー前提の新規要素（タップ・導体・負荷分配）を追加する。

### Phase A — 変電所の実体化（P2 再起動・構造の本丸）
- `SubstationSite`（物理変電所。**地域重複を canonical ID で同一実体化**）→ `VoltageLevel`（sid@kv）→ `BusbarSection` / `Bay` / `Terminal` の dataclass + DB テーブル（`src/db` 3層の C 層に接続）
- **接続レコードの永続化**: 現在 build 時に計算して捨てている束縛（どの線端がどの変電所のどの電圧階級に、どの根拠で: polygon/leadin/name/stitch/tie + provenance + confidence）を D 層でなく C 層の第一級データに昇格。build は「幾何からの再推論」から「接続レコードの適用+差分検出」へ — **「機械的に更新できる仕組み」（2026-06-08 確定方針）の接続版**
- CIM L2 の Substation を物理変電所ベースに是正（地域1個 → 実変電所毎、VoltageLevel を変電所内階級に）
- 検証: 既存の島数/ρ/AC 非悪化ゲート（committed スコアカード不可触・新日付JSONのみ）

### Phase B — 変電所内の電気設備（タップ・変圧器の実体化）
- `PowerTransformer` を第一級レコードに（現: 潮流時に合成）。台数・容量・HV/LV・**TapChanger**（substation_attributes の枠を実際に使う）
- データは出典必須ルール（capacity_provenance 方式）で充填: 電力各社の供給計画・OCCTO 設備計画等。無い値は合成典型値のまま `synthetic` provenance を明示（捏造禁止の徹底）
- CIM に RatioTapChanger を emit

### Phase C — 属性の出典付き充填（ROADMAP_ASSET Phase 1 と合流）
- 変電所電圧 untagged 43.3% の解消（= ROADMAP 1-D。関西154kV超CSV・OCCTO・P03 名寄せ）
- 回線のオブジェクト化（`ref` タグ・回線名の取り込み、1号線/2号線）
- 導体→電気定数: wires/conductor からの R/X 計算 or 出典付き実データ（line_types.yaml の典型値を provenance 付きで上書き可能に)

### Phase D — 負荷の分配構造
- 配電用変電所の二次側に負荷を接続する構造（EnergyConsumer を変電所 LV 側へ）
- `measured_bus_loads` 1,222 バスの正典潮流への接続（= ROADMAP Phase 3 前倒しの核）

**依存関係**: A が土台（B の変圧器・D の負荷は A の VoltageLevel に繋ぐ。C は独立に走れるが A のスキーマがあると格納先が定まる）。

### 進め方の推奨: 嶺南で実証 → 機械化
過去のオーナー方針「**まだ機械処理を急がず嶺南を手で正確化してから機械化**」（2026-06-15）に従い、Phase A のスキーマを全国一括で設計せず、**嶺南（bay/busbar 実データが最も濃い実証地）で1変電所の完全な内部構造（母線・ベイ・変圧器・タップ・回線・導体・負荷）を手で作り、スキーマを確定してから機械展開**するのが安全。SubScope（構造図）と接続編集エディタ（:8088）がそのまま検証器になる。

---

## 6. 本評価の根拠（調査方法）

並列調査エージェント3系統（接続モデル/電気属性/CIM・負荷）+ 実測集計。主要根拠:
- `src/powerflow/snapped_topology.py`（束縛・multi_voltage・伝播・circuits）
- `src/powerflow/transforms.py:24-42`（_TRAFO_PARAMS 合成典型値）・`connectivity.py`（kv 無視の座標縮退）
- `src/cim/level2.py:94-98,159-176`（Substation=地域1個）・`dist/cim_level2/okinawa_L2_EQ.xml` クラス頻度実測
- `src/powerflow/load_estimator.py:332-345,499-536`（負荷直付け按分）
- `data/*.geojson` 全国タグ充足実測（lines 40,077 / subs 6,962）・`data/grid.db`（substation_attributes 0行・enrichments 243,093行）
- `docs/reports/island_classify_*_2026-06-24.json` 全国集計・`docs/GRIDSTITCH_PLAN.md`・`docs/VISION.md`・`docs/ROADMAP_ASSET.md`
