# keitouzu crosswalk 地理整合裁定（スクリーニング） — 2026-08-08

AGJ ノード座標 vs keitouzu 発行 region の bbox（+0.3°バッファ）による機械裁定。
**接頭辞 region の不一致だけでは誤マッチと断定できない**（OSM抽出bboxの越境スピルオーバー、
他社エリア内の自社設備がある）ため、座標で判定する。最終裁定は人間判断。

- 対応総数: 657（ok 634 ／ borderline 11 ／ likely 9 ／ **confirmed 3**）

## confirmed — 沖縄跨ぎ（独立系統ゆえ物理的に不可能）

| keitouzu (region) | → ajg対応 | 座標 | 逸脱° | method |
|---|---|---|---:|---|
| 87 (okinawa) | 真壁変電所 `tokyo_sub_1646` | 36.29,140.08 | 8.78 | name_t1_national |
| 48 (okinawa) | 美里町変電所 `kyushu_sub_308` | 32.63,130.91 | 4.73 | name_t3_national |
| 47 (okinawa) | 高原変電所 `kyushu_sub_549` | 31.94,131.03 | 4.04 | name_t1_national |

## likely — home bbox から 1.0° 超逸脱（同名異地の可能性濃厚）

| keitouzu (region) | → ajg対応 | 座標 | 逸脱° | method |
|---|---|---|---:|---|
| 新地 (tohoku) | 新地変電所 `kyushu_sub_317` | 32.74,129.87 | 9.13 | name_t1_national |
| 小国町 (tohoku) | 小国町変電所 `kyushu_sub_250` | 33.10,131.09 | 7.91 | name_t1_national |
| 平田 (tohoku) | 平田変電所 `chugoku_sub_410` | 35.43,132.83 | 6.17 | name_t1_national |
| 港町 (kyushu) | 港区変電所 154kV `chubu_sub_1107@154` | 35.09,136.90 | 4.8 | name_t3_national |
| 速見 (kyushu) | 関西電力送配電 速見変電所 154kV `kansai_sub_535@154` | 34.74,135.59 | 3.49 | name_t1_national |
| 小坂水力変電所 (chubu) | 小坂町変電所 66kV `tohoku_sub_757@66` | 40.34,140.75 | 3.34 | name_t3_national |
| 下田 (tohoku) | 下田変電所 `kansai_sub_212` | 34.54,135.70 | 3.3 | name_t1_national |
| 金山変電所 (chubu) | 金山変電所 110kV `chugoku_sub_141@110` | 34.66,134.03 | 1.97 | name_t1_national |
| 和泉 (hokuriku) | 和泉変電所 `tokyo_sub_1254` | 36.31,139.46 | 1.56 | name_t1_national |

## borderline — 1.0° 以内の逸脱（境界局・越境設備の可能性。個別確認推奨）

| keitouzu (region) | → ajg対応 | 座標 | 逸脱° | method |
|---|---|---|---:|---|
| 大原変電所 (chubu) | 大原変電所 `tokyo_sub_616` | 35.25,140.39 | 1.19 | name_t1_national |
| 梅原変電所 (chubu) | 梅原変電所 `kansai_sub_122` | 34.26,135.14 | 0.86 | name_t1_national |
| 上越 (tohoku) | 上越変電所 `tokyo_sub_1765` | 37.15,138.27 | 0.73 | name_t1_national |
| 潮見変電所 (chubu) | 潮見変電所 `tokyo_sub_864` | 35.37,139.91 | 0.71 | name_t1_national |
| 東上越 (tohoku) | 東上越変電所 275kV `tokyo_sub_1766@275` | 37.19,138.37 | 0.63 | name_t1_national |
| 松川 (tokyo) | 松川村変電所 `chubu_sub_529` | 36.43,137.84 | 0.56 | name_t3_national |
| 開G (kansai) | 成出変電所 `chubu_sub_930` | 36.35,136.87 | 0.55 | deanon |
| 新信濃 (tokyo) | 新信濃変電所 `tokyo_sub_1731` | 36.13,137.88 | 0.52 | name_t1_region |
| 南いわき (tokyo) | 南いわき開閉所 `tohoku_sub_168` | 37.38,140.81 | 0.38 | name_t1_national |
| 新福島 (tokyo) | 新福島変電所 500kV `tohoku_sub_153@500` | 37.36,140.96 | 0.36 | name_t1_national |
| 御所 (hokuriku) | 御所変電所 `chubu_sub_674` | 36.39,138.24 | 0.34 | name_t1_national |

## エッジ文脈裁定 — 直線2°超の辺の有罪端点

その站の他の keitouzu 隣接局の対応座標中央値から 1.0° 超離れた端点対応を有罪と判定。
bbox 内の同名異地（例: 横浜の高田→上越の高田）もこの規則で捕捉。

| 辺 | kV | region | 直線° | 有罪端点 → 誤対応 | 文脈乖離° |
|---|---|---|---:|---|---:|
| 10222 | 154 | chubu | 2.97 | 潮見変電所→`tokyo_sub_864` | 2.97 |
| 10351 | 154 | chubu | 3.03 | 潮見変電所→`tokyo_sub_864`; 東海変電所→`chubu_sub_299` | 2.97; 1.75 |
| 40030 | 154 | chubu | 2.06 | 梅原変電所→`kansai_sub_122` | 2.06 |
| (9) | 132 | okinawa | 7.04 | 48→`kyushu_sub_308` | 6.95 |
| (66) | 66 | okinawa | 6.49 | 47→`kyushu_sub_549` | 6.49 |
| (69) | 66 | okinawa | 6.95 | 48→`kyushu_sub_308` | 6.95 |
| (70) | 66 | okinawa | 6.95 | 48→`kyushu_sub_308` | 6.95 |
| (71) | 66 | okinawa | 6.95 | 48→`kyushu_sub_308` | 6.95 |
| (無名) | 220 | kyushu | 4.71 | 速見→`kansai_sub_535@154` | 4.71 |
| (無名) | 154 | tohoku | 7.83 | 平田→`chugoku_sub_410` | 7.83 |
| (無名) | 154 | tohoku | 9.08 | 小国町→`kyushu_sub_250` | 9.08 |
| 基幹_送電線No.10 | 154 | tokyo | 2.2 | 高田→`tokyo_sub_1772` | 2.14 |

**除外推奨対応（confirmed/likely + エッジ有罪の和集合）: 16 件** — 機械可読は JSON の `excluded_mappings`。
crosswalk の上流修正報告・crosscheck からの除外に使う。**採用系の裁定（80断絶の原図照合）とは別物**。

---
生成: `scripts/keitouzu/adjudicate_xwalk.py`
