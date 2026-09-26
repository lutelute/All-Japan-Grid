# reports/ — モデル判断の記録と改善台帳

このディレクトリは、AIモデル（Claude Opus / Fable 等）がこのプロジェクトに対して下した
**評価・設計判断・改善の記録**を残す場所。

## なぜ残すか

- このプロジェクトの方法論・再接続・潮流モデルは大部分がAI生成であり、
  **どのモデルが・いつ・何を根拠に・どう判断したか**は再評価のための一次資料になる
- 改善は数値で語る: `ajgrid validate --topology --all --solve` のKPI
  （断片化・合成線率・収束・電圧範囲）を判断の前後で記録し、効果を測定可能にする

## 構成

| ファイル | 内容 |
|---|---|
| `IMPROVEMENT_LOG.md` | 改善台帳。セッション単位で モデル / 日付 / 変更 / KPI変化 を1エントリずつ追記 |
| `YYYY-MM-DD_<model>_<topic>.md` | 個別の評価・設計判断レポート（台帳から参照） |
| [敷地・端子・母線の接続監査ツール](../SITE_CONNECTION_REVIEW_TOOL.md) | Claude / Codex共通CLI、判断手順、試行錯誤、再現条件 |
| [2026-09-13 接続比較HTML](codex_same_site_trial_2026-09-13/index.html) | 全27組のBefore / After / 第三案、航空写真、電気解析、PPT |
| [2026-09-15 AC・Ybus診断のBefore/After](codex_ac_diagnosis_2026-09-15/index.html) | 目標Q制約付きACは未収束。支線復元・需要重み・再実行・写真・PPT |

## エントリの書き方（IMPROVEMENT_LOG）

- **モデル名は正直に**: 記録がない過去セッションは「記録なし」とする。推測で埋めない
- **KPIは計測値のみ**: `docs/reports/topology_baseline_*.json` との diff
  （`ajgrid validate --topology --all --baseline <json>`）を根拠にする
- 限界・未解決・「便宜」（需要スケール等）は隠さず書く — 誇張防止が公共価値
