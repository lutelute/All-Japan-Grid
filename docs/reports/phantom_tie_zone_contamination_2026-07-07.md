# 幻tie「kyushu↔shikoku 445MW」の解剖 — 正体はbbox重なりによるzone汚染（系統的）

- 日付: 2026-07-07 / モデル: Claude Fable 5
- 位置づけ: `docs/reports/slack_tie_diagnosis_2026-07-05.md` §3で発見した幻tieの
  特定作業（**特定=機械・修正判断=人間** — 本レポートは修正をしていない）
- 再現: `PYTHONPATH=. .venv/bin/python scripts/diagnose_zone_contamination.py --island west`
  → `zone_contamination_{west,east}_2026-07-07.json`（本文の数字はすべてここから）

## TL;DR

幻tieの実体は**山口県内の中国電力の実在系統2本**だった。九州と四国を結ぶ線は存在せず、
地域抽出bboxの重なりで山口県のノードが kyushu / shikoku とラベルされ、その間の線が
「連系線」として集計されていた。さらに調べると、これは氷山の一角で、
**bbox重なり由来のzone汚染は west 全域に系統的**に存在する（①tie集計の汚染、
②実tie「本四連系線」の不可視化、③物理枝の二重生成、④需要の地理誤配置、
⑤発電所の二重計上）。**west の UC vs PF tie突合（07-05）は連系線比較としては無効**と
訂正する。east は汚染が軽く（実tie回廊と重なる）、tie MAE 384MW の正の検証は概ね維持。

## 1. 幻tieの実体（2本 — どちらも中国電力の域内系統）

west PFモデル（10,193バス/9,793線, `build_island_net`）で zone ペア {kyushu, shikoku}
を跨ぐ線は次の2本のみ:

| line | kv | 並列 | 長さ | 端点(from) | 端点(to) | 実体 |
|---|---|---|---|---|---|---|
| 8146 | 500 | 2 | 52.1km | [shikoku] junction (34.41343, 132.25646)=岩国北部 | [kyushu] 東山口変電所 500kV (34.19979, 131.82605) | 中国電力500kV幹線の一部（山口幹線と推定） |
| 8777 | 220 | 2 | 10.7km | [shikoku] 田布施町変電所 220kV (33.96303, 132.05472) | [kyushu] 古開作変電所 220kV (33.96567, 132.09133) | 中国電力220kV（柳井周辺） |

座標はすべて山口県（柳井市・田布施町・山口市・岩国北部）= **中国電力の領土**。
500kV・並列2の line 8146 が t=11 の「445MW」の主経路とみられる。

生データ（`docs/data/built/all.json`）では kyushu-shikoku 跨ぎ枝は12本あるが、
バス化時の端点解決（`pick()` = 同一座標候補から kv 一致の最初）で多くが chugoku
コピーに解決され、PFモデルでは2本に収斂する。

## 2. 根本原因チェーン

1. **bboxの重なり**（`docs/data/built/regions_bbox.json`）:
   kyushu = lat≤34.3, lon≤132.1 / shikoku = lat≤34.4, lon≥132.0 が、いずれも
   山口県南東部（chugoku領土）に食い込む。
2. **per-region抽出の越境**: 山口県エリア（lat 33.9–34.5, lon 131.6–132.3）のノード数は
   kyushu.json 64 / shikoku.json 82 / chugoku.json 120 — 同じ物理設備が最大3地域に重複。
3. **マージでdedupしない**: `built_view_all`（`src/server/built_view.py:32-35`）は
   地域ビューを連結し `region=出所ファイル名` を刻むだけ。同一座標の重複を統合しない。
4. **バス化で出所がzoneになる**: `build_island_net`
   （`scripts/run_full_powerflow_from_db.py:195-204`）はノードエントリ毎に1バスを作り
   `zone = n["region"]`。枝端点は同一座標候補から「kv一致の最初」（nodes順=REGIONS_ALL順）
   を選ぶため、どの地域コピーが選ばれるかは順序依存。

## 3. 系統的影響（west、計測値）

### ① tie集計（`tie_flows_by_pair`）の汚染 — 全ペア

zone跨ぎ線の本数は実在連系の規模と乖離:

| ペア | 跨ぎ線 | 実在連系 | 所見 |
|---|---|---|---|
| chubu↔hokuriku | 225本 | 南福光BTB（AC貫通線なしが正） | ほぼ全て岐阜・福井境の誤属性 |
| chubu↔kansai | 139本 | 三重東近江ほか | 三重・岐阜西部の誤属性が混入 |
| chugoku↔shikoku | 114本 | 本四連系線(500kV) | **500kVが1本も無い**（②参照）。66/110/187kVの誤属性ばかり |
| chugoku↔kyushu | 99本 | 関門連系線(500kV) | 実tieは1本(line9792)。他は関門周辺・山口の誤属性 |
| kansai↔shikoku | 9本 | 阿南紀北**直流**（AC線ゼロが正） | 9本全てが徳島県内の四国電力系統（阿波・国府・南小松島・阿南）— kansai bbox(lon≥134.5)の食い込み |
| kyushu↔shikoku | 2本 | **なし** | 幻tie（§1） |

07-05のtie突合の west 側の数字（chugoku→shikoku 方向逆転 -3,098MW、
kansai→shikoku 過小など）は、この汚染された集計の産物であり、
**連系線フロー比較としては無効**。east 側（tohoku→tokyo MAE 384MW）は跨ぎ線50本が
実tie回廊（福島・栃木境）とほぼ一致するため概ね有効。

### ② 実tie「本四連系線」の不可視化 + 物理二重化

瀬戸大橋の海峡横断（児島↔坂出）は**二重に生成され、どちらも同一zone内部線**:

- line 6316: [chugoku] 菰池二丁目 500kV ↔ [chugoku] 昭和町二丁目_2 500kV（par=1）
- line 7796: [shikoku] junction(同座標) ↔ [shikoku] 昭和町二丁目_2 500kV（par=2）

端点座標が丸め5桁未満で微差のため別バスとなり統合されず、
モデル上は par 1+2 = 実質3回線ぶんが並走する。tie集計には一切現れない。

### ③ 物理枝の二重生成（重なり帯全域）

- 関門ルート: 大久保二丁目→新山口 500kV が chugoku コピー（line6210, par=4）と
  kyushu コピー（line8319, par=6）で並存（par数も食い違う）
- 下関 110kV 群も同様に二重（line6251/8389, line6252/8390 par=5×2）
- 実の関門連系線横断は line9792（新山口[chugoku]↔北九州[kyushu] 500kV）として見えている

### ④ 需要の地理誤配置

`allocate_loads` は zone 別の需要プールを zone ラベルのバスへ按分するため、
**九州需要の一部が山口県の変電所に配られる**（逆も同様）。同一座標に複数zoneの
バスが並存する箇所は west 全体で **1,623箇所**（chubu|hokuriku 533、chubu|kansai 456、
chugoku|shikoku 378、chugoku|kyushu 180、…）— 同一物理点が複数zoneの負荷を受ける。
UC注入（`inject_dispatch_by_zone`）も同じ zone ラベルに依存する。

### ⑤ 発電所の二重計上

`attach_generators` は `data/{region}_plants.geojson` を地域別に読むが、
bbox重なりで同一発電所が複数ファイルに存在し**二重に系統へ付与**される:

- 下関火力: kyushu側(-1→燃料別デフォルト容量) + chugoku側(575MW) の二重
- 下松火力(700MW)・岩国火力(850MW が shikoku_plants にも)・生見川ダム 等
- 同名重複の規模: chugoku|shikoku **261件**・chubu|hokuriku **236件**・
  chubu|kansai 162件・chugoku|kyushu 61件・kansai|shikoku 25件（淡路島の風力等）

## 4. east の対照（軽症）

tohoku↔tokyo: 跨ぎ線50本（500kV 3・275kV 9 を含む=実tie回廊と整合）、
複数zone並存139箇所、同名発電所重複122件（那須塩原・いわき周辺）。
汚染はあるが実連系回廊と地理的に重なるため、07-05の正の検証結果
（MAE 384MW）の解釈は維持できる。ただし局所線の混入はあるので再集計で締め直す価値あり。

## 5. これまでの結果への含意（誠実な訂正）

- **無効**: west の UC vs PF tie 突合表（slack_tie_diagnosis §3 west）。
  再集計（zone再属性後）まで連系線の議論には使わない。
- **要再評価**: west slack 7.6%（backbone）・fragmentation の一部に、
  重複バス・二重発電・需要誤配置が寄与している可能性。
  zone修正はslack内訳（east 9.2%の分解を含む）の前提を変え得る。
- **維持**: east tie 正の検証（概ね）・okinawa 診断（単一地域なので汚染なし）・
  Ybus 出荷物（zone非依存の行列。ただし重複枝は含まれる→v5候補課題）。

## 6. 修正オプション（判断=人間・オーナー）

| 案 | 内容 | 効果 | コスト/リスク |
|---|---|---|---|
| **A. zone再属性**（推奨） | 座標→県→エリアのマッピングでバス/ノードの region を再割当（物理接続は不変） | 幻tie消滅・本四がtieとして復活・需要/UC注入の地理が正しくなる | 県ポリゴン(または簡易県境)の導入。built資産は不変でPF側の属性のみなら小工事 |
| B. 重複dedup | 同一座標(k5)ノード+同一枝の統合（②③の解消） | 物理二重化の解消・断片減 | par不一致(4vs6)の裁定規則が必要。OSM再確認が筋（OSM信頼方針） |
| C. 抽出クリップ | per-region抽出をservice-areaでクリップし直す | 根治 | built全再生成・全下流に波及（大工事） |

A→B の段階実施を推奨。Aだけでも tie 集計・需要配置・UC注入は正しくなる。
幻tie 2本は「削除」ではなく chugoku 内部線として正しく残る（=現実の回復）。

## 7. 再現

```bash
PYTHONPATH=. .venv/bin/python scripts/diagnose_zone_contamination.py --island west
PYTHONPATH=. .venv/bin/python scripts/diagnose_zone_contamination.py --island east
```

出力JSON: `docs/reports/zone_contamination_{west,east}_2026-07-07.json`
（跨ぎ線の全リスト・座標・複数zone並存・発電所重複を収録）
