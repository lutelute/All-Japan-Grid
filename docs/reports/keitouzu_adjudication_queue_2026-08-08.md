# keitouzu 食い違い裁定キュー — 2026-08-08

元データ: `keitouzu_crosscheck_2026-08-08.json`（crosswalk 誤マッチ裁定後の食い違い 92 本）。
各行の原図リンク（Internet Archive）で公式系統図に当たり、verdict を JSON に記入する。
**採用（builtへの接続追加）は人間判断＋`docs/MODEL_INTERVENTIONS.md` 記帳が必須。**

- **A: 完全断絶（別成分） 30 本** — builtに経路が全く無い。最優先
- B: 遠距離接続 hop7+ 34 本
- C: 近距離 hop5-6 28 本 — 粒度差の可能性も残る

## A: 完全断絶（30本）

| ☐ | kV | 線名 | from — to | region | hops | 原図 |
|---|---|---|---|---|---:|---|
| ☐ | 500 | 基L46 | 無名発電所P1（基L46・基L47、基S24西） — 基S24 | chugoku | 断絶 | [原図](https://web.archive.org/web/20260806093657/https://www.energia.co.jp/nw/service/retailer/keitou/access/pdf/keitoukousei2025.pdf) |
| ☐ | 500 | 24 | Q — P | kansai | 断絶 | [原図](https://web.archive.org/web/20260806093636/https://www.kansai-td.co.jp/consignment/disclosure/pdf/01_keitou_2024.pdf) |
| ☐ | 275 | 世田谷線 | 世田谷 — 荏田 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 南池上線 | 南川崎 — 池上 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 城南線 | 城南 — 江東 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 川崎高輪線 | 東川崎 — 高輪 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 新宿城南線 | 城南 — 新宿 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 新宿線 | 北多摩 — 新宿 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 東内幸町線 | 東内幸町 — 豊島 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 東新宿水道橋線 | 東新宿 — 水道橋 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 東新宿線 | 北多摩 — 東新宿 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 葛南世田谷線 | 世田谷 — 葛南 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 豊洲内幸町線 | 新豊洲 — 東内幸町 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 豊洲永代橋線 | 新豊洲 — 永代橋 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 高輪線 | 東内幸町 — 高輪 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 墨東線 | 北葛飾 — 墨東 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 墨東線 | 墨東 — 永代橋 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 760 | 東清水変電所 — 駿河変電所 | chubu | 断絶 | [原図](https://web.archive.org/web/20260806093227/https://powergrid.chuden.co.jp/resource/goannai/hatsuden_kouri/takuso_kyokyu/rule/rule_63.pdf) |
| ☐ | 275 | 753/751/780 | 駿河変電所 — 静岡変電所 | chubu | 断絶 | [原図](https://web.archive.org/web/20260806093227/https://powergrid.chuden.co.jp/resource/goannai/hatsuden_kouri/takuso_kyokyu/rule/rule_63.pdf) |
| ☐ | 220 | 基L47 | 無名発電所P1（基L46・基L47、基S24西） — 基S24 | chugoku | 断絶 | [原図](https://web.archive.org/web/20260806093657/https://www.energia.co.jp/nw/service/retailer/keitou/access/pdf/keitoukousei2025.pdf) |
| ☐ | 154 | 常盤台線 | 常盤台 — 戸田 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 犀川線 | 新町 — 松川 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 豊常線 | 常盤台 — 豊島 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 60070 | 玉川変電所 — 三河変電所 | chubu | 断絶 | [原図](https://web.archive.org/web/20260806093227/https://powergrid.chuden.co.jp/resource/goannai/hatsuden_kouri/takuso_kyokyu/rule/rule_63.pdf) |
| ☐ | 154 | 0587 | 中仙台 — 五ツ橋 | tohoku | 断絶 | [原図](https://web.archive.org/web/20251017083234/https://nw.tohoku-epco.co.jp/consignment/system/demand/pdf/jisseki_kikan01_map_2024_02.pdf) |
| ☐ | 154 | 0588 | 中仙台 — 南仙台 | tohoku | 断絶 | [原図](https://web.archive.org/web/20251017083234/https://nw.tohoku-epco.co.jp/consignment/system/demand/pdf/jisseki_kikan01_map_2024_02.pdf) |
| ☐ | 154 | 0674/0675 | 中新潟 — 寄居浜 | tohoku | 断絶 | [原図](https://web.archive.org/web/20251017083234/https://nw.tohoku-epco.co.jp/consignment/system/demand/pdf/jisseki_kikan01_map_2024_02.pdf) |
| ☐ | 154 | 0703/0706 | 東上越 — 魚沼 | tohoku | 断絶 | [原図](https://web.archive.org/web/20251017083234/https://nw.tohoku-epco.co.jp/consignment/system/demand/pdf/jisseki_kikan01_map_2024_02.pdf) |
| ☐ | 154 | 栃山線 | 簗瀬町 — 小山 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 栃山線 | 簗瀬町 — 新栃木 | tokyo | 断絶 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |

## B: hop7+（34本）

| ☐ | kV | 線名 | from — to | region | hops | 原図 |
|---|---|---|---|---|---:|---|
| ☐ | DC | 飛騨信濃直流幹線 | 飛騨変換所 — 新信濃 | inter | 12 | interconnect-pass-20260803 |
| ☐ | 500 | 新豊洲線 | 新京葉 — 新豊洲 | tokyo | 8 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 北武蔵野線 | 新座 — 練馬 | tokyo | 11 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 千葉葛南線 | 千葉中央 — 葛南 | tokyo | 10 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 南川崎線 | 京浜 — 南川崎 | tokyo | 10 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 豊島線 | 京北 — 豊島 | tokyo | 12 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 川崎豊洲線 | 東川崎 — 新豊洲 | tokyo | 34 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 江東線 | 新京葉 — 江東 | tokyo | 8 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 京北線 | 京北 — 南川越 | tokyo | 7 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 基幹_送電線No.10 | 東川崎 — 西東京 | tokyo | 15 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 小北線 | 小山 — 野木 | tokyo | 14 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 栃山線 | 小山 — 新栃木 | tokyo | 10 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 橋本線 | 橋本 — 港北 | tokyo | 8 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 猪苗代新幹線（里） | 小山 — 河内 | tokyo | 11 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 群馬幹線(里) | 南川越 — 群馬 | tokyo | 7 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | H044 | 御所 — 加賀 | hokuriku | 10 | [原図](https://web.archive.org/web/20260806093448/https://www.rikuden.co.jp/nw_notification/attach/keitou_kikan01_jisseki_05.pdf) |
| ☐ | 154 | H063 | 御所 — 北金沢 | hokuriku | 12 | [原図](https://web.archive.org/web/20260806093448/https://www.rikuden.co.jp/nw_notification/attach/keitou_kikan01_jisseki_05.pdf) |
| ☐ | 154 | 30081 | 四日市火力変電所 — 西名古屋変電所 | chubu | 7 | [原図](https://web.archive.org/web/20260806093227/https://powergrid.chuden.co.jp/resource/goannai/hatsuden_kouri/takuso_kyokyu/rule/rule_63.pdf) |
| ☐ | 154 | 30100 | 西名古屋変電所 — 四日市火力変電所 | chubu | 7 | [原図](https://web.archive.org/web/20260806093227/https://powergrid.chuden.co.jp/resource/goannai/hatsuden_kouri/takuso_kyokyu/rule/rule_63.pdf) |
| ☐ | 154 | 121 | CU — CV | kansai | 15 | [原図](https://web.archive.org/web/20260806093636/https://www.kansai-td.co.jp/consignment/disclosure/pdf/01_keitou_2024.pdf) |
| ☐ | 154 | 0574 | 仙台 — 泉 | tohoku | 7 | [原図](https://web.archive.org/web/20251017083234/https://nw.tohoku-epco.co.jp/consignment/system/demand/pdf/jisseki_kikan01_map_2024_02.pdf) |
| ☐ | 154 | 0583 | 五ツ橋 — 仙台港 | tohoku | 8 | [原図](https://web.archive.org/web/20251017083234/https://nw.tohoku-epco.co.jp/consignment/system/demand/pdf/jisseki_kikan01_map_2024_02.pdf) |
| ☐ | 154 | 0742 | 根白石 — 泉 | tohoku | 7 | [原図](https://web.archive.org/web/20251017083234/https://nw.tohoku-epco.co.jp/consignment/system/demand/pdf/jisseki_kikan01_map_2024_02.pdf) |
| ☐ | 154 | 小北線 | 南赤塚 — 小山 | tokyo | 14 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 猪苗代新幹線 | 五霞 — 小山 | tokyo | 12 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 猪苗代新幹線 | 東野田 — 小山 | tokyo | 14 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 小松川線 | 東小岩 — 京北 | tokyo | 8 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 基幹_送電線No.10 | 黒川 — 東川崎 | tokyo | 14 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 基幹_送電線No.10 | 百合ヶ丘 — 東川崎 | tokyo | 12 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 栃山線 | 栃山 — 小山 | tokyo | 14 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 66 | (35) | 27 — 13 | okinawa | 8 | [原図](https://web.archive.org/web/20260806095015/https://www.okiden.co.jp/shared/pdf/business-support/service/juyo-and-sohaiden/keitouzu1.pdf) |
| ☐ | 66 | (36) | 27 — 13 | okinawa | 8 | [原図](https://web.archive.org/web/20260806095015/https://www.okiden.co.jp/shared/pdf/business-support/service/juyo-and-sohaiden/keitouzu1.pdf) |
| ☐ | 66 | (43) | 21 — 10 | okinawa | 14 | [原図](https://web.archive.org/web/20260806095015/https://www.okiden.co.jp/shared/pdf/business-support/service/juyo-and-sohaiden/keitouzu1.pdf) |
| ☐ | 66 | (44) | 10 — 9 | okinawa | 12 | [原図](https://web.archive.org/web/20260806095015/https://www.okiden.co.jp/shared/pdf/business-support/service/juyo-and-sohaiden/keitouzu1.pdf) |

## C: hop5-6（28本）

| ☐ | kV | 線名 | from — to | region | hops | 原図 |
|---|---|---|---|---|---:|---|
| ☐ | 500 | 新坂戸線 | 新坂戸 — 新新田 | tokyo | 5 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 500 | 福島東幹線(里) | 新いわき — 新筑波 | tokyo | 6 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 500 | 西上武幹線 | 新所沢 — 西群馬 | tokyo | 5 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 500 | 0005 | 宮城中央 — 西仙台 | tohoku | 5 | [原図](https://web.archive.org/web/20251017083234/https://nw.tohoku-epco.co.jp/consignment/system/demand/pdf/jisseki_kikan01_map_2024_02.pdf) |
| ☐ | 500 | 山崎智頭線 | 開D — 基S27 | inter | 5 | interconnect-pass-20260803 |
| ☐ | 275 | 東京西線 | 新多摩 — 西東京 | tokyo | 6 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 江東線 | 新京葉 — 葛南 | tokyo | 6 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 港北線 | 港北 — 西東京 | tokyo | 6 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 西南川越線 | 南川越 — 多摩 | tokyo | 6 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 275 | 170 | 鈴鹿開閉所 — 西濃変電所 | chubu | 6 | [原図](https://web.archive.org/web/20260806093227/https://powergrid.chuden.co.jp/resource/goannai/hatsuden_kouri/takuso_kyokyu/rule/rule_63.pdf) |
| ☐ | 154 | 下総線 | 下総 — 新京葉 | tokyo | 5 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 亀戸線 | 亀戸 — 北葛飾 | tokyo | 5 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 北多摩線 | 千歳 — 武蔵野 | tokyo | 5 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 志木線 | 南川越 — 戸田 | tokyo | 5 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 中富線 | 武蔵赤坂 — 千歳 | tokyo | 6 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 北船橋線 | 新京葉 — 下総 | tokyo | 5 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 50052 | 飯田変電所 — 南信変電所 | chubu | 5 | [原図](https://web.archive.org/web/20260806093227/https://powergrid.chuden.co.jp/resource/goannai/hatsuden_kouri/takuso_kyokyu/rule/rule_63.pdf) |
| ☐ | 154 | 0676 | 中新潟 — 北新潟 | tohoku | 6 | [原図](https://web.archive.org/web/20251017083234/https://nw.tohoku-epco.co.jp/consignment/system/demand/pdf/jisseki_kikan01_map_2024_02.pdf) |
| ☐ | 154 | 群馬幹線（里） | 上里 — 南川越 | tokyo | 6 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 京北線 | 新郷 — 南川越 | tokyo | 6 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 小松川線 | 東小岩 — 北葛飾 | tokyo | 5 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 北船橋線 | 二和東 — 下総 | tokyo | 5 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 橋本線 | 恩田 — 橋本 | tokyo | 5 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 橋本線 | 原町田 — 橋本 | tokyo | 5 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 橋本線 | 相模原 — 港北 | tokyo | 6 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 154 | 群馬幹線(里) | 上里 — 南川越 | tokyo | 6 | [原図](http://web.archive.org/web/20260413144431/https://www4.tepco.co.jp/pg/consignment/system/pdf/jisseki_kikan.pdf?251028) |
| ☐ | 66 | (3) | 22 — 27 | okinawa | 6 | [原図](https://web.archive.org/web/20260806095015/https://www.okiden.co.jp/shared/pdf/business-support/service/juyo-and-sohaiden/keitouzu1.pdf) |
| ☐ | 66 | (38) | 22 — 27 | okinawa | 6 | [原図](https://web.archive.org/web/20260806095015/https://www.okiden.co.jp/shared/pdf/business-support/service/juyo-and-sohaiden/keitouzu1.pdf) |

---
生成: `scripts/keitouzu/gen_adjudication_queue.py`
