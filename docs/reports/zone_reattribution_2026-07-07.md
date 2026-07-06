# zone再属性（A案）実装 — 幻tie消滅・本四復活・複数zone並存1,623→10

- 日付: 2026-07-07 / モデル: Claude Fable 5
- 位置づけ: `phantom_tie_zone_contamination_2026-07-07.md` で提示した修正オプションのうち
  **A案（座標→県→エリアの領土再属性・物理接続は不変）** のオーナー承認を受けた実装。
- 再現: `PYTHONPATH=. .venv/bin/python scripts/diagnose_zone_contamination.py --island west`
  （`--no-territory` で旧挙動と比較可能）

## TL;DR

builtノードの region を「抽出bbox出所」から「領土（座標→都道府県→一般送配電エリア）」へ
再属性した（**17,333ノード中2,855変更・物理接続は無変更・周波数を跨ぐ移動は禁止**）。
幻tie「kyushu↔shikoku」は消滅し、不可視だった本四連系線が tie として復活、複数zone並存
座標は 1,623→**10**（飛騨境界の既知残渣のみ）。発電所の重複付与（下関火力の二重計上等）も
osm_id dedup（領土地域コピー優先）で解消した。

## 1. 実装

| 部品 | 内容 |
|---|---|
| `data/reference/japan_prefectures_simplified.geojson` | 県ポリゴン47件（国土地理院 Global Map Japan v2 由来 dataofjapan/land を簡略化0.002°・出典はファイル内`_meta`） |
| `src/powerflow/region_attribution.py` | `area_of_coord(lat,lon)`＝点内包（沖合は最近傍県）→県→エリア。静岡のみ富士川（lon≥138.62→tokyo）で分割 |
| **周波数ガード** | **50/60Hzを跨ぐ再属性は禁止**（`AREA_FREQ`）。県近似は周波数境界で実態と乖離する — 新信濃変換所（東京電力50Hz・長野県）や佐久・軽井沢（東京電力エリア in 長野県）を chubu へ移すと east の実在50Hz幹線（安曇幹線等）が切れる。同一周波数内の誤属性だけを直し、境界の帰属は抽出元ラベル（OSMトレースの連続性）を保持。skipped_freq として開示: chubu→tokyo 249 / tokyo→chubu 210 / chubu→tohoku 41 / hokuriku→tohoku 22 |
| `build_island_net(..., territory=True)` | バス化前にノードregionを再属性（既定ON・`region_src`に旧値を退避・冪等）。同一周波数内の島所属も正しくなる（青函: hokkaido→tohoku 26 / tohoku→hokkaido 9） |
| `attach_generators(..., territory=True)` | 同一osm_idの重複コピーを1回だけ採用（領土地域のファイル優先） |
| `tests/test_region_attribution.py` | 関門・本四・青函・富士川・嶺南・周波数ガードなど19ピン |

## 2. 効果（diagnose_zone_contamination 07-07 同日before/after）

### west（10,193バス/9,793線 — 島構成は不変）

| 指標 | before | after |
|---|---|---|
| 複数zone並存座標 | 1,623箇所 | **10**（chubu\|hokuriku飛騨残渣のみ） |
| kyushu↔shikoku（幻ペア） | 2本 | **0本（消滅）** |
| 本四連系線（chugoku↔shikoku 500kV） | **0本（不可視）** | 2本（復活） |
| 関門（chugoku↔kyushu） | 99本(500kV 1) | 5本(500kV 3) |
| chubu↔hokuriku | 225本 | 33本 |
| kansai↔shikoku | 9本(全て徳島県内の誤属性) | 3本 |
| zone跨ぎ線 総数 | 613本 | **90本** |

### east（6,205→6,222バス — 青函修正分）

tohoku↔tokyo 跨ぎ 50→30本（500kV 3→11本 = 相馬双葉幹線等の実回廊がクリアに）、
並存139→0。

## 3. west backbone 24h のやり直し（slack と tie 突合）

### slack の弧（誠実化→較正）

| 構成 | mean \|slack\|/demand | 分解 |
|---|---|---|
| 07-05正典（汚染+重複あり・旧計器） | 7.44% | 残差9.17%が未計装（重複発電の見せかけ受け皿が slack を人工的に低く見せていた） |
| A案+plants dedup（bridgeなし） | 13.92% | 正直化で露出: clip 4.27%（kyushu原子力等）+ **unmatched 10.97%＝嶺南原発**（下記）− 輸出3.30% |
| A案+dedup+bridge+**原発zone_override** | **2.14%**（signed **−2.13%**） | unmatched 10.97→**0.04%**。負のslack≒**東西FC輸出2,100MW/h** をPF島が吐き出せない構造項（境界注入=次のレバーで消える見込み） |

**嶺南原発の発見**: A案で高浜・大飯・美浜が立地どおり hokuriku zone になったが、UCは
**関西電力の電源として kansai にディスパッチ**する（毎時~6.6GW が unmatched 化）。
立地と電源計上エリアの乖離は `nuclear_status.yaml` の region（既存参照データ）から
capacity_bridge が **gen単位 zone_override** を出すことで解消（橘湾・敦賀火力と同じ機構）。

### tie突合（PF zone跨ぎ集計 vs UC連系フロー・bridged 22h）

| ペア | MAE | PF平均 | UC平均 | 所見 |
|---|---|---|---|---|
| kansai↔shikoku（阿南紀北） | **198MW** | −1,539 | −1,385 | **正の検証**。OSMがDC幹線を線としてトレースしており、インピーダンスモデルでもほぼ同量が流れる |
| chubu↔hokuriku | 408MW | 96 | 228 | 概ね整合 |
| chugoku↔shikoku（本四） | 531MW | −721 | −190 | 復活した本四が可視。方向は一致 |
| chubu↔kansai | 3,065MW | 3,456 | 391 | **PFは枝容量制約なしの自然配分**（UCは運用容量2,530で制約）— 構造差 |
| hokuriku↔kansai | 6,556MW | 6,847 | 291 | **嶺南原発の自社幹線潮流**（高浜・大飯・美浜→関西、~6.8GW）が県境跨ぎに計上される。OCCTO連系線とは別物 — zone跨ぎ集計の限界として開示 |
| chugoku↔kyushu（関門） | 3,420MW | 1,732 | −1,689 | **方向逆転が残存** — 島内slack位置・B案未実施の重複回廊・zone内の電源配分が絡む。境界注入・B案後に再評価 |

07-05の突合表（無効と訂正済み）と違い、この表は**意味のある比較**になった:
一致（阿南紀北）・構造差（容量制約なし）・モデル限界（自社幹線 vs 連系線の区別不能）が
それぞれ分離して読める。

### ハマり⑨の再発と回避

west backbone + bridge + zone_override 構成で **t=17/19 に BLAS abort が再発**
（`cblas_dgemv/dtrsv invalid value`・_BOUNDED_ACでは防げない・構成依存で発生時刻が変わる）。
回避=**時間帯チャンクのプロセス隔離+JSONマージ**。abort時刻は `blas_abort` レコードとして
明示（silent truncation禁止）→ 22/24収束（AC 20 + dc_fallback 2 + abort 2）。

## 4. 開示・限界（県近似の残渣）

- **周波数境界は直さない（意図的）**: 山梨・静岡東部への chubu 抽出はみ出し（60Hz側の
  見せかけ主張）は残る。修正には運用者/周波数タグの一次データが必要（B/C案の領域）
- **供給区域と県境の乖離（同一周波数内）は未処理**: 岐阜県飛騨（神岡等=北陸電力）、
  三重県熊野の一部（=関西）、兵庫県赤穂の一部（=中国）。chubu↔hokuriku に残る33本の
  大半はこの飛騨境界
- **B案（重複ノード・枝のdedup）は未実施**: 関門ルートの並行重複（par4+par6）等の物理二重化
  は残る（chugoku↔kyushu 500kV 3本のうち実横断は1、他は重複コピー）
- 県ポリゴンは簡略化0.002°（境界から~200mの点は隣県に誤判定しうる）
- built資産（docs/data/built/*.json）は無変更 — 再属性は計算層（build_island_net）で実施。
  ビュー/エディタ側・dist/ybus（バス表のzone列）への反映は次回正典更新で（オーナー判断）

## 5. 再現

```bash
python -m pytest tests/test_region_attribution.py -q            # 境界ピン19件
PYTHONPATH=. .venv/bin/python scripts/diagnose_zone_contamination.py --island west
PYTHONPATH=. .venv/bin/python scripts/diagnose_zone_contamination.py --island west --no-territory  # 旧挙動
```
