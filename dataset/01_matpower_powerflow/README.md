# 01 — MATPOWER 配布ケースで潮流計算

配布物 `dist/matpower_national/<island>.mat` を読み、潮流計算（AC / DC）を実行する最小例です。
MATLAB（MATPOWER）版と Python（pandapower）版を用意しています。

## 配布ケースについて

- 非同期 **4 島**：`hokkaido`（50Hz）/ `east`（東北+東京・50Hz）/ `west`（中部以西・60Hz）/ `okinawa`（60Hz）。
  周波数が異なる島は同期しないので、島ごとに独立した `.mat` です。
- 各 `.mat` は MATPOWER v2 形式の `mpc`（`baseMVA` / `bus` / `branch` / `gen`）。
  **発電コスト `gencost` は含みません**（根拠のないコストを捏造しない方針）。したがって
  `runpf`（通常潮流）向けで、`runopf`（最適潮流）はできません。
- 表は CSV でも同梱：`<island>_bus.csv` / `_branch.csv` / `_gen.csv` と、人間可読な
  `_busname.csv` / `_branchname.csv` / `_genname.csv`（発電機の実名・燃料付き）。
- 検証結果は `dist/matpower_national/meta.json`（島ごとのバス/枝/発電機数・AC 収束・往復検証）。

## Python 版（MATLAB 不要）

```bash
pip install pandapower scipy numpy
python solve_pf.py                 # okinawa（最小・数秒）
python solve_pf.py hokkaido
python solve_pf.py east --dc       # DC 潮流
python solve_pf.py west --csv out  # 結果バス表を out/ に CSV 出力
```

`pandapower.converter.matpower.from_mpc` で `.mat` を読み込み、`runpp`（AC）で解きます。
非収束時は `rundcpp`（DC）に自動フォールバック。

## MATLAB 版（MATPOWER）

```matlab
% 先に MATPOWER を path に通す（パスは各自の環境に合わせる）
addpath(genpath('/path/to/matpower8.1'));
solve_pf('okinawa');       % または 'hokkaido' / 'east' / 'west'
solve_pf('east', 'dc');    % DC 潮流
```

`solve_pf.m` は MATPOWER のパスを**直書きしません**。実行前に `addpath` で通してください
（MATPOWER: https://matpower.org/ , BSD-3-Clause）。

## 期待される出力（沖縄）

```
RESULT: AC CONVERGED
  total generation:       1320 MW
  total load:             1301 MW
  transmission loss:        18 MW  (1.39 % of load)
  voltage Vm:        0.985 - 1.010 pu
```

## ⚠ 「収束」＝「正しく解けた」ではない

配布ケースは建造断面のスナップショットで、発電機出力 `gen(:,2)` と負荷は時間断面として
整合していません。**多成分の島**（沖縄以外は複数の弱連結成分に分かれ、各成分に 1 つ slack を
持ちます）では、単純な `runpf` で**損失が負になる／過大になる**などの需給不整合が現れます。
スクリプトはこれを検出して注意を表示します。

- 潮流の**挙動**を確認したい → 単一成分の **`okinawa`** を使う（綺麗に閉じます）。
- 大規模島で**需給整合した**潮流が欲しい → UC で 24 時間の発電計画を作ってから潮流に渡す
  （UC→潮流連成）。入口は [`../02_uc_from_excel/`](../02_uc_from_excel/)。
