# auto-claude ブランチ群の採点 — マージ可否判定（2026-07-16）

モデル: Claude Fable 5。オーナー指示「採点してマージ」に基づく審査記録。
対象: `auto-claude/001〜005`（2026-03-05〜03-12 に別アクター Claude Opus 4.6 が作成・全て main から約4ヶ月乖離）。

## 結論: マージすべきブランチは無い（3本は取り込み済み・2本は不採用）

| ブランチ | 判定 | 根拠 |
|---|---|---|
| 003 transmission-capacity | **取り込み済み** | 先端 `0092a76` が main の祖先（`git merge-base --is-ancestor` 確認） |
| 004 adaptive-uc-solver | **取り込み済み** | 同上（`053277b` が main の祖先） |
| 002 geographic-attribute | **取り込み済み(空)** | 分岐後0コミット。先端=分岐点 `37bc141`（PR #8）は main に入っている |
| 001 network-reconstruction | **不採用 (D)** | 下記詳細 |
| 005 fuel-checkbox-legend | **不採用/マージ不能** | 下記詳細 |

## 001 不採用の詳細（3コミット・+703行）

1. **核心機能が別解で解決済み**: 目的は「変圧器自動挿入+擬似バスでPF収束」だが、mainは
   v1.4.0で全10地域AC収束を達成済み（変圧器は snapped_topology/built正典/CIM PowerTransformer/
   介入#22 の系譜で処理）。3月時点の pandapower_builder への253行は設計が過去のもの
2. **捏造禁止方針に抵触**: `parse_plants` が「容量不明→10.0 MW デフォルト」「最近傍変電所へ
   マッチ」を導入する。前者は出典必須DB（1-Cで2,581件を出典付きで充填した対象に無出典既定値を
   書く）に、後者は最近傍法廃止の教訓（topology_rootcause）に真っ向から反する
3. **マージ実測4ファイル衝突**: README / WHITEPAPER / geojson_loader / geojson_parser。
   WHITEPAPER +345行はv1.3〜1.6の全面改稿を経た現行と非互換（「AI自律改善ビジョン」の追記は
   誠実性レビュー方針とも不整合）

## 005 不採用の詳細（1コミット）

1. **機能は実装済み**: 「凡例に燃料種チェックボックス+All/Clear」は、mainのサイドバー
   発電所種別セクション（`buildFuelCheckboxes`・全選択/全解除）として同等機能が出荷済み。
   凡例側は 2026-07-15 のモバイル改修で折りたたみチップ化しており、チェックボックス追加は
   モバイル設計とも逆行
2. **物理的にマージ不能**: コミット `79777f5` の tree object が欠落
   （`unable to read bec8c89...`・既知の git 欠落 blob 問題）。diff / cherry-pick とも不可

## 提案（要オーナー承認・未実施）

- ローカル worktree 3件（`.auto-claude/worktrees/tasks/001,002,005`）と対応ローカルブランチの削除
- リモートブランチ `auto-claude/001〜004` の削除（001は否決記録が本レポートに残るため）
- 005 はローカルのみ+object欠落のため、削除すると1コミットは完全消滅（機能はmain実装済み）

削除はいずれも破壊的操作のため実行していない。
