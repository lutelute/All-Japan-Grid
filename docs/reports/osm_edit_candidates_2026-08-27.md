# OSM編集候補 — 母線なし変電所の判読より (2026-08-27)

issue #49 の衛星判読(14所)で「未マッピング(A)」「タグ欠測(A′)」と判定された所。
判読はSubSLD実証ペア図(地理院シームレスフォト)による。**編集は1件ずつ人が確認して行う**(自動編集しない)。

| 分類 | 変電所 | kV | region | 所見 | 推奨編集 | 編集リンク |
|---|---|---|---|---|---|---|
| A | 新坂戸変電所 | 500 | tokyo | 屋外AIS・母線列明瞭 | 構内way(line=busbar/bay)の新規描画 | [edit](https://www.openstreetmap.org/edit#map=18/35.962199/139.436352) |
| A | 新新田変電所 | 500 | tokyo | 屋外AIS・母線列視認 | 構内way(line=busbar/bay)の新規描画 | [edit](https://www.openstreetmap.org/edit#map=18/36.326245/139.304743) |
| A | 南九州変電所 | 500 | kyushu | 大規模AIS・ベイ列明瞭 | 構内way(line=busbar/bay)の新規描画 | [edit](https://www.openstreetmap.org/edit#map=18/31.957715/130.655602) |
| A | 三河変電所 | 275 | chubu | 巨大AIS・全面にベイ列(本命) | 構内way(line=busbar/bay)の新規描画 | [edit](https://www.openstreetmap.org/edit#map=18/34.844231/137.470462) |
| A | 北総変電所 | 275 | tokyo | AIS・北縁に母線/門型列 | 構内way(line=busbar/bay)の新規描画 | [edit](https://www.openstreetmap.org/edit#map=18/35.711218/140.265613) |
| A- | 東仙台変電所 | 275 | tohoku | 小規模AIS・短母線視認可 | 構内way(line=busbar/bay)の新規描画 | [edit](https://www.openstreetmap.org/edit#map=18/38.278234/141.041151) |
| A- | 田原(変電所) | 275 | chubu | 小規模AIS・屋外機器視認 | 構内way(line=busbar/bay)の新規描画 | [edit](https://www.openstreetmap.org/edit#map=18/34.658468/137.307283) |
| A- | 清水変電所 | 154 | chubu | 都市AIS・機器列視認 | 構内way(line=busbar/bay)の新規描画 | [edit](https://www.openstreetmap.org/edit#map=18/35.016661/138.454735) |
| A' | Gifu Substation | 500 | chubu | 構内way・vertexあり busbarタグ欠落(タグ付与のみで母線化) | line=busbar タグ付与(既存構内way) | [edit](https://www.openstreetmap.org/edit#map=18/35.635684/136.962608) |
| line-missing | 小千谷近郊 66kV接続線 | 66 | tokyo | 衛星で導体視認・OSMに線featureなし(介入#36 sat-001で正典適用済み) | power=line way の新規描画(z18判読図: docs/reports/figs/satellite_pilot/z18_c3_ojiya66.png) | [edit](https://www.openstreetmap.org/edit#map=17/37.3082/138.8228) |

- A=屋外AISで母線視認可(way新規描画) / A′=タグ付与のみ / line-missing=線feature自体の欠落
- 出典: docs/data/fragments/osm_edit_candidates.json(機械可読) / issue #49 コメント参照
- 地理院タイルのOSMトレース利用は許諾済み(編集時に最新状況を要確認)