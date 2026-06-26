# All-Japan-Grid — データ論文 readiness ロードマップ / Data-paper readiness

作成 2026-06-27 / モデル claude-opus-4-8。`docs/reports/formal_review_2026-06-26.md`(審査)と `docs/reports/international_benchmark_2026-06-27.md`(国際比較)を**出版への具体的行動**に変換した capstone。本命投稿先 = **Nature Scientific Data**（新規性を評価せず "first" 論争を回避できる）。代替 = IEEE Data Descriptions / Data in Brief（負の結果も歓迎）。

---

## 0. 一言で

データ成果物の中身（出典・ライセンス・CGMES・配信）は投稿水準に近い（minor 寄り）が、**(a) 論文本文の数値自己矛盾、(b) 訂正容量の潮流未伝播、(c) DOI/再現DAG/OSM断面時刻の欠落、(d) 新規性の過剰主張**が査読ブロッカー。本ロードマップはそれを要件別に潰す。

## 1. Readiness スコアカード（Sci Data 要件 × AGJ 現状 × 行動）

| 要件 / Requirement | 現状 | 担当 | 行動 / TODO |
|---|---|---|---|
| **DOI 付きデータ寄託**（承認リポジトリ） | ❌ none（AGJ と KPG-193 のみ DOI 無し） | オーナー | Zenodo に GitHub Release 連携 → concept + version DOI、CITATION.cff に `doi:` 追加 |
| 機械可読メタデータ | △ CITATION.cff / DATA_DICTIONARY / NOTICE | AI | `datapackage.json`(Frictionless, OPSD流) を追加、**OSM 断面時刻(osm3s.timestamp)を配布物に埋込** |
| **Data Records** 節 | △ DATA_CATALOG / DATA_DICTIONARY | AI | ファイル単位の records を Sci Data 形式に整形（geojson 各層・CGMES・MATPOWER・容量出典 jsonl） |
| **Technical Validation** 節 | △ scorecard 実在（TEPCO ρ・関西97%・CGMES 10/10） | AI | 3 検証を 1 節に集約し**限界を同じ文で開示**（ρ=代理指標／実測AC 0.46-0.60／関西は母数182中38本・クラス限定／容量は表示専用） |
| Usage Notes（再利用指針） | △ README | AI | 再利用手順 + **ODbL share-alike 義務** + 帰属（NOTICE 参照）を明記 |
| データライセンス | ✅ ODbL + NOTICE + CITATION ODbL 併記 | — | 完了（本セッション） |
| 再現性 | △ uv.lock / regenerate_all | AI | **raw OSM→成果物のワンコマンド DAG**(Snakemake/Makefile) + lock + バンドル固定。CI に regen→`git diff` ゲート |
| 新規性の言い回し | △ README はヘッジ済 / 論文は未 | papers(別agent) | 国際比較の **scoped novelty 文**へ統一、"first openly available" を撤去（H1 と同時） |

## 2. 査読ブロッカー（審査 + 国際比較から）と解消

| # | ブロッカー | 解消 | 状態 |
|---|---|---|---|
| B1 | `ieee-openaccess.tex` 変電所数 散文8,164 vs 自Table/データ6,962（UC機数757 vs 646） | 単一正典値 **6,962** に統一 | papers 別agent管轄＝**協調必須** |
| B2 | 訂正容量が潮流に未伝播（蘇我1,440MW・大間 幻発電所が検証ρに残存） | `capacity_mw` へ昇格 or ビルダで `_sourced` 優先、もしくは**「表示専用・潮流は元値」を論文/README/辞書で明示** | **辞書で開示済**(DATA_DICTIONARY §3.4) / 潮流伝播は未 |
| B3 | "first" 未ヘッジ・過剰主張 | 国際比較の **scoped novelty 文**を採用（組合せの初出に限定） | 素材供給済（benchmark） |
| B4 | ρ=0.721 を潮流検証として提示／PyPSA-Eur ρ=0.96-0.998 と横並べ | 代理指標と明記し**物理量が異なる(incommensurable)注記**、実測AC 0.46-0.60 を併記 | README 済 / 論文は未 |
| B5 | DOI/再現DAG/OSM断面時刻 欠落 | §1 の通り | 一部開示（NOTICE に断面ギャップ明記） |

## 3. 投稿に使える scoped novelty 文（benchmark 由来・そのまま流用可）

> OSM から抽出し要素ごと出典を付した**日本の全国(全10広域・50/60Hz)送電網**を、**CGMES ネイティブ(L1+L2, 10/10 VALID・0 dangling・cim2pp 往復)**を含む標準交換形式(CGMES+MATPOWER+pandapower+GeoJSON)で相互運用可能に公開し、**事業者公表の実測線路別潮流(TEPCO)に対する順位相関検証**(interior ρ=0.721=容量/トポロジ代理、実測AC ρ≈0.46-0.60)と電圧クラス突合(関西TD 37/38)まで併せ持つ、我々の知る限り初の公開データセットである。

**言ってはいけない**: 「電力一般で OSM 抽出が新規」「実測突合自体が新規」「ρ=0.721 が潮流一致」。

## 4. 優先順路（2 週間スケール）

1. **【即・AI】** Technical Validation 集約 + Usage Notes + `datapackage.json` + OSM 断面時刻埋込（B5/メタ要件を一掃）。
2. **【AI・要判断】** B2 潮流伝播（`capacity_mw` 昇格 or `_sourced` 優先）→ 幻発電所除去 → 検証ρ再計測。または「表示専用」を最終決定として論文に固定。
3. **【協調】** papers と B1/B3/B4 を同期（数値統一・novelty 文・ρ 注記）。**別agentが papers 作業中につき同時編集を避ける**。
4. **【オーナー】** Zenodo DOI + CITATION `doi:`。
5. **【AI】** 再現 DAG(Snakemake/Makefile) + CI regen→diff ゲート。

## 5. 本セッションで既に消化した項目（再掲・検証済）

ライセンス帰属(NOTICE/CITATION ODbL)・出典容量160件・ρ正直化・pages overlay 修正・関西97%スコアカード・CHANGELOG v1.4/Unreleased・SECURITY.md・DATA_DICTIONARY §3.4(B2 開示)・本ロードマップ + 審査 + 国際比較の三部作。

---
出典: `docs/reports/formal_review_2026-06-26.md`, `docs/reports/international_benchmark_2026-06-27.md`, Nature Scientific Data 投稿規程(新規性非評価・Technical Validation 必須)。
