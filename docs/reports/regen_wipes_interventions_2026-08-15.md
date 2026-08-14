# 事故記録: regenerate_all が適用済み介入を黙って消した — 派生物への in-place 適用の罠

- 日付: 2026-08-15 早朝（正典適用の直後）
- 種別: **実害を伴う設計欠陥の発見と恒久修正**（[[feedback_record_failures]]）
- 修正: `scripts/regenerate_all.py` に適用ステップを組み込み（同コミット）

## 何が起きたか

介入#28（v1: 公表接続13本）と#29（v2: 76本+region是正95）は
`docs/data/built/all.json` への **in-place 適用**だった。ところが
`regenerate_all.py` の先頭ステップ `build_editor_data.py` は **all.json を
基底 extract から再構築する**（=all.json は正典ではなく派生物）。

正典適用の直後に regenerate_all を実行した結果、**適用済みの89本+region是正が
黙って消え、PF が 8/11 の pre-apply 数値に戻った**。検出できたのは
east の vm_max が 1.7625178045385312 と **8/11 の値に浮動小数点まで完全一致**
したことから（実モデルが違えば起こり得ない）。
[[project_agj_db_unification]] が警告していた「enrich の GeoJSON in-place 変異」
問題の実害がここでも出た形。

## 恒久修正 — 「再構築後に必ず再適用」パターン

`apply_capacity_sources`（build_static_site の後に出典容量を再適用する既存ステップ）と
同じパターンで、STEPS の build_editor_data 直後に2段を追加:

```
build_editor_data → apply_disclosure_v1(--write) → apply_disclosure_v2(--from-worklist --write) → …
```

- 両スクリプトに**冪等ガード**（既存 disclosure 枝の端点対は skip）を追加
- v2 に `--from-worklist`: worklist を再計算せず**コミット済みの帳簿 JSON から適用**
  （audit ファイル(untracked)に依存しない・帳簿=介入の①根拠②帳簿そのもの）

## 副産物 — v2 は 83本でなく76本が正しい

5:15 の適用時、帳簿がバグ修正後の監査で再計算され、**OSM 線で既に本系統に繋がる
下北半島チェーンの冗長エッジ7本が正しく脱落**していた（83→76）。これは正しい挙動:
既に接続がある場所に公表エッジを重ねると**並列回線の二重計上**になる。
今夜の実証接続の正確な合計は **v1 13本 + v2 76本 = 89本**。

## 教訓

1. **派生物に in-place 適用した介入は、生成パイプラインに組み込まれるまで「適用済み」と
   言ってはいけない**。適用スクリプトを書いたら、同時に regenerate_all の STEPS に載せる。
2. 再計算で数値が「前の出荷値と完全一致」したら、それは安定ではなく**入力が戻った**兆候。
   浮動小数点の完全一致は再計算が起きていない/同一入力の証拠として使える。
3. `--revert`/bak による無効化は、rebuild を挟むと意味が変わる（bak は旧系譜のスナップショット）。
   パイプライン化以後の無効化手段は「STEPS から外す or --disable」+ git が正。
