# 現行UCの静的監査

確認日: 2026-10-23。対象commit: `e9457f4a34933c000932fae3688ec75b16f2e82c`。
出発ブランチ: `docs/1987-recheck`。専用ブランチ: `research/uc800-open-solver-plan`。
本作業はソースと既存JSONの読取りに基づく。**新しいUC求解・性能測定・不具合修正は実施していない。**

## 1. 再利用できるもの

- [solver.py](../../../src/uc/solver.py): PuLPによるu/p/v/w、3種起動費、蓄電、地域間連系線、HiGHS warm start。
- [rolling.py](../../../src/uc/rolling.py): 48h窓・24h確定、SOC・稼働状態・連続ON/OFF期間の引継ぎ。
- [scenario.py](../../../src/uc/scenario.py): シナリオ構築、重複除去・容量補完・稼働状態等のデータ整備。
- [uc_annual.py](../../../scripts/uc_annual.py) / [uc_benchmark.py](../../../scripts/uc_benchmark.py): 既存の実行入口とレポート。
- [UC_HANDOFF.md](../../UC_HANDOFF.md): 系統を消費する前のYbusゲートとデータの限界。

## 2. 計画の前提を変える発見

| 優先度 | コード上で確認した事実 | 研究への影響と対応案 |
|---|---|---|
| P0 | `solver._select_solver` はHiGHS系だけを分岐し、その他はCBCに進む | 現状で `solver_name="SCIP"` を指定してもSCIPを選べない。明示的adapterとeffective solver記録、要求バックエンド不在時の失敗を実装する |
| P0 | `solver._extract_solution` は `model.sol_status == 1` のときgap=0.0を設定。実際のdual boundを読まない | 保存されたgap=0を最適性の証明に使わない。native status、UB、LB、停止理由を取得する |
| P0 | `rolling` は全窓が `Optimal` なら年間statusも同名。retryではgapを3%、10%へ緩める | 窓の停止基準・年間の実行可能性・年間最適性を別フィールドにする |
| P0 | `UCParameters` に初期出力pの欄がなく、`add_ramp_constraints` は窓内の隣接時刻だけを見る | 連続ONでも窓をまたぐ出力ランプを保証できない。初期pと境界ランプの検証・制約を追加する |
| P0 | `add_startup_type_constraints` に `initial_history_h` が渡らず、look-backは窓内に切り詰められる | 最小up/down用前史はあるがhot/warm/cold分類の前史が不足。境界の停止時間と起動状態を統一する |
| P0 | `_recompute_cost` は3種起動をhot相当で概算し、先頭の前状態を既定OFFとする | UBに使う目的関数として不足。年頭条件・全起動種別・停止費・期間長・ペナルティを同じ定義で再計算する |
| P0 | `_extract_solution` は最適化目的値からspillペナルティを引いて `total_cost` として報告 | その値と元モデルのLBでgapを作れない。solver objectiveと経済費用を分ける |
| P0 | `uc_annual_merge` が確認するのは日付区間の重複・欠落と子status。u/p/SOC等の境界一致は照合しない | warmup後の独立チャンクをつなぐだけでは年間実行可能性の証明にならない。境界状態を保存し修復する |
| P1 | `_build_objective` は燃料費・時間費用に期間長を掛けず、ランプ値も期間長で換算しない | 第1版は1h限定と明記。30分化は費用・ランプ・最小時間を一貫して換算してから行う |
| P1 | 予備力は主に `sum(Pmax*u) >= demand*(1+margin)` | 応動時間・出力余裕・SOC・地域間の送達可能性まで保証する予備力とは異なる。モデル水準を明示する |
| P1 | 通常の解抽出は `result.status == "Optimal"` の場合のみ | time limitで得た実行可能incumbentを捨てうる。実行可能性と停止理由を分離して保持する |
| P1 | Generatorの基礎モデルは発電所を表し、記録名 `n_thermal` に水力等も含まれる | 800台の定義を、施設数・個別ユニット数・起動停止対象数に分解して台帳化する |
| P1 | 地域需給と連系線容量のモデルが `nodal` と呼ばれている | 現行の地域集約transport modelと母線DC/ACモデルを区別して報告する |

関連箇所: [models.py](../../../src/uc/models.py)、[constraints.py](../../../src/uc/constraints.py)、[generator.py](../../../src/model/generator.py)、[uc_annual_merge.py](../../../scripts/uc_annual_merge.py)。

`decomposition.py` の地域・燃料別分割や `TimeWindowDecomposer` も、分割後の目的値・最大gapをそのまま全国・年間の証明に利用しない。新規手法は元問題への緩和・制限の関係を明示して別途検証する。

## 3. 保存済みの計算実績をどう読むか

| 保存ファイル | 記録値 | 利用できる根拠 / 利用できない主張 |
|---|---|---|
| [2026-06-12の24h JSON](../../reports/uc_benchmark_fy2025r1_measured_2026-06-12.json) | 531 Generator、HiGHS API、11.5秒、要求gap 1%、記録gap 0 | 既存経路に動作実績がある。個別火力800台・厳密gap 0・現在環境での速度を証明しない |
| [年間merge JSON](../../reports/uc_annual_fy2025r1measured_2026-06-11.json) | 13チャンク、389窓、最大チャンク3753秒、時間合計32534.8秒、365日 | 年間規模の集計実績。全チャンクの同時開始・資源・待ち時間が不明なので3753秒を年間end-to-end時間としない |

年間JSONの `cpu_time_s_sum` はmergeコードでは子の `solve_time_s` の和。CPU使用時間の実測値やcore-hourとは異なる。費用はローリング再計算の近似とチャンク丸めを含み、年間UBとして未認定。

24h JSONの `n_thermal_loaded=521` はfuel_counts合計と対応し、nuclear・hydro・pumped_hydro等を含む。`n_thermal=478` も個別火力ユニット数として使わない。既存データを800に水増しせず、実ユニット由来のケースと、規模検証用の合成ケースを分ける。

## 4. 最初に作る検証ケース

1. 時間制限終了だがincumbentがあるケース。解を保持しgapを0にしない。
2. 一つの発電機が窓境界でONを維持し、pだけ大きく変わるケース。境界ランプ違反を検出する。
3. 窓の直前から停止している発電機のhot/warm/cold分類と起動費。
4. 独立チャンクの継ぎ目でSOCが食い違うケース。日付が連続でも拒否する。
5. spillや不足ペナルティが非ゼロのケース。全目的値・経済費用・診断量を混同しない。
6. 4〜10台・24〜72hで一括MILPと分解を比較。各LB ≤ 既知最適値 ≤ 検証済みUBを確認する。

これらは今後の実装の受入条件であり、本計画作成時に実行したテストではない。
