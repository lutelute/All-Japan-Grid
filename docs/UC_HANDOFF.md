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
- west(中部以西の統合)はAC不成立の経緯あり、ゾーナルDC推奨
- 詳細: README「66 kV Programme — Verdict & Ceiling」・docs/reports/IMPROVEMENT_LOG.md
