# 02 — Excel で発電機を設定 → ユニットコミットメント (UC)

発電機のパラメータと 24 時間需要を **Excel** で編集し、24 時間の最小コスト起動停止計画
（どの発電機を・いつ・どれだけ動かすか）を MILP で解きます。表計算で設定 → Python で求解、の
2 ステップです。

## 手順

```bash
pip install openpyxl pulp matplotlib pyyaml

# 1) 実在フリートから編集用テンプレートを生成
python make_template.py                 # → generators_template.xlsx（沖縄）
#    別地域: python make_template.py --island okinawa --peak-mw 2000

# 2) Excel を開いて編集（発電機の追加/削除・費用・需要の変更）

# 3) UC を解く
python run_uc.py                        # → uc_result.xlsx / uc_result.png
#    別ファイル: python run_uc.py --xlsx my_generators.xlsx --out result.xlsx
```

## `generators_template.xlsx` の構成（3 シート）

**generators**（発電機 1 台 = 1 行）

| 列 | 意味 | 出所 |
|---|---|---|
| `id` / `name` | 発電機 ID / 発電所名 | 名前は OSM 由来の実在フリート |
| `fuel` | 燃料（coal/lng/oil/nuclear/hydro/wind/solar/…） | OSM 由来 |
| `bus` | 接続バス番号 | MATPOWER 配布ケースのバス |
| `Pmax_MW` | 定格出力 | OSM 由来（実在フリート） |
| `Pmin_MW` | 最小出力 | **例題仮定**（火力=定格 30%）・要編集 |
| `marginal_cost_JPY_per_MWh` | 限界費用 | **例題既定**（燃料別・要編集） |
| `startup_cost_JPY` / `shutdown_cost_JPY` | 起動費 / 停止費 | 例題既定 |
| `min_up_h` / `min_down_h` | 最小連続運転 / 停止時間 | 例題既定 |
| `no_load_cost_JPY_per_h` | 無負荷固定費（起動中） | 例題既定 |
| `init_on` | 初期状態（1=運転中 / 0=停止） | 既定 0 |

**demand**：`hour`（0–23）× `demand_MW`。発電機の Pmax 合計より需要が大きいと解なし（infeasible）。

**readme**：各列の説明と出典（Excel を開けば読めます）。

## 出力

- `uc_result.xlsx`
  - **dispatch** シート：発電機 × 時刻の出力 [MW]（最終行に需要）
  - **summary** シート：ステータス・総コスト・発電機別のエネルギー/起動回数/費用内訳
- `uc_result.png`：燃料別の積み上げ発電量 + 需要曲線

沖縄フリート（火力 2800 MW）＋ 2000 MW ピーク需要の既定設定では、`status=Optimal` で
merit order 通り（安い石炭が主力・ピーク時に石油）に解けます。

## 値の出所（誠実性）

- **発電所名・燃料・定格（Pmax）は OSM 由来の実在フリート**です。
- **限界費用・起動費・最小 up/down 時間・最小出力（Pmin）は例題用の一般既定値**
  （`config/uc_config.yaml` の typical estimates）で、特定発電所の実測値ではありません。
  実データがあれば Excel 上で書き換えてください。
- 再生可能電源（solar/wind）は本例題では**変動性を簡略化**し、限界費用 0 の上限固定として
  扱っています（時間別の出力変動 CF は入れていません）。より現実的な断面は
  `config/uc_scenarios/fy2023.yaml` と全国 UC 例（リポジトリの `examples/uc_*.py`）を参照。

## しくみ（内部）

`run_uc.py` は Excel の各行を `src.model.generator.Generator` に、`demand` を
`src.uc.models.DemandProfile` に変換し、`src.uc.solver.solve_uc()`（PuLP + HiGHS/CBC）で
解きます。ソルバ本体はリポジトリの `src/uc/` にあり、このバンドルにも同梱されています。
