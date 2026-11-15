# 回線数(par)の出典補完 — 介入#44 候補(2026-11-15)

- 状態: **正典適用済み**
- 出典レコード 2098(種別: {'capacity_csv': 1303, 'keitouzu': 165, 'impedance_tokens': 218, 'kyushu_pool': 377, 'manual': 3, 'flow_records': 32})、照合 2093(方法: {'name': 600, 'route': 878, 'name+endpoint': 615})、提案枝 3535、**更新 289 枝**(増やす方向のみ)
- 更新の kv 別: {'154.0': 47, '275.0': 25, '77.0': 38, '0.0': 14, '66.0': 110, '500.0': 20, '187.0': 2, '110.0': 12, '220.0': 21}
- 更新の地域別: {'kansai': 59, 'chubu': 7, 'tokyo': 111, 'tohoku': 2, 'shikoku': 16, 'chugoku': 12, 'kyushu': 87}
- 更新の照合方法別: {'name': 81, 'name+endpoint': 56, 'route': 152} / 出典種別: {'capacity_csv': 221, 'flow_records': 7, 'impedance_tokens': 41, 'keitouzu': 22, 'kyushu_pool': 99, 'manual': 4}
- par 遷移: {'1->2': 257, '1->4': 4, '2->3': 5, '1->3': 19, '2->4': 4}
- 食い違い(同一枝に別の回線数): 61 / 上限 8 超で保留: 0
- 未照合の出典: 5({'capacity_csv': 5})

## C① が指摘した線の現状

| 線 | 枝数 | par(前) | par(後) |
|---|---:|---|---|
| 本四連系(菰池二丁目~福江町三丁目 500kV) | 0 | [] | [] |
| 上野線 275kV | 5 | [1] | [3] |
| 上野水道橋線 275kV | 6 | [1] | [3] |
| 山代~久原 500kV | 3 | [1] | [1] |

## 指摘線に関係する出典レコード

- **本四連系**: shikoku 四国中央東幹線（送電線No.3） 500kV n=2 [keitouzu/route:1枝]; shikoku 阿波幹線（送電線No.4） 500kV n=2 [keitouzu/route:1枝]; shikoku 吉野川線（送電線No.26） 187kV n=2 [keitouzu/route:2枝]; shikoku 香川線（送電線No.29） 187kV n=2 [keitouzu/route:2枝]; shikoku 麻線（送電線No.30） 187kV n=2 [keitouzu/route:2枝]; shikoku 高松線（送電線No.31） 187kV n=4 [keitouzu/route:2枝]; kansai 西播東岡山線 500kV n=2 [impedance_tokens/route:1枝]; chugoku 新岡山幹線 500kV n=2 [impedance_tokens/route:1枝]
- **上野線**: tokyo 上野線 275kV n=3 [capacity_csv/route:5枝]; kyushu 大分上野線 66kV n=2 [kyushu_pool/route:2枝]
- **上野水道橋線**: tokyo 上野水道橋線 275kV n=3 [capacity_csv/name+endpoint:6枝]
- **山代~久原**: kyushu 山代分岐線 66kV n=2 [kyushu_pool/route:6枝]

## 食い違い(上位)

| 枝 | kV | par | 提案 |
|---|---:|---:|---|
| 高津線;東意岐部支線 | 154.0 | 4 | n=2(conf3,name), n=1(conf3,name), n=1(conf3,name), n=1(conf3,name), n=3(conf2,name+endpoint) |
| 高津線;東意岐部支線 | 154.0 | 4 | n=2(conf3,name), n=1(conf3,name), n=1(conf3,name), n=1(conf3,name), n=3(conf2,name+endpoint) |
| 高津線;意岐部線 | 154.0 | 2 | n=1(conf3,name), n=1(conf3,name), n=1(conf3,name), n=3(conf2,name+endpoint) |
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

## 読み方・限界

- 回線数は**構造事実**として公表資料の quote 付きで台帳化した(`data/reference/circuit_counts.jsonl`)。容量値はコミットしない(All-Rights-Reserved 方針)
- `route` 照合は端点変電所間の同階級最短経路(迂回 ≤1.6・途中に別の同階級変電所なし)に当てるため、OSM の区間名が違っても届く。経路が実線形と違う可能性は残る(帳簿の n_hops/detour で点検)
- `name` 照合は線名+地域+電圧階級。端点が解決できた場合は 3km 以内の枝であることを要求
- 増やす方向のみ。OSM の `circuits` が出典より大きい枝はそのまま(食い違いとして帳簿)
- インピーダンス表の回線トークン数は**下限**(表に載る回線だけ)
