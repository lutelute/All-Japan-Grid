# 介入 #19/#20/#21 の既定ON化 — 判断パッケージと実施記録（2026-07-10）

- **決定**: 介入 #19（県別実需要配分 `--pref-demand`）・#20（無効電力の局所補償 `--reactive-comp`）・
  #21（bbox二重抽出のdedup `--dedup-nodes`）の3件を **既定ON** にする。
  オーナー承認 2026-07-10（「アクション全て実行しよう」— 07-09引き継ぎ§3の既定ON化判断に対する承認）。
- **理由（一言で）**: #21は正典に元からあった**同一物理線の二重計上**（境界線インピーダンス半減→損失過小）の
  是正であり、既定OFFのままでは配布物が既知欠陥入りになる。#19/#20は east full AC の正しい前提
  （真実の需要地理＋実在する無効電力設備のモデル化）であり、全島24h検証済み
  （`allisland_24h_reactive_2026-07-09.md`）。
- **範囲**: `build_island_net`（既定 `dedup_nodes=True`）と、その正規CLI 3本
  （`run_full_powerflow_from_db.py` / `uc_to_pf_built.py` / `gen_ybus_numeric.py`）。
  #8 boundary-injection / #13 bridge は**今回の対象外**（従来どおり opt-in）。
  MATPOWER national 出荷（`export_national_matpower.py`）は別ビルダー（snapped系譜）のため**非対象**。

---

## 1. 無効化手段（介入台帳の3点セット③）

| 従来挙動に戻す | フラグ |
|---|---|
| zone一様の需要配分 | `--no-pref-demand` |
| 無効電力補償なし | `--no-reactive-comp` |
| dedupなし（二重計上込み） | `--no-dedup-nodes` |

**不変量**: 本コミット時点の HEAD で `--no-*` 3連を付けた実行は、フリップ前 HEAD のフラグ無し実行と
完全一致する（下記プローブの old 列がまさにそれ）。

---

## 2. 証拠1 — 全島 before/after プローブ（8ラン・プロセス隔離・生JSON同梱）

`probes/default_on_2026-07-10/`（`run_probe.sh` → `compare.py`、生JSON = `{old,new}/{island}/summary.json`）。
old=従来既定（3フラグOFF相当）、new=新既定。**差分は3介入の合成効果**である点に注意
（介入単体の単離は各レポート: #19=`a_plan_east_ac_regression_2026-07-08.md`§7・
#20=`east_network_reactive_2026-07-09.md`§3・#21=`west_fragmentation_rootcause_2026-07-09.md`§5-7 で実施済み）。

| 島 | 指標 | old | new | 差 |
|---|---|---|---|---|
| hokkaido | バス / 成分 | 819 / 52 | 802 / 35 | −17 / −17 |
| hokkaido | AC | 収束 | 収束 | loss 75.7→81.7MW |
| east | バス / 成分 | 6,222 / 532 | 6,002 / 312 | −220 / −220 |
| east | AC | 収束 | 収束 | loss 2,087→2,736MW（+31%） |
| west | バス / 成分 | 10,193 / 2,531 | 8,204 / 544 | −1,989 / −1,987 |
| west | AC / DC | AC不成立 / DC成立 | AC不成立 / DC成立 | 設計どおりDC運用維持 |
| okinawa | バス / 成分 | 99 / 7 | 98 / 6 | −1 / −1 |
| okinawa | AC | 収束 | 収束 | loss 16.5→15.8MW |

機械判定（`compare.py`）: **4島すべて「解成立の退行なし」かつ「成分数の改善」= 総合OK**。

読み方の注意（誠実性）:
- **east の損失増（+648MW）は改悪ではなく是正**。二重計上エッジの除去で境界線のインピーダンス半減が
  解消され（#21）、県別需要（#19）で需要地理が真実化した結果。07-05以前の「低い損失」は
  誤需要地理＋二重計上の上の値だった。
- east `vm_max` 1.59→1.75 は既知の**66kV軽負荷ポケット41バス（0.66%）**（`east_network_reactive_2026-07-09.md`§4）。
  次の網側精緻化対象であり、本既定化で新たに生じたものではない。
- west は引き続き **full AC 不成立 = 誠実にDC**（dedupは断片化を直すがACの特効薬ではない: 同§5「限界」）。

## 3. 証拠2 — ゲート44件 PASS とピン更新2件

`pytest tests/test_substation_structures.py tests/test_ybus_numeric.py tests/test_transformer_provenance.py
tests/test_region_attribution.py -q` → **44 passed**。

既定フリップに伴い**回帰ピン2件を意図的に更新**（ピンの更新規約「意図的なモデル改善時のみ」に該当）:
- `test_regression_pin_okinawa`: n_bus 99→98（島内重複ノード1件のdedup。nnz/n_trafoは不変）
- `test_v4_version_and_changelog`: YBUS_VERSION 4.0.0→5.0.0

## 4. 証拠3 — 数値Ybus正典 v5.0.0（指紋系譜）

`gen_ybus_numeric.py` 再生成。全島で対称性=機械精度・再構成恒等式=機械精度・gate=PASS。
meta.json に `dedup_nodes`（enabled / n_node_merged / n_edge_dup_removed）を刻印。

| 島 | v4 bus | v5 bus | v4 fingerprint | v5 fingerprint | dedup(node/edge) |
|---|---|---|---|---|---|
| hokkaido | 836 | 802 | `2acdbc3d0fef5f91` | `b424beb42770b931` | 17 / 4 |
| east | 6,205 | 6,002 | `c0392c7804117e90` | `d9f56d06cf23142b` | 220 / 191 |
| west | 10,193 | 8,204 | `5e196db1f9a3d2df` | `4dc8dad77e8523ec` | 1,989 / 1,440 |
| okinawa | 99 | 98 | `2a5c0ef0ca6210e7` | `de38456ec9b77fec` | 1 / 0 |

**注**: v4→v5 のバス差は dedup 単独ではない。v4 生成（07-04）は A案 territory 既定化（07-07）**以前**で、
v5 は「territory 再属性 + dedup」の初回正典再生成（例: hokkaido 836 −(territory 17) −(dedup 17) = 802）。
v4 の完全再現は当時のcommitのチェックアウトによる（`--no-dedup-nodes` 単独では territory 分が残る）。

## 5. 併せて実施 — #20 補償率0.6の出典アンカー（格上げ）

`reactive_comp_provenance_2026-07-10.md`（一次資料調査）: 四国電力送配電のEGC提出実測
（2024・URL/逐語引用つき）から換算し、**直近実測≈0.8・1990年代≈0.05 のレンジ内で 0.6 は保守側**
（送電端力率0.991相当・2000年代中盤水準）と裏づけた。「中央値設定・実測値ではない」注記は
「一次資料アンカーの保守側」に更新（台帳#20）。**0.8への引き上げは要再スイープの将来課題**
（単一TSO・グラフ目視±10-15%のため今回は見送り）。

## 6. 残課題（この決定で消えないもの）

1. east 電圧外れ値41バスの網側精緻化（並列回線・変圧器容量・無効配分の現実化）
2. west full AC（本丸はトポロジ接続回復・GridStitch系）
3. 96断面 UC×潮流正典の新既定での再生成（→ v1.6.0 リリースとセット）
4. #8/#13 の既定判断（未着手のまま）

---

*関連: `docs/MODEL_INTERVENTIONS.md` #19/#20/#21（台帳更新済み）・
`osm_grid_pitfalls_methodology_2026-07-10.md`（本件診断群の方法論統合）*
