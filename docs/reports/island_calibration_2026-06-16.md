# 島変電所のデータ校正 (region / voltage) — A島接続の前処理

作成: 2026-06-16 / **Claude Opus 4.8** / オーナー指示「(c) 先にデータ校正(region/voltage)でA判定を精緻化してから」。

入力: `docs/reports/island_substations_2026-06-16.json`(全国855島) / 突合先: 全地域 `data/<region>_substations.geojson`(OSM変電所6962件)。
生成器: `scripts/calibrate_islands.py` → `docs/reports/island_calibration_2026-06-16.json`(精緻化済みworklist)。

## 0. 原則(なぜ「派生レポート」か)

**基底extractは不変**(捏造禁止・破壊的再生成禁止)。`region` は GeoJSON のファイル所属で決まる構造属性で、
enrichments では上書きできない。よって本校正は基底を書き換えず、**派生レポートだけ**を出す。
この refined worklist が A島接続の入力になる(正しい地域・正しい電圧で接続先を探す)。
モデル本体・committedスコアカードは不変。

## 1. 方法(一次根拠)

| 校正軸 | 一次根拠 | ルール |
|---|---|---|
| **region** | OSM `operator`(電力会社=系統地域) | operator→地域(北海道電力→hokkaido…中国電力→chugoku)がタグ地域と食い違えば誤タグと判定。鉄道事業者/J-POWER/operator無は地域確定不能=据え置き。 |
| **voltage** | OSM `voltage`(実タグ) | 名称埋め込みkV(「○○変電所 220kV」)・島census kV と OSM実値を比較し**不一致を検出**。 |

座標bboxは津軽海峡域(下北⇄北海道)等で重複し判別不能 → **operator を地域の真の根拠**に採用。

## 2. 結果(855島)

| 指標 | 件数 |
|---|---|
| 電圧不一致(名称/census vs OSM) | **60** |
| region誤タグ(operator根拠・高確度) | **32** |
| 鉄道operator(き電用=B寄り) | 90 |
| OSM未突合 | 12 |

### region誤タグ内訳(タグ → operator根拠の正地域)

| タグ地域 | 正地域 | 件数 | 該当(レポートL18の指摘と一致) |
|---|---|---|---|
| tohoku | tokyo | 9 | 群馬・栃木のTEPCO資産(鬼怒川154kV 等) |
| kansai | shikoku | 7 | — |
| hokkaido | tohoku | 4 | **下北半島(青森)の東北電力**(東通154kV・佐井66kV 等) |
| shikoku | chugoku | 3 | 広島・山口の中国電力(八幡・上平原110kV 等) |
| tohoku | hokkaido | 2 | — |
| tokyo | tohoku | 2 | — |
| chugoku | kyushu | 2 | — |
| hokuriku | tokyo | 1 | **新信濃変電所275kV(東京電力PG)** |
| kansai | chubu | 1 | 長野木曽系 |
| chugoku | shikoku | 1 | — |

> operator根拠は**下限**: 黒瀬・廿日市(中国電力NWだが OSM operator=無)のように operator が欠落する誤タグは
> ここに出ない(座標bboxも判別不能)。真の誤タグ数はこれより多い。operator有=確証できる32件を確定扱いとする。

## 3. 電圧不一致の解決方針(重要)

**単純な「OSM優先」では誤る**。本レポートは不一致の**検出**に徹し、権威的な単一値を断定しない
(`name_kv` / `osm_kv` を併記)。解決は以下の優先順:

1. **Web検証済み(研究レポート [verified])が最優先**。例: **東通村変電所**は名称154kV・OSM66kVだが、
   東北NW下北半島154kV系統として154kVを検証済 → **154kVが正**(OSMの66kVは不完全)。
2. 検証が無い場合は **OSM実タグが既定の一次根拠**。例: **黒瀬・廿日市**(名称220kV・OSM110kV)は
   レポートが「220kV表記は誤」と確認 → **110kVが正**。
3. いずれも無ければ flag のまま(将来のWeb検証/OSM貢献の対象)。

高電圧(名称≥110kV)の不一致11件は個別確認対象。`null`揺れ・名称の旧称残存・OSM電圧欠落が混在。

## 4. A判定への影響(精緻化の効果)

- **region校正 → 接続先targetingを正す**。例: shikoukタグの八幡変電所は実は chugoku(中国電力) →
  接続先は中国電力系統で探すべき。座標近接探索は地域非依存なので接続先候補自体は出るが、
  地域の文脈(系統図・運営者・優先度)が正しくなる。
- **voltage校正 → 優先度/表示を正す**。HV≥66kV方針では A/B はほぼ変わらない(110kVでも220kVでもA)が、
  接続優先度(500>275>154>110>66)と電圧階級モデルが正確になる。
- **A/Bの反転は稀**。校正の主効果は「正しい地域・正しい電圧で繋ぐ」ための前処理。

## 5. 適用範囲(非破壊)

- 基底GeoJSON・supplement・cuts・モデル本体・スコアカードは**一切変更しない**。
- region remap は**buildに適用しない**(全国ビュー`built_view_all`は座標キーで越境連結するため、
  接続性は地域タグに依存しない)。本レポートは worklist のメタデータとして接続作業に使う。
- 次段: この refined worklist を用いて A島接続(編集ツールで欠落連系線を描く→adopt→verify)。
  優先=high確度95件(都心275kV地中網/大間500kV/中国220kV島嶼/下北154kV)。
