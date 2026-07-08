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

## MATLAB版と Python版で多成分島の扱いが違う（重要）

沖縄以外の島は複数の弱連結成分に分かれ、各成分に 1 つ slack（REF バス）を持ちます。この
**多成分ケースの扱いが 2 つの実装で異なります**（実機確認済み）:

| 島 | MATLAB (MATPOWER `runpf`) | Python (pandapower `from_mpc`) |
|---|---|---|
| okinawa（単一成分） | AC 収束・損失 2.2 % ✅ | AC 収束・損失 1.4 % ✅ |
| hokkaido（9 成分） | **AC 収束・損失 +3.5 %** ✅ | 損失 −68 %（不整合）⚠ |

- **配布 `.mat` 自体は健全**です。MATPOWER は複数 slack を正しく扱い、各成分で需給を閉じます。
- **pandapower の `from_mpc` は複数 slack を正しく変換できず**、多成分島で損失が負になる等の
  不整合が出ます。`solve_pf.py` はこれを検出して注意を表示します（`.mat` の欠陥ではありません）。

そのため:
- Python で潮流の**挙動**を確認したい → 単一成分の **`okinawa`**（綺麗に閉じます）。
- Python で**大規模島**を扱いたい → MATLAB 版（MATPOWER）を使うか、UC で 24 時間の発電計画を
  作ってから潮流に渡す（UC→潮流連成）。入口は [`../02_uc_from_excel/`](../02_uc_from_excel/)。

> なお「潮流が収束した」＝「正しく解けた」ではない一般則は変わりません。配布ケースは建造断面の
> スナップショット（発電機出力は時間断面として厳密に需給調整されたものではない）である点は
> 引き続き留意してください。
