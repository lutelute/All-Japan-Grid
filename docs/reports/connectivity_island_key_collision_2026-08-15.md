# 連結性の島判定バグ — 座標キーの先勝ち衝突で境界の枝が黙って捨てられていた

- 日付: 2026-08-15（深夜の自律作業）
- 対象: `src/powerflow/connectivity.py::compute_connectivity`（連結性の単一権威）
- 種別: **検証器のバグ修正**（モデルデータは不変・介入ではない）
- 修正コミット: e54186f
- 効果: **本系統外ノード 2107 → 1885（222ノード回復）**

## 何が起きていたか

`compute_connectivity` は座標キー(round5≈1m)を頂点として島(hokkaido/east/west/okinawa)ごとに
連結成分を計算する。座標キー→島の対応を `island_of.setdefault(key, island)` で作っていたため
**最初に現れたノードの島が勝ち**、同一座標に別島ラベルの重複コピーがあると、
もう片方の島ではその座標キーが「他島のもの」と judged され、**そのキーに触れる枝が
すべて黙って捨てられていた**。

## 衝突の実測（2026-08-15・現正典）

| パターン | キー数 | 実体 |
|---|---|---|
| east↔west | 203 | 中部↔東京境界（静岡・長野）の junction 重複。`tokyo junction X` と `chubu junction X` が**完全同一座標** |
| east↔hokkaido | 17 | **下北半島**（青森県）の変電所・junctionにhokkaidoラベルの完全重複コピー |
| 計 | **220** | |

## 実害の代表例 — 下北半島

下北変電所(154/66)・大畑・大湊・仲崎・佐井・東通・東通村・岩屋には
**hokkaidoラベルの完全重複コピー（同名・同kv・同一座標）**が存在する
（大間の region 誤タグ＝介入#28 と同じ bbox 混入。青森箱 lat<41.6, lon>140.6 内の
hokkaido ラベルは 20 ノード）。ノード列で hokkaido コピーが先に現れるため
座標キーが hokkaido 島に奪われ、east 島では下北半島に触れる**OSM実在の枝がすべて捨てられ**、
半島全体が「孤立変電所」として監査に載っていた。

→ **孤立変電所監査（705件→v1適用後685件）の一部は、モデルの欠損ではなく
検証器の人工物だった**。修正だけで 222 ノードが本系統に復帰した。

## 修正

エッジの島内判定を「先勝ちの island_of」から**島ごとの座標キー集合**に変更:

```python
# before: island_of.get(ka) == isl and island_of.get(kb) == isl
# after:  ka in island_keys[isl] and kb in island_keys[isl]
```

キーは複数の島に属してよい（重複コピーが実在する以上、それがデータの実態）。
各島は自分のノードが立つキー同士の枝だけを見る。返り値の互換は維持
（`island_of` は表示用にそのまま残る）。

## 検証

- 修正後、下北変電所(tohoku)は**既存OSM枝だけで** east 本系統に復帰（main=True）。
  公表線（下北A,B線→六ヶ所154 等）は worklist v2 が実線として上乗せする。
- 本系統外 2107→1885 の差 222 ≒ 衝突キー数 220 と整合。
- 島の成分数: east 307 / west 685 / hokkaido 35 / okinawa 6（修正後・v2適用前）。

## 限界・残課題

- east↔west の junction 重複 203 キーは**データとしては残っている**（今回の修正で
  連結性の実害は消えたが、二重登録そのもの＝跨region重複884組[topoRAG]の解消は別課題）。
- 青森箱の hokkaido ラベル 20 ノードの region 是正は worklist v2（介入#29）に同梱
  （連結性はキー集合修正だけで直るが、region は負荷配分・島統計に効くため是正が必要）。
- run_full_powerflow_from_db は compute_connectivity を使わない（region→島で直接組む）ため
  潮流側にこのバグの影響はない。影響範囲は監査・ビューア(built_view)・エディタ(build_editor_data)・
  apply系スクリプトのドライラン数値。
