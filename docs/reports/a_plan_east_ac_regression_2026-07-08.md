# A案回帰の原因確定 — east全規模ACを壊したのは「需要の空間配分」（2026-07-08）

## 0. 結論（1段落）

zone領土再属性（A案, `bafca13`）が east 全規模AC（6,205バス）を壊した回帰
（territory=False→thr45で99.0%給電AC / True→10.8%見せかけ解のみ）の原因を、
7変種の切り分けプローブで**「同一島内の zone 貼り替えが `allocate_loads` の
需要空間配分を変えること」単独**と確定した。当初の容疑者だった
**plants osm_id dedup と青函の島構成変化は無罪**（物理トポロジがT0と完全同一でも
壊れる）。注入マスク側の寄与は軽微（単独なら prune 一段深い thr=30 で正当なAC解に到達）。
含意として、**07-05の「east全規模AC 99.0%」は誤った需要地理（bbox由来zone）の上に
成立していた限界的な解**であり、需要地理を領土に正すと成立しない。

## 1. 背景

- A案 = ノード region を「座標→県ポリゴン→一般送配電エリア」で再属性
  （`src/powerflow/region_attribution.py`、`build_island_net` 既定ON）。
  幻tie消滅・本四復活など tie 構造の修正には成功
  （`docs/reports/phantom_tie_zone_contamination_2026-07-07.md`）。
- 一方で 07-07 のプローブで east 全規模AC が territory=True でのみ破綻すると判明
  （ハマり⑩の給電率ガード served≥95% が見せかけ解を却下 → 誠実 dc_fallback）。
  原因候補として (a) plants dedup による発電分布変化、(b) 青函再属性
  （hokkaido↔tohoku 26/9ノード）の島構成変化が挙げられていた。

## 2. 方法

east full・fy2023r2・t=12 注入・正典と同一の prune ladder
（thr=None→45→30→20）＋有界ACチェーン＋給電率ガード（served≥95%）。
1変種=1プロセス（ハマり⑨ BLAS abort 隔離）。プローブ一式は
`docs/reports/probes/a_regression_2026-07-08/` に保存（スクリプト2本＋生JSON5本）。

### 第1弾: A案の2成分を独立に切る（4変種）

| 変種 | 再属性 | dedup | バス | 発電機 | 判定 |
|---|---|---|---|---|---|
| T0（旧挙動） | OFF | OFF | 6,205 | 8,514 / 195,138MW | ✅ **AC thr=45 served 0.9897 loss 5,797MW** |
| T1（A案） | ON | ON | 6,222 | 8,235 / 186,597MW | ❌ dc_fallback（thr=20 で見せかけ 0.1078） |
| T1_nodedup | ON | **OFF** | 6,222 | 8,514 / 195,138MW | ❌ dc_fallback（同一署名 0.1078） |
| T1_noseikan | ON（島跨ぎskip） | ON | **6,205** | 8,235 / 186,597MW | ❌ dc_fallback（同一署名 0.107） |

- T0/T1 は 07-05/07-07 の良基準・悪基準を数値まで再現（プローブの妥当性）。
- **T1_noseikan は物理トポロジ（6,205バス・517成分）が T0 と完全同一**なのに破綻
  → 犯人は物理構成でなく **zone ラベル**。dedup も無罪（T1_nodedup が破綻）。
- 注入の集計（load_scale 0.7742/1.1052・clip coal 968MW・unmatched 0）は
  **全変種で同一** → 集計でなく空間配置の問題。

### 第2弾: zone の使用箇所を外科的に分解（3変種）

同一ネット（再属性build・島跨ぎskip・dedup OFF = T0とトポロジ/発電機完全同一）で、
`net.bus.zone` を需要配分時と注入時に別々に差し替え:

| 変種 | 需要配分zone | 注入zone | 判定 |
|---|---|---|---|
| Z_sanity | 旧 | 旧 | ✅ AC thr=45 **served 0.9897 / loss 5,797.2MW（T0とbit一致）** |
| **Z_loads_new** | **新** | 旧 | ❌ **dc_fallback**（thr=45/30非収束・thr=20見せかけ0.1084） |
| Z_inject_new | 旧 | 新 | ✅ AC thr=30 served 0.9912 / loss 6,480MW |

**需要配分だけを新zoneにすると T1 と同一署名で破綻。** 注入マスクだけなら
prune が一段深くなる（45→30）ものの正当なAC解に到達する。

## 3. メカニズム（定量）

同一島内の貼り替えの実体（`region_attribution` の県ベース再属性）:

- **tokyo→tohoku 233ノード** = 新潟県128 + 福島県105（500kV×14・275kV×11・66kV×122）
  — 柏崎刈羽・福島浜通り一帯の東京電力設備を含む帯
- **tohoku→tokyo 117ノード** = 栃木県92 + 群馬県14 + 茨城県11（500kV×9・66kV×74）

`allocate_loads` は zone 一様×電圧階級重み（66kV=0.5 … 500kV=0.05）で
地域ピーク（tokyo 52,000MW / tohoku 13,000MW × lf0.85）を配るため、
zone が変わると**1バスあたり需要が跳ぶ**:

- 66kVバスの受け持ち: tokyo属 23.6MW ⇄ tohoku属 11.3MW（**約2倍差**）
- 負荷を持つ移動バス110個の合計: 新潟・福島側 1,419→671MW（−748MW）、
  栃木・群馬・茨城側 414→866MW（+452MW）
- 正味 **約1GW規模の需要が回廊帯（東北南部＝東京北部の弱い66kV網）で移動**し、
  thr=45/30 の prune 後ネットが NR 非収束に転落する。

## 4. 解釈（誠実に）

1. **A案は間違っていない**: 新潟=東北NW供給区域・栃木=東京PG供給区域は事実であり、
   貼り替え後の需要帰属の方が現実に近い。
2. **壊れた真因は需要配分モデルの粗さ**: 「zone内一様×電圧重み」は、県をまたいで
   需要密度が大きく違う現実（東京都心と栃木県北部が同じ 23.6MW/66kVバス）を
   表現できない。誤ったzone（bbox）では偶然バランスし、正しいzone（領土）では
   矛盾が露呈した。
3. **07-05「east全規模AC 99.0%」の再解釈**: この解は誤需要地理の上の限界解。
   territory=False での AC 主張には「旧需要地理」の注記が必要
   （成果物引用ルール: 「AC収束」はprune込み明示、に追記対象）。
4. backbone 計算モデル（+bridge+境界注入で slack≒損失 3.06%）はこの問題の影響を
   受けにくい（需要・発電を≥154kVへ帳簿つき集約するため 66kV 帯の空間配分粗さが
   消える）— full と backbone の判定が割れた理由も同じ構図。

## 5. 対応の選択肢（オーナー判断・自動採用しない）

| 案 | 内容 | 評価 |
|---|---|---|
| (a) 需要配分の細分化 | zone一様→県/市区町村単位の実需要（販売電力量・人口）按分。A案の領土zoneと組で初めて需要地理が閉じる | **根本対応・推奨（中期）**。出典必須DB方針と整合 |
| (b) prune ladder拡張・Q制約緩和 | fullのAC探索を深くする対症療法 | 見せかけ解ガードはあるが「AC成功」の意味が薄まる。非推奨 |
| (c) 現状の誠実運用 | full=dc_fallback表示（現状動作）・AC実証はbackboneが担う | **ゼロ工数・短期はこれ**。既にガードが機能しており嘘はない |
| (d) 需要だけ旧zone維持 | allocate_loadsのみ region_src を使う | 誤地理の固定化=不誠実。**却下推奨** |

短期 (c) ＋ 中期 (a) を推奨。(a) に着手する場合は出典付き需要データ
（各社販売電力量・県別需要）の収集が先行タスクになる。

## 6. 再現手順

```bash
# 第1弾（4変種・プロセス分離）
.venv/bin/python docs/reports/probes/a_regression_2026-07-08/probe_a_regression.py T0 /tmp/T0.json
# 第2弾（zone機構分解・3変種）
.venv/bin/python docs/reports/probes/a_regression_2026-07-08/probe_a_regression2.py /tmp/probe2.json
```

生JSON（本レポートの全数値の出所）: 同ディレクトリの
`T0.json / T1.json / T1_nodedup.json / T1_noseikan.json / probe2.json`。
