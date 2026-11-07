# 送電線のつながりの点検（OSM 2026-11-05 取得・正典 c6c6a9108212）

`scripts/audit_route_connectivity.py` が書いた。**候補の一覧で、誤りの判定ではない。**観測（OSM の線を路線にまとめたもの、docs/OSM_ROUTES.md）と正典（docs/data/built）を分けて数える。直すのは航空写真・OSM・公表値の根拠があるものだけで、直しは介入台帳（docs/MODEL_INTERVENTIONS.md）で行う。地図では map.html の「つながりの点検」で印を出せる。

数えないもの: 変電所・発電所の敷地の中、引留め鉄構・終端・架空と地中の切替で終わる線の端。電圧の違う線が鉄塔の点を共有する所（ほとんどが併架で OSM の誤りではない）。

## 種類ごと・地域ごとの数（かっこ内は 154 kV 以上）

| 種類 | 北海道 | 東北 | 東京 | 中部 | 北陸 | 関西 | 中国 | 四国 | 九州 | 沖縄 | 計 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 線の端の 60 m 以内に別の線(つなぎ忘れの候補) | 36（7） | 57（7） | 832（43） | 956（18） | 341（15） | 292（34） | 251（19） | 28 | 147（13） | 77 | **3,017**（156） |
| 線の端の 300 m 以内に変電所(引込みの描き残し) | 5（1） | 25 | 56（5） | 40（2） | 12（1） | 33（1） | 29 | 4 | 29（4） | 1 | **234**（14） |
| 線の端が何もない所で終わる | 57（1） | 224（5） | 460（19） | 745（26） | 192（3） | 401（16） | 376（5） | 142 | 256（9） | 18 | **2,871**（84） |
| 線の端が取得範囲の外 | 0 | 12（4） | 8（5） | 3（1） | 0 | 7 | 0 | 0 | 1 | 16 | **47**（10） |
| 同じ名前・電圧の路線が 2 km 以内の隙間で途切れる(両側とも線の端がどこにも続かない) | 0 | 0 | 8（1） | 0 | 0 | 1 | 0 | 0 | 3 | 0 | **12**（1） |
| 正典: 変電所でない接続点で電圧の違う枝がつながる | 0 | 2（2） | 16（8） | 22（10） | 1（1） | 13（8） | 1 | 1（1） | 2（1） | 1 | **59**（31） |
| 正典: 変電所でない接続点で枝が 1 本(行き止まり) | 85（10） | 283（45） | 739（91） | 354（103） | 27（19） | 271（40） | 198（33） | 57（7） | 249（18） | 5 | **2,268**（366） |

## 観測の候補（154 kV 以上）は正典でどうなっているか

154 kV 以上の観測の候補 254 か所のうち、正典の枝の形が 60 m 以内を通るのは 150 か所（正典では線がその先へ続いている＝OSM の描き方の問題で、正典は直さなくてよい候補）。残り 104 か所は正典でも線がその場所を通っていない。

## 154 kV 以上の観測の候補

| 種類 | 地域 | 路線 | kV | 位置 | 手がかり | 正典の枝まで |
|---|---|---|---:|---|---|---:|
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1084271494](https://www.openstreetmap.org/way/1084271494)） | 500 | [35.55618, 135.96948](https://www.openstreetmap.org/#map=18/35.55618/135.96948) | 8 m 先に 名前なしの線 | 62 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1084271493](https://www.openstreetmap.org/way/1084271493)） | 500 | [35.55624, 135.96951](https://www.openstreetmap.org/#map=18/35.55624/135.96951) | 8 m 先に 名前なしの線 | 58 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1084271489](https://www.openstreetmap.org/way/1084271489)） | 500 | [35.55672, 135.96973](https://www.openstreetmap.org/#map=18/35.55672/135.96973) | 8 m 先に 名前なしの線 | 61 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1084271488](https://www.openstreetmap.org/way/1084271488)） | 500 | [35.55679, 135.96976](https://www.openstreetmap.org/#map=18/35.55679/135.96976) | 8 m 先に 名前なしの線 | 65 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1084271487](https://www.openstreetmap.org/way/1084271487)） | 500 | [35.55685, 135.96980](https://www.openstreetmap.org/#map=18/35.55685/135.96980) | 8 m 先に 名前なしの線 | 71 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1083544719](https://www.openstreetmap.org/way/1083544719)） | 500 | [35.55686, 135.97009](https://www.openstreetmap.org/#map=18/35.55686/135.97009) | 8 m 先に 名前なしの線 | 96 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1083544720](https://www.openstreetmap.org/way/1083544720)） | 500 | [35.55689, 135.97001](https://www.openstreetmap.org/#map=18/35.55689/135.97001) | 8 m 先に 名前なしの線 | 90 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1083544721](https://www.openstreetmap.org/way/1083544721)） | 500 | [35.55691, 135.96993](https://www.openstreetmap.org/#map=18/35.55691/135.96993) | 8 m 先に 名前なしの線 | 84 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1084685253](https://www.openstreetmap.org/way/1084685253)） | 275 | [35.55732, 135.97428](https://www.openstreetmap.org/#map=18/35.55732/135.97428) | 20 m 先に 名前なしの線 | 102 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1084685254](https://www.openstreetmap.org/way/1084685254)） | 275 | [35.55742, 135.97390](https://www.openstreetmap.org/#map=18/35.55742/135.97390) | 15 m 先に 名前なしの線 | 117 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 253528803](https://www.openstreetmap.org/way/253528803)） | 154 | [35.06802, 136.88029](https://www.openstreetmap.org/#map=18/35.06802/136.88029) | 14 m 先に 名前なしの線 | 13 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 253528805](https://www.openstreetmap.org/way/253528805)） | 154 | [35.06813, 136.88033](https://www.openstreetmap.org/#map=18/35.06813/136.88033) | 14 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 814581997](https://www.openstreetmap.org/way/814581997)） | 154 | [36.29455, 137.37025](https://www.openstreetmap.org/#map=18/36.29455/137.37025) | 10 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1028287106](https://www.openstreetmap.org/way/1028287106)） | 154 | [36.46696, 136.96776](https://www.openstreetmap.org/#map=18/36.46696/136.96776) | 34 m 先に 名前なしの線 | 34 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1028287107](https://www.openstreetmap.org/way/1028287107)） | 154 | [36.46704, 136.96739](https://www.openstreetmap.org/#map=18/36.46704/136.96739) | 34 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1553357116](https://www.openstreetmap.org/way/1553357116)） | 154 | [36.75065, 137.64005](https://www.openstreetmap.org/#map=18/36.75065/137.64005) | 32 m 先に 名前なしの線 | 56 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1553357115](https://www.openstreetmap.org/way/1553357115)） | 154 | [36.75098, 137.63991](https://www.openstreetmap.org/#map=18/36.75098/137.63991) | 38 m 先に 名前なしの線 | 71 m |
| 線の端の 60 m 以内に別の線 | 中部 | 名前なし（[way 1088664726](https://www.openstreetmap.org/way/1088664726)） | 154 | [37.01262, 137.79676](https://www.openstreetmap.org/#map=18/37.01262/137.79676) | 41 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 1427454340](https://www.openstreetmap.org/way/1427454340)） | 500 | [35.53928, 132.99132](https://www.openstreetmap.org/#map=18/35.53928/132.99132) | 33 m 先に 島根原子力幹線 | 33 m |
| 線の端の 60 m 以内に別の線 | 中国 | 島根原子力幹線（[way 1427454341](https://www.openstreetmap.org/way/1427454341)） | 500 | [35.53938, 132.99167](https://www.openstreetmap.org/#map=18/35.53938/132.99167) | 33 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 中国 | 新小倉火力線（[way 1517852073](https://www.openstreetmap.org/way/1517852073)） | 220 | [33.90617, 130.86232](https://www.openstreetmap.org/#map=18/33.90617/130.86232) | 14 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 405811248](https://www.openstreetmap.org/way/405811248)） | 220 | [33.90627, 130.86223](https://www.openstreetmap.org/#map=18/33.90627/130.86223) | 14 m 先に 新小倉火力線 | 0 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 405811258](https://www.openstreetmap.org/way/405811258)） | 220 | [33.90631, 130.86201](https://www.openstreetmap.org/#map=18/33.90631/130.86201) | 15 m 先に 名前なしの線 | 15 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 405811260](https://www.openstreetmap.org/way/405811260)） | 220 | [33.90647, 130.86188](https://www.openstreetmap.org/#map=18/33.90647/130.86188) | 14 m 先に 名前なしの線 | 15 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 405811249](https://www.openstreetmap.org/way/405811249)） | 220 | [33.90660, 130.86280](https://www.openstreetmap.org/#map=18/33.90660/130.86280) | 16 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 405811248](https://www.openstreetmap.org/way/405811248)） | 220 | [33.90664, 130.86193](https://www.openstreetmap.org/#map=18/33.90664/130.86193) | 12 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 405811245](https://www.openstreetmap.org/way/405811245)） | 220 | [33.90680, 130.86222](https://www.openstreetmap.org/#map=18/33.90680/130.86222) | 12 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 405811258](https://www.openstreetmap.org/way/405811258)） | 220 | [33.90682, 130.86288](https://www.openstreetmap.org/#map=18/33.90682/130.86288) | 4 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 405811249](https://www.openstreetmap.org/way/405811249)） | 220 | [33.90696, 130.86251](https://www.openstreetmap.org/#map=18/33.90696/130.86251) | 12 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 405811260](https://www.openstreetmap.org/way/405811260)） | 220 | [33.90697, 130.86276](https://www.openstreetmap.org/#map=18/33.90697/130.86276) | 4 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 912685770](https://www.openstreetmap.org/way/912685770)） | 220 | [34.43411, 132.96627](https://www.openstreetmap.org/#map=18/34.43411/132.96627) | 8 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 1427454287](https://www.openstreetmap.org/way/1427454287)） | 220 | [34.56786, 132.51170](https://www.openstreetmap.org/#map=18/34.56786/132.51170) | 10 m 先に 名前なしの線 | 13 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 1427454298](https://www.openstreetmap.org/way/1427454298)） | 220 | [34.56797, 132.51180](https://www.openstreetmap.org/#map=18/34.56797/132.51180) | 11 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 1427454287](https://www.openstreetmap.org/way/1427454287)） | 220 | [34.56802, 132.51168](https://www.openstreetmap.org/#map=18/34.56802/132.51168) | 7 m 先に 名前なしの線 | 12 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 1191968007](https://www.openstreetmap.org/way/1191968007)） | 187 | [34.34269, 133.84242](https://www.openstreetmap.org/#map=18/34.34269/133.84242) | 52 m 先に 名前なしの線 | 52 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 1191968008](https://www.openstreetmap.org/way/1191968008)） | 187 | [34.34299, 133.84285](https://www.openstreetmap.org/#map=18/34.34299/133.84285) | 52 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 中国 | 名前なし（[way 1191968009](https://www.openstreetmap.org/way/1191968009)） | 187 | [34.34429, 133.84349](https://www.openstreetmap.org/#map=18/34.34429/133.84349) | 38 m 先に 名前なしの線 | 98 m |
| 線の端の 60 m 以内に別の線 | 北海道 | 名前なし（[way 640518254](https://www.openstreetmap.org/way/640518254)） | 275 | [42.61280, 141.80516](https://www.openstreetmap.org/#map=18/42.61280/141.80516) | 14 m 先に 名前なしの線 | 352 m |
| 線の端の 60 m 以内に別の線 | 北海道 | 西音更線;岩松線（[way 256549580](https://www.openstreetmap.org/way/256549580)） | 187 | [43.00583, 143.10905](https://www.openstreetmap.org/#map=18/43.00583/143.10905) | 0 m 先に 岩松線 | 0 m |
| 線の端の 60 m 以内に別の線 | 北海道 | 名前なし（[way 640882699](https://www.openstreetmap.org/way/640882699)） | 187 | [43.02277, 141.41987](https://www.openstreetmap.org/#map=18/43.02277/141.41987) | 8 m 先に 南札幌幹線 | 121 m |
| 線の端の 60 m 以内に別の線 | 北海道 | 名前なし（[way 255122144](https://www.openstreetmap.org/way/255122144)） | 187 | [43.02286, 141.41976](https://www.openstreetmap.org/#map=18/43.02286/141.41976) | 8 m 先に 南札幌幹線 | 95 m |
| 線の端の 60 m 以内に別の線 | 北海道 | 名前なし（[way 1467938571](https://www.openstreetmap.org/way/1467938571)） | 187 | [43.42142, 141.84351](https://www.openstreetmap.org/#map=18/43.42142/141.84351) | 31 m 先に 名前なしの線 | 197 m |
| 線の端の 60 m 以内に別の線 | 北海道 | 名前なし（[way 1467938570](https://www.openstreetmap.org/way/1467938570)） | 187 | [43.42157, 141.84319](https://www.openstreetmap.org/#map=18/43.42157/141.84319) | 18 m 先に 名前なしの線 | 180 m |
| 線の端の 60 m 以内に別の線 | 北海道 | 名前なし（[way 1467938569](https://www.openstreetmap.org/way/1467938569)） | 187 | [43.42168, 141.84302](https://www.openstreetmap.org/#map=18/43.42168/141.84302) | 18 m 先に 名前なしの線 | 173 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1238881246](https://www.openstreetmap.org/way/1238881246)） | 500 | [36.99601, 136.83641](https://www.openstreetmap.org/#map=18/36.99601/136.83641) | 15 m 先に 名前なしの線 | 157 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1238881247](https://www.openstreetmap.org/way/1238881247)） | 500 | [36.99607, 136.83625](https://www.openstreetmap.org/#map=18/36.99607/136.83625) | 15 m 先に 名前なしの線 | 172 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1238881253](https://www.openstreetmap.org/way/1238881253)） | 275 | [36.99584, 136.84035](https://www.openstreetmap.org/#map=18/36.99584/136.84035) | 7 m 先に 名前なしの線 | 171 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1238881254](https://www.openstreetmap.org/way/1238881254)） | 275 | [36.99600, 136.84043](https://www.openstreetmap.org/#map=18/36.99600/136.84043) | 8 m 先に 名前なしの線 | 164 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1238881244](https://www.openstreetmap.org/way/1238881244)） | 275 | [36.99643, 136.83646](https://www.openstreetmap.org/#map=18/36.99643/136.83646) | 41 m 先に 名前なしの線 | 164 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1238881255](https://www.openstreetmap.org/way/1238881255)） | 275 | [36.99722, 136.83691](https://www.openstreetmap.org/#map=18/36.99722/136.83691) | 9 m 先に 名前なしの線 | 108 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1238881256](https://www.openstreetmap.org/way/1238881256)） | 275 | [36.99738, 136.83700](https://www.openstreetmap.org/#map=18/36.99738/136.83700) | 9 m 先に 名前なしの線 | 96 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 第２福井火力線（[way 316250970](https://www.openstreetmap.org/way/316250970)） | 154 | [36.34701, 136.46313](https://www.openstreetmap.org/#map=18/36.34701/136.46313) | 0 m 先に 第２福井火力線/粟津線 | 0 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 第２福井火力線/粟津線（[way 1222018235](https://www.openstreetmap.org/way/1222018235)） | 154 | [36.34701, 136.46313](https://www.openstreetmap.org/#map=18/36.34701/136.46313) | 0 m 先に 第２福井火力線 | 0 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1239633327](https://www.openstreetmap.org/way/1239633327)） | 154 | [36.56364, 136.99617](https://www.openstreetmap.org/#map=18/36.56364/136.99617) | 13 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1239633332](https://www.openstreetmap.org/way/1239633332)） | 154 | [36.56376, 136.99615](https://www.openstreetmap.org/#map=18/36.56376/136.99615) | 13 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1238881231](https://www.openstreetmap.org/way/1238881231)） | 154 | [36.99496, 136.83987](https://www.openstreetmap.org/#map=18/36.99496/136.83987) | 6 m 先に 名前なしの線 | 65 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1238881232](https://www.openstreetmap.org/way/1238881232)） | 154 | [36.99507, 136.83993](https://www.openstreetmap.org/#map=18/36.99507/136.83993) | 5 m 先に 名前なしの線 | 78 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1238881231](https://www.openstreetmap.org/way/1238881231)） | 154 | [36.99533, 136.83880](https://www.openstreetmap.org/#map=18/36.99533/136.83880) | 13 m 先に 名前なしの線 | 81 m |
| 線の端の 60 m 以内に別の線 | 北陸 | 名前なし（[way 1238881232](https://www.openstreetmap.org/way/1238881232)） | 154 | [36.99543, 136.83886](https://www.openstreetmap.org/#map=18/36.99543/136.83886) | 13 m 先に 名前なしの線 | 77 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 839633885](https://www.openstreetmap.org/way/839633885)） | 500 | [35.34970, 135.26856](https://www.openstreetmap.org/#map=18/35.34970/135.26856) | 17 m 先に 名前なしの線 | 128 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 839633885](https://www.openstreetmap.org/way/839633885)） | 500 | [35.34987, 135.26619](https://www.openstreetmap.org/#map=18/35.34987/135.26619) | 18 m 先に 名前なしの線 | 136 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 839633886](https://www.openstreetmap.org/way/839633886)） | 500 | [35.35015, 135.26862](https://www.openstreetmap.org/#map=18/35.35015/135.26862) | 18 m 先に 名前なしの線 | 178 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685241](https://www.openstreetmap.org/way/1084685241)） | 500 | [35.55484, 135.97350](https://www.openstreetmap.org/#map=18/35.55484/135.97350) | 9 m 先に 名前なしの線 | 149 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685242](https://www.openstreetmap.org/way/1084685242)） | 500 | [35.55492, 135.97353](https://www.openstreetmap.org/#map=18/35.55492/135.97353) | 9 m 先に 名前なしの線 | 158 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685240](https://www.openstreetmap.org/way/1084685240)） | 500 | [35.55499, 135.97356](https://www.openstreetmap.org/#map=18/35.55499/135.97356) | 9 m 先に 名前なしの線 | 166 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685238](https://www.openstreetmap.org/way/1084685238)） | 500 | [35.55515, 135.97363](https://www.openstreetmap.org/#map=18/35.55515/135.97363) | 8 m 先に 名前なしの線 | 184 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685239](https://www.openstreetmap.org/way/1084685239)） | 500 | [35.55522, 135.97367](https://www.openstreetmap.org/#map=18/35.55522/135.97367) | 8 m 先に 名前なしの線 | 193 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685237](https://www.openstreetmap.org/way/1084685237)） | 500 | [35.55529, 135.97370](https://www.openstreetmap.org/#map=18/35.55529/135.97370) | 9 m 先に 名前なしの線 | 186 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685234](https://www.openstreetmap.org/way/1084685234)） | 500 | [35.55547, 135.97378](https://www.openstreetmap.org/#map=18/35.55547/135.97378) | 8 m 先に 名前なしの線 | 176 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685236](https://www.openstreetmap.org/way/1084685236)） | 500 | [35.55553, 135.97381](https://www.openstreetmap.org/#map=18/35.55553/135.97381) | 8 m 先に 名前なしの線 | 172 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685241](https://www.openstreetmap.org/way/1084685241)） | 500 | [35.55558, 135.97114](https://www.openstreetmap.org/#map=18/35.55558/135.97114) | 9 m 先に 名前なしの線 | 166 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685235](https://www.openstreetmap.org/way/1084685235)） | 500 | [35.55560, 135.97384](https://www.openstreetmap.org/#map=18/35.55560/135.97384) | 8 m 先に 名前なしの線 | 169 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685242](https://www.openstreetmap.org/way/1084685242)） | 500 | [35.55566, 135.97118](https://www.openstreetmap.org/#map=18/35.55566/135.97118) | 8 m 先に 名前なしの線 | 158 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084685240](https://www.openstreetmap.org/way/1084685240)） | 500 | [35.55572, 135.97121](https://www.openstreetmap.org/#map=18/35.55572/135.97121) | 8 m 先に 名前なしの線 | 152 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084271495](https://www.openstreetmap.org/way/1084271495)） | 500 | [35.55588, 135.97019](https://www.openstreetmap.org/#map=18/35.55588/135.97019) | 8 m 先に 名前なしの線 | 130 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084271494](https://www.openstreetmap.org/way/1084271494)） | 500 | [35.55595, 135.97022](https://www.openstreetmap.org/#map=18/35.55595/135.97022) | 8 m 先に 名前なしの線 | 128 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1083544719](https://www.openstreetmap.org/way/1083544719)） | 500 | [35.55595, 135.96967](https://www.openstreetmap.org/#map=18/35.55595/135.96967) | 8 m 先に 名前なしの線 | 92 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1083544720](https://www.openstreetmap.org/way/1083544720)） | 500 | [35.55598, 135.96959](https://www.openstreetmap.org/#map=18/35.55598/135.96959) | 8 m 先に 名前なしの線 | 86 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1083544721](https://www.openstreetmap.org/way/1083544721)） | 500 | [35.55600, 135.96951](https://www.openstreetmap.org/#map=18/35.55600/135.96951) | 8 m 先に 名前なしの線 | 79 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084271493](https://www.openstreetmap.org/way/1084271493)） | 500 | [35.55602, 135.97025](https://www.openstreetmap.org/#map=18/35.55602/135.97025) | 8 m 先に 名前なしの線 | 126 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084271495](https://www.openstreetmap.org/way/1084271495)） | 500 | [35.55611, 135.96945](https://www.openstreetmap.org/#map=18/35.55611/135.96945) | 8 m 先に 名前なしの線 | 66 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1083544713](https://www.openstreetmap.org/way/1083544713)） | 500 | [35.55614, 135.97018](https://www.openstreetmap.org/#map=18/35.55614/135.97018) | 8 m 先に 名前なしの線 | 114 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 829610478](https://www.openstreetmap.org/way/829610478)） | 500 | [35.55616, 135.97010](https://www.openstreetmap.org/#map=18/35.55616/135.97010) | 8 m 先に 名前なしの線 | 106 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084271492](https://www.openstreetmap.org/way/1084271492)） | 500 | [35.55618, 135.97033](https://www.openstreetmap.org/#map=18/35.55618/135.97033) | 8 m 先に 名前なしの線 | 124 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1083544712](https://www.openstreetmap.org/way/1083544712)） | 500 | [35.55619, 135.97002](https://www.openstreetmap.org/#map=18/35.55619/135.97002) | 8 m 先に 名前なしの線 | 98 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084271491](https://www.openstreetmap.org/way/1084271491)） | 500 | [35.55625, 135.97036](https://www.openstreetmap.org/#map=18/35.55625/135.97036) | 8 m 先に 名前なしの線 | 124 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1084271490](https://www.openstreetmap.org/way/1084271490)） | 500 | [35.55632, 135.97039](https://www.openstreetmap.org/#map=18/35.55632/135.97039) | 8 m 先に 名前なしの線 | 124 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 839633884](https://www.openstreetmap.org/way/839633884)） | 275 | [35.35223, 135.26689](https://www.openstreetmap.org/#map=18/35.35223/135.26689) | 11 m 先に 名前なしの線 | 147 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 829610443](https://www.openstreetmap.org/way/829610443)） | 275 | [35.70364, 135.96415](https://www.openstreetmap.org/#map=18/35.70364/135.96415) | 31 m 先に 名前なしの線 | 39 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 829610444](https://www.openstreetmap.org/way/829610444)） | 275 | [35.70377, 135.96385](https://www.openstreetmap.org/#map=18/35.70377/135.96385) | 31 m 先に 名前なしの線 | 45 m |
| 線の端の 60 m 以内に別の線 | 関西 | 滝原分岐線R（[way 464058881](https://www.openstreetmap.org/way/464058881)） | 154 | [34.37950, 136.41838](https://www.openstreetmap.org/#map=18/34.37950/136.41838) | 38 m 先に 三瀬谷分岐線 | 0 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1201727821](https://www.openstreetmap.org/way/1201727821)） | 154 | [34.73943, 135.58949](https://www.openstreetmap.org/#map=18/34.73943/135.58949) | 33 m 先に 名前なしの線 | 26 m |
| 線の端の 60 m 以内に別の線 | 関西 | 名前なし（[way 1201727820](https://www.openstreetmap.org/way/1201727820)） | 154 | [34.73968, 135.58914](https://www.openstreetmap.org/#map=18/34.73968/135.58914) | 42 m 先に 名前なしの線 | 36 m |
| 線の端の 60 m 以内に別の線 | 九州 | 新鹿児島線（[way 700628504](https://www.openstreetmap.org/way/700628504)） | 220 | [31.85623, 130.19986](https://www.openstreetmap.org/#map=18/31.85623/130.19986) | 35 m 先に 川内火力線 | 1 m |
| 線の端の 60 m 以内に別の線 | 九州 | 新鹿児島線（[way 405699053](https://www.openstreetmap.org/way/405699053)） | 220 | [31.85636, 130.19993](https://www.openstreetmap.org/#map=18/31.85636/130.19993) | 19 m 先に 川内火力線 | 0 m |
| 線の端の 60 m 以内に別の線 | 九州 | 川内火力線（[way 700628501](https://www.openstreetmap.org/way/700628501)） | 220 | [31.85652, 130.20000](https://www.openstreetmap.org/#map=18/31.85652/130.20000) | 19 m 先に 新鹿児島線 | 1 m |
| 線の端の 60 m 以内に別の線 | 九州 | 川内火力線（[way 700628502](https://www.openstreetmap.org/way/700628502)） | 220 | [31.85667, 130.20004](https://www.openstreetmap.org/#map=18/31.85667/130.20004) | 36 m 先に 新鹿児島線 | 0 m |
| 線の端の 60 m 以内に別の線 | 九州 | 松島火力南線（[way 238176475](https://www.openstreetmap.org/way/238176475)） | 220 | [32.94164, 129.59627](https://www.openstreetmap.org/#map=18/32.94164/129.59627) | 42 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 九州 | 名前なし（[way 743584646](https://www.openstreetmap.org/way/743584646)） | 220 | [32.94175, 129.59670](https://www.openstreetmap.org/#map=18/32.94175/129.59670) | 42 m 先に 松島火力南線 | 42 m |
| 線の端の 60 m 以内に別の線 | 九州 | 名前なし（[way 219971749](https://www.openstreetmap.org/way/219971749)） | 220 | [33.49093, 130.62149](https://www.openstreetmap.org/#map=18/33.49093/130.62149) | 46 m 先に 筑豊線 | 22 m |
| 線の端の 60 m 以内に別の線 | 九州 | 筑豊線（[way 219568500](https://www.openstreetmap.org/way/219568500)） | 220 | [33.49128, 130.62125](https://www.openstreetmap.org/#map=18/33.49128/130.62125) | 46 m 先に 名前なしの線 | 49 m |
| 線の端の 60 m 以内に別の線 | 九州 | 名前なし（[way 405811245](https://www.openstreetmap.org/way/405811245)） | 220 | [33.90643, 130.86252](https://www.openstreetmap.org/#map=18/33.90643/130.86252) | 16 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 九州 | 名前なし（[way 405811246](https://www.openstreetmap.org/way/405811246)） | 220 | [33.90650, 130.86267](https://www.openstreetmap.org/#map=18/33.90650/130.86267) | 16 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 九州 | 名前なし（[way 405811243](https://www.openstreetmap.org/way/405811243)） | 220 | [33.90666, 130.86296](https://www.openstreetmap.org/#map=18/33.90666/130.86296) | 16 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 九州 | 名前なし（[way 405811241](https://www.openstreetmap.org/way/405811241)） | 220 | [33.90671, 130.86208](https://www.openstreetmap.org/#map=18/33.90671/130.86208) | 12 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 九州 | 名前なし（[way 405811246](https://www.openstreetmap.org/way/405811246)） | 220 | [33.90688, 130.86236](https://www.openstreetmap.org/#map=18/33.90688/130.86236) | 11 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 東北 | 名前なし（[way 233174202](https://www.openstreetmap.org/way/233174202)） | 275 | [37.15488, 139.24861](https://www.openstreetmap.org/#map=18/37.15488/139.24861) | 13 m 先に 名前なしの線 | 13 m |
| 線の端の 60 m 以内に別の線 | 東北 | 名前なし（[way 233174204](https://www.openstreetmap.org/way/233174204)） | 275 | [37.15491, 139.24846](https://www.openstreetmap.org/#map=18/37.15491/139.24846) | 13 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 東北 | 名前なし（[way 233174203](https://www.openstreetmap.org/way/233174203)） | 275 | [37.15494, 139.24827](https://www.openstreetmap.org/#map=18/37.15494/139.24827) | 17 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 東北 | 名前なし（[way 779308565](https://www.openstreetmap.org/way/779308565)） | 154 | [37.31772, 139.03421](https://www.openstreetmap.org/#map=18/37.31772/139.03421) | 21 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 東北 | 名前なし（[way 325971038](https://www.openstreetmap.org/way/325971038)） | 154 | [37.63419, 139.63108](https://www.openstreetmap.org/#map=18/37.63419/139.63108) | 49 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 東北 | 名前なし（[way 829088646](https://www.openstreetmap.org/way/829088646)） | 154 | [38.27264, 140.99209](https://www.openstreetmap.org/#map=18/38.27264/140.99209) | 20 m 先に 名前なしの線 | 214 m |
| 線の端の 60 m 以内に別の線 | 東北 | 名前なし（[way 829088647](https://www.openstreetmap.org/way/829088647)） | 154 | [38.27442, 140.99226](https://www.openstreetmap.org/#map=18/38.27442/140.99226) | 23 m 先に 名前なしの線 | 328 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340294679](https://www.openstreetmap.org/way/340294679)） | 500 | [35.93018, 139.90987](https://www.openstreetmap.org/#map=18/35.93018/139.90987) | 17 m 先に 名前なしの線 | 115 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340290783](https://www.openstreetmap.org/way/340290783)） | 500 | [36.10470, 139.83424](https://www.openstreetmap.org/#map=18/36.10470/139.83424) | 18 m 先に 名前なしの線 | 148 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340290779](https://www.openstreetmap.org/way/340290779)） | 500 | [36.10480, 139.83458](https://www.openstreetmap.org/#map=18/36.10480/139.83458) | 17 m 先に 名前なしの線 | 116 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340290783](https://www.openstreetmap.org/way/340290783)） | 500 | [36.10934, 139.83220](https://www.openstreetmap.org/#map=18/36.10934/139.83220) | 36 m 先に 名前なしの線 | 174 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340290779](https://www.openstreetmap.org/way/340290779)） | 500 | [36.10943, 139.83259](https://www.openstreetmap.org/#map=18/36.10943/139.83259) | 36 m 先に 名前なしの線 | 141 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1134672259](https://www.openstreetmap.org/way/1134672259)） | 275 | [35.48262, 140.01902](https://www.openstreetmap.org/#map=18/35.48262/140.01902) | 17 m 先に 名前なしの線 | 80 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1134672258](https://www.openstreetmap.org/way/1134672258)） | 275 | [35.48274, 140.01913](https://www.openstreetmap.org/#map=18/35.48274/140.01913) | 17 m 先に 名前なしの線 | 64 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1134672261](https://www.openstreetmap.org/way/1134672261)） | 275 | [35.48313, 140.01946](https://www.openstreetmap.org/#map=18/35.48313/140.01946) | 17 m 先に 名前なしの線 | 28 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1134672260](https://www.openstreetmap.org/way/1134672260)） | 275 | [35.48326, 140.01956](https://www.openstreetmap.org/#map=18/35.48326/140.01956) | 17 m 先に 名前なしの線 | 30 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1081097242](https://www.openstreetmap.org/way/1081097242)） | 275 | [35.88682, 140.72996](https://www.openstreetmap.org/#map=18/35.88682/140.72996) | 24 m 先に 名前なしの線 | 1 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1081097241](https://www.openstreetmap.org/way/1081097241)） | 275 | [35.88693, 140.73020](https://www.openstreetmap.org/#map=18/35.88693/140.73020) | 24 m 先に 名前なしの線 | 25 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340301063](https://www.openstreetmap.org/way/340301063)） | 275 | [35.93245, 139.91045](https://www.openstreetmap.org/#map=18/35.93245/139.91045) | 47 m 先に 名前なしの線 | 116 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340301076](https://www.openstreetmap.org/way/340301076)） | 275 | [35.93271, 139.90986](https://www.openstreetmap.org/#map=18/35.93271/139.90986) | 47 m 先に 名前なしの線 | 135 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340301062](https://www.openstreetmap.org/way/340301062)） | 275 | [35.93297, 139.90928](https://www.openstreetmap.org/#map=18/35.93297/139.90928) | 46 m 先に 名前なしの線 | 107 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340300426](https://www.openstreetmap.org/way/340300426)） | 275 | [35.93338, 139.90944](https://www.openstreetmap.org/#map=18/35.93338/139.90944) | 8 m 先に 名前なしの線 | 150 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340300421](https://www.openstreetmap.org/way/340300421)） | 275 | [35.93355, 139.90954](https://www.openstreetmap.org/#map=18/35.93355/139.90954) | 10 m 先に 名前なしの線 | 151 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1082612597](https://www.openstreetmap.org/way/1082612597)） | 275 | [35.94004, 140.66198](https://www.openstreetmap.org/#map=18/35.94004/140.66198) | 25 m 先に 住友金属線 | 97 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340700779](https://www.openstreetmap.org/way/340700779)） | 275 | [36.10485, 139.83375](https://www.openstreetmap.org/#map=18/36.10485/139.83375) | 38 m 先に 名前なしの線 | 180 m |
| 線の端の 60 m 以内に別の線 | 東京 | 阿武隈線（[way 105884502](https://www.openstreetmap.org/way/105884502)） | 275 | [36.91716, 140.81433](https://www.openstreetmap.org/#map=18/36.91716/140.81433) | 59 m 先に 勿来幹線 | 1 m |
| 線の端の 60 m 以内に別の線 | 東京 | 勿来幹線（[way 1556490127](https://www.openstreetmap.org/way/1556490127)） | 275 | [36.91718, 140.81367](https://www.openstreetmap.org/#map=18/36.91718/140.81367) | 59 m 先に 阿武隈線 | 2 m |
| 線の端の 60 m 以内に別の線 | 東京 | 新川線（[way 81838531](https://www.openstreetmap.org/way/81838531)） | 154 | [35.52960, 139.68592](https://www.openstreetmap.org/#map=18/35.52960/139.68592) | 45 m 先に 島崎線 | 101 m |
| 線の端の 60 m 以内に別の線 | 東京 | 横浜火力東線7・8L（[way 134772644](https://www.openstreetmap.org/way/134772644)） | 154 | [35.53511, 139.65040](https://www.openstreetmap.org/#map=18/35.53511/139.65040) | 20 m 先に 横浜火力東線5・6L | 69 m |
| 線の端の 60 m 以内に別の線 | 東京 | 横浜火力東線5・6L（[way 134772645](https://www.openstreetmap.org/way/134772645)） | 154 | [35.53527, 139.65049](https://www.openstreetmap.org/#map=18/35.53527/139.65049) | 20 m 先に 横浜火力東線7・8L | 51 m |
| 線の端の 60 m 以内に別の線 | 東京 | 城山線（[way 1025959662](https://www.openstreetmap.org/way/1025959662)） | 154 | [35.58934, 139.28406](https://www.openstreetmap.org/#map=18/35.58934/139.28406) | 0 m 先に 城山線・GLP相模原線 | 0 m |
| 線の端の 60 m 以内に別の線 | 東京 | 桜ヶ丘線（[way 37812945](https://www.openstreetmap.org/way/37812945)） | 154 | [35.60631, 139.51011](https://www.openstreetmap.org/#map=18/35.60631/139.51011) | 41 m 先に 生田線 | 41 m |
| 線の端の 60 m 以内に別の線 | 東京 | 和田堀線（[way 37814102](https://www.openstreetmap.org/way/37814102)） | 154 | [35.67422, 139.58960](https://www.openstreetmap.org/#map=18/35.67422/139.58960) | 12 m 先に 北烏山線 | 62 m |
| 線の端の 60 m 以内に別の線 | 東京 | 北多摩線（[way 37814060](https://www.openstreetmap.org/way/37814060)） | 154 | [35.67468, 139.58839](https://www.openstreetmap.org/#map=18/35.67468/139.58839) | 20 m 先に 高井戸線 | 79 m |
| 線の端の 60 m 以内に別の線 | 東京 | 下総線（[way 1137194991](https://www.openstreetmap.org/way/1137194991)） | 154 | [35.72370, 139.98332](https://www.openstreetmap.org/#map=18/35.72370/139.98332) | 18 m 先に 北船橋線 | 53 m |
| 線の端の 60 m 以内に別の線 | 東京 | 北船橋線（[way 1137194992](https://www.openstreetmap.org/way/1137194992)） | 154 | [35.72377, 139.98350](https://www.openstreetmap.org/#map=18/35.72377/139.98350) | 18 m 先に 下総線 | 38 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1139095719](https://www.openstreetmap.org/way/1139095719)） | 154 | [35.76431, 139.87389](https://www.openstreetmap.org/#map=18/35.76431/139.87389) | 11 m 先に 名前なしの線 | 15 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1139095718](https://www.openstreetmap.org/way/1139095718)） | 154 | [35.76439, 139.87383](https://www.openstreetmap.org/#map=18/35.76439/139.87383) | 10 m 先に 亀戸線 | 9 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1138582148](https://www.openstreetmap.org/way/1138582148)） | 154 | [35.86841, 139.90421](https://www.openstreetmap.org/#map=18/35.86841/139.90421) | 21 m 先に 北千葉浄水線 | 0 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1138582147](https://www.openstreetmap.org/way/1138582147)） | 154 | [35.86854, 139.90382](https://www.openstreetmap.org/#map=18/35.86854/139.90382) | 22 m 先に 名前なしの線 | 22 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340300422](https://www.openstreetmap.org/way/340300422)） | 154 | [35.93221, 139.90894](https://www.openstreetmap.org/#map=18/35.93221/139.90894) | 15 m 先に 名前なしの線 | 45 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 340300424](https://www.openstreetmap.org/way/340300424)） | 154 | [35.93233, 139.90901](https://www.openstreetmap.org/#map=18/35.93233/139.90901) | 15 m 先に 名前なしの線 | 50 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1140763570](https://www.openstreetmap.org/way/1140763570)） | 154 | [35.95337, 139.96395](https://www.openstreetmap.org/#map=18/35.95337/139.96395) | 12 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1140763569](https://www.openstreetmap.org/way/1140763569)） | 154 | [35.95344, 139.96404](https://www.openstreetmap.org/#map=18/35.95344/139.96404) | 12 m 先に 名前なしの線 | 11 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1065779751](https://www.openstreetmap.org/way/1065779751)） | 154 | [36.46183, 139.90989](https://www.openstreetmap.org/#map=18/36.46183/139.90989) | 12 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1065779750](https://www.openstreetmap.org/way/1065779750)） | 154 | [36.46184, 139.90976](https://www.openstreetmap.org/#map=18/36.46184/139.90976) | 12 m 先に 名前なしの線 | 12 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1140701482](https://www.openstreetmap.org/way/1140701482)） | 154 | [36.54246, 139.99405](https://www.openstreetmap.org/#map=18/36.54246/139.99405) | 10 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1140701481](https://www.openstreetmap.org/way/1140701481)） | 154 | [36.54255, 139.99403](https://www.openstreetmap.org/#map=18/36.54255/139.99403) | 10 m 先に 名前なしの線 | 10 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1072562259](https://www.openstreetmap.org/way/1072562259)） | 154 | [36.78533, 139.94699](https://www.openstreetmap.org/#map=18/36.78533/139.94699) | 10 m 先に 名前なしの線 | 0 m |
| 線の端の 60 m 以内に別の線 | 東京 | 名前なし（[way 1072562258](https://www.openstreetmap.org/way/1072562258)） | 154 | [36.78543, 139.94700](https://www.openstreetmap.org/#map=18/36.78543/139.94700) | 10 m 先に 名前なしの線 | 11 m |
| 線の端の 300 m 以内に変電所 | 中部 | 碧南岡崎線（[way 102286794](https://www.openstreetmap.org/way/102286794)） | 154 | [34.84271, 136.96496](https://www.openstreetmap.org/#map=18/34.84271/136.96496) | 95 m 先に 川口町五丁目変電所 | 68 m |
| 線の端の 300 m 以内に変電所 | 中部 | 名前なし（[way 209269427](https://www.openstreetmap.org/way/209269427)） | 154 | [35.52037, 137.52353](https://www.openstreetmap.org/#map=18/35.52037/137.52353) | 194 m 先に 落合川 | 101 m |
| 線の端の 300 m 以内に変電所 | 北海道 | 名前なし（[way 640518256](https://www.openstreetmap.org/way/640518256)） | 275 | [42.61332, 141.80561](https://www.openstreetmap.org/#map=18/42.61332/141.80561) | 198 m 先に 苫小牧市変電所_3 | 339 m |
| 線の端の 300 m 以内に変電所 | 北陸 | 名前なし（[way 212039849](https://www.openstreetmap.org/way/212039849)） | 275 | [35.50466, 136.87157](https://www.openstreetmap.org/#map=18/35.50466/136.87157) | 99 m 先に 関開閉所 | 0 m |
| 線の端の 300 m 以内に変電所 | 関西 | 名前なし（[way 177615692](https://www.openstreetmap.org/way/177615692)） | 275 | [35.08196, 136.61782](https://www.openstreetmap.org/#map=18/35.08196/136.61782) | 121 m 先に 西名古屋変電所 | 126 m |
| 線の端の 300 m 以内に変電所 | 九州 | 名前なし（[way 704876994](https://www.openstreetmap.org/way/704876994)） | 500 | [33.13411, 131.72736](https://www.openstreetmap.org/#map=18/33.13411/131.72736) | 75 m 先に 東九州変電所 | 134 m |
| 線の端の 300 m 以内に変電所 | 九州 | 東九州幹線（[way 180914523](https://www.openstreetmap.org/way/180914523)） | 500 | [33.13531, 131.72754](https://www.openstreetmap.org/#map=18/33.13531/131.72754) | 95 m 先に 東九州変電所 | 1 m |
| 線の端の 300 m 以内に変電所 | 九州 | 新鹿児島線（[way 237473951](https://www.openstreetmap.org/way/237473951)） | 220 | [31.53681, 130.46348](https://www.openstreetmap.org/#map=18/31.53681/130.46348) | 61 m 先に 新鹿児島変電所 | 0 m |
| 線の端の 300 m 以内に変電所 | 九州 | 名前なし（[way 239770590](https://www.openstreetmap.org/way/239770590)） | 220 | [32.74501, 129.91324](https://www.openstreetmap.org/#map=18/32.74501/129.91324) | 91 m 先に 長崎変電所 | 162 m |
| 線の端の 300 m 以内に変電所 | 東京 | 千葉火力線1・2L（[way 156332175](https://www.openstreetmap.org/way/156332175)） | 275 | [35.56433, 140.11276](https://www.openstreetmap.org/#map=18/35.56433/140.11276) | 44 m 先に 新浜町変電所 | 187 m |
| 線の端の 300 m 以内に変電所 | 東京 | 東内幸町線（[way 1556157684](https://www.openstreetmap.org/way/1556157684)） | 275 | [35.66931, 139.75743](https://www.openstreetmap.org/#map=18/35.66931/139.75743) | 98 m 先に 東内幸町変電所 | 135 m |
| 線の端の 300 m 以内に変電所 | 東京 | 東富士線（[way 726559377](https://www.openstreetmap.org/way/726559377)） | 154 | [35.13872, 138.87821](https://www.openstreetmap.org/#map=18/35.13872/138.87821) | 77 m 先に 駿東変電所 | 113 m |
| 線の端の 300 m 以内に変電所 | 東京 | ちば野菊の里浄水場線（[way 1035805907](https://www.openstreetmap.org/way/1035805907)） | 154 | [35.75619, 139.89115](https://www.openstreetmap.org/#map=18/35.75619/139.89115) | 200 m 先に 矢切変電所 | 98 m |
| 線の端の 300 m 以内に変電所 | 東京 | 名前なし（[way 519031689](https://www.openstreetmap.org/way/519031689)） | 154 | [36.69290, 138.90662](https://www.openstreetmap.org/#map=18/36.69290/138.90662) | 111 m 先に 須川変電所 | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 179417726](https://www.openstreetmap.org/way/179417726)） | 275 | [34.98681, 136.84771](https://www.openstreetmap.org/#map=18/34.98681/136.84771) | — | 125 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 179417721](https://www.openstreetmap.org/way/179417721)） | 275 | [34.98729, 136.84680](https://www.openstreetmap.org/#map=18/34.98729/136.84680) | — | 91 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 179417719](https://www.openstreetmap.org/way/179417719)） | 275 | [34.98921, 136.84431](https://www.openstreetmap.org/#map=18/34.98921/136.84431) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 253528811](https://www.openstreetmap.org/way/253528811)） | 275 | [35.04169, 136.90122](https://www.openstreetmap.org/#map=18/35.04169/136.90122) | — | 492 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 170366049](https://www.openstreetmap.org/way/170366049)） | 275 | [35.13692, 137.01156](https://www.openstreetmap.org/#map=18/35.13692/137.01156) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 632100416](https://www.openstreetmap.org/way/632100416)） | 275 | [35.14282, 136.56028](https://www.openstreetmap.org/#map=18/35.14282/136.56028) | — | 1 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 192745037](https://www.openstreetmap.org/way/192745037)） | 275 | [35.46798, 137.16856](https://www.openstreetmap.org/#map=18/35.46798/137.16856) | — | 76 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 1028287078](https://www.openstreetmap.org/way/1028287078)） | 275 | [36.21914, 136.88126](https://www.openstreetmap.org/#map=18/36.21914/136.88126) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 210090105](https://www.openstreetmap.org/way/210090105)） | 154 | [34.78731, 138.04215](https://www.openstreetmap.org/#map=18/34.78731/138.04215) | — | 681 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 1165383734](https://www.openstreetmap.org/way/1165383734)） | 154 | [34.87115, 136.52069](https://www.openstreetmap.org/#map=18/34.87115/136.52069) | — | 1 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 204310099](https://www.openstreetmap.org/way/204310099)） | 154 | [34.97159, 137.12558](https://www.openstreetmap.org/#map=18/34.97159/137.12558) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 192565281](https://www.openstreetmap.org/way/192565281)） | 154 | [34.98449, 137.90252](https://www.openstreetmap.org/#map=18/34.98449/137.90252) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 210234473](https://www.openstreetmap.org/way/210234473)） | 154 | [35.01025, 137.90819](https://www.openstreetmap.org/#map=18/35.01025/137.90819) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 192745035](https://www.openstreetmap.org/way/192745035)） | 154 | [35.45395, 137.13494](https://www.openstreetmap.org/#map=18/35.45395/137.13494) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 209429365](https://www.openstreetmap.org/way/209429365)） | 154 | [35.69595, 137.74729](https://www.openstreetmap.org/#map=18/35.69595/137.74729) | — | 1 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 211037493](https://www.openstreetmap.org/way/211037493)） | 154 | [35.78046, 137.96432](https://www.openstreetmap.org/#map=18/35.78046/137.96432) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 1256864650](https://www.openstreetmap.org/way/1256864650)） | 154 | [36.07796, 137.41196](https://www.openstreetmap.org/#map=18/36.07796/137.41196) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 815037707](https://www.openstreetmap.org/way/815037707)） | 154 | [36.15360, 137.23840](https://www.openstreetmap.org/#map=18/36.15360/137.23840) | — | 1 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 1239633343](https://www.openstreetmap.org/way/1239633343)） | 154 | [36.38197, 137.18139](https://www.openstreetmap.org/#map=18/36.38197/137.18139) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 1239633349](https://www.openstreetmap.org/way/1239633349)） | 154 | [36.47665, 137.18773](https://www.openstreetmap.org/#map=18/36.47665/137.18773) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 547580179](https://www.openstreetmap.org/way/547580179)） | 154 | [36.53719, 137.43834](https://www.openstreetmap.org/#map=18/36.53719/137.43834) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 1256591815](https://www.openstreetmap.org/way/1256591815)） | 154 | [36.59514, 136.68648](https://www.openstreetmap.org/#map=18/36.59514/136.68648) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 名前なし（[way 976024184](https://www.openstreetmap.org/way/976024184)） | 154 | [36.78578, 137.06422](https://www.openstreetmap.org/#map=18/36.78578/137.06422) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 朝日小川線（[way 592161705](https://www.openstreetmap.org/way/592161705)） | 154 | [36.88753, 137.62869](https://www.openstreetmap.org/#map=18/36.88753/137.62869) | — | 0 m |
| 線の端が何もない所で終わる | 中部 | 新愛本黒部線/黒部江口線（[way 1553336174](https://www.openstreetmap.org/way/1553336174)） | 154 | [36.89057, 137.47849](https://www.openstreetmap.org/#map=18/36.89057/137.47849) | — | 144 m |
| 線の端が何もない所で終わる | 中部 | 青海線（[way 618356286](https://www.openstreetmap.org/way/618356286)） | 154 | [37.01336, 137.79650](https://www.openstreetmap.org/#map=18/37.01336/137.79650) | — | 85 m |
| 線の端が何もない所で終わる | 中国 | 名前なし（[way 243471277](https://www.openstreetmap.org/way/243471277)） | 220 | [33.95483, 132.12312](https://www.openstreetmap.org/#map=18/33.95483/132.12312) | — | 1 m |
| 線の端が何もない所で終わる | 中国 | 名前なし（[way 185941787](https://www.openstreetmap.org/way/185941787)） | 220 | [34.44514, 132.87067](https://www.openstreetmap.org/#map=18/34.44514/132.87067) | — | 67 m |
| 線の端が何もない所で終わる | 中国 | 名前なし（[way 151462889](https://www.openstreetmap.org/way/151462889)） | 220 | [34.44520, 132.76022](https://www.openstreetmap.org/#map=18/34.44520/132.76022) | — | 0 m |
| 線の端が何もない所で終わる | 中国 | 名前なし（[way 661745203](https://www.openstreetmap.org/way/661745203)） | 187 | [34.12649, 133.66559](https://www.openstreetmap.org/#map=18/34.12649/133.66559) | — | 0 m |
| 線の端が何もない所で終わる | 中国 | 名前なし（[way 1191968009](https://www.openstreetmap.org/way/1191968009)） | 187 | [34.34905, 133.85256](https://www.openstreetmap.org/#map=18/34.34905/133.85256) | — | 737 m |
| 線の端が何もない所で終わる | 北海道 | 京極幹線（[way 624389505](https://www.openstreetmap.org/way/624389505)） | 275 | [42.93764, 140.97134](https://www.openstreetmap.org/#map=18/42.93764/140.97134) | — | 0 m |
| 線の端が何もない所で終わる | 北陸 | 名前なし（[way 315662818](https://www.openstreetmap.org/way/315662818)） | 275 | [36.48431, 137.71842](https://www.openstreetmap.org/#map=18/36.48431/137.71842) | — | 4720 m |
| 線の端が何もない所で終わる | 北陸 | 名前なし（[way 814581988](https://www.openstreetmap.org/way/814581988)） | 154 | [36.00573, 137.29472](https://www.openstreetmap.org/#map=18/36.00573/137.29472) | — | 0 m |
| 線の端が何もない所で終わる | 北陸 | 名前なし（[way 1221247460](https://www.openstreetmap.org/way/1221247460)） | 154 | [36.38426, 136.63939](https://www.openstreetmap.org/#map=18/36.38426/136.63939) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 名前なし（[way 466221560](https://www.openstreetmap.org/way/466221560)） | 500 | [33.86073, 134.65037](https://www.openstreetmap.org/#map=18/33.86073/134.65037) | — | 1 m |
| 線の端が何もない所で終わる | 関西 | 名前なし（[way 324539814](https://www.openstreetmap.org/way/324539814)） | 500 | [35.52424, 135.34489](https://www.openstreetmap.org/#map=18/35.52424/135.34489) | — | 1 m |
| 線の端が何もない所で終わる | 関西 | 名前なし（[way 1301298483](https://www.openstreetmap.org/way/1301298483)） | 275 | [34.73210, 134.81509](https://www.openstreetmap.org/#map=18/34.73210/134.81509) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 名前なし（[way 1301298483](https://www.openstreetmap.org/way/1301298483)） | 275 | [34.73686, 134.80095](https://www.openstreetmap.org/#map=18/34.73686/134.80095) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 名前なし（[way 622454358](https://www.openstreetmap.org/way/622454358)） | 275 | [35.13530, 136.57610](https://www.openstreetmap.org/#map=18/35.13530/136.57610) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 名前なし（[way 632100415](https://www.openstreetmap.org/way/632100415)） | 275 | [35.16734, 136.50291](https://www.openstreetmap.org/#map=18/35.16734/136.50291) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 名前なし（[way 211909768](https://www.openstreetmap.org/way/211909768)） | 275 | [35.17612, 136.81641](https://www.openstreetmap.org/#map=18/35.17612/136.81641) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 名前なし（[way 320444666](https://www.openstreetmap.org/way/320444666)） | 275 | [35.55898, 135.25380](https://www.openstreetmap.org/#map=18/35.55898/135.25380) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 電発尾鷲連絡線（[way 445839393](https://www.openstreetmap.org/way/445839393)） | 154 | [34.06710, 136.17745](https://www.openstreetmap.org/#map=18/34.06710/136.17745) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 紀勢分岐線（[way 464058879](https://www.openstreetmap.org/way/464058879)） | 154 | [34.27134, 136.40174](https://www.openstreetmap.org/#map=18/34.27134/136.40174) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 南島分岐線（[way 464058880](https://www.openstreetmap.org/way/464058880)） | 154 | [34.28249, 136.49806](https://www.openstreetmap.org/#map=18/34.28249/136.49806) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 三瀬谷分岐線（[way 464062750](https://www.openstreetmap.org/way/464062750)） | 154 | [34.38811, 136.40125](https://www.openstreetmap.org/#map=18/34.38811/136.40125) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 栃原分岐線（[way 464062751](https://www.openstreetmap.org/way/464062751)） | 154 | [34.43898, 136.50134](https://www.openstreetmap.org/#map=18/34.43898/136.50134) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 名前なし（[way 159659128](https://www.openstreetmap.org/way/159659128)） | 154 | [34.61094, 135.60843](https://www.openstreetmap.org/#map=18/34.61094/135.60843) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 名前なし（[way 159036312](https://www.openstreetmap.org/way/159036312)） | 154 | [34.69817, 135.44842](https://www.openstreetmap.org/#map=18/34.69817/135.44842) | — | 0 m |
| 線の端が何もない所で終わる | 関西 | 名前なし（[way 1219903063](https://www.openstreetmap.org/way/1219903063)） | 154 | [35.42859, 136.30674](https://www.openstreetmap.org/#map=18/35.42859/136.30674) | — | 0 m |
| 線の端が何もない所で終わる | 九州 | 川内原子力線（[way 1525026888](https://www.openstreetmap.org/way/1525026888)） | 500 | [31.83313, 130.19523](https://www.openstreetmap.org/#map=18/31.83313/130.19523) | — | 1 m |
| 線の端が何もない所で終わる | 九州 | 川内原子力線（[way 1525026888](https://www.openstreetmap.org/way/1525026888)） | 500 | [31.83344, 130.19521](https://www.openstreetmap.org/#map=18/31.83344/130.19521) | — | 35 m |
| 線の端が何もない所で終わる | 九州 | 苓北火力線・苓北一の勢線（[way 213736246](https://www.openstreetmap.org/way/213736246)） | 500 | [32.48474, 130.04433](https://www.openstreetmap.org/#map=18/32.48474/130.04433) | — | 0 m |
| 線の端が何もない所で終わる | 九州 | 松浦火力線（[way 176776864](https://www.openstreetmap.org/way/176776864)） | 500 | [33.34857, 129.68433](https://www.openstreetmap.org/#map=18/33.34857/129.68433) | — | 0 m |
| 線の端が何もない所で終わる | 九州 | 大分製鉄線（[way 1517875990](https://www.openstreetmap.org/way/1517875990)） | 220 | [33.25342, 131.65292](https://www.openstreetmap.org/#map=18/33.25342/131.65292) | — | 104 m |
| 線の端が何もない所で終わる | 九州 | 大分製鉄線（[way 1517875990](https://www.openstreetmap.org/way/1517875990)） | 220 | [33.25358, 131.65289](https://www.openstreetmap.org/#map=18/33.25358/131.65289) | — | 121 m |
| 線の端が何もない所で終わる | 九州 | 山家鳥栖線（[way 173296915](https://www.openstreetmap.org/way/173296915)） | 220 | [33.45774, 130.51630](https://www.openstreetmap.org/#map=18/33.45774/130.51630) | — | 0 m |
| 線の端が何もない所で終わる | 九州 | 新日鉄戸畑線（[way 1511503197](https://www.openstreetmap.org/way/1511503197)） | 220 | [33.90402, 130.82575](https://www.openstreetmap.org/#map=18/33.90402/130.82575) | — | 0 m |
| 線の端が何もない所で終わる | 九州 | 名前なし（[way 318438197](https://www.openstreetmap.org/way/318438197)） | 220 | [33.96781, 131.16703](https://www.openstreetmap.org/#map=18/33.96781/131.16703) | — | 489 m |
| 線の端が何もない所で終わる | 東北 | 名前なし（[way 1042235622](https://www.openstreetmap.org/way/1042235622)） | 275 | [38.66275, 140.90429](https://www.openstreetmap.org/#map=18/38.66275/140.90429) | — | 0 m |
| 線の端が何もない所で終わる | 東北 | 名前なし（[way 170197075](https://www.openstreetmap.org/way/170197075)） | 154 | [37.94403, 139.08222](https://www.openstreetmap.org/#map=18/37.94403/139.08222) | — | 0 m |
| 線の端が何もない所で終わる | 東北 | 名前なし（[way 103760550](https://www.openstreetmap.org/way/103760550)） | 154 | [38.26415, 141.01819](https://www.openstreetmap.org/#map=18/38.26415/141.01819) | — | 0 m |
| 線の端が何もない所で終わる | 東北 | 名前なし（[way 769008376](https://www.openstreetmap.org/way/769008376)） | 154 | [38.44990, 140.04689](https://www.openstreetmap.org/#map=18/38.44990/140.04689) | — | 0 m |
| 線の端が何もない所で終わる | 東北 | 名前なし（[way 721658981](https://www.openstreetmap.org/way/721658981)） | 154 | [39.26953, 141.86826](https://www.openstreetmap.org/#map=18/39.26953/141.86826) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | 神流川線（[way 563756739](https://www.openstreetmap.org/way/563756739)） | 500 | [36.03395, 138.70539](https://www.openstreetmap.org/#map=18/36.03395/138.70539) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | 住友金属線（[way 1082612596](https://www.openstreetmap.org/way/1082612596)） | 275 | [35.94174, 140.66346](https://www.openstreetmap.org/#map=18/35.94174/140.66346) | — | 111 m |
| 線の端が何もない所で終わる | 東京 | 常陸那珂火力線（[way 103827618](https://www.openstreetmap.org/way/103827618)） | 275 | [36.43570, 140.60958](https://www.openstreetmap.org/#map=18/36.43570/140.60958) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | 東海原子力線（[way 658373455](https://www.openstreetmap.org/way/658373455)） | 275 | [36.46754, 140.60513](https://www.openstreetmap.org/#map=18/36.46754/140.60513) | — | 1 m |
| 線の端が何もない所で終わる | 東京 | 八木沢線（[way 518992990](https://www.openstreetmap.org/way/518992990)） | 275 | [36.91016, 139.05577](https://www.openstreetmap.org/#map=18/36.91016/139.05577) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | 勿来幹線（[way 1556490127](https://www.openstreetmap.org/way/1556490127)） | 275 | [36.91725, 140.81341](https://www.openstreetmap.org/#map=18/36.91725/140.81341) | — | 23 m |
| 線の端が何もない所で終わる | 東京 | 旭硝子千葉線（[way 1133622347](https://www.openstreetmap.org/way/1133622347)） | 154 | [35.53324, 140.08849](https://www.openstreetmap.org/#map=18/35.53324/140.08849) | — | 128 m |
| 線の端が何もない所で終わる | 東京 | 柿生線;川崎火力線（[way 77166686](https://www.openstreetmap.org/way/77166686)） | 154 | [35.53398, 139.67178](https://www.openstreetmap.org/#map=18/35.53398/139.67178) | — | 32 m |
| 線の端が何もない所で終わる | 東京 | 東海鳥屋線（建設中）（[way 1220959276](https://www.openstreetmap.org/way/1220959276)） | 154 | [35.55212, 139.25576](https://www.openstreetmap.org/#map=18/35.55212/139.25576) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | 戸越線（[way 90836518](https://www.openstreetmap.org/way/90836518)） | 154 | [35.59404, 139.64484](https://www.openstreetmap.org/#map=18/35.59404/139.64484) | — | 456 m |
| 線の端が何もない所で終わる | 東京 | 戸越線（[way 90836518](https://www.openstreetmap.org/way/90836518)） | 154 | [35.59746, 139.64763](https://www.openstreetmap.org/#map=18/35.59746/139.64763) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | 桜ヶ丘線（[way 36737022](https://www.openstreetmap.org/way/36737022)） | 154 | [35.60838, 139.50903](https://www.openstreetmap.org/#map=18/35.60838/139.50903) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | 名前なし（[way 638224923](https://www.openstreetmap.org/way/638224923)） | 154 | [35.78494, 138.42454](https://www.openstreetmap.org/#map=18/35.78494/138.42454) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | 名前なし（[way 1140712967](https://www.openstreetmap.org/way/1140712967)） | 154 | [36.18280, 139.87885](https://www.openstreetmap.org/#map=18/36.18280/139.87885) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | コベルコパワー真岡線（[way 1061336374](https://www.openstreetmap.org/way/1061336374)） | 154 | [36.45865, 139.97220](https://www.openstreetmap.org/#map=18/36.45865/139.97220) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | 原子力線（[way 1139127266](https://www.openstreetmap.org/way/1139127266)） | 154 | [36.46448, 140.60510](https://www.openstreetmap.org/#map=18/36.46448/140.60510) | — | 153 m |
| 線の端が何もない所で終わる | 東京 | 名前なし（[way 1139149695](https://www.openstreetmap.org/way/1139149695)） | 154 | [36.49455, 140.41750](https://www.openstreetmap.org/#map=18/36.49455/140.41750) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | 新里連系線（[way 1149340788](https://www.openstreetmap.org/way/1149340788)） | 154 | [36.63893, 139.81438](https://www.openstreetmap.org/#map=18/36.63893/139.81438) | — | 0 m |
| 線の端が何もない所で終わる | 東京 | 須田貝線（[way 519055294](https://www.openstreetmap.org/way/519055294)） | 154 | [36.72053, 138.98289](https://www.openstreetmap.org/#map=18/36.72053/138.98289) | — | 0 m |

## 正典: 変電所でない接続点で電圧の違う枝がつながる所（全件）

変圧器なしで電圧は変わらないので、モデルの誤接続の有力な候補。併架の鉄塔で別の電圧の線どうしをつないでしまった可能性が高い。

| 地域 | 電圧 | 枝の名前 | 位置 | 本系統 | 最寄りの変電所 |
|---|---|---|---|---|---|
| 中部 | 77 / 500 kV | 中部送電線_711・中部電力パワーグリッド（株）大須賀変電所~上ノ原変電所線・第二浜岡幹線 | [34.67553, 138.15922](https://www.openstreetmap.org/#map=18/34.67553/138.15922) | はい | 上ノ原変電所_2 275kV（5,216 m） |
| 中部 | 66 / 77 kV | 津東丸之内線・近鉄部田線 | [34.72498, 136.50117](https://www.openstreetmap.org/#map=18/34.72498/136.50117) | いいえ | 桜田町変電所（1,801 m） |
| 中部 | 77 / 275 kV | 三河線・新城分岐線・西日本電線新城線 | [34.87901, 137.46841](https://www.openstreetmap.org/#map=18/34.87901/137.46841) | はい | 新三河変電所 275kV（1,959 m） |
| 中部 | 66 / 77 kV | 中部送電線_66・戸崎六ッ美線・美合町変電所~中部電力八帖変電所線 | [34.93884, 137.15852](https://www.openstreetmap.org/#map=18/34.93884/137.15852) | はい | 六ッ美変電所（1,803 m） |
| 中部 | 77 / 275 kV | 612 | [35.06841, 137.06690](https://www.openstreetmap.org/#map=18/35.06841/137.06690) | はい | 三好変電所 275kV（404 m） |
| 中部 | 77 / 154 kV | 昭和町寛政-1;寛政築港連絡-1 | [35.10387, 136.86075](https://www.openstreetmap.org/#map=18/35.10387/136.86075) | はい | 寛政変電所 154kV（323 m） |
| 中部 | 66 / 77 kV | JR 西相模-沼津線・JR熱海分岐線・天野変電所~立花二丁目変電所線 / 大仁線 / 三島変電所~函南町変電所線 / 函南町変電所~土肥六丁目変電所線 / 熱・ | [35.14489, 139.03412](https://www.openstreetmap.org/#map=18/35.14489/139.03412) | いいえ | 来宮変電所（5,684 m） |
| 中部 | 77 / 154 kV | 前田町三丁目変電所~愛知変電所線・平戸橋町変電所~北豊田変電所 (Kita Toyota Hendensho)線・平戸橋町変電所~豊田市変電所線・豊田市変電所~ | [35.14915, 137.34435](https://www.openstreetmap.org/#map=18/35.14915/137.34435) | はい | 愛知変電所 500kV（7,997 m） |
| 中部 | 154 / 275 kV | namebind・中部送電線_692・豊田市変電所~愛知変電所線 | [35.15873, 137.43278](https://www.openstreetmap.org/#map=18/35.15873/137.43278) | はい | 豊田市変電所 (untyped)（5,006 m） |
| 中部 | 66 / 77 kV | 中部送電線_27・東京送電線_13 | [35.20005, 138.56187](https://www.openstreetmap.org/#map=18/35.20005/138.56187) | はい | 中野台二丁目変電所（3,149 m） |
| 中部 | 66 / 77 kV | 中野台二丁目変電所~中島町変電所線・東京電力パワーグリッド 66.0kV線・浅間上町変電所~中島町変電所線・浅間上町変電所~中島町変電所線 / 東京電力パワーグ | [35.20822, 138.62457](https://www.openstreetmap.org/#map=18/35.20822/138.62457) | はい | 中島町変電所（3,654 m） |
| 中部 | 66 / 77 kV | leadin・新長浜変電所~長浜変電所線・新長浜支線 | [35.39062, 136.28554](https://www.openstreetmap.org/#map=18/35.39062/136.28554) | はい | 新長浜変電所 66kV（932 m） |
| 中部 | 77 / 154 kV | 中部電力パワーグリッド 154.0kV線・加茂野町鷹之巣変電所~西栃井変電所線・太田分岐線-1 | [35.46406, 137.01427](https://www.openstreetmap.org/#map=18/35.46406/137.01427) | はい | 太田変電所（2,410 m） |
| 中部 | 154 / 275 kV | 北陸電力送配電 154.0kV線・奥野々変電所~色浜変電所_2線 | [35.67311, 136.08920](https://www.openstreetmap.org/#map=18/35.67311/136.08920) | はい | 敦賀変電所 154kV（3,032 m） |
| 中部 | 77 / 500 kV | tokyo_line_4153・中部送電線_390・東京電力パワーグリッド 500.0kV線 | [36.14065, 138.23408](https://www.openstreetmap.org/#map=18/36.14065/138.23408) | はい | 諏訪変電所 154kV（12,696 m） |
| 中部 | 66 / 77 kV | tokyo_line_4153・中部送電線_390・中部電力パワーグリッド 77.0kV線 / 島川原変電所~小諸市変電所線 / 諏訪変電所~島川原変電所線・八 | [36.16566, 138.17455](https://www.openstreetmap.org/#map=18/36.16566/138.17455) | はい | 諏訪変電所 154kV（9,388 m） |
| 中部 | 66 / 77 kV | 佐久平駅東変電所~小諸市変電所線・小諸市変電所~佐久平駅東変電所線・島川原変電所~佐久平駅東変電所線 | [36.30449, 138.45060](https://www.openstreetmap.org/#map=18/36.30449/138.45060) | はい | 小諸市変電所（872 m） |
| 中部 | 66 / 77 kV | tokyo_line_4149・中丸子変電所~八重原変電所線・八重原変電所~諏訪変電所線・大屋変電所~八重原変電所線・大屋変電所~八重原変電所線 / 中部電力パ | [36.32587, 138.30210](https://www.openstreetmap.org/#map=18/36.32587/138.30210) | はい | 中丸子変電所（2,658 m） |
| 中部 | 66 / 77 kV | 中部送電線_919・大屋変電所~小諸市変電所線・大屋変電所~小諸市変電所線 / 小諸市変電所~大字御代田変電所線 / 東京電力海瀬発電所~大字御代田変電所線・東 | [36.32945, 138.43587](https://www.openstreetmap.org/#map=18/36.32945/138.43587) | はい | 小諸市変電所（2,274 m） |
| 中部 | 66 / 77 kV | 中部送電線_841・九十九線 / 軽磯線 / 東京送電線_261・人見線 / 碓氷線 / 九十九線 / 軽磯線 / 東京送電線_261・大字御代田変電所~軽井沢 | [36.33262, 138.61314](https://www.openstreetmap.org/#map=18/36.33262/138.61314) | はい | 軽井沢変電所（2,139 m） |
| 中部 | 77 / 154 kV | 三国町新保変電所~上野変電所線・第２福井火力線・第２福井火力線/粟津線 | [36.37541, 136.48184](https://www.openstreetmap.org/#map=18/36.37541/136.48184) | はい | 新小松変電所 154kV（655 m） |
| 中部 | 66 / 77 kV | tokyo_line_4151・中部送電線_370・国分変電所~真田変電所線・国分変電所~真田変電所線 / 東信坂城連絡線 / 東信大屋線 / 中部電力パワーグ | [36.40647, 138.26751](https://www.openstreetmap.org/#map=18/36.40647/138.26751) | はい | 国分変電所（2,268 m） |
| 中国 | 66 / 110 kV | 富岡変電所~倉敷市変電所線・田頭変電所~富岡変電所線・笠岡変電所~富岡変電所線・鴨方変電所~富岡変電所線 | [34.50338, 133.53940](https://www.openstreetmap.org/#map=18/34.50338/133.53940) | はい | 富岡変電所（1,471 m） |
| 北陸 | 66 / 154 kV | 北陸電力送配電 66.0kV線・南金沢変電所~川北変電所線・川北変電所~北金沢変電所線・新小松線 | [36.48971, 136.54366](https://www.openstreetmap.org/#map=18/36.48971/136.54366) | はい | 川北変電所（2,479 m） |
| 関西 | 77 / 154 kV | 相賀分岐線・関西送電線_81・電源尾鷲南勢線 | [34.15846, 136.27198](https://www.openstreetmap.org/#map=18/34.15846/136.27198) | はい | 宮ノ上変電所（11,308 m） |
| 関西 | 66 / 77 kV | 尾崎支線;尾崎信達線 | [34.36004, 135.25065](https://www.openstreetmap.org/#map=18/34.36004/135.25065) | はい | 尾崎変電所 66kV（150 m） |
| 関西 | 66 / 500 kV | 東吉野変電所~関西電力北野台変電所線・紀北変換所~東大和開閉所線・関西送電線_90 / 東吉野変電所~関西電力北野台変電所線 | [34.40253, 135.82159](https://www.openstreetmap.org/#map=18/34.40253/135.82159) | いいえ | 関西電力北野台変電所 500kV（813 m） |
| 関西 | 77 / 154 kV | namebind・八尾変電所~天美変電所線・金田線・長曽根支線 | [34.58627, 135.51910](https://www.openstreetmap.org/#map=18/34.58627/135.51910) | はい | 天美変電所（847 m） |
| 関西 | 66 / 77 kV | 大蔵谷線;有瀬舞子線・関西電力送配電 77.0kV線・須磨変電所~西神戸変電所線 | [34.67038, 135.08278](https://www.openstreetmap.org/#map=18/34.67038/135.08278) | はい | 須磨変電所（3,383 m） |
| 関西 | 154 / 275 kV | namebind・新奈良線 | [34.69878, 135.65088](https://www.openstreetmap.org/#map=18/34.69878/135.65088) | はい | 石切変電所 154kV（1,044 m） |
| 関西 | 66 / 77 kV | leadin・関西電力送配電 77.0kV線 | [34.70373, 135.40864](https://www.openstreetmap.org/#map=18/34.70373/135.40864) | はい | 道意町七丁目変電所 77kV（648 m） |
| 関西 | 66 / 77 kV | 関西電力送配電 22.0kV線・関西電力送配電 77.0kV線 | [34.77042, 135.44284](https://www.openstreetmap.org/#map=18/34.77042/135.44284) | いいえ | 椎堂変電所 77kV（916 m） |
| 関西 | 77 / 154 kV | 中部送電線_451・中部送電線_885・庄野新鈴鹿線・関西送電線_549・関西送電線_828 | [34.83695, 136.51826](https://www.openstreetmap.org/#map=18/34.83695/136.51826) | はい | 住吉五丁目変電所（1,924 m） |
| 関西 | 66 / 77 kV | 関西送電線_246・高槻上牧線 | [34.85880, 135.64134](https://www.openstreetmap.org/#map=18/34.85880/135.64134) | はい | 梶原六丁目変電所_2（866 m） |
| 関西 | 66 / 275 kV | 溝口変電所~福崎変電所線・溝口支線・関西送電線_259 | [35.05844, 134.74602](https://www.openstreetmap.org/#map=18/35.05844/134.74602) | はい | 開閉所（8,177 m） |
| 関西 | 77 / 154 kV | namebind・蓮台寺町変電所~高宮変電所線・高宮変電所~雨降野変電所線 | [35.21582, 136.25348](https://www.openstreetmap.org/#map=18/35.21582/136.25348) | はい | 高宮変電所 (untyped)（2,294 m） |
| 関西 | 66 / 154 kV | 中部送電線_75・平和町上三宅変電所~平野町四丁目変電所線・平和町上三宅変電所~祖父江町大牧変電所線・関西送電線_444 | [35.23307, 136.75530](https://www.openstreetmap.org/#map=18/35.23307/136.75530) | はい | 平和町上三宅変電所 154kV（1,092 m） |
| 九州 | 66 / 220 kV | 中九州大平線・八代変電所~頭地開閉所線 | [32.45961, 130.70809](https://www.openstreetmap.org/#map=18/32.45961/130.70809) | はい | 新坂本変電所（9,019 m） |
| 九州 | 66 / 110 kV | 長府支線;長府線 | [34.00815, 130.98401](https://www.openstreetmap.org/#map=18/34.00815/130.98401) | はい | 長府変電所 66kV（118 m） |
| 沖縄 | 66 / 132 kV | leadin | [26.43108, 127.84008](https://www.openstreetmap.org/#map=18/26.43108/127.84008) | はい | 石川東山二丁目変電所 66kV（1,258 m） |
| 四国 | 110 / 220 kV | 段原変電所~廿日市変電所線・西広島変電所~廿日市変電所線 | [34.41135, 132.26044](https://www.openstreetmap.org/#map=18/34.41135/132.26044) | はい | 新西広島変電所 110kV（296 m） |
| 東北 | 66 / 154 kV | tokyo_line_4260・東北電力ネットワーク 154.0kV線・西山寺町変電所~笹川変電所線 | [37.33051, 140.34098](https://www.openstreetmap.org/#map=18/37.33051/140.34098) | はい | 笹川変電所（2,652 m） |
| 東北 | 66 / 154 kV | leadin・仙台港変電所~東若林変電所線・東北電力ネットワーク 154.0kV線・東若林変電所~仙台港変電所線・東若林変電所~鶴巻二丁目変電所線 | [38.24220, 140.96369](https://www.openstreetmap.org/#map=18/38.24220/140.96369) | はい | 東若林変電所 154kV（1,253 m） |
| 東京 | 66 / 77 / 154 kV | 中野台二丁目変電所~浅間上町変電所線・岩渕-沼津線・岳南線 / 東京電力パワーグリッド 154.0kV線 / 東京電力パワーグリッド 154.0kV線 / 田代 | [35.19628, 138.64022](https://www.openstreetmap.org/#map=18/35.19628/138.64022) | いいえ | 浅間上町変電所（4,592 m） |
| 東京 | 66 / 77 kV | 中部送電線_187・東京電力パワーグリッド 66.0kV線 / 箱根町変電所~須雲川変電所線 / 函南町変電所~須雲川変電所線 / 元箱根線・箱根町変電所~須雲 | [35.23335, 139.11402](https://www.openstreetmap.org/#map=18/35.23335/139.11402) | いいえ | 箱根町変電所（114 m） |
| 東京 | 66 / 77 kV | 中部送電線_845・中部送電線_847・東京送電線_113・東京送電線_113 / 東京電力パワーグリッド 66.0kV線 / 浅間上町変電所~中島町変電所線  | [35.23909, 138.58939](https://www.openstreetmap.org/#map=18/35.23909/138.58939) | はい | 中島町変電所（1,133 m） |
| 東京 | 66 / 77 kV | leadin | [35.28234, 139.14285](https://www.openstreetmap.org/#map=18/35.28234/139.14285) | はい | 多古変電所 77kV（1,275 m） |
| 東京 | 66 / 77 kV | 中部送電線_189・東京送電線_35・東京電力パワーグリッド 66.0kV線・東京電力パワーグリッド 66.0kV線 / 大雄線 | [35.34890, 139.08990](https://www.openstreetmap.org/#map=18/35.34890/139.08990) | いいえ | 小田急電鉄 松田変電所（4,435 m） |
| 東京 | 66 / 154 kV | 田代幹線・田代幹線 / 田代幹線 / 田代幹線 / 田代幹線 / 田代幹線 / 富士川線・韮崎市変電所~市川大門線 | [35.48878, 138.32805](https://www.openstreetmap.org/#map=18/35.48878/138.32805) | はい | 身延変電所（16,304 m） |
| 東京 | 66 / 275 kV | 豊岡線;上ノ原線・青梅線・青梅線;上ノ原線・飯能線 | [35.80016, 139.31584](https://www.openstreetmap.org/#map=18/35.80016/139.31584) | はい | 青梅変電所 275kV（622 m） |
| 東京 | 66 / 154 kV | 京北線;新倉線・戸田線・戸田線 / 荒川右岸線・笹目線 / 新倉線・笹目線;朝霞線 | [35.80426, 139.62271](https://www.openstreetmap.org/#map=18/35.80426/139.62271) | はい | 朝霞変電所 66kV（1,795 m） |
| 東京 | 66 / 154 kV | 南葛線;東尾久線 | [35.82604, 139.78193](https://www.openstreetmap.org/#map=18/35.82604/139.78193) | はい | 京北変電所 66kV（376 m） |
| 東京 | 66 / 154 kV | 京北線;脇田線 | [35.89294, 139.48100](https://www.openstreetmap.org/#map=18/35.89294/139.48100) | はい | 福原変電所 66kV（282 m） |
| 東京 | 66 / 154 kV | 佐野線 / 板倉線・佐野線 / 赤麻線・楠線 | [36.27430, 139.60370](https://www.openstreetmap.org/#map=18/36.27430/139.60370) | はい | 南佐野変電所（2,420 m） |
| 東京 | 66 / 77 kV | 国分変電所~真田変電所線 / 東信坂城連絡線 / 東信大屋線 / 中部電力パワーグリッド 77.0kV線 / 小諸市変電・大屋変電所~小諸市変電所線 / 小諸市 | [36.29061, 138.49770](https://www.openstreetmap.org/#map=18/36.29061/138.49770) | はい | 佐久平駅東変電所（3,062 m） |
| 東京 | 66 / 154 kV | 東太田線/毛里田線・東太田線/藪塚線・毛里田線/藪塚線/金山線 | [36.31568, 139.33113](https://www.openstreetmap.org/#map=18/36.31568/139.33113) | はい | 東毛変電所 66kV（1,861 m） |
| 東京 | 66 / 77 kV | leadin・中部送電線_841・東京送電線_261・軽磯線 | [36.33087, 138.62050](https://www.openstreetmap.org/#map=18/36.33087/138.62050) | はい | 軽井沢変電所（1,454 m） |
| 東京 | 66 / 77 kV | 中部送電線_1053・東京送電線_269 | [36.52294, 138.62030](https://www.openstreetmap.org/#map=18/36.52294/138.62030) | はい | 大津変電所（3,092 m） |
| 東京 | 66 / 77 kV | 中部送電線_1053・東京送電線_269・軽井沢変電所~大津変電所線 | [36.52332, 138.61718](https://www.openstreetmap.org/#map=18/36.52332/138.61718) | はい | 大津変電所（3,113 m） |

## 作り直し方

```bash
PYTHONPATH=. python scripts/audit_route_connectivity.py --raw <data/osm_raw_towers のある場所>
```

閾値: 別の線まで 60 m・変電所まで 300 m・同じ名前の隙間 2,000 m。入力の SHA256 は docs/data/route_audit/audit.json に書いている。
