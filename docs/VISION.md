# Vision — All-Japan-Grid as a National Power-System Asset

**この文書の目的 / Purpose.** All-Japan-Grid を「OSM から作った地図」から「日本の電力業界が
継続的に使える資産（an open, living, standards-based reference model of Japan's grid）」へ
育てるための戦略計画。技術フェーズ（P1–P7）は [ROADMAP.md](ROADMAP.md)、データ層の機械化は
[DB_ARCHITECTURE.md](DB_ARCHITECTURE.md)、CIM/CGMES 規格化は [CIM_MAPPING.md](CIM_MAPPING.md) を
参照。本書はそれらを束ねる「なぜ・誰のために・どこへ」を定義する。

---

## 1. なぜ資産になりうるか / Why this can become an asset

日本には、**公開・再現可能・規格準拠の全国系統モデルが事実上存在しない**。OCCTO・各
一般送配電事業者は系統情報を持つが、機械可読な統合モデルとして外部に開かれてはいない。
研究者・スタートアップ・教育機関・規制当局・海外の系統解析ツールが「日本の系統」を一つの
データセットとして掴む手段がない、という構造的な空白がある。

All-Japan-Grid は既にこの空白の**骨格**を埋めている:

- **全国トポロジ** — OSM 由来、10 地域・40,077 線・6,962 変電所・19,138 発電所、頂点グラフ
  スナップで実ルート連結（断片化を大幅改善）。
- **国際規格での交換形式** — IEC 61970 CIM / CGMES 2.4.15（EQ/TP/SSH/SV/GL）。PowerFactory・
  pandapower `cim2pp` 等と相互運用。Level 2 は 8/10 地域が native に潮流収束。
- **再現性** — 決定的 mRID、バージョン付き Release、CITATION、データ辞書/カタログ。
- **機械的更新の土台** — SQLite の R/C/D 三層（[DB_ARCHITECTURE.md](DB_ARCHITECTURE.md)）。
  raw OSM とキュレーションを分離し、再取得しても人手の補正を失わない設計。

## 2. 正直な現在地 / Honest current state

**今は「研究・教育・可視化グレード」であり、運用・計画グレードではない。** この線引きを
曖昧にしないことが、業界の信頼を得る前提。

| 揃っているもの | 本質的に欠けているもの（資産化の核心課題） |
|---|---|
| 地理トポロジ・接続性 | **権威ある電気パラメータ**（R/X/B、変圧器、母線接続の実態） |
| 規格準拠の交換形式(CIM) | **実需要・発電機諸元**（出力範囲・コスト・ランプ） |
| 再現性・バージョニング | **第三者検証**（OCCTO/事業者公開値との突合せ） |
| 機械更新の土台(DB) | **データの権威性**（OSM の `operator` タグ等は無保証） |

現状の電気値は電圧クラス別の標準値・kV² 近似・文献値。相対傾向や merit order は有意だが、
個別設備の運用可否判断には使えない。**この限界を明示し続けることが、誇張された「日本系統
モデル」が氾濫しないための公共的価値でもある。**

## 3. 5つの柱 / Five pillars

### Pillar 1 — Living dataset（機械的に更新され続けるデータ）
OSM は日々変わる。資産であるためには「一度作った静的データ」ではなく、**fetch → ingest →
enrich(DB) → export** が機械的に回り、人手のキュレーションが再取得で消えない仕組みが要る。
DB 統一（R/C/D 層）はこのためのもの。→ **§5 近接タスク**で完成させる。

### Pillar 2 — Standards & interoperability（規格と相互運用）
CIM/CGMES を入口に、MATPOWER/.mat、pandapower、PSS/E、PyPSA への橋渡しを増やす。
「日本系統を自分のツールに 1 行で取り込める」状態が普及の条件。CGMES boundary set・
決定的 mRID は既に整備済み。次は CGMES の厳格検証（CIMverter 等）と PyPSA-Earth 連携。

### Pillar 3 — From topology to a validated electrical model（地図→検証済み電気モデル）★最難関・最高価値

> **連携が律速。具体的な事業者・OCCTO 連携の実行設計は [ENGAGEMENT.md](ENGAGEMENT.md) を参照。**
資産の本丸。合成パラメータを**権威データで置換・検証**する:
- 国土数値情報 P03（発電所）、OCCTO 供給計画・連系線容量・エリア需要、JEPX エリアプライス。
- 文献値（Glover/Sarma 等）から voltage-class 別 R/X/B の**不確かさ付き**推定へ。
- 公開された個別実測値が得られた区間を「検証済み」とタグ付けし、合成区間と峻別する
  （データ単位の `provenance` / `confidence`。DB の C 層がこれを担う）。
これは単独では完結せず、**事業者・OCCTO・研究機関との連携**が前提。本プロジェクトの役割は
「受け皿となる規格準拠の器」を用意し、権威データが入った瞬間に全国モデルへ統合できる
ようにしておくこと。

### Pillar 4 — Tooling & access（ツールとアクセス）
「データセット」から「ツール」へ:
- 統一 CLI（`ajgrid regions|solve|cim|db|map`）でデータ取得〜潮流〜CIM出力を一気通貫（✅ 実装済み）。
- 安定した Python API（`src/` を正本化済み＝Phase C で達成）。
- 取り込み 1 行のサンプル（pandapower CIM/MATPOWER は✅検証済み、PyPSA/MATLAB/PSS-E は文書化）
  ＝ [INTEROP.md](INTEROP.md) + [`examples/import_quickstart.py`](../examples/import_quickstart.py)。
- ライブ地図（GitHub Pages）＝意思決定者向けの入口。

### Pillar 5 — Governance, provenance, trust（統治・来歴・信頼）
業界資産の通貨は信頼。
- すべての属性に来歴（source / confidence / 取得日）。DB の `enrichments` が既に source 列を持つ。
- 明確なバージョニング・CITATION・免責（地図≠運用モデル の明示は継続）。
- コントリビューション経路（事業者・研究者が誤接続・実値を投稿 → `manual`/`external` source で
  DB に取り込み、再取得後も保持）。
- ライセンス整合（データ ODbL / コード MIT）。

## 4. 段階目標 / Milestones

| 段階 | 到達点 | 主な前提 |
|---|---|---|
| **M0（現在）** | 研究・教育グレードの公開トポロジ + CIM L1/L2 + DB 土台 | 達成済み（v1.3.0） |
| **M1** | **Living tool**: 機械更新が全エンリッチャで完結、統一 CLI、来歴完備 | サーバー実行（API/GML）。§5 |
| **M2** | **Validated patches**: P03/OCCTO 等で一部区間を検証済みタグ化、不確かさ付き電気値 | 外部データ取得・連携 |
| **M3** | **Interop reference**: PyPSA/PSS-E 連携、CGMES 厳格検証通過、引用される標準データセット | M1+M2 |
| **M4** | **Industry-grade collaboration**: 事業者/OCCTO との突合せで運用近接モデル | 業界連携・データ提供 |

M2 以降は技術だけでなく**データの権威性とパートナーシップ**が律速。だからこそ M0–M1 で
「権威データが入る器」を規格準拠・機械更新・来歴完備で完成させておくことが、本プロジェクトの
コントロール下にある最重要投資となる。

## 5. 近接タスク（Pillar 1 完成 = 機械更新の閉ループ）

DB 統一はあと少しで「全エンリッチャが DB に書く」状態になる。現状 2/6（endpoint 命名・audit）が
DB 化済み。残り（geocode×2・overpass・p03）は **live API / P03 GML が必要なため実行はサーバー
（pws-160core）だが、DB 書き込みのコード経路は確立パターンで整備できる**:
- 各エンリッチャのロジックを純粋関数に抽出 → DB 版アダプタが `enrichments` に書く（専用 source、
  `LEGACY_SOURCES` 外）→ 合成/モックテスト。実行は `scripts/db/enrich.py` をサーバーで。
- p03 は欠落した P03 GML パーサ（旧 `src/parser`）の再建を伴う＝Pillar 3 の入口でもある
  （P03 = 権威ある発電所データ）。
- 完成後、`data/*.geojson` を正式に **DB の派生生成物**に降格し、追跡正本を
  `data/db/enrichments.jsonl`（来歴付きキュレーション）+ raw スナップショットへ。

その先（Pillar 4）は統一 CLI と取り込みサンプル。地図とデータは既にあるので、**「器」を
完成させ、権威データを待つ**——これが日本の電力業界の資産へ至る、地に足のついた道筋。
