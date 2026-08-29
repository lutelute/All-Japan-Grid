# 第6波: westフルスケールAC — 軽井沢・嬬恋ポケットの解剖と介入#38 (2026-08-30)

## 出発点
介入#37でwest backbone(≥154kV)はAC成立(`provisional_infeed_decision_2026-08-30.md`)。
フルはDCのまま → キラーは154kV未満の層に確定。#37適用後の新ベースラインで
フルネットNRを k=1..6 で止める onset 診断を実施。

## 発見1: 震源は大阪でなく長野東信〜群馬 (`west_ac_onset_full_2026-08-30.json`)
- iter=1 で |V|∈[0.352, 6.649]、偏差>0.15 が 66kV×22 + 77kV×29 バス(154kV以上ほぼ無傷)
- 上位はすべて [chubu] の 軽井沢変電所・大字御代田変電所・chubu junction 36.3:138.5
  (御代田)・36.52:138.6 (**群馬県嬬恋**) — |V|>6 の異常上昇型で振動発散

## 発見2: 三方向裏取り(コード・データ・実世界)
1. **島分けはregionラベルのみ** (`build_island_net` L260: `ISLAND_OF[n["region"]]`)。
   regionは抽出bbox由来ラベル+領土再属性(座標→県→エリア)だが、**周波数跨ぎ
   全面ガード**(region_attribution.py)が是正を恒久スキップ
2. **抽出こぼれの実在**: 群馬(嬬恋77kV群・榛名275/500kV junction)・埼玉(JR東
   神保原)・神奈川(鴨宮)・山梨(リニア都留)の座標なのに region=chubu。
   bbox(東信)内229ノードは tokyo/chubu の二重登録(同一施設ペア多数)
3. **#35の逆流**: apply_node_hygiene(周波数ガード無し)が tokyo junction 8件を
   chubu へ再帰属(実データ hygiene=intervention35 で確認)
4. **実世界**(出典つき): 軽井沢・御代田・小諸・佐久は**中部電力PG供給区域**
   (東電PGの長野県内供給区域は存在しない)。50Hzは小諸市・佐久市の一部+
   軽井沢町の一部のみ。50/60Hzの県内交流接続は無し(接点は新信濃FCの交直変換のみ)。
   JR東の自営送電線は新潟→群馬→埼玉(神保原・岡部)で長野へは達しない。
   ただし東電PGの66kV碓氷線は軽井沢開閉所まで到達(東電群馬系統図)

## 発見3: 神保原=(b)region誤ラベル (jinbohara-probe)
JR東神保原変電所(埼玉県上里町, 座標正)が region=chubu で west に混入し2バス孤立
クラスタ化 → #37 が同じく誤帰属の榛名junctionへ **44km誤縫合**。

## 介入#38: 周波数跨ぎ再属性の精緻化 (本波で正典化)
ガードの動機は混在県(長野=東信の一部50Hz・新潟・静岡)の飛び地保護であり、
**周波数が県内で一意な県への抽出こぼれまで保護するのは過剰**。
`UNIFORM_FREQ_PREFS`(関東7都県+山梨=50Hz、愛知以西+北陸=60Hz)への是正に限り
跨ぎ再属性を許可。#35にも同ガードを追加。#37には max_dist_km=40 上限
(超過は capped=True で台帳のみ=誤帰属縫合の検出面化)。
- ドライラン: 是正275件(chubu→tokyo 266・tokyo→chubu 9)。
  長野の50Hz資産(tokyo→chubu 143件)はガード維持
- 退避: `--no-freq-fix-reattr`(両ドライバ・pref_demand貫通)

## 検証 (fy2023r2ピーク断面)
| ケース | before | after #38 |
|---|---|---|
| west backbone AC | ac・(仮)7件・slack 6,155MW | **ac維持**・(仮)6件(神保原縫合消滅)・slack 5,608MW |
| east full | ac・slack 5,229MW | **ac**・slack 5,154MW・(仮)1件(鴨宮114MW→新秦野15km、受入側で正しく台帳化) |
| west full onset | iter=1〜6 振動発散 \|V\|∈[0.009, 8.52] | **iter=5で収束** \|V\|∈[0.798, 1.031]、残偏差は江田島0.67等の局所低電圧のみ |
| west full 正典 | dc (ISLAND_MODE) | (下記) |

## west full 正典ACの判定
`ISLAND_MODE["west"]="ac"` に切替後の正典CLI(uc_to_pf_built・fullモデル・
prune ladder+served≥95%ガード込み)、fy2023r2 ピーク断面 t=17 (69,938MW):

- **solver=ac・converged=True・served 100.0%・6.6s — westフルスケール
  (7,928バス)のAC解がプロジェクト史上初めて成立**
- (仮)#37は9件計1,440MW(全て3〜28kmの近距離縫合・capped無し)
- 正直な開示: slack合計9,176MW(需要比13.1%、DC時6,305MWより増 — AC損失
  2,871MWをslackが負担)、vm_min=0.667(江田島66kVポケット等の局所低電圧)。
  次の改善候補=slack配分の地理検証・江田島/三国77kVの給電構造
- 失敗時はsolve_hourのdc_fallbackが残るため運用安全側

## 帰結
1. 介入#38を正典化(既定ON)・#35ガード・#37距離上限・ISLAND_MODE west→ac
2. 残宿題: 江田島・大阪三国の局所低電圧(<0.75pu)の構造調査、
   新潟・静岡・長野の混在県は個別ポリゴン/リスト化するまでガード維持、
   tokyo_sub接頭辞×西regionの41件監査(disclosure v2 region_fix由来の疑い)
