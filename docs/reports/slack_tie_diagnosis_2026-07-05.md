# slack吸収の解剖と連系線フロー突合 — UC×全規模潮流の品質診断 2026-07-05

**モデル**: Claude Fable 5
**入力**: `uc_pf_built_hokkaido_east_west_okinawa_allhours_2026-07-05.json`(96断面)
**ツール**: `scripts/diagnose_slack.py`(新設・成分別slack解剖) / `scripts/uc_to_pf_built.py --inject-main-comp-only`(検証用)
**方針**: 機械は診断・定量化・材料整形まで。**接続の採用判断は人間**(オーナー 2026-07-05:
「AIや機械判定がまだ微妙」)。本レポートは判断材料であり、修正の実施判断はしていない。

## 1. 結論 — slackは1つの問題ではなく、島ごとに主犯が違う

| 島 | slack供給/負荷 | 主犯 | 数字 |
|---|---|---|---|
| east(t=17) | 37.3%(22.1GW) | **断片上の実在電源**+prune | 断片に発電容量17.9GW(451台)が孤立 |
| hokkaido(t=18) | 18.1%(0.8GW) | **断片負荷** | slack+の54.8%が断片成分(発電ゼロ成分279MW) |
| okinawa(t=11) | 56.3%(0.9GW) | **燃料別容量の不一致** | UC石油1,482MW要求 vs PF石油系600MW |
| west | (DC・5.7%) | — | DCは角度解のためslack小さめ。診断はAC化後 |

## 2. east 25.5-37.3% の4メカニズム分解(t=17実測)

```
UC需要 59,353MW に対する slack供給 22,121MW / 吸収 -5,990MW の内訳:

(1) 断片負荷            6,077MW  負荷按分が主成分外の変電所にも載る(構造的)
(2) 断片上の実在電源     17.9GW容量  奥清津1600・玉原1200・磯子1200・鹿島製鉄1152・
                                  品川1140など実在大型電源のOSM接続点が主網から孤立。
                                  容量比例注入17.0GWが断片に落ち、-6.0GWを断片slackが
                                  吸収し、主成分は同量を主slackで再供給する二重計上
(3) prune起因の未達     ~8.8GW  ピーク断面のAC収束はprune ladder(発散枝の刈り)で成立
                                  → 注入53.5GWに対し実受電44.6GW。「収束」の代償
(4) 実損失              5-6GW   下位網のR/X典型値・低電圧バス(vm 0.63-0.68)の症状
```

**検証実験**(`--inject-main-comp-only`): 断片gen 451台を停止すると slack は16.1→20.1GW
へ**悪化**する。理由=断片上の電源は幻ではなく**実在**(石炭系はzone別に見ると主成分側
容量が不足し coal 4,320MW が clip)。つまり「注入先の除外」は解でなく、
**根本解=断片接続の修復(人間判断)** または **発電接続を主成分バスへ張り替える
接続ポリシー変更(要オーナー判断)** の二択であることが数字で確定した。

## 3. 連系線フロー突合(UC=OCCTO運用容量制約つき vs PF=網インピーダンス自然配分)

### east: tohoku→tokyo(容量5,550MW) — **整合**
- 24時間: MAE 384MW(フローの~7%)・median差 -61MW
- UCが容量上限に張り付く時間帯もPFは±数百MWで追随。OSM網の自然な潮流配分が
  OCCTO連系線容量と整合するという、モデル全体の**正の検証結果**

### west(t=11) — 大きな乖離(DC・容量制約なしの構造差)
| 区間 | UC | PF(DC) | 所見 |
|---|---|---|---|
| chubu→kansai | 2,530(容量上限) | 4,690 | 網は契約容量の1.9倍を流したがる |
| chugoku→shikoku | +219 | **-3,098** | 方向逆転。下の幻ルートと関連疑い |
| kansai→shikoku | -1,400 | -142 | 過小 |

### 発見: 実在しない連系線「kyushu↔shikoku 445MW」
PFのzone跨ぎ集計に **九州-四国間のtie潮流445MW** が存在する。**現実にこの連系線は
存在しない**(OCCTO連系線10本にも無い)。built内のzone境界誤り(region誤属性の線)か
OSMの誤接続。→ **人間レビュー案件**(座標・該当線の特定は次段の作業。west側の
tie乖離の一部もこの幻ルート経由の可能性)

## 4. 次の一手の選択肢(判断材料 — 実施は要オーナー判断)

| 選択肢 | 効く先 | 性質 |
|---|---|---|
| A. 断片接続の修復(梃子候補210件のレビュー) | east(2)(3)・hokkaido(1) | **人間判断**。エディタ(:8088/editor)でのレビューが前提 |
| B. 発電接続を「最寄り主成分バス」へ変更 | east(2) | モデリングポリシー(機械実装可・物理的にも妥当=実在電源は実網に繋がっている)。ただし距離が伸びるケースの扱いは要判断 |
| C. 負荷按分を主成分限定にする(断片=unserved明示) | (1) | ポリシー変更。誠実性は上がるが「需要の一部を配らない」ことの明示が必要 |
| D. okinawaの燃料フリート較正(capacity_bridge適用) | okinawa | 既存機構(uc_to_pf_nationalで使用中)のbuilt系への移植 |
| E. kyushu-shikoku幻tieの特定と修正 | west突合 | 特定は機械・修正判断は人間 |

## 5. 再現

```bash
PYTHONPATH=. python scripts/diagnose_slack.py --island east --hour 17
PYTHONPATH=. python scripts/diagnose_slack.py --island okinawa
PYTHONPATH=. python scripts/uc_to_pf_built.py --islands east --hours 17 --inject-main-comp-only
```
出力: `slack_diagnosis_{island}_t{h}_2026-07-05.json` / `uc_pf_built_east_t17_maincomp_2026-07-05.json`
