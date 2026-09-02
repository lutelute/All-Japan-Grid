# 回線数(par)の出典補完 — 介入#44 候補(2026-09-02)

- 状態: **正典適用済み**
- 出典レコード 4913(種別: {'capacity_csv': 3516, 'keitouzu': 199, 'impedance_tokens': 371, 'kyushu_pool': 780, 'manual': 1, 'flow_records': 46})、照合 2079(方法: {'name': 637, 'route': 840, 'name+endpoint': 602})、提案枝 3844、**更新 421 枝**(増やす方向のみ)
- 更新の kv 別: {'154.0': 52, '275.0': 24, '77.0': 41, '66.0': 217, '0.0': 15, '0': 1, '500.0': 22, '187.0': 5, '110.0': 18, '220.0': 26}
- 更新の地域別: {'chubu': 23, 'kansai': 96, 'tokyo': 183, 'tohoku': 2, 'chugoku': 49, 'shikoku': 40, 'kyushu': 95, 'hokkaido': 1}
- 更新の照合方法別: {'name': 134, 'name+endpoint': 102, 'route': 185} / 出典種別: {'capacity_csv': 400, 'flow_records': 7, 'impedance_tokens': 50, 'keitouzu': 27, 'kyushu_pool': 99, 'manual': 3}
- par 遷移: {'1->2': 383, '1->4': 6, '2->3': 6, '1->3': 19, '2->4': 7}
- 食い違い(同一枝に別の回線数): 66 / 上限 8 超で保留: 0
- 未照合の出典: 2834({'capacity_csv': 2213, 'keitouzu': 34, 'impedance_tokens': 168, 'kyushu_pool': 403, 'flow_records': 16})

## C① が指摘した線の現状

| 線 | 枝数 | par(前) | par(後) |
|---|---:|---|---|
| 本四連系(菰池二丁目~福江町三丁目 500kV) | 2 | [1] | [2] |
| 上野線 275kV | 5 | [1] | [3] |
| 上野水道橋線 275kV | 6 | [1] | [3] |
| 山代~久原 500kV | 3 | [1] | [1] |

## 指摘線に関係する出典レコード

- **本四連系**: shikoku 讃岐坂出線 187kV n=2 [capacity_csv/未照合:0枝]; shikoku 讃岐鳴門線 187kV n=2 [capacity_csv/未照合:0枝]; shikoku 四国中央東幹線（送電線No.3） 500kV n=2 [keitouzu/route:2枝]; shikoku 阿波幹線（送電線No.4） 500kV n=2 [keitouzu/route:2枝]; shikoku 吉野川線（送電線No.26） 187kV n=2 [keitouzu/route:4枝]; shikoku 讃岐坂出線（送電線No.27） 187kV n=2 [keitouzu/未照合:0枝]; shikoku 香川線（送電線No.29） 187kV n=2 [keitouzu/route:4枝]; shikoku 麻線（送電線No.30） 187kV n=2 [keitouzu/route:4枝]
- **上野線**: kansai 上野線 33kV n=1 [capacity_csv/未照合:0枝]; kansai 上野線 22kV n=1 [capacity_csv/未照合:0枝]; kansai 千種上野線 33kV n=1 [capacity_csv/未照合:0枝]; kansai 安積上野線 33kV n=1 [capacity_csv/未照合:0枝]; tokyo 上野線 275kV n=3 [capacity_csv/route:5枝]; kyushu 大分上野線 66kV n=2 [kyushu_pool/route:2枝]
- **上野水道橋線**: tokyo 上野水道橋線 275kV n=3 [capacity_csv/name+endpoint:6枝]
- **山代~久原**: kyushu 山代分岐線 66kV n=2 [kyushu_pool/route:6枝]; kyushu 木風山代線 66kV n=2 [kyushu_pool/未照合:0枝]

## 食い違い(上位)

| 枝 | kV | par | 提案 |
|---|---:|---:|---|
| 高津線;東意岐部支線 | 154.0 | 4 | n=2(conf3,name), n=1(conf3,name), n=1(conf3,name), n=1(conf3,name), n=3(conf2,name+endpoint) |
| 高津線;東意岐部支線 | 154.0 | 4 | n=2(conf3,name), n=1(conf3,name), n=1(conf3,name), n=1(conf3,name), n=3(conf2,name+endpoint) |
| 高津線;意岐部線 | 154.0 | 4 | n=1(conf3,name), n=1(conf3,name), n=1(conf3,name), n=3(conf2,name+endpoint) |
| 高津線 | 154.0 | 2 | n=1(conf3,name), n=1(conf3,name), n=1(conf3,name), n=3(conf2,name+endpoint) |
| 神戸港線;上筒井線 | 77.0 | 6 | n=2(conf3,name), n=1(conf3,name) |
| 群馬幹線 | 154.0 | 4 | n=2(conf3,name+endpoint), n=2(conf3,route), n=2(conf3,name+endpoint), n=2(conf2,name+endpoint), n=2(conf2,name+endpoint), n=2(conf2,name+endpoint), n=2(conf2,name+endpoint), n=2(conf2,name+endpoint), n=2(conf2,name+endpoint), n=2(conf2,route), n=2(conf1,name+endpoint), n=2(conf1,name+endpoint), n=2(conf1,name+endpoint), n=2(conf1,name+endpoint), n=2(conf1,name+endpoint), n=2(conf1,name+endpoint), n=1(conf1,route) |
| 上越幹線 | 154.0 | 2 | n=2(conf3,name+endpoint), n=2(conf3,route), n=2(conf3,name+endpoint), n=1(conf1,route), n=1(conf1,name+endpoint) |
| 上越幹線 | 154.0 | 2 | n=2(conf3,name+endpoint), n=2(conf3,route), n=2(conf3,name+endpoint), n=1(conf1,route), n=1(conf1,name+endpoint) |
| 上越幹線 | 154.0 | 2 | n=2(conf3,name+endpoint), n=2(conf3,name+endpoint), n=1(conf1,name+endpoint) |
| 上越幹線 | 154.0 | 2 | n=2(conf3,name+endpoint), n=2(conf3,name+endpoint), n=1(conf1,name+endpoint) |
| 上越幹線 | 154.0 | 2 | n=2(conf3,name+endpoint), n=2(conf3,name+endpoint), n=1(conf1,name+endpoint) |
| 上越幹線 | 154.0 | 2 | n=2(conf3,name+endpoint), n=2(conf3,name+endpoint), n=1(conf1,name+endpoint) |
| 上越幹線 | 154.0 | 2 | n=2(conf3,name+endpoint), n=2(conf3,name+endpoint), n=1(conf1,name+endpoint) |
| 赤城南線 | 66.0 | 2 | n=2(conf3,name), n=1(conf3,name) |
| 赤城南線 | 66.0 | 2 | n=2(conf3,name), n=1(conf3,name) |
| 白石線 | 154.0 | 6 | n=3(conf3,route), n=3(conf3,route), n=2(conf3,route), n=2(conf3,route), n=2(conf2,route) |
| 白石線 | 154.0 | 6 | n=3(conf3,route), n=3(conf3,route), n=2(conf3,route), n=2(conf3,route), n=2(conf2,route) |
| 北島線 | 154.0 | 10 | n=4(conf3,route), n=2(conf3,route), n=2(conf3,route), n=2(conf2,route) |
| 島崎線 | 154.0 | 4 | n=4(conf3,route), n=2(conf2,route) |
| 島崎線 | 154.0 | 4 | n=4(conf3,route), n=2(conf2,route) |
| 新鶴見線 | 154.0 | 6 | n=4(conf3,route), n=2(conf2,route) |
| 島崎線 | 154.0 | 6 | n=4(conf3,route), n=2(conf2,route) |
| 橋本線 | 154.0 | 4 | n=4(conf3,route), n=4(conf2,route), n=4(conf2,route), n=4(conf2,route), n=4(conf2,name+endpoint), n=4(conf2,name+endpoint), n=4(conf2,route), n=2(conf2,route) |
| 橋本線 | 154.0 | 4 | n=4(conf3,route), n=4(conf2,route), n=4(conf2,route), n=4(conf2,route), n=4(conf2,name+endpoint), n=4(conf2,name+endpoint), n=4(conf2,route), n=2(conf2,route) |
| 橋本線 | 154.0 | 4 | n=4(conf3,route), n=4(conf2,route), n=4(conf2,route), n=4(conf2,route), n=4(conf2,name+endpoint), n=4(conf2,name+endpoint), n=4(conf2,route), n=2(conf2,route) |

## 未照合の主要線(≥154kV・上位)

| 地域 | 線名 | kV | n | from→to | 種別 | 理由 |
|---|---|---:|---:|---|---|---|
| chubu | 愛岐幹線 | 500 | 2 | 岐阜開閉所→愛知変電所 | impedance_tokens | unresolved endpoints |
| chubu | 岐阜連絡線 | 500 | 2 | 岐阜開閉所→北部変電所 | impedance_tokens | unresolved endpoints |
| chubu | 東栄幹線 | 500 | 2 | 東部変電所→東栄変電所 | impedance_tokens | unresolved endpoints |
| chubu | 豊根連絡線 | 500 | 2 | 東栄変電所→豊根開閉所 | impedance_tokens | unresolved endpoints |
| chugoku | 中国東幹線 | 500 | 2 | 日野変電所→智頭変電所 | impedance_tokens | unresolved endpoints |
| kansai | 播磨線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 東播線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 丹波線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 能勢線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 北河内線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 播磨中央線 | 500 | 2 | 開閉所→ | capacity_csv | no name |
| kansai | 播磨西線 | 500 | 2 | →開閉所 | capacity_csv | no name |
| kansai | 播磨北線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 大河内線 | 500 | 2 | 開閉所→ | capacity_csv | no name |
| kansai | 新綾部線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 若狭幹線（山） | 500 | 2 | →開閉所 | capacity_csv | no name |
| kansai | 北近江線 | 500 | 2 | →開閉所 | capacity_csv | no name |
| kansai | 丹後幹線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 若狭幹線（里） | 500 | 2 | →開閉所 | capacity_csv | no name |
| kansai | 奥多々良木線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 南大和線 | 500 | 2 | 開閉所→ | capacity_csv | no name |
| kansai | 山城南線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 北和泉線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 南和泉線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 信貴線 | 500 | 2 | → | capacity_csv | no name |
| kansai | 紀北線 | 500 | 2 | 変換所→ | capacity_csv | no name |
| kansai | 播磨北線 | 500 | 2 | 大河内開閉所(開M)→山崎開閉所(開D) | impedance_tokens | unresolved endpoints |
| kansai | 大河内線 | 500 | 2 | 新綾部変電所→大河内開閉所(開M) | impedance_tokens | unresolved endpoints |
| kansai | 山崎智頭線 | 500 | 2 | 山崎開閉所(開D)→智頭変電所(中国) | impedance_tokens | unresolved endpoints |
| kansai | 播磨北線 | 500 | 2 | 発電所→山崎開閉所（開4） | flow_records | unresolved endpoints |
| kansai | 大河内線 | 500 | 2 | 新綾部変電所→発電所 | flow_records | unresolved endpoints |
| kansai | 山城南支線 | 500 | 2 | 南京都変電所→１３４T（北大和線） | flow_records | unresolved endpoints |
| kansai | 山崎智頭線 | 500 | 2 | 山崎開閉所（開4）→智頭変電所（中国） | flow_records | unresolved endpoints |
| kansai | 山城南支線
※12/6以降 北大和線（南京都→東大和） | 500 | 2 | 南京都変電所→134T（北大和線）
※12/6以降 北大和線（南京都変電所→東大和開閉所（開C）） | flow_records | unresolved endpoints |
| kyushu | 脊振幹線 | 500 | 2 | 3脊振→4中央 | impedance_tokens | unresolved endpoints |
| kyushu | □□□□線 | 500 | 2 | 68苓北→7中九州 | impedance_tokens | unresolved endpoints |
| kyushu | □□□□線 | 500 | 2 | 17発電所→9南九州 | impedance_tokens | unresolved endpoints |
| kyushu | 宮崎幹線 | 500 | 2 | 10宮崎→9南九州 | impedance_tokens | unresolved endpoints |
| kyushu | 日向幹線 | 500 | 2 | 8東九州→11ひむか | impedance_tokens | unresolved endpoints |
| kyushu | 玄海幹線１号線 | 500 | 1 | →西九州 | kyushu_pool | name-match rejected: 2 edges none within 3.0km of resolved endpoints |
| kyushu |  | 500 | 2 | → | kyushu_pool | no name |
| kyushu |  | 500 | 2 | →西九州 | kyushu_pool | unresolved endpoints |
| kyushu |  | 500 | 2 | →中九州 | kyushu_pool | unresolved endpoints |
| kyushu | 苓北火力線 | 500 | 2 | 11発電所→7中九州 | flow_records | unresolved endpoints |
| shikoku | 阿波幹線 | 500 | 2 | → | capacity_csv | no name |
| shikoku | 南阿波幹線 | 500 | 2 | 阿南変換所→ | capacity_csv | unresolved endpoints |
| shikoku | 橘湾火力線 | 500 | 2 | <7>発電所→阿南変換所 | capacity_csv | unresolved endpoints |
| shikoku | 南阿波幹線（送電線No.5） | 500 | 2 | 阿南変換所→阿波変電所 | keitouzu | unresolved endpoints |
| shikoku | 橘湾火力線（送電線No.6） | 500 | 2 | 発電所〈7〉→阿南変換所 | keitouzu | unresolved endpoints |
| tokyo | 富岡線 | 500 | 2 | → | capacity_csv | name found but kv/region mismatch |
| tokyo | 新いわき線 | 500 | 2 | 新今市（開）→新いわき（開） | capacity_csv | unresolved endpoints |
| tokyo | 福島中幹線 | 500 | 2 | 新茂木→新いわき（開） | capacity_csv | unresolved endpoints |
| tokyo | 福島東幹線里線 | 500 | 2 | 新筑波→新いわき（開） | capacity_csv | unresolved endpoints |
| tokyo | 新いわき線 | 500 | 2 | 新いわき開閉所→新今市開閉所 | impedance_tokens | unresolved endpoints |
| tokyo | 新古河線 | 500 | 2 | 新坂戸変電所→(分岐)新古河線 | impedance_tokens | name-match rejected: 4 edges none within 3.0km of resolved endpoints |
| chubu | 佐久間西幹里線 | 275 | 2 | 分岐点→電源名古屋変電所 | impedance_tokens | unresolved endpoints |
| chubu | 愛知分岐線 | 275 | 2 | 愛知変電所→分岐点 | impedance_tokens | unresolved endpoints |
| chubu | 電名瀬戸線 | 275 | 2 | 電源名古屋変電所→瀬戸変電所 | impedance_tokens | unresolved endpoints |
| chubu | 南武平町松ケ枝線 | 275 | 2 | 松ケ枝変電所→南武平町変電所 | impedance_tokens | unresolved endpoints |
| chubu | 下広井南武平町線 | 275 | 2 | 南武平町変電所→下広井変電所 | impedance_tokens | unresolved endpoints |

## 読み方・限界

- 回線数は**構造事実**として公表資料の quote 付きで台帳化した(`data/reference/circuit_counts.jsonl`)。容量値はコミットしない(All-Rights-Reserved 方針)
- `route` 照合は端点変電所間の同階級最短経路(迂回 ≤1.6・途中に別の同階級変電所なし)に当てるため、OSM の区間名が違っても届く。経路が実線形と違う可能性は残る(帳簿の n_hops/detour で点検)
- `name` 照合は線名+地域+電圧階級。端点が解決できた場合は 3km 以内の枝であることを要求
- 増やす方向のみ。OSM の `circuits` が出典より大きい枝はそのまま(食い違いとして帳簿)
- インピーダンス表の回線トークン数は**下限**(表に載る回線だけ)
