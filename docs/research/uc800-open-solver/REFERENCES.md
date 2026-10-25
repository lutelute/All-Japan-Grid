# 一次資料と本計画への使い方

確認日: 2026-10-23。以下の公開事実と、本計画独自の設計提案・未検証仮説を区別する。ソフトウェア版・ビルド条件は実装開始時に固定する。

## ソルバーと開発基盤

| 資料 | 確認した内容 | 本計画での用途 |
|---|---|---|
| [ZIB: Yuji Shinano](https://www.zib.de/members/shinano) | ParaSCIP/FiberSCIP（UG）の開発者の研究業績・関連文献 | 並列化の背景と適切な引用の確認。個別の協力合意はこのページから推定しない |
| [UG公式](https://ug.zib.de/) | UGの汎用並列化基盤、ParaSCIPはSCIP/MPI、FiberSCIPはSCIP/Pthreads。2026年9月公開のUG 1.1.0の案内 | 同一問題の探索並列化の第一候補。過去の多数コア実績をUCの速度保証には使わない |
| [SCIP公式](https://www.scipopt.org/) | 2026年9月のSCIP 10.1.0 / Suite 10.1.0、GCG 4.1.0、UG 1.1.0。SCIPは8.0.3以降Apache-2.0 | 開発候補の確認。SCIPとSuite全体の依存ライセンスを同一視しない |
| [SCIP concurrent solving](https://scipopt.org/doc/html/CONCSCIP.php) | 異なる設定のSCIPインスタンスで同一問題を並列求解する機能 | FiberSCIPとは別の比較対象。thread数や設定を記録 |
| [SCIP: primal heuristicの追加](https://www.scipopt.org/scip/doc/html/HEUR.php) | callback、プラグイン登録、sub-SCIPを使うheuristicの実装点 | UC近傍探索を拡張する入口。MPI互換性は別に検証 |
| [UG 1.0.0 manual](https://ug.zib.de/doc-1.0.0/html/) | frameworkの概念、programming、パラメータへの入口 | 設計概念の把握用。1.1.0のABI/APIをこの旧版文書だけで確定しない |
| [GCG pricingの公式解説](https://gcg.or.rwth-aachen.de/doc-3.5.0/pricing.html) | restricted masterとpricing、branch-and-price | 年間分解の代替候補。文書は3.5.0なので採用版で実装仕様を再確認 |

SCIP公式の配布表にはParaSCIPを含まないビルドもある。PySCIPOptをインストールしただけでParaSCIP/MPIも利用可能になるとは仮定しない。採用OS・MPI・LP solverでビルドし、小ケースで起動・解交換・終了・再開を確認する。

UG公式はLGPLによる配布と引用方法を記載している。実際に配布する版のLICENSEと各依存を確認し、SCIP・UG・データ・自作拡張を区別して記録する。引用はUG公式が指定するParaSCIP論文、および使用版のCITATION/DOIを採用する。

## UCの定式化・比較対象

1. [Morales-España, Latorre, Ramos: Tight and Compact MILP Formulation for the Thermal Unit Commitment Problem（著者公開原稿）](https://pascua.iit.comillas.edu/aramos/papers/V3.3_Tight_Compact_UC.pdf)。tightnessとcompactnessを両方比較する根拠。専用制約を取り込む際は本プロジェクトの起動・ランプ定義との整合を確認する。
2. [Knueven, Ostrowski, Watson (2020): On Mixed-Integer Programming Formulations for the Unit Commitment Problem](https://pubsonline.informs.org/doi/10.1287/ijoc.2019.0944)。既存・新規の定式化部品と参照実装を比較した研究。定式化を部品単位で検証する方針の基準。
3. [UnitCommitment.jl 0.4: Problem definition](https://anl-ceeesa.github.io/UnitCommitment.jl/0.4/guides/problem/)。発電・storage・系統等の定義と、DC線路制約の逐次生成。正準入力・比較モデルの意味合わせに使う。
4. [UnitCommitment.jl 0.4: 公開instance配布](https://axavier.org/UnitCommitment.jl/0.4/instances/)。外部ベンチマーク候補。各ケースの元データ・論文・条件を確認し、版とハッシュを固定する。
5. [A long-term unit commitment problem with hydrothermal coordination for economic and emission control in large-scale electricity systems](https://link.springer.com/article/10.1007/s00291-020-00576-y)。長期UCと水力・貯蔵・排出制約を扱う先行研究。年間を扱うこと自体を新規性としないための比較対象。

## 本計画で未確認のこと

- この800台モデルでSCIPがHiGHSより速いか、ParaSCIPが何コアまで伸びるか。
- 年間gap 1%以下に必要な時間、メモリ、分解粒度。
- 提案する近傍・資源配分の新規性と既存手法に対する優位性。
- 個別ユニット800台分のデータ充足率、対象年度、利用できるHPC資源。
- ZIB側が推奨する具体的な開発経路・保守範囲・共同研究上の役割。

これらは文献からの断定を避け、実験・台帳・協議で埋める。
