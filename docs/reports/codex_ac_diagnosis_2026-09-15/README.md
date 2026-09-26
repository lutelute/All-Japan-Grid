# 東日本AC・Ybus診断と宮城中央支線の復元試験

[Before/After HTML](index.html) / [補足PowerPoint 6枚](AllJapanGrid_AC_Ybus_review_2026-09-15.pptx) / [ツール説明](../../AC_DIAGNOSIS_TOOL.md)

**目標55,250 MWのQ制約付きACは未収束。** 支線復元と同一設備の合成需要重み補正に効果はあるが、制約を外した診断結果を運転可能な解とは扱わない。

- `input_network.json.gz`：一度組み立てた元回路のJSON。pickleを読まず、全機器の推定値を同条件で再実行する。
- `input_metadata.json`：元built入力SHA、組立フラグ・ソース、需要設定、pandapower版、回路・計画SHA。
- `branch_plan.json`：青葉幹線の元線形の分割、宮城中央支線、構内引込2本。
- `load_identity_plan.json`：同じOSM設備・地域・モデル電圧の70組。照合できなかった元設備も残す。
- `results.json`：4変種のAC、Ybus、Q制約遷移、運転点比率の試験。`complete`は試験実行の完了を表し、AC目標の達成ではない。
- `sources/`：OSM形状の抜粋、公式表の該当行、航空写真タイル・撮影期間・SHA。
- `exploration/`：初期値、補償、仮容量・回線、人口配分、実験solverなどの失敗を含む探索記録。初期の需要重み補正は68組。正式再実行の70組と区別する。
- `figures/`：地図重ね合わせとPowerPointのプレビュー。地理院の写真に重ねた線形はモデル・OSM由来。撮影期間は宮城中央2023年10〜11月、安良里2020年8〜12月、大郷2023年5月。
- `manifest.json`：保存ファイルのSHA。`qa.json`：検証範囲と利用できなかった表示環境。

```sh
python3 scripts/review_ac_solvability.py summary
python3 scripts/review_ac_solvability.py verify
python3 scripts/review_ac_solvability.py replay --out /tmp/ajg-ac-replay
```

元の枝と設備点を残し、コピー上で試験する。変圧器・発電機・Q上下限・基準母線は不変。支線の定数・需要の場所・補償・仮想補給はモデル仮定を含む。実測潮流に対する誤差改善率は未評価。
