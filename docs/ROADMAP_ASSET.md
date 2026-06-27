# All-Japan-Grid 資産化ロードマップ — 「出典付き全国送電網」という唯一無二の資産へ

策定 2026-06-25 / 根拠: 多ラウンド反復評価 + 3系統の事実調査(カバレッジ定量・国際ベンチマーク・器の拡張設計)
方針合意(オーナー): **「データセット正典 → 解析基盤」を段階的に / 最優先軸は「カバレッジ拡大」**

---

## 0. 要旨

カバレッジ拡大の最も効果的で機械化可能な正体は、**「線(幾何)を増やすこと」ではなく「全設備を"出典付き"で充填し、その出典を正典グラフ(`all.json`)と CGMES まで運ぶこと」**である。これにより**カバレッジ拡大と信頼性磐石化が同時に達成**され、AGJ は「OSM抽出 × 実測潮流突合 × CGMES出力 × 要素ごと出典」を全て備えた、**国際的に前例のない公開系統データセット**になる。

## 1. 戦略の核心 — なぜ「出典付き充填」なのか(調査で確定した事実)

| 当初の想定 | 調査で判明した事実 | 含意 |
|---|---|---|
| 66kV以下の線が足りない | データは既に66/77kV主体(線48.3%/変電所36.7%)。薄いのは**電圧"タグ"** — 変電所の**43.8%(3,049/6,962)がuntagged**(関西67%/中部62%) | 拡大すべきは線でなく**属性の充填** |
| 線の幾何を外部から増やせる | OSM独立の幾何源は**GSI `PwrTrnsmL`(optimal_bvmap-v1)一択**(実DL確認・再配布可)。データ天井①地中②回廊③常開点は**機械取得源が存在しない**(③は原理的に非公開) | 幾何拡大は限定的・天井は誠実に「埋めない」 |
| 発電所容量は揃っている | 使える容量は**6.7%(1,280/19,138)のみ**。九州・沖縄は全件プレースホルダ(-1) | 容量充填の余地が巨大 |
| 出典は容量45件だけが弱点 | **出典が正典グラフにも CGMES にも一切伝播していない**(`built_view.py`で無条件全喪失)。`Enrichment`テーブルに`source_url`列すら無い | **伝播の穴**こそ本丸 |

**国際比較の決定的事実**: PyPSA-Eur / SciGRID / GridKit / Xiong 2025 はいずれも CGMES 非対応・実測潮流突合なし。AGJ は中身で既に国際水準を超える部分があり、足りないのは "作法" のみ。

## 2. 北極星

> 日本全国送電網の、**全設備に検証可能な出典が付き**、**CGMES ネイティブで出力され**、**ワンコマンドで再生成でき**、Nature Scientific Data 級に引用される正典オープンデータセット — その上に、**実測負荷で検証された解析基盤**を載せる。

## 3. ロードマップ

### Phase 0 — 地雷除去(即日〜1週間 / 機械化度 ★★★)
*カバレッジを積む前に。放置すると「嘘の上に網羅」になる。モデルを変えない範囲に限定。*

- ρ見出しの正直化: `0.721`は「回廊使用率の順位相関(容量代理)」と明記し、実測潮流 `ρ≈0.46/0.60` を二段で併記
- `git gc --prune=now`: tmp_pack 残骸 8.35GiB を回収(履歴無損失)
- 依存 lock(uv.lock、数値コア固定)、CI の Python 版整合(宣言 vs 3.12)
- 変電所数"三分裂"の統一: **papers 散文8,164 のみ未統一**(CHANGELOG/DATA_CATALOG/README は 6,962 で是正済・実測で確認) → 正典 6,962。papers は別agent管轄=協調
- west AC「収束」の正直化: per-component slack 前提を成果物・白書・論文で明示
- テスト隔離: supplement の有無でテストが壊れない fixture/env(作業ツリーの赤を止める)
- 掃除: `.coverage` / 一時CSV を .gitignore、未追跡の島分類レポート10本をコミット、台帳を HEAD に追従

### Phase 1 — カバレッジ拡大の本体 = 出典付き充填 + provenance 伝播(数週間 / 機械化度 ★★☆)
*「人間にはできない」何万設備への網羅的出典付与。資産の本体。*

- **1-A 出典DBを全設備に一般化**: `capacity_provenance.py`(45件の手本)を汎用化、`Enrichment` に `source_url/quote/retrieved_at/collected_by` 列追加(migration v5)
- **1-B 伝播の穴を塞ぐ(最重要)**: `built_view.py` で出典透過、CIM `IdentifiedObject.description` に出典URL、export `--markers` 標準化 — 出典が `all.json`・CGMES まで届く
- **1-C 発電所容量の出典付き一括補完**: GEM Integrated Power Tracker(CC-BY) + 45件方式を機械拡張、九州/沖縄の全欠2,581件を解消
- **1-D 電圧タグ充填**: 既存ローカルの関西154kV超CSV・OCCTO・P03 を名寄せし untagged 43.8% を出典付きで削減
- **1-E GSI `PwrTrnsmL` 幾何取込**: dataspace に `gsi_bvmap` プロバイダ追加、OSM独立幾何でギャップを機械検出(「初の非OSM幾何検証」)
- **1-F okinawa supplement の正典採用判断**: 物理根拠ある補完(線118/発電所連系点7)を before/after 図つきで採用 → okinawa.json/CIM 再生成 → pin 更新

### Phase 2 — 正典化 = 引用される作法(Phase1と並行可 / 機械化度 ★★★)

- REUSE/SPDX + `LICENSES/` + **NOTICE**(OSM ODbL帰属 / 国土数値情報P03 / TEPCO / **WRI CC-BY**)
- **Zenodo DOI** 連携(concept + version DOI)、CITATION.cff にデータの ODbL 併記
- **ワンコマンド再生成**(Snakefile/Makefile、raw始点) + **CI 再現性ゲート**(regen→`git diff`ゼロ / CGMES 0 dangling / 全値に出典URL)
- **データ論文**: 本命 Nature Scientific Data(新規性を評価せず "first" 論争を回避)、負の結果(AI再接続失敗)は Data in Brief

### Phase 3 — 解析基盤 = 検証済みプラットフォーム(後段 / 機械化度 ★★☆)

- **合成負荷 → 実測負荷**: `measured_bus_loads` 1,222バスを正典潮流に接続、ρ を正直な土俵で測定
- MSM connector Phase 2(再エネCF、UC較正)
- MATPOWER 三重実装の集約(gencost 方針の矛盾解消)、PyPSA 相互変換の CI 検証

## 4. 品質ゲート(AIが機械的に保証し続ける = 一度作った正典が永久に劣化しない)

- 権威フィールドの全値に出典URL(欠落は CI で REJECT)
- `regen → git diff` ゼロ(再現性)
- CGMES 0 dangling(標準準拠)
- provenance 伝播テスト(出典が built / CIM に乗ることを golden test で保証)

## 5. 「人間にはできない」の体現

1. **網羅的出典付与**: 何万設備に WebFetch→`validate_record`→DB を反復で回し全値に URL+逐語引用
2. **多ソースクロスバリデーション**: OSM × GSI × P03 × 各社CSV を機械突合し矛盾を自動検出
3. **継続的再検証**: CI が「全値に出典・regen再現・CGMES整合・provenance伝播」を毎push機械チェック

## 6. 主張できる新規性(査読耐性・先行研究との差分)

- 「OSM抽出した公開系統を、事業者公表の実測潮流(per-line flows)と突合した、我々の知る限り初の事例」(スコープ限定・"to our knowledge")
- 「日本全国系統の CGMES ネイティブ公開データセット」(PyPSA-Eur/Earth/SciGRID/GridKit いずれも非対応)
- 要素ごと provenance + 統一DBからの機械的再生成

**主張してはいけない**: 「ρ=0.721 で実測検証」を見出しにすること(0.721は容量代理の順位相関、実測潮流は0.46/0.60)。「a first」断定。

---
*次の更新: Phase 0 着手後、IMPROVEMENT_LOG 台帳に各 before/after を登録する。*
