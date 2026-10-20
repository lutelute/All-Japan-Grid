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
- 検証結果は `dist/matpower_national/meta.json`（島ごとのバス/枝/発電機数・AC 収束・往復検証・縮約の帳簿）。
- **4 島とも AC 潮流が MATPOWER の既定の許容誤差で収束します**（v1.9.0 から。需要は fy2023 既定断面）。

| 島 | バス | 損失 | 電圧 Vm | 備考 |
|---|---:|---:|---|---|
| `okinawa` | 100 | 1.93 % | 0.972–1.003 | 最小・数秒 |
| `hokkaido` | 831 | 2.63 % | 0.860–1.022 | |
| `east` | 6,253 | 2.95 % | 0.858–1.023 | 練馬・板橋周辺の 66kV が低め |
| `west` | 7,979 | 2.17 % | 0.775–1.037 | 江田島の 66kV の木 1 本（6 バス）を親バスへ畳んである。大阪・三国周辺の 77kV が低い |

west の縮約: 全部入りだと、需要を変電所へ均等に割った配分のせいで江田島の 66kV 1 回線（69 MVA）に
172 MW が載り、送れる解が存在しません。この木だけを親（宮原変電所）へ畳み、負荷は保存しています。
畳んだ木は `meta.json` の `islands[].reduction.trees` に、根・バス名・負荷つきで残しています
（介入台帳 #52・`docs/reports/matpower_dist_ac_2026-10-20.md`）。

## Python 版（MATLAB 不要）

```bash
pip install pandapower scipy numpy
python solve_pf.py                 # okinawa（最小・数秒）
python solve_pf.py hokkaido
python solve_pf.py east --dc       # DC 潮流
python solve_pf.py west --csv out  # 西（約 8,000 バス）。結果バス表を out/ に CSV 出力
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
  total generation:       1386 MW
  total load:             1360 MW
  transmission loss:        26 MW  (1.93 % of load)
  voltage Vm:        0.972 - 1.003 pu
```

MATLAB 版（MATPOWER 8.1 の `runpf`）と Python 版（pandapower）は同じ数字になります。
ケースには解いた状態（VM/VA）が入っていますが、VM=1・VA=0 のフラット始動からでも
4〜6 回の反復で収束します。

## 複数の slack（REF バス）について

各島は、本系統から切れた小さな断片を含み、連結成分ごとに 1 つ slack（REF バス）を持ちます
（east は 220 個）。断片の需要は、実在しない合成の電源（slack）が賄っています。MATPOWER も
pandapower もこれを正しく解きます。

> v1.7.0 までの Python 版は、同じバスの 2 台目以降の発電機（`from_mpc` が `sgen` にする）を
> 発電に数えておらず、損失が負に見えていました。原因を「pandapower は複数 slack を扱えない」と
> 説明していましたが、それは誤りでした（v1.9.0 で修正）。

> なお「潮流が収束した」＝「正しく解けた」ではない一般則は変わりません。配布ケースは建造断面の
> スナップショット（発電機出力は時間断面として厳密に需給調整されたものではない）で、線路定数は
> 電圧階級ごとの代表値です。線ごとの潮流や電圧の値は個別に引用せず、地域ごとの集計や傾向を
> 見る用途に使ってください。
