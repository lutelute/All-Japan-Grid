# 改善台帳 — モデル別セッション記録

セッション単位の改善記録。**モデル名は記録がある場合のみ記載**（推測で埋めない）。
KPIは `ajgrid validate --topology --all --solve` の計測値
（ベースライン: `docs/reports/topology_baseline_*.json`）を根拠とする。
2026-06-10以降のエントリはモデル名の記録を必須とする。

---

## 2026-06-10 — **Fable 5** — backboneモデルでAC 10/10（②）+ 外部照合の初計測（①完結）

- **② AC-solvable backbone** (`decbad0`): `reduce_to_backbone`（≥154kV保持、下位網発電を
  境界バスへBFS集約、需要は縮約後に配分、閾値は地域別auto-degrade）
  - **AC 10/10 native収束**（従来9/10）。**関西が全量需要22,833MWで収束**（従来x0.3〜0.4スケール必須）
  - vm_min 全地域≥0.91（フルモデル: 東京0.78/北海道0.81）、東京過負荷583%→127%
  - 需要スケールladderの撤去がこのモデルでは可能に。`ajgrid solve <region> --backbone`
  - 副産物: reconnector の dense-Ybus クラッシュ修正（小網で顕在化した潜在バグ）
- **① 外部照合** : Web実調査で正解ソース確定（`docs/VALIDATION_SOURCES.md`）。
  **旧メモのC02=電力施設は誤り（C02=港湾、KSJに送電線データは存在しない）**
  - 関西送配電CSV（線路名・回線数・容量、毎日更新）との照合実装 `src/validation/external_match.py`
  - **初計測（関西）**: 公式235線の名前一致40%（厳密17.9%）・**500kV 34線中20線が名前で発見不可**・
    circuits タグ一致56% — 入力(OSM)自体の欠落が初めて定量化された
  - 発見: 東電PGが**変電所×線路名つき1時間値潮流CSV**(2024通年)を公開 = 東京エリアの接続+潮流の正解

## 2026-06-10 — **Fable 5** — プロジェクト評価と検証フレームワーク（①）

- **判断レポート**: [2026-06-10_fable5_evaluation.md](2026-06-10_fable5_evaluation.md)
- **背景**: ユーザー評価「潮流計算と系統の点・線の接続が弱い」→ 全面監査の結果、
  診断は正確で、**接続の弱さが潮流の弱さの根本原因**という構造を確認
- **変更**:
  - `src/validation/`（トポロジ・潮流KPI: 断片化 / 合成線率 / 収束 / 電圧 / OSMタグ証拠）
  - `ajgrid validate --topology`（`--solve` / `--json` / `--baseline` diff）
  - 回帰pinテスト `tests/test_topology_metrics.py`（okinawa exact + 品質フロア + slow全域sweep）
  - KPIベースライン `docs/reports/topology_baseline_2026-06-10.json`
  - 改善計画①〜⑥（評価レポート参照）の起点
- **計測で確定した新事実**:
  - 公開データの合成線率: 関西14.6%・九州9.4%・東京5.8%（n_components=1は橋渡しの結果）
  - `circuits` タグ（並行回線数の直接証拠）が46〜60%充足なのに未活用
  - 関西は電圧タグ31%欠落 / 四国はビルダー段階で56成分・カバー57%
  - okinawa solved n_components=4 は離島の実分離（>5km海峡は捏造しない設計）= 正直な挙動

## 2026-06-08〜10 — モデル記録なし — DB統一(R/C/D)・M1実証・CIM修正・ツール化

- DB機械更新ループ（fetch→ingest→enrich→export）完成、pws-160coreでM1実証
- CIM/CGMES L2のP0バグ9件修正（parallel無視・長さ1000倍など、REVIEW_FINDINGS）
- P03権威データ3,109発電所、`pip install -e .` → `ajgrid` CLI化
- 全体レビュー（7アングル・36候補→CONFIRMED10件）= `REVIEW_FINDINGS.md`

## 2026-05-29〜06-06 — 一部 **Opus 4.7**（記録あり）— トポロジ再設計・west究明

- **Opus 4.7**: PR #13（Sonnet 4.6作業）でAC NR発散→kV²重み復帰+北海道隔離で収束回復
- 頂点グラフ+スナップ法ビルダー（東京481→134成分）、再接続「星形」バグ修正、
  keep_stubsデフォルト化で地域AC 10/10収束（当時計測）
- west島AC非収束の真因確定（154kV未満下位網、`docs/WEST_AC_ANALYSIS.md`）
- 関西AC非収束=電圧安定限界（PVノーズ）と確定、demand-scaled可視化で開示

## 〜2026-05-26 — モデル記録なし — 初期構築

- OSM取得・10地域GeoJSON・MATPOWER全国2189バスケース・GitHub Pages可視化
- 最近傍50kmマッチ法（後に大半の線をdropすると判明→snapped法で置換）
