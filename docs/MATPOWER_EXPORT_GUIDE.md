# MATPOWER Export Guide

All-Japan-Grid のスナップ済みトポロジを **MATPOWER 形式** (`.mat`) に書き出し、
MATPOWER / pandapower で検証する手順です。実装は `src/matpower/exporter.py`、
実行例は `examples/export_and_solve_matpower.py` を参照。

---

## クイックスタート (Copy-paste)

```bash
PYTHONPATH=. python3 examples/export_and_solve_matpower.py okinawa
```

引数に地域名を渡すと、その地域のスナップ済みネットワークを MATPOWER ケースに変換し、
`output/matpower/<region>_snapped.mat` に保存、再読込ラウンドトリップと
pandapower 潮流計算による求解性検証まで一気に行います。複数指定も可:

```bash
PYTHONPATH=. python3 examples/export_and_solve_matpower.py okinawa shikoku
```

出力例(各地域ごと): bus/branch/gen/gencost の件数、GENCOST の merit order
($/MWh)、`.mat` が書けて再読込できたか、pandapower 潮流が収束したか。

---

## 1. スナップ済み GridNetwork からケースを構築

```python
from examples.build_snapped_topology import build_network_snapped
from src.matpower.exporter import build_matpower_case, save_case_to_matfile

net = build_network_snapped("okinawa")          # src.model.grid_network.GridNetwork
case = build_matpower_case(network=net)         # snapped 経路
```

`build_matpower_case(network=...)` は内部で `_build_case_from_model_network()` を
呼び、以下を行います:

- 最大連結成分に限定(well-posed な AC NR のため)。
- 電圧クラス + 線長から pu パラメータ (R/X/B/定格) を導出 (`_model_line_pu`)。
- 負荷を **kV² 重み付け**で配分(HV 寄りにしてヤコビアンを良条件に保つ)。
- 1 バス 1 発電機を割当(最大容量を採用)。スラックは「最も連結が良く容量大の
  発電機バス」(degree≥3 を優先)。
- BUS/BRANCH/GEN/**GENCOST** を生成(OPF 対応)。

返り値 `case` の主なキー: `BUS`, `BRANCH`, `GEN`, `GENCOST`(`gencost` も別名),
`baseMVA`, `gen_fuel`, `bus_names`, `n_bus`, `n_gen`, `slack_bus`(1-indexed),
`diagnostics`, `compensation`。

---

## 2. mpc 構造体の中身

`save_case_to_matfile` は標準的な MATPOWER `mpc` 構造体にまとめます
(`version`, `baseMVA`, `bus`, `branch`, `gen`, `gencost`)。インデックスは
**1-based**。`baseMVA` は既定 100.0 MVA。

### BUS (各行 13 列 → MATPOWER 規約)
`BUS_I, BUS_TYPE, PD, QD, GS, BS, BUS_AREA, VM, VA, BASE_KV, ZONE, VMAX, VMIN`

- `BUS_TYPE`: **1 = PQ**, **2 = PV**, **3 = REF (slack)**。
  発電機バスかつ `base_kv ≥ 77` のとき PV、スラックは REF、他は PQ。
- `VMAX/VMIN` 既定 1.05 / 0.95。

### BRANCH (構築時 9 列、保存時 13 列にパディング)
`F_BUS, T_BUS, BR_R, BR_X, BR_B, RATE_A, RATE_B, RATE_C, TAP`
+ 保存時に `SHIFT=0, BR_STATUS=1, ANGMIN=-360, ANGMAX=360` を付加
(`_pad_branch_matpower`)。`TAP=0` は変圧器でない通常線。`RATE_A` は電圧クラス別の
標準定格 [MVA]。

### GEN (構築時 10 列、保存時 21 列にパディング)
`GEN_BUS, PG, QG, QMAX, QMIN, VG, MBASE, GEN_STATUS, PMAX, PMIN`
+ capability-curve / ramp 列 (11..20) は 0 = 無制約 (`_pad_gen_matpower`)。

### GENCOST (各行 7 列) — OPF 必須
`MODEL, STARTUP, SHUTDOWN, NCOST, c2, c1, c0`(多項式モデル MODEL=2, NCOST=3)。
コスト関数 `f(P)=c2·P² + c1·P + c0`。

- `c1` = 燃料種別の限界費用 [$/MWh]。`data/reference/generator_defaults.yaml`
  (JPY)を FX 150 JPY/USD で換算。ファイルが無い場合は
  `_FALLBACK_COST_USD_PER_MWH`(原子力<石炭<LNG<石油、再エネ≒0)を使用。
- `c2 = 0.001`(微小な凸性で OPF を厳密凸化し多重最適を回避)。
- merit order は燃料種別で決まり、`_gencost_fuel_key` が
  nuclear/coal/lng/oil/hydro/solar/wind/biomass を区別します。

---

## 3. `.mat` への書き出し

```python
save_case_to_matfile(case, "output/matpower/okinawa.mat")
```

- 親ディレクトリは自動生成。`do_compression=True` で大規模ケースも小さく保存。
- `mpc` 構造体でラップするため MATPOWER の `loadcase` / pandapower の `from_mpc`
  両方で読めます。

---

## 4. pandapower で検証

### 潮流 (runpp)
```python
import pandapower.converter as pc
import pandapower as pp

net = pc.from_mpc("output/matpower/okinawa_snapped.mat")
pp.runpp(net)
print(net.res_bus.vm_pu.min(), net.res_bus.vm_pu.max())
```

`examples/export_and_solve_matpower.py` は実際には
`scripts/export_powerflow_pages.build_and_solve(region, topology="snapped",
reconnect=True)` を使い、**公開マップと完全に同じ求解経路**(同じトポロジ修正・
スラック選択・バランシング・剪定)で AC/DC 収束を確認します。

### 最適潮流 (runopf)
```python
import pandapower as pp
pp.runopf(net)          # GENCOST があるので OPF 可能
```

---

## 注意点 (Caveats)

- **生 OSM ケースの OPF は緩和制約が必要**。`VMAX/VMIN`(1.05/0.95)や線の熱定格を
  そのまま使うと、合成インピーダンス・疎なトポロジ・近似負荷配分のせいで OPF が
  実行不能 (infeasible) になりがちです。電圧上下限を広げ(例 0.9/1.1 以上)、
  線定格を緩めてから `runopf` してください。
- GENCOST の絶対額は計画レベルの近似(FX 150 換算)。**merit order(相対順序)は
  意味があるが、目的関数の絶対値は鵜呑みにしない**こと。
- legacy 経路 `build_matpower_case()`(引数なし、約 2189 バス)は GeoJSON 由来の
  別モデルで、北海道は HVDC 連系のため既定で分離されます。地域単位の解析には
  snapped 経路 (`network=...`) を推奨。
- `examples/export_and_solve_matpower.py` は地域ごとに `OK / INCOMPLETE` を判定:
  `.mat` ラウンドトリップ一致 かつ gencost 行数==発電機数 かつ 潮流収束 で OK。
