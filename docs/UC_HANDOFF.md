# UC開発への引き渡し条件 — Ybus出荷品質ゲート

別プロジェクトで開発中のUC(起動停止計画)がこの系統モデルを安全に消費するための契約。
**ユーザー指示(2026-06-11): UCを解く際は必ずYbus判定を通すこと。**

## ゲートの実行

```bash
PYTHONPATH=. python -m src.powerflow.ybus_gate tokyo            # フルモデル
PYTHONPATH=. python -m src.powerflow.ybus_gate --backbone tokyo # 縮約モデル
# 終了コード: 0=PASS / 1=FAIL(島名つき) / 2=データ無し
```

プログラムからは `src.powerflow.ybus_gate.ybus_gate(net)` — pandapower netを渡すと
島別の縮約Ybus条件数(1ノルム推定・密逆行列なし)と pass/fail を返す。

## 保証内容（2026-06-11計測）

全10地域のフルモデルが **PASS**（閾値 1e9）:

| 範囲 | cond₁(縮約Ybus) |
|---|---|
| 最良 okinawa | 5.6e5 |
| 最悪 chubu/tokyo | 1.2–2.0e8 |

- 閾値1e9は**既知良品(AC収束する全10地域)の最悪値の1桁上**に較正
- 既知不良(west統合島=連鎖変圧器でAC NR崩壊, docs/WEST_AC_ANALYSIS.md)は
  この閾値を大きく超える見込み — west構築時の実測が残TODO

## UC側の使い方の約束

1. 網を取得（`ajgrid solve <region> --source db` 等）したら **解く前に ybus_gate**
2. FAILした島の上の最適化結果は数値的に無意味 — 解かずに島名を報告する
3. ゾーン集約UCなら島単位の集約が安全（島はゲート出力 `islands` に列挙）

## モデル側の既知の限界（正直な注意書き）

- 需要 = 実測ピン(東電開示1,222変電所) + 合成残差。時系列ではなく断面
- 定格(max_i_ka)は標準値ベース — UC の線路制約に使うなら余裕係数を
- west(中部以西の統合)は2026-06-12以降AC収束(台帳63/85/91: プルーン12°段+OSM忠実束縛)。島単体ACは vm_min~0.67(西伊豆・四国放射の正直な物理)を含む — 電圧品質が要る用途は注意
- 詳細: README「66 kV Programme — Verdict & Ceiling」・docs/reports/IMPROVEMENT_LOG.md


## 燃料別帯判定の intake デモ（F5/X3・台帳94）

UCの時系列（または断面）を**実測の年間帯（q50..p95）**に通す入口は
`ajgrid reconcile --uc-csv <file>`。CSV契約は3列:

```csv
area,metric,value_mw
関西,demand_mw,16039
関西,gen_by_fuel:nuclear,6578
関西,gen_by_fuel:thermal_combined,5299
```

- `metric` 語彙: `demand_mw` / `gen_by_fuel:{nuclear,gas,coal,oil,hydro,
  geothermal,biomass,solar,wind,pumped,battery,interconnect,thermal_combined,
  thermal_other}`。**火力を合算でしか公表しない社（関西・中国）は
  `thermal_combined`** — モデル側検証（--solve-region）でも gas+coal+oil 合算で
  同じ帯に通る
- 帯の出典: 東京=TSO需給実績12ヶ月(F2) / 関西9・中国9・北陸14帯=研究室NAS
  `demand_raw`（F7、`scripts/db/calibrate.py --nas03 ...`で再現） /
  需要=OCCTO（M10）。すべて `measured_area_stats`（data/grid.db）
- 実演（UC fy2025r1 の 2023-12-13 関西断面・日量→時平均MW換算）:

```
UC 関西/demand_mw:             16,039 MW -> q50..p95 (q50 15,272 / p95 23,031)
UC 関西/gen_by_fuel:nuclear:    6,578 MW -> >p95    (q50 4,883 / p95 5,636)
UC 関西/gen_by_fuel:hydro:        792 MW -> <q50    (q50 1,369 / p95 2,475)
UC 関西/gen_by_fuel:thermal_combined: 5,299 MW -> <q50 (q50 7,276 / p95 11,741)
UC 関西/gen_by_fuel:solar:        932 MW -> q50..p95
```

読み方: 帯はFY2023-24実測の**年間分布**なので、断面の正否でなく
「分布のどこにいるか」を返す。上の nuclear >p95 は fy2025r1 シナリオの
原子力断面（6.6GW）が検証日（2023-12、4.9GW平均）と**ビンテージ違い**で
あることを正しく検出した例（UC側 ledger 22 と同じ結論に独立到達）。
帯外=エラーではなく「シナリオと実測断面の前提差を述べよ」のシグナル。
