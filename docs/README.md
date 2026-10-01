# 文書の地図 / Documentation map

`docs/` は GitHub Pages のサイト(`index.html` ほか)と、設計・方法論・運用の文書を兼ねている。
ここは文書側の索引。ツールの一覧はダッシュボード(https://lutelute.github.io/All-Japan-Grid/)にある。

`docs/` serves both the GitHub Pages site and the project documents. This page indexes the documents;
the dashboard lists the tools.

## まず読む / Start here

| 文書 | 何が書いてあるか |
|---|---|
| [DATASET.md](DATASET.md) | データセットの詳細(ファイル形式・CIM/CGMES・出典・エンリッチメント・**限界**・既知の品質問題)。README から移した原文 |
| [MODEL_INTERVENTIONS.md](MODEL_INTERVENTIONS.md) | **介入台帳** — 「つながって見える・解けて見える」を作っている仮定の全リスト(根拠・帳簿・無効化の方法) |
| [WHAT_TO_CHECK.md](WHAT_TO_CHECK.md) | ライブマップの見どころ |
| [HIGHLIGHTS.md](HIGHLIGHTS.md) | リリースごとの要点(全履歴は [CHANGELOG](../CHANGELOG.md)) |
| [TECHNICAL_FAQ.md](TECHNICAL_FAQ.md) | よくある技術的な質問 |

## 方法論 / Methods

| 文書 | 何が書いてあるか |
|---|---|
| [../WHITEPAPER.md](../WHITEPAPER.md) | 全体の手法(OSM からの組み立て・検証) |
| [SUBSLD_METHOD.md](SUBSLD_METHOD.md) | SubSLD 法 — 変電所の構内図×単線結線図を全国で機械生成する |
| [OBSERVED_VS_DERIVED.md](OBSERVED_VS_DERIVED.md) | 公表値(observed)と計算値(derived)を混ぜないための規約 |
| [GENERATOR_DB.md](GENERATOR_DB.md) | 発電所 DB の出典と層 |
| [VALIDATION_SOURCES.md](VALIDATION_SOURCES.md) | 検証に使える外部の正解データ |
| [COVERAGE.md](COVERAGE.md) | 来歴・検証カバレッジ(`ajgrid coverage` で作り直せるスナップショット) |
| [YBUS_SOLVABILITY.md](YBUS_SOLVABILITY.md)・[WEST_AC_ANALYSIS.md](WEST_AC_ANALYSIS.md)・[PV_CURVES.md](PV_CURVES.md) | Ybus の条件数と可解性、西の AC 収束の原因分析、連続潮流 |
| [../hazard/nankai/README.md](../hazard/nankai/README.md) | 南海トラフ地震の電力ハザード(損傷 → カスケード → 復旧) |

## データを使う / Using the data

| 文書 | 何が書いてあるか |
|---|---|
| [INTEROP.md](INTEROP.md) | pandapower・PyPSA などへ 1 行で取り込む |
| [MATPOWER_EXPORT_GUIDE.md](MATPOWER_EXPORT_GUIDE.md) | MATPOWER 形式での書き出し |
| [CIM_MAPPING.md](CIM_MAPPING.md) | IEC 61970 CIM / CGMES への対応表 |
| [../dataset/README.md](../dataset/README.md) | 配布バンドル(clone 不要で潮流計算まで) |
| [REPRODUCIBILITY.md](REPRODUCIBILITY.md) | 再現手順 |

## 設計 / Design

| 文書 | 何が書いてあるか |
|---|---|
| [DB_ARCHITECTURE.md](DB_ARCHITECTURE.md) | DB の 3 層化(R/C/D)と正典の流れ |
| [DATA_SPACE.md](DATA_SPACE.md) | 外部データを源泉に置いたまま必要な断面だけ取る設計 |
| [CONNECTION_EDITOR_DESIGN.md](CONNECTION_EDITOR_DESIGN.md) | 接続編集プラットフォーム |
| [UC_HANDOFF.md](UC_HANDOFF.md)・[UC_VALIDATION_PLAN.md](UC_VALIDATION_PLAN.md) | UC(起動停止計画)への引き渡し条件と検証ループ |

## 方針・連携 / Strategy

| 文書 | 何が書いてあるか |
|---|---|
| [VISION.md](VISION.md) | 全体構想 |
| [ROADMAP_ASSET.md](ROADMAP_ASSET.md) | 「出典付き全国送電網」への資産化ロードマップ |
| [ENGAGEMENT.md](ENGAGEMENT.md)・[INTEGRATION_STANCE.md](INTEGRATION_STANCE.md) | 事業者・OCCTO・研究機関との連携設計と外部連携の立場 |

## 運用 / Operations

| 文書 | 何が書いてあるか |
|---|---|
| [REALTIME_OPS.md](REALTIME_OPS.md) | NOW 断面(でんき予報 → 潮流 → Pages)を毎時更新する仕組み |
| [ZENODO_DOI.md](ZENODO_DOI.md) | DOI 発行の手順(発行は保留中) |

## 記録 / Records

- [reports/](reports/) — 判断と検証のレポート(日付つき)。索引は [reports/README.md](reports/README.md)、時系列の台帳は [reports/IMPROVEMENT_LOG.md](reports/IMPROVEMENT_LOG.md)
- [archive/plans/](archive/plans/) — 完了・停止した計画(66kV プログラム、全面改修、GridStitch、topoRAG など)
- [slides/](slides/) — 発表スライド(版と日付つき)

## README の GIF / README animations

README の GIF は `docs/assets/gif/` にあり、`python scripts/make_readme_gifs.py` で撮り直せる
(ページをブラウザで台本どおりに操作して録画する)。README の数字は `cog -r README.md` で
データから書き直す(`scripts/readme_numbers.py`)。
