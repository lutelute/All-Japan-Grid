# 鉄塔・番号・回線数の補完 — 前と後（2026-11-07）

前: OSM 2026-06-15 取得（90 ファイル）。後: OSM 2026-11-05 取得（1 ファイル、`scripts/fetch_osm_power.py`。送電線・鉄塔と route=power の relation 575 本を、タグを全部付けて取り直した）。数えたのは `scripts/export_osm_routes.py`（docs/OSM_ROUTES.md）。

推定で埋めたものは、地図のカードで必ず「推定」と書き、本物の番号・回線数に見せない。

## 取り直しのきっかけと、その確かめ（関東の区域 (35.6,139.2)-(35.9,139.6)）

取り直しのきっかけは「この区域で 6 月の取得分の鉄塔が今の OSM より約 19% 少ない（3,004 基に対し 3,686 基）」という確認だったが、
これは**数え間違いだった**（オーナー側が 11-07 に訂正。Overpass で区域にかかる送電線の点を全部取っていたので、区域の外にはみ出した線の鉄塔まで数えていた）。
区域の中だけに絞ると 2,985 基（ref あり 2,212・name あり 921）で、こちらの数とも合う。**6 月の取得分に鉄塔の抜けは無かった。**

| 数えたもの | 区域の数 |
|---|---:|
| 6 月の取得分の `power=tower` | 3,004（ref あり 2,189・name あり 790） |
| 11-05 の日本の抽出の `power=tower`（線に載っていない鉄塔も含む） | 3,008（ref あり 2,215・name あり 923） |
| オーナー側の数え直し（Overpass、区域の中だけ） | 2,985（ref あり 2,212・name あり 921） |

取り直しは、OSM を 11-05 時点に新しくする意味で残した（全国で鉄塔 +1,024、番号か名前のある鉄塔 +1,592、route=power の relation 577 本を回線数の推定に使えるようになった）。
入力は nas03 の `osm_jp_power/20261105_agj_transmission/`（抽出そのものと、送電線・鉄塔・route=power に絞った pbf。SHA256 は同じ場所の MANIFEST.sha256）。

- 番号の推定: 同じ線の上で前後に番号のある鉄塔があり、間の基数が番号の差と合うときだけ埋める。路線によって違う番号になる鉄塔（併架など）は埋めない
- 「〇〇線の n 基目」: 番号も推定も無い鉄塔で、路線が一筆書きにたどれるときだけ、北の端から数えた順を出す（OSM に番号なしと明記）
- 線の折れ点: 架空線の途中の点で鉄塔のタグが無いもの。鉄塔の位置であることが多いので、別の印（推定）で出す
- 回線数の推定: OSM に回線数の無い線で、交流は導体数 ÷ 3（3 の倍数のときだけ）、直流は導体数 ÷ 2、それも無ければこの線を通る route=power の relation の数

## 鉄塔

### 前（取り直す前）

| 地域 | 鉄塔 | 番号か名前（OSM） | 番号（推定） | n 基目だけ（推定） | どれも無い | 線の折れ点（推定の鉄塔） |
|---|---:|---:|---:|---:|---:|---:|
| 北海道 | 31,507 | 1,876（6%） | 6 | 16,479 | 13,146 | 4,103 |
| 東北 | 43,848 | 840（2%） | 37 | 39,696 | 3,275 | 3,965 |
| 東京 | 43,474 | 19,601（45%） | 969 | 17,540 | 5,364 | 2,118 |
| 中部 | 34,703 | 1,920（6%） | 11 | 30,696 | 2,076 | 2,017 |
| 北陸 | 7,477 | 46（1%） | 0 | 6,953 | 478 | 866 |
| 関西 | 27,081 | 2,198（8%） | 219 | 23,274 | 1,390 | 2,369 |
| 中国 | 21,437 | 666（3%） | 3 | 20,223 | 545 | 1,153 |
| 四国 | 8,107 | 40（0%） | 0 | 7,742 | 325 | 486 |
| 九州 | 26,809 | 3,614（13%） | 272 | 20,903 | 2,020 | 1,424 |
| 沖縄 | 1,142 | 67（6%） | 0 | 1,042 | 33 | 66 |
| **計** | **245,585** | **30,868**（13%） | **1,517** | **184,548** | **28,652** | **18,567** |

### 後（取り直し・補完のあと）

| 地域 | 鉄塔 | 番号か名前（OSM） | 番号（推定） | n 基目だけ（推定） | どれも無い | 線の折れ点（推定の鉄塔） |
|---|---:|---:|---:|---:|---:|---:|
| 北海道 | 31,624 | 2,234（7%） | 65 | 16,281 | 13,044 | 5,795 |
| 東北 | 44,015 | 867（2%） | 48 | 39,833 | 3,267 | 3,989 |
| 東京 | 43,616 | 19,823（45%） | 1,049 | 17,431 | 5,313 | 2,166 |
| 中部 | 35,041 | 2,016（6%） | 29 | 30,581 | 2,415 | 2,026 |
| 北陸 | 7,564 | 226（3%） | 169 | 6,102 | 1,067 | 870 |
| 関西 | 27,154 | 2,199（8%） | 219 | 23,346 | 1,390 | 2,359 |
| 中国 | 21,470 | 667（3%） | 3 | 20,257 | 543 | 1,181 |
| 四国 | 8,144 | 40（0%） | 0 | 7,779 | 325 | 523 |
| 九州 | 26,837 | 4,321（16%） | 273 | 20,236 | 2,007 | 1,371 |
| 沖縄 | 1,144 | 67（6%） | 0 | 1,042 | 35 | 52 |
| **計** | **246,609** | **32,460**（13%） | **1,855** | **182,888** | **29,406** | **20,332** |

鉄塔は 245,585 → 246,609 基（+1,024）。番号か名前のある鉄塔は OSM で 30,868 → 32,460、推定の番号 1,855、n 基目だけ 182,888。番号・名前・推定・n 基目のどれも無いのは 28,652 → 29,406。

## 回線数（OSM の線）

### 前

| 地域 | OSM の線（line・cable） | 回線数あり（OSM） | 推定（導体数 ÷ 3） | 推定（直流） | 推定（route=power） | 不明 |
|---|---:|---:|---:|---:|---:|---:|
| 北海道 | 4,171 | 1,642（39%） | 2,228 | 2 | 0 | 299 |
| 東北 | 6,303 | 3,939（62%） | 60 | 1 | 0 | 2,303 |
| 東京 | 8,253 | 5,012（61%） | 783 | 0 | 0 | 2,458 |
| 中部 | 3,492 | 1,567（45%） | 318 | 0 | 0 | 1,607 |
| 北陸 | 1,170 | 1,023（87%） | 1 | 0 | 0 | 146 |
| 関西 | 3,440 | 1,807（53%） | 118 | 3 | 0 | 1,512 |
| 中国 | 2,152 | 1,093（51%） | 160 | 0 | 0 | 899 |
| 四国 | 936 | 659（70%） | 3 | 0 | 0 | 274 |
| 九州 | 2,987 | 1,667（56%） | 544 | 1 | 0 | 775 |
| 沖縄 | 117 | 54（46%） | 8 | 0 | 0 | 55 |
| **計** | **33,021** | **18,463**（56%） | **4,223** | **7** | **0** | **10,328** |

### 後

| 地域 | OSM の線（line・cable） | 回線数あり（OSM） | 推定（導体数 ÷ 3） | 推定（直流） | 推定（route=power） | 不明 |
|---|---:|---:|---:|---:|---:|---:|
| 北海道 | 4,539 | 1,558（34%） | 2,119 | 2 | 2 | 858 |
| 東北 | 6,317 | 3,942（62%） | 59 | 1 | 2 | 2,313 |
| 東京 | 8,320 | 5,046（61%） | 829 | 0 | 53 | 2,392 |
| 中部 | 3,527 | 1,574（45%） | 328 | 0 | 9 | 1,616 |
| 北陸 | 1,194 | 1,028（86%） | 28 | 0 | 0 | 138 |
| 関西 | 3,484 | 1,863（53%） | 117 | 3 | 13 | 1,488 |
| 中国 | 2,168 | 1,121（52%） | 160 | 0 | 2 | 885 |
| 四国 | 946 | 664（70%） | 3 | 0 | 0 | 279 |
| 九州 | 3,060 | 1,714（56%） | 601 | 1 | 3 | 741 |
| 沖縄 | 117 | 54（46%） | 8 | 0 | 0 | 55 |
| **計** | **33,672** | **18,564**（55%） | **4,252** | **7** | **84** | **10,765** |

回線数のある線は OSM で 18,463 → 18,564、推定 4,230 → 4,343。どちらも無いのは 10,328 → 10,765。

## 地図の線（正典の枝）の回線数

地図の線 19,909 本のうち、回線数が OSM にある 9,277 本・導体数からの推定 447 本・不明 10,185 本。

### 正典の回線数（計算に使う値）と OSM の回線数が食い違う線: 931 本

OSM の回線数が 1 つの値の線だけを比べた。正典の回線数は台帳・公表値・推定から決めていて（docs/MODEL_INTERVENTIONS.md）、どちらが正しいかはこの表だけでは決めない。正典の回線数は、同じ 2 点を結ぶ並行の線をまとめた数（par）のことがあるので、「OSM 2 → 正典 4」のように正典の方が多いものは誤りとは限らない。気にすべきは、OSM で 2 回線以上なのに正典で 1 回線の線（潮流を 1 回線ぶんの重さで計算している）。

正典の方が少ない線（OSM で多い）: 412 本。うち OSM 2 回線以上で正典 1 回線: 190 本。

組み合わせ（OSM → 正典）: 2 → 4 回線 191 本・4 → 2 回線 183 本・2 → 3 回線 142 本・4 → 1 回線 97 本・1 → 2 回線 95 本・2 → 1 回線 63 本・6 → 2 回線 23 本・3 → 1 回線 19 本

| 地域 | 電圧 | 線 | OSM の回線数 | 正典の回線数 | OSM |
|---|---:|---|---:|---:|---|
| 中部 | 500 kV | 色浜変電所~疋田変電所線 / 関西送電線_715 | 2 | 1 | [way 1085387373](https://www.openstreetmap.org/way/1085387373) |
| 中部 | 275 kV | 佐久間東幹線（山線） / 佐久間東幹線（山線） / 佐久間東幹線（山線） | 2 | 1 | [way 150065046](https://www.openstreetmap.org/way/150065046) |
| 中部 | 275 kV | 原二丁目変電所~東名古屋変電所線 | 2 | 5 | [way 179417727](https://www.openstreetmap.org/way/179417727) |
| 中部 | 275 kV | 幸田変電所~古井町変電所線 | 2 | 1 | [way 511558324](https://www.openstreetmap.org/way/511558324) |
| 中部 | 275 kV | 西尾変電所~吉良町中野変電所線 | 2 | 3 | [way 909243011](https://www.openstreetmap.org/way/909243011) |
| 中部 | 275 kV | 高根町上ケ洞変電所~北部変電所線 | 2 | 3 | [way 209518469](https://www.openstreetmap.org/way/209518469) |
| 中部 | 154 kV | 中部送電線_373 / 遠江高塚線 / 遠江高塚線 / 遠江高塚線 | 6 | 1 | [way 643172773](https://www.openstreetmap.org/way/643172773) |
| 中部 | 154 kV | 岩倉北一宮線;岩倉北一宮-4 | 4 | 2 | [way 161767716](https://www.openstreetmap.org/way/161767716) |
| 中部 | 110 kV | 大村一丁目変電所~中部電力株式会社　日吉変電所線 | 2 | 3 | [way 1089980993](https://www.openstreetmap.org/way/1089980993) |
| 中部 | 110 kV | 大村一丁目変電所~中部電力株式会社　日吉変電所線 | 2 | 4 | [way 1089980993](https://www.openstreetmap.org/way/1089980993) |
| 中部 | 77 kV | leadin | 2 | 4 | [way 640531374](https://www.openstreetmap.org/way/640531374) |
| 中部 | 77 kV | namebind | 2 | 4 | [way 185287527](https://www.openstreetmap.org/way/185287527) |
| 中部 | 77 kV | 中部送電線_329 / 浅間温泉一丁目変電所~出川二丁目変電所線 | 2 | 1 | [way 316420967](https://www.openstreetmap.org/way/316420967) |
| 中部 | 77 kV | 中部送電線_437 | 6 | 1 | [way 909245383](https://www.openstreetmap.org/way/909245383) |
| 中部 | 77 kV | 中部電力パワーグリッド 154.0kV線 | 4 | 1 | [way 253935213](https://www.openstreetmap.org/way/253935213) |
| 中部 | 77 kV | 中部電力パワーグリッド 154.0kV線 | 4 | 1 | [way 1478580060](https://www.openstreetmap.org/way/1478580060) |
| 中部 | 77 kV | 中部電力パワーグリッド 275.0kV線 | 4 | 1 | [way 638317379](https://www.openstreetmap.org/way/638317379) |
| 中部 | 77 kV | 中部電力パワーグリッド 日進変電所~中部電力（株）豊明変電所線 | 4 | 1 | [way 179389585](https://www.openstreetmap.org/way/179389585) |
| 中部 | 77 kV | 中部電力パワーグリッド 日進変電所~中部電力（株）豊明変電所線 | 4 | 1 | [way 179389585](https://www.openstreetmap.org/way/179389585) |
| 中部 | 77 kV | 中部電力パワーグリッド（株）大須賀変電所~上ノ原変電所線 | 4 | 1 | [way 256765111](https://www.openstreetmap.org/way/256765111) |
| 中部 | 77 kV | 中部電力（株）豊明変電所~東名古屋変電所線 | 4 | 1 | [way 253528802](https://www.openstreetmap.org/way/253528802) |
| 中部 | 77 kV | 北刈谷南安城線;北刈谷依佐美線 | 4 | 1 | [way 253935213](https://www.openstreetmap.org/way/253935213) |
| 中部 | 77 kV | 北刈谷南安城線;北刈谷依佐美線 | 4 | 1 | [way 253935213](https://www.openstreetmap.org/way/253935213) |
| 中部 | 77 kV | 吉野工業所静岡線 | 2 | 3 | [way 192557250](https://www.openstreetmap.org/way/192557250) |
| 中部 | 77 kV | 大堂寺線 | 2 | 4 | [way 1245768082](https://www.openstreetmap.org/way/1245768082) |
| 中部 | 77 kV | 岡崎西尾線 | 4 | 5 | [way 501255377](https://www.openstreetmap.org/way/501255377) |
| 中部 | 77 kV | 岩滑西町三丁目変電所~南起変電所線 | 4 | 1 | [way 242872977](https://www.openstreetmap.org/way/242872977) |
| 中部 | 77 kV | 弥次ヱ町四丁目変電所~港区変電所線 | 2 | 3 | [way 177660149](https://www.openstreetmap.org/way/177660149) |
| 中部 | 77 kV | 昭和町寛政-1;寛政築港連絡-2 | 4 | 1 | [way 177941540](https://www.openstreetmap.org/way/177941540) |
| 中部 | 77 kV | 有松変電所~中部電力パワーグリッド 日進変電所線 | 4 | 1 | [way 253528809](https://www.openstreetmap.org/way/253528809) |
| 中部 | 77 kV | 東海鉄道岩渕線 | 4 | 1 | [way 618344852](https://www.openstreetmap.org/way/618344852) |
| 中部 | 77 kV | 東清水変電所~清水変電所線 | 2 | 4 | [way 618344851](https://www.openstreetmap.org/way/618344851) |
| 中部 | 77 kV | 植田湖西線 | 4 | 1 | [way 416862614](https://www.openstreetmap.org/way/416862614) |
| 中部 | 77 kV | 浅山一丁目変電所~原二丁目変電所線 | 4 | 1 | [way 242643055](https://www.openstreetmap.org/way/242643055) |
| 中部 | 77 kV | 浅山一丁目変電所~原二丁目変電所線 | 4 | 1 | [way 242643055](https://www.openstreetmap.org/way/242643055) |
| 中部 | 77 kV | 浜松高塚西線 | 6 | 1 | [way 192366189](https://www.openstreetmap.org/way/192366189) |
| 中部 | 77 kV | 蒲原一丁目変電所~富士市変電所線 | 4 | 1 | [way 1329891438](https://www.openstreetmap.org/way/1329891438) |
| 中部 | 77 kV | 豊川玉川線;羽栗豊川線 | 4 | 6 | [way 1476225875](https://www.openstreetmap.org/way/1476225875) |
| 中部 | 77 kV | 遠江高塚線 | 6 | 1 | [way 192380157](https://www.openstreetmap.org/way/192380157) |
| 中部 | 66 kV | 玉川変電所~三島変電所線 / 大仁線 / 三島変電所~函南町変電所線 / 函南町変電所~土肥六丁目変電所線 / 熱海線  | 2 | 1 | [way 202034645](https://www.openstreetmap.org/way/202034645) |
| 中国 | 500 kV | 島根原子力幹線 | 2 | 3 | [way 170977490](https://www.openstreetmap.org/way/170977490) |
| 中国 | 275 kV | namebind | 2 | 3 | [way 552508972](https://www.openstreetmap.org/way/552508972) |
| 中国 | 220 kV | 中国電力ネットワーク 220.0kV線 | 2 | 4 | [way 1427454298](https://www.openstreetmap.org/way/1427454298) |
| 中国 | 220 kV | 第二島根原子力幹線 | 2 | 3 | [way 170977489](https://www.openstreetmap.org/way/170977489) |
| 中国 | 110 kV | 中国送電線_147 | 2 | 1 | [way 625315242](https://www.openstreetmap.org/way/625315242) |
| 中国 | 110 kV | 中国送電線_147 | 2 | 4 | [way 625315242](https://www.openstreetmap.org/way/625315242) |
| 中国 | 110 kV | 中国送電線_411 / 八雲町変電所~西新町三丁目変電所線 | 2 | 1 | [way 171054309](https://www.openstreetmap.org/way/171054309) |
| 中国 | 110 kV | 中国電力ネットワーク 110.0kV線 | 2 | 6 | [way 449493454](https://www.openstreetmap.org/way/449493454) |
| 中国 | 110 kV | 中国電力ネットワーク 110.0kV線 | 2 | 7 | [way 449497411](https://www.openstreetmap.org/way/449497411) |
| 中国 | 110 kV | 作木変電所~北広島町変電所線 | 2 | 1 | [way 1003898616](https://www.openstreetmap.org/way/1003898616) |
| 中国 | 110 kV | 北尾道変電所~尾道変電所線 | 4 | 5 | [way 317641585](https://www.openstreetmap.org/way/317641585) |
| 中国 | 110 kV | 南西条変電所~中野五丁目変電所線 | 2 | 3 | [way 181382617](https://www.openstreetmap.org/way/181382617) |
| 中国 | 110 kV | 岡山変電所~倉敷変電所線 | 2 | 5 | [way 317557311](https://www.openstreetmap.org/way/317557311) |
| 中国 | 110 kV | 広島変電所~東広島変電所線 | 2 | 4 | [way 150339277](https://www.openstreetmap.org/way/150339277) |
| 中国 | 77 kV | 中国送電線_192 | 1 | 2 | [way 704062038](https://www.openstreetmap.org/way/704062038) |
| 中国 | 66 kV | 中国電力ネットワーク 66.0kV線 | 1 | 3 | [way 597814809](https://www.openstreetmap.org/way/597814809) |
| 中国 | 66 kV | 安瀬ブリヂストン北九州工場線 | 2 | 6 | [way 680183972](https://www.openstreetmap.org/way/680183972) |
| 北海道 | 275 kV | Benten Substation~苫小牧市変電所線 | 2 | 4 | [way 640503500](https://www.openstreetmap.org/way/640503500) |
| 北海道 | 275 kV | 南早来線 | 2 | 4 | [way 640503497](https://www.openstreetmap.org/way/640503497) |
| 北海道 | 275 kV | 道南幹線 (Dōnan-kansen) / 北海道電力ネットワーク 275.0kV線 | 2 | 1 | [way 180133432](https://www.openstreetmap.org/way/180133432) |
| 北海道 | 275 kV | 道央北幹線;室蘭西幹線 | 4 | 2 | [way 254548829](https://www.openstreetmap.org/way/254548829) |
| 北海道 | 187 kV | 上十勝支線 | 1 | 2 | [way 624374427](https://www.openstreetmap.org/way/624374427) |
| 北海道 | 187 kV | 函館幹線 (Hakodate-kansen) | 2 | 4 | [way 254267686](https://www.openstreetmap.org/way/254267686) |
| 北海道 | 187 kV | 北海道電力ネットワーク 187.0kV線 | 2 | 4 | [way 171940163](https://www.openstreetmap.org/way/171940163) |
| 北海道 | 187 kV | 富村線 | 1 | 2 | [way 624374426](https://www.openstreetmap.org/way/624374426) |
| 北海道 | 187 kV | 旭川幹線 | 2 | 4 | [way 104736423](https://www.openstreetmap.org/way/104736423) |
| 北海道 | 187 kV | 道央北幹線;室蘭西幹線 | 4 | 2 | [way 254548829](https://www.openstreetmap.org/way/254548829) |
| 北海道 | 187 kV | 電源開発送変電ネットワーク 187.0kV線 | 1 | 2 | [way 617425235](https://www.openstreetmap.org/way/617425235) |
| 北海道 | 66 kV | leadin | 1 | 2 | [way 1456557547](https://www.openstreetmap.org/way/1456557547) |
| 北海道 | 66 kV | namebind | 2 | 3 | [way 541061394](https://www.openstreetmap.org/way/541061394) |
| 北海道 | 66 kV | イオンモール旭川西地中支線 | 2 | 3 | [way 1530485913](https://www.openstreetmap.org/way/1530485913) |
| 北海道 | 66 kV | ニセコ尻別支線 | 1 | 2 | [way 1472866534](https://www.openstreetmap.org/way/1472866534) |
| 北海道 | 66 kV | 中札内線 | 2 | 6 | [way 1479854597](https://www.openstreetmap.org/way/1479854597) |
| 北海道 | 66 kV | 二股線 | 1 | 2 | [way 1081993438](https://www.openstreetmap.org/way/1081993438) |
| 北海道 | 66 kV | 函館線 | 2 | 4 | [way 1524541425](https://www.openstreetmap.org/way/1524541425) |
| 北海道 | 66 kV | 北海道送電線_2 | 1 | 2 | [way 255117667](https://www.openstreetmap.org/way/255117667) |
| 北海道 | 66 kV | 北海道送電線_50 / 北海道送電線_57 / 空知線 | 2 | 1 | [way 618492951](https://www.openstreetmap.org/way/618492951) |
| 北海道 | 66 kV | 北海道送電線_54 / 深川市変電所~西名寄変電所線 | 2 | 1 | [way 531136660](https://www.openstreetmap.org/way/531136660) |
| 北海道 | 66 kV | 北海道送電線_57 / 空知線 | 2 | 1 | [way 256131719](https://www.openstreetmap.org/way/256131719) |
| 北海道 | 66 kV | 北海道電力ネットワーク 66.0kV線 | 1 | 2 | [way 458674439](https://www.openstreetmap.org/way/458674439) |
| 北海道 | 66 kV | 北海道電力ネットワーク 66.0kV線 | 1 | 4 | [way 624211462](https://www.openstreetmap.org/way/624211462) |
| 北海道 | 66 kV | 北海道電力ネットワーク 66.0kV線 / 千歳線 | 2 | 1 | [way 1062807063](https://www.openstreetmap.org/way/1062807063) |
| 北海道 | 66 kV | 士幌線 | 1 | 2 | [way 195069614](https://www.openstreetmap.org/way/195069614) |
| 北海道 | 66 kV | 富川線 | 1 | 2 | [way 256549584](https://www.openstreetmap.org/way/256549584) |
| 北海道 | 66 kV | 川端線 | 1 | 2 | [way 1489693964](https://www.openstreetmap.org/way/1489693964) |
| 北海道 | 66 kV | 手稲東線 | 2 | 3 | [way 179863098](https://www.openstreetmap.org/way/179863098) |
| 北海道 | 66 kV | 手稲渓仁会地中支線 | 2 | 3 | [way 1523945766](https://www.openstreetmap.org/way/1523945766) |
| 北海道 | 66 kV | 昆布線 | 1 | 2 | [way 675025091](https://www.openstreetmap.org/way/675025091) |
| 北海道 | 66 kV | 有珠線 | 1 | 3 | [way 209817374](https://www.openstreetmap.org/way/209817374) |
| 北海道 | 66 kV | 有珠線 | 4 | 1 | [way 254667989](https://www.openstreetmap.org/way/254667989) |
| 北海道 | 66 kV | 泉沢線 (Izumisawa-sen) | 2 | 3 | [way 642938802](https://www.openstreetmap.org/way/642938802) |
| 北海道 | 66 kV | 浦河線 | 1 | 2 | [way 1479036475](https://www.openstreetmap.org/way/1479036475) |
| 北海道 | 66 kV | 清水沢支線 | 1 | 2 | [way 1489693977](https://www.openstreetmap.org/way/1489693977) |
| 北海道 | 66 kV | 滝里線 | 1 | 2 | [way 1467938620](https://www.openstreetmap.org/way/1467938620) |
| 北海道 | 66 kV | 然別第線 | 1 | 3 | [way 1479804650](https://www.openstreetmap.org/way/1479804650) |
| 北海道 | 66 kV | 熊牛支線 | 1 | 2 | [way 550159498](https://www.openstreetmap.org/way/550159498) |
| 北海道 | 66 kV | 空知線 | 2 | 5 | [way 256131719](https://www.openstreetmap.org/way/256131719) |
| 北海道 | 66 kV | 虻田線 | 1 | 2 | [way 308295204](https://www.openstreetmap.org/way/308295204) |
| 北海道 | 66 kV | 豊浦支線 | 1 | 2 | [way 308295201](https://www.openstreetmap.org/way/308295201) |
| 北海道 | 66 kV | 野花南線 | 1 | 2 | [way 1467938597](https://www.openstreetmap.org/way/1467938597) |
| 北陸 | 275 kV | 中部電力パワーグリッド 275.0kV線 | 1 | 2 | [way 1028287074](https://www.openstreetmap.org/way/1028287074) |
| 北陸 | 275 kV | 中部電力パワーグリッド 275.0kV線 | 2 | 3 | [way 572566521](https://www.openstreetmap.org/way/572566521) |
| 北陸 | 275 kV | 中部電力パワーグリッド 275.0kV線 | 2 | 4 | [way 170568515](https://www.openstreetmap.org/way/170568515) |
| 北陸 | 275 kV | 北陸電力送配電 275.0kV線 | 1 | 2 | [way 1028287074](https://www.openstreetmap.org/way/1028287074) |
| 北陸 | 275 kV | 北陸電力送配電 275.0kV線 | 2 | 3 | [way 572566521](https://www.openstreetmap.org/way/572566521) |
| 北陸 | 275 kV | 新愛本変電所~富南変電所線 | 1 | 2 | [way 320560150](https://www.openstreetmap.org/way/320560150) |
| 北陸 | 275 kV | 新愛本変電所~富南変電所線 | 1 | 2 | [way 320560150](https://www.openstreetmap.org/way/320560150) |
| 北陸 | 275 kV | 高根町上ケ洞変電所~三ツ渕変電所線 | 2 | 3 | [way 209518469](https://www.openstreetmap.org/way/209518469) |
| 北陸 | 275 kV | 高根町上ケ洞変電所~新信濃変電所線 | 1 | 2 | [way 315662819](https://www.openstreetmap.org/way/315662819) |
| 北陸 | 154 kV | 中部電力パワーグリッド 154.0kV線 | 1 | 2 | [way 1239633351](https://www.openstreetmap.org/way/1239633351) |
| 北陸 | 154 kV | 伏木変電所~万葉線株式会社 米島変電所線 | 4 | 7 | [way 537848242](https://www.openstreetmap.org/way/537848242) |
| 北陸 | 154 kV | 伏木変電所~万葉線株式会社 米島変電所線 | 4 | 7 | [way 537848242](https://www.openstreetmap.org/way/537848242) |
| 北陸 | 154 kV | 北陸電力送配電 154.0kV線 | 1 | 2 | [way 1239633351](https://www.openstreetmap.org/way/1239633351) |
| 北陸 | 154 kV | 寺津変電所~春日変電所線 | 2 | 4 | [way 549124639](https://www.openstreetmap.org/way/549124639) |
| 北陸 | 154 kV | 寺津変電所~春日変電所線 | 2 | 4 | [way 549124639](https://www.openstreetmap.org/way/549124639) |
| 北陸 | 154 kV | 寺津変電所~飛驒市変電所線 | 2 | 3 | [way 1239633377](https://www.openstreetmap.org/way/1239633377) |
| 北陸 | 154 kV | 寺津変電所~飛驒市変電所線 | 2 | 3 | [way 1239633377](https://www.openstreetmap.org/way/1239633377) |
| 北陸 | 154 kV | 敦賀連絡線 | 2 | 1 | [way 990617546](https://www.openstreetmap.org/way/990617546) |
| 北陸 | 154 kV | 松本市変電所_3~竜島変電所線 | 2 | 1 | [way 729291147](https://www.openstreetmap.org/way/729291147) |
| 北陸 | 154 kV | 松本市変電所_3~竜島変電所線 | 2 | 1 | [way 729291147](https://www.openstreetmap.org/way/729291147) |
| 北陸 | 154 kV | 竜島変電所~新信濃変電所線 | 2 | 1 | [way 638291361](https://www.openstreetmap.org/way/638291361) |
| 北陸 | 154 kV | 竜島変電所~新信濃変電所線 | 2 | 1 | [way 638291361](https://www.openstreetmap.org/way/638291361) |
| 北陸 | 77 kV | leadin | 1 | 2 | [way 1028287079](https://www.openstreetmap.org/way/1028287079) |
| 北陸 | 77 kV | leadin | 1 | 2 | [way 1028287079](https://www.openstreetmap.org/way/1028287079) |
| 北陸 | 77 kV | leadin | 2 | 3 | [way 1256591784](https://www.openstreetmap.org/way/1256591784) |
| 北陸 | 77 kV | leadin | 2 | 3 | [way 1256591784](https://www.openstreetmap.org/way/1256591784) |
| 北陸 | 77 kV | 中部送電線_938 / 粟津線 | 4 | 1 | [way 1550043378](https://www.openstreetmap.org/way/1550043378) |
| 北陸 | 77 kV | 中部電力パワーグリッド 77.0kV線 | 1 | 2 | [way 1028287082](https://www.openstreetmap.org/way/1028287082) |
| 北陸 | 77 kV | 丸岡町舛田変電所~松岡線 | 4 | 1 | [way 315639799](https://www.openstreetmap.org/way/315639799) |
| 北陸 | 77 kV | 丸岡町舛田変電所~松岡線 | 4 | 1 | [way 315639799](https://www.openstreetmap.org/way/315639799) |
| 北陸 | 77 kV | 北陸電力送配電 77.0kV線 | 1 | 2 | [way 1028287082](https://www.openstreetmap.org/way/1028287082) |
| 北陸 | 77 kV | 南金沢変電所~川北変電所線 | 4 | 1 | [way 316207181](https://www.openstreetmap.org/way/316207181) |
| 北陸 | 77 kV | 南金沢変電所~川北変電所線 | 4 | 1 | [way 316207181](https://www.openstreetmap.org/way/316207181) |
| 北陸 | 77 kV | 小松線 | 2 | 4 | [way 316250951](https://www.openstreetmap.org/way/316250951) |
| 北陸 | 77 kV | 小松線 | 2 | 4 | [way 316250951](https://www.openstreetmap.org/way/316250951) |
| 北陸 | 77 kV | 第２福井火力線/粟津線 | 4 | 2 | [way 1222018235](https://www.openstreetmap.org/way/1222018235) |
| 北陸 | 77 kV | 箱宮町変電所~河内町きりの里変電所線 | 2 | 1 | [way 775721897](https://www.openstreetmap.org/way/775721897) |
| 北陸 | 66 kV | leadin | 1 | 2 | [way 1239288531](https://www.openstreetmap.org/way/1239288531) |
| 北陸 | 66 kV | leadin | 1 | 2 | [way 1239288531](https://www.openstreetmap.org/way/1239288531) |
| 北陸 | 66 kV | leadin | 2 | 4 | [way 708293544](https://www.openstreetmap.org/way/708293544) |
| 北陸 | 66 kV | leadin | 2 | 4 | [way 708293544](https://www.openstreetmap.org/way/708293544) |
| 北陸 | 66 kV | namebind | 1 | 2 | [way 1239099859](https://www.openstreetmap.org/way/1239099859) |
| 北陸 | 66 kV | 三ケ変電所~塚原変電所線 | 3 | 1 | [way 829531833](https://www.openstreetmap.org/way/829531833) |
| 北陸 | 66 kV | 三ケ変電所~塚原変電所線 | 3 | 1 | [way 829531833](https://www.openstreetmap.org/way/829531833) |
| 北陸 | 66 kV | 三ケ変電所~大門変電所線 | 3 | 1 | [way 538127087](https://www.openstreetmap.org/way/538127087) |
| 北陸 | 66 kV | 三ケ変電所~大門変電所線 | 3 | 1 | [way 538127087](https://www.openstreetmap.org/way/538127087) |
| 北陸 | 66 kV | 中部送電線_1019 / 波岡変電所~福岡町下蓑新変電所線 | 2 | 1 | [way 973892228](https://www.openstreetmap.org/way/973892228) |
| 北陸 | 66 kV | 中部送電線_446 / 中部送電線_283 | 2 | 1 | [way 637675513](https://www.openstreetmap.org/way/637675513) |
| 北陸 | 66 kV | 中部送電線_664 | 2 | 1 | [way 1076297988](https://www.openstreetmap.org/way/1076297988) |
| 北陸 | 66 kV | 伏木変電所~万葉線株式会社 米島変電所線 | 3 | 1 | [way 535575248](https://www.openstreetmap.org/way/535575248) |
| 北陸 | 66 kV | 伏木変電所~万葉線株式会社 米島変電所線 | 3 | 1 | [way 535575248](https://www.openstreetmap.org/way/535575248) |
| 北陸 | 66 kV | 寺津変電所~北笹津変電所線 | 2 | 4 | [way 1025730668](https://www.openstreetmap.org/way/1025730668) |
| 北陸 | 66 kV | 寺津変電所~北笹津変電所線 | 2 | 4 | [way 1025730668](https://www.openstreetmap.org/way/1025730668) |
| 北陸 | 66 kV | 朝日町変電所~糸魚川市変電所線 / 中部送電線_283 | 2 | 1 | [way 637675513](https://www.openstreetmap.org/way/637675513) |
| 北陸 | 66 kV | 森変電所~草島変電所線 | 1 | 2 | [way 1076292728](https://www.openstreetmap.org/way/1076292728) |
| 北陸 | 66 kV | 森変電所~草島変電所線 | 1 | 2 | [way 1076292728](https://www.openstreetmap.org/way/1076292728) |
| 北陸 | 66 kV | 水須変電所~中滝変電所線 | 2 | 5 | [way 527846722](https://www.openstreetmap.org/way/527846722) |
| 北陸 | 66 kV | 水須変電所~中滝変電所線 | 2 | 5 | [way 527846722](https://www.openstreetmap.org/way/527846722) |
| 北陸 | 66 kV | 稲荷町三丁目変電所~犬島四丁目変電所線 | 2 | 4 | [way 1076292729](https://www.openstreetmap.org/way/1076292729) |
| 北陸 | 66 kV | 稲荷町三丁目変電所~犬島四丁目変電所線 | 2 | 4 | [way 1076292729](https://www.openstreetmap.org/way/1076292729) |
| 北陸 | 66 kV | 能登部線/高浜線 | 4 | 2 | [way 316207173](https://www.openstreetmap.org/way/316207173) |
| 北陸 | 66 kV | 能登部線/高浜線 | 4 | 2 | [way 316207173](https://www.openstreetmap.org/way/316207173) |
| 関西 | 500 kV | 揖斐洞戸幹線 | 2 | 4 | [way 162065377](https://www.openstreetmap.org/way/162065377) |
| 関西 | 500 kV | 揖斐洞戸幹線 | 2 | 4 | [way 162065377](https://www.openstreetmap.org/way/162065377) |
| 関西 | 500 kV | 紀北変換所~東大和開閉所線 | 2 | 1 | [way 191816977](https://www.openstreetmap.org/way/191816977) |
| 関西 | 500 kV | 西部幹線 | 2 | 4 | [way 162065376](https://www.openstreetmap.org/way/162065376) |
| 関西 | 500 kV | 西部幹線 | 2 | 4 | [way 162065376](https://www.openstreetmap.org/way/162065376) |
| 関西 | 275 kV | leadin | 2 | 3 | [way 493787278](https://www.openstreetmap.org/way/493787278) |
| 関西 | 275 kV | 丸山幹線 | 2 | 3 | [way 162056802](https://www.openstreetmap.org/way/162056802) |
| 関西 | 275 kV | 丸山幹線 | 2 | 3 | [way 162056802](https://www.openstreetmap.org/way/162056802) |
| 関西 | 275 kV | 伊勢幹線 | 2 | 3 | [way 170793715](https://www.openstreetmap.org/way/170793715) |
| 関西 | 275 kV | 伊勢幹線 | 2 | 3 | [way 170793715](https://www.openstreetmap.org/way/170793715) |
| 関西 | 275 kV | 六地蔵変電所~白鳥町大島変電所線 | 2 | 4 | [way 170568515](https://www.openstreetmap.org/way/170568515) |
| 関西 | 275 kV | 泉南東大阪線 | 2 | 4 | [way 191816982](https://www.openstreetmap.org/way/191816982) |
| 関西 | 275 kV | 甲賀線 | 2 | 4 | [way 191001719](https://www.openstreetmap.org/way/191001719) |
| 関西 | 275 kV | 白木一丁目変電所~嶺南変電所線 | 2 | 5 | [way 725340694](https://www.openstreetmap.org/way/725340694) |
| 関西 | 275 kV | 関西送電線_223 | 2 | 4 | [way 963680009](https://www.openstreetmap.org/way/963680009) |
| 関西 | 275 kV | 青野町変電所~十六町変電所線 / 丸山幹線 | 2 | 1 | [way 162056802](https://www.openstreetmap.org/way/162056802) |
| 関西 | 154 kV | 中部送電線_857 / 中部送電線_346 | 4 | 1 | [way 1180366826](https://www.openstreetmap.org/way/1180366826) |
| 関西 | 154 kV | 北大和線;南京都奈良線 | 4 | 2 | [way 949748591](https://www.openstreetmap.org/way/949748591) |
| 関西 | 154 kV | 北大和線;南京都奈良線 | 4 | 2 | [way 949748592](https://www.openstreetmap.org/way/949748592) |
| 関西 | 154 kV | 揖斐変電所~西濃変電所線 | 4 | 5 | [way 162058673](https://www.openstreetmap.org/way/162058673) |
| 関西 | 154 kV | 揖斐変電所~西濃変電所線 | 4 | 5 | [way 162058673](https://www.openstreetmap.org/way/162058673) |
| 関西 | 154 kV | 揖斐川町変電所~揖斐変電所線 / 中部送電線_635 | 4 | 1 | [way 1063933386](https://www.openstreetmap.org/way/1063933386) |
| 関西 | 154 kV | 新生駒野江線;古川橋意岐部線;茨田浜線 | 6 | 2 | [way 934906563](https://www.openstreetmap.org/way/934906563) |
| 関西 | 154 kV | 新生駒野江線;古川橋意岐部線;茨田浜線 | 6 | 2 | [way 934906563](https://www.openstreetmap.org/way/934906563) |
| 関西 | 154 kV | 本町北線;古川橋豊里町線 | 6 | 4 | [way 254574158](https://www.openstreetmap.org/way/254574158) |
| 関西 | 154 kV | 栗東線 | 6 | 1 | [way 932242845](https://www.openstreetmap.org/way/932242845) |
| 関西 | 154 kV | 膳所変電所~螢谷変電所線 | 2 | 1 | [way 682070469](https://www.openstreetmap.org/way/682070469) |
| 関西 | 154 kV | 西尾張~海部開閉所線 | 4 | 1 | [way 170793704](https://www.openstreetmap.org/way/170793704) |
| 関西 | 154 kV | 西尾張~海部開閉所線 | 4 | 1 | [way 170793704](https://www.openstreetmap.org/way/170793704) |
| 関西 | 154 kV | 関西電力送配電 富田変電所~北大阪変電所線 | 2 | 8 | [way 191539411](https://www.openstreetmap.org/way/191539411) |
| 関西 | 154 kV | 鳥飼八町一丁目変電所~関西電力送配電 鳥飼変電所線 | 8 | 9 | [way 1122827981](https://www.openstreetmap.org/way/1122827981) |
| 関西 | 77 kV | leadin | 1 | 2 | [way 1067042007](https://www.openstreetmap.org/way/1067042007) |
| 関西 | 77 kV | leadin | 2 | 3 | [way 192046339](https://www.openstreetmap.org/way/192046339) |
| 関西 | 77 kV | leadin | 2 | 3 | [way 770099330](https://www.openstreetmap.org/way/770099330) |
| 関西 | 77 kV | leadin | 4 | 5 | [way 254865486](https://www.openstreetmap.org/way/254865486) |
| 関西 | 77 kV | namebind | 4 | 5 | [way 191434699](https://www.openstreetmap.org/way/191434699) |
| 関西 | 77 kV | namebind | 4 | 5 | [way 1305511933](https://www.openstreetmap.org/way/1305511933) |
| 関西 | 77 kV | namebind | 4 | 8 | [way 1187919737](https://www.openstreetmap.org/way/1187919737) |
| 関西 | 77 kV | 三田弥生が丘線〔取付〕 | 2 | 1 | [way 599982053](https://www.openstreetmap.org/way/599982053) |
| 関西 | 77 kV | 中部送電線_427 | 2 | 3 | [way 1284143084](https://www.openstreetmap.org/way/1284143084) |
| 関西 | 77 kV | 今津塩津線 | 2 | 4 | [way 895420662](https://www.openstreetmap.org/way/895420662) |
| 関西 | 77 kV | 今津塩津線 | 2 | 4 | [way 895420662](https://www.openstreetmap.org/way/895420662) |
| 関西 | 77 kV | 前浜線; 大浜前浜線 | 6 | 4 | [way 927209321](https://www.openstreetmap.org/way/927209321) |
| 関西 | 77 kV | 勧進橋東線;横大路勧進橋線 | 2 | 3 | [way 1190047733](https://www.openstreetmap.org/way/1190047733) |
| 関西 | 77 kV | 勧進橋東線;横大路勧進橋線 | 6 | 2 | [way 541374678](https://www.openstreetmap.org/way/541374678) |
| 関西 | 77 kV | 勧進橋東線;横大路勧進橋線 | 6 | 2 | [way 541374678](https://www.openstreetmap.org/way/541374678) |
| 関西 | 77 kV | 北立花線 | 2 | 6 | [way 190248056](https://www.openstreetmap.org/way/190248056) |
| 関西 | 77 kV | 南京都奈良線;平城木津線 | 4 | 2 | [way 241805094](https://www.openstreetmap.org/way/241805094) |
| 関西 | 77 kV | 南大浜線;伊丹多田線 | 8 | 2 | [way 110682952](https://www.openstreetmap.org/way/110682952) |
| 関西 | 77 kV | 南大浜線;伊丹多田線 | 8 | 2 | [way 110682952](https://www.openstreetmap.org/way/110682952) |
| 関西 | 77 kV | 古川橋豊里町線 | 2 | 4 | [way 254574151](https://www.openstreetmap.org/way/254574151) |
| 関西 | 77 kV | 向日町男山線 | 2 | 9 | [way 201073527](https://www.openstreetmap.org/way/201073527) |
| 関西 | 77 kV | 唐崎変電所~鳥飼八町一丁目変電所線 | 6 | 1 | [way 254574143](https://www.openstreetmap.org/way/254574143) |
| 関西 | 77 kV | 唐崎支線 | 4 | 2 | [way 865576767](https://www.openstreetmap.org/way/865576767) |
| 関西 | 77 kV | 園田線 | 4 | 6 | [way 157532216](https://www.openstreetmap.org/way/157532216) |
| 関西 | 77 kV | 城西変電所~姫路変電所線 | 4 | 8 | [way 242685092](https://www.openstreetmap.org/way/242685092) |
| 関西 | 77 kV | 宇治線 | 4 | 5 | [way 1032923224](https://www.openstreetmap.org/way/1032923224) |
| 関西 | 77 kV | 小曽根味生線 | 2 | 3 | [way 968809156](https://www.openstreetmap.org/way/968809156) |
| 関西 | 77 kV | 市小路変電所~北島変電所線 | 2 | 3 | [way 831552334](https://www.openstreetmap.org/way/831552334) |
| 関西 | 77 kV | 新加古川変電所~西区変電所線 | 2 | 3 | [way 509403718](https://www.openstreetmap.org/way/509403718) |
| 関西 | 77 kV | 新奈良線 | 4 | 1 | [way 201053525](https://www.openstreetmap.org/way/201053525) |
| 関西 | 77 kV | 新奈良線 | 4 | 1 | [way 201053525](https://www.openstreetmap.org/way/201053525) |
| 関西 | 77 kV | 新生駒野江線;古川橋意岐部線;茨田浜線 | 6 | 4 | [way 934906563](https://www.openstreetmap.org/way/934906563) |
| 関西 | 77 kV | 新生駒野江線;古川橋意岐部線;茨田浜線 | 6 | 4 | [way 934906563](https://www.openstreetmap.org/way/934906563) |
| 関西 | 77 kV | 本町北線;古川橋豊里町線 | 6 | 2 | [way 254574158](https://www.openstreetmap.org/way/254574158) |
| 関西 | 77 kV | 泉北線 | 2 | 3 | [way 192046339](https://www.openstreetmap.org/way/192046339) |
| 関西 | 77 kV | 淀川東線 | 4 | 1 | [way 375408524](https://www.openstreetmap.org/way/375408524) |
| 関西 | 77 kV | 淀川東線 | 4 | 1 | [way 375408524](https://www.openstreetmap.org/way/375408524) |
| 関西 | 77 kV | 淀川東線 | 4 | 1 | [way 375408524](https://www.openstreetmap.org/way/375408524) |
| 関西 | 77 kV | 淀川枚方線 | 2 | 4 | [way 865576769](https://www.openstreetmap.org/way/865576769) |
| 関西 | 77 kV | 王寺北葛城線;近鉄王寺線;ニチアス線 | 4 | 5 | [way 160415415](https://www.openstreetmap.org/way/160415415) |
| 関西 | 77 kV | 砂川線;信達線;尾崎信達線 | 6 | 2 | [way 1226606672](https://www.openstreetmap.org/way/1226606672) |
| 関西 | 77 kV | 西島山線 | 4 | 8 | [way 190171563](https://www.openstreetmap.org/way/190171563) |
| 関西 | 77 kV | 西飾磨支線 | 2 | 4 | [way 798162358](https://www.openstreetmap.org/way/798162358) |
| 関西 | 77 kV | 関西幹線;櫟本線 | 4 | 2 | [way 161639375](https://www.openstreetmap.org/way/161639375) |
| 関西 | 77 kV | 関西送電線_407 / 新長浜支線 | 3 | 1 | [way 42341309](https://www.openstreetmap.org/way/42341309) |
| 関西 | 77 kV | 関西送電線_538 | 2 | 3 | [way 1284143084](https://www.openstreetmap.org/way/1284143084) |
| 関西 | 77 kV | 関西送電線_75 | 2 | 4 | [way 1183927483](https://www.openstreetmap.org/way/1183927483) |
| 関西 | 77 kV | 関西送電線_8 / 向日町横大路線 | 4 | 1 | [way 201295992](https://www.openstreetmap.org/way/201295992) |
| 関西 | 66 kV | 起変電所~祖父江町祖父江変電所線 | 6 | 7 | [way 293400306](https://www.openstreetmap.org/way/293400306) |
| 関西 | 66 kV | 起変電所~祖父江町祖父江変電所線 | 6 | 7 | [way 293400306](https://www.openstreetmap.org/way/293400306) |
| 関西 | 0 kV | 関西中国間連系線 | 2 | 1 | [way 242253554](https://www.openstreetmap.org/way/242253554) |
| 九州 | 500 kV | 北九州幹線 | 2 | 4 | [way 188004925](https://www.openstreetmap.org/way/188004925) |
| 九州 | 500 kV | 北九州幹線 | 2 | 4 | [way 1512987121](https://www.openstreetmap.org/way/1512987121) |
| 九州 | 500 kV | 関門連系線 | 2 | 4 | [way 1510787459](https://www.openstreetmap.org/way/1510787459) |
| 九州 | 500 kV | 関門連系線 | 2 | 4 | [way 1510787459](https://www.openstreetmap.org/way/1510787459) |
| 九州 | 220 kV | 中国電力ネットワーク 220.0kV線 | 1 | 2 | [way 405811260](https://www.openstreetmap.org/way/405811260) |
| 九州 | 220 kV | 九州送電線_356 | 2 | 3 | [way 991390717](https://www.openstreetmap.org/way/991390717) |
| 九州 | 220 kV | 九州送電線_544 / 古開作変電所~美和町西畑変電所線 | 2 | 1 | [way 243471277](https://www.openstreetmap.org/way/243471277) |
| 九州 | 220 kV | 九州電力送配電 220.0kV線 | 1 | 2 | [way 405811260](https://www.openstreetmap.org/way/405811260) |
| 九州 | 220 kV | 九州電力送配電 220.0kV線 | 2 | 1 | [way 373168338](https://www.openstreetmap.org/way/373168338) |
| 九州 | 220 kV | 川内原子力支線 | 1 | 2 | [way 700628505](https://www.openstreetmap.org/way/700628505) |
| 九州 | 220 kV | 新小倉火力線1L | 1 | 3 | [way 1517856236](https://www.openstreetmap.org/way/1517856236) |
| 九州 | 220 kV | 新小倉火力線1L | 1 | 3 | [way 1517856236](https://www.openstreetmap.org/way/1517856236) |
| 九州 | 220 kV | 新小倉火力線2/3L | 2 | 3 | [way 1517856238](https://www.openstreetmap.org/way/1517856238) |
| 九州 | 220 kV | 新小倉火力線2/3L | 2 | 3 | [way 1517856238](https://www.openstreetmap.org/way/1517856238) |
| 九州 | 220 kV | 武雄変電所~九州電力西九州変電所線 | 2 | 4 | [way 185623492](https://www.openstreetmap.org/way/185623492) |
| 九州 | 220 kV | 西福岡赤坂線 | 2 | 4 | [way 957758568](https://www.openstreetmap.org/way/957758568) |
| 九州 | 220 kV | 西谷北線 | 2 | 3 | [way 240453244](https://www.openstreetmap.org/way/240453244) |
| 九州 | 220 kV | 西谷北線 | 2 | 3 | [way 240453244](https://www.openstreetmap.org/way/240453244) |
| 九州 | 110 kV | 三池変電所~荒尾変電所線 | 2 | 3 | [way 705754036](https://www.openstreetmap.org/way/705754036) |
| 九州 | 110 kV | 三池変電所~荒尾変電所線 | 2 | 3 | [way 705762662](https://www.openstreetmap.org/way/705762662) |
| 九州 | 110 kV | 三財線 | 1 | 2 | [way 756532307](https://www.openstreetmap.org/way/756532307) |
| 九州 | 110 kV | 下関変電所~中国電力 西下関開閉所線 | 4 | 5 | [way 370263799](https://www.openstreetmap.org/way/370263799) |
| 九州 | 110 kV | 下関変電所~中国電力 西下関開閉所線 | 4 | 5 | [way 370263799](https://www.openstreetmap.org/way/370263799) |
| 九州 | 110 kV | 下関火力支線;長府支線;下関小月線 | 4 | 2 | [way 204259793](https://www.openstreetmap.org/way/204259793) |
| 九州 | 110 kV | 下関火力支線;長府支線;下関小月線 | 4 | 2 | [way 204259793](https://www.openstreetmap.org/way/204259793) |
| 九州 | 110 kV | 下関火力支線;長府支線;下関小月線 | 4 | 2 | [way 204259793](https://www.openstreetmap.org/way/204259793) |
| 九州 | 110 kV | 下関火力支線;長府支線;下関小月線 | 4 | 2 | [way 204259793](https://www.openstreetmap.org/way/204259793) |
| 九州 | 110 kV | 中国電力ネットワーク 110.0kV線 | 2 | 4 | [way 318564793](https://www.openstreetmap.org/way/318564793) |
| 九州 | 110 kV | 中国電力ネットワーク 110.0kV線 | 2 | 4 | [way 620165555](https://www.openstreetmap.org/way/620165555) |
| 九州 | 110 kV | 九州送電線_19 | 2 | 3 | [way 231877110](https://www.openstreetmap.org/way/231877110) |
| 九州 | 110 kV | 九州電力送配電 110.0kV線 | 1 | 2 | [way 762549241](https://www.openstreetmap.org/way/762549241) |
| 九州 | 110 kV | 九州電力送配電 110.0kV線 | 2 | 4 | [way 318564793](https://www.openstreetmap.org/way/318564793) |
| 九州 | 110 kV | 九州電力送配電 110.0kV線 | 2 | 4 | [way 620165555](https://www.openstreetmap.org/way/620165555) |
| 九州 | 110 kV | 九州電力送配電 110.0kV線 | 2 | 6 | [way 203776444](https://www.openstreetmap.org/way/203776444) |
| 九州 | 110 kV | 塚原上椎葉線 | 2 | 4 | [way 704877008](https://www.openstreetmap.org/way/704877008) |
| 九州 | 110 kV | 塚原日向線 | 2 | 4 | [way 704877010](https://www.openstreetmap.org/way/704877010) |
| 九州 | 110 kV | 塚原諸塚線 | 2 | 3 | [way 704877009](https://www.openstreetmap.org/way/704877009) |
| 九州 | 110 kV | 若松東京製鉄線 | 1 | 4 | [way 1512779320](https://www.openstreetmap.org/way/1512779320) |
| 九州 | 66 kV | JR九州 二日市変電所~朝倉変電所線 | 1 | 4 | [way 405511228](https://www.openstreetmap.org/way/405511228) |
| 九州 | 66 kV | JR九州筑豊分岐線 | 1 | 2 | [way 367489621](https://www.openstreetmap.org/way/367489621) |
| 九州 | 66 kV | leadin | 1 | 2 | [way 708228093](https://www.openstreetmap.org/way/708228093) |
| 九州 | 66 kV | leadin | 2 | 3 | [way 405811255](https://www.openstreetmap.org/way/405811255) |
| 九州 | 66 kV | leadin | 2 | 3 | [way 405811255](https://www.openstreetmap.org/way/405811255) |
| 九州 | 66 kV | leadin | 2 | 3 | [way 976858878](https://www.openstreetmap.org/way/976858878) |
| 九州 | 66 kV | leadin | 2 | 3 | [way 1509657519](https://www.openstreetmap.org/way/1509657519) |
| 九州 | 66 kV | leadin | 2 | 3 | [way 1509657519](https://www.openstreetmap.org/way/1509657519) |
| 九州 | 66 kV | 上津役UBE三菱黒崎線 | 2 | 4 | [way 296788635](https://www.openstreetmap.org/way/296788635) |
| 九州 | 66 kV | 上野分岐線 | 2 | 6 | [way 715382093](https://www.openstreetmap.org/way/715382093) |
| 九州 | 66 kV | 下関小月線 | 2 | 3 | [way 710495987](https://www.openstreetmap.org/way/710495987) |
| 九州 | 66 kV | 下関小月線 | 2 | 3 | [way 710495987](https://www.openstreetmap.org/way/710495987) |
| 九州 | 66 kV | 九州旅客鉄道株式会社 66.0kV線 | 1 | 2 | [way 1199896271](https://www.openstreetmap.org/way/1199896271) |
| 九州 | 66 kV | 九州電力送配電 220.0kV線 | 4 | 2 | [way 392732955](https://www.openstreetmap.org/way/392732955) |
| 九州 | 66 kV | 九州電力送配電 66.0kV線 | 1 | 3 | [way 776251062](https://www.openstreetmap.org/way/776251062) |
| 九州 | 66 kV | 九州電力送配電 66.0kV線 | 2 | 3 | [way 410965632](https://www.openstreetmap.org/way/410965632) |
| 九州 | 66 kV | 九州電力送配電 66.0kV線 | 2 | 3 | [way 755381532](https://www.openstreetmap.org/way/755381532) |
| 九州 | 66 kV | 九州電力送配電 66.0kV線 | 2 | 3 | [way 1030940566](https://www.openstreetmap.org/way/1030940566) |
| 九州 | 66 kV | 九州電力送配電 66.0kV線 | 2 | 3 | [way 1364683694](https://www.openstreetmap.org/way/1364683694) |
| 九州 | 66 kV | 九州電力送配電 66.0kV線 | 2 | 4 | [way 367493006](https://www.openstreetmap.org/way/367493006) |
| 九州 | 66 kV | 二島上津役線 | 2 | 4 | [way 296788632](https://www.openstreetmap.org/way/296788632) |
| 九州 | 66 kV | 二島浅川線 | 2 | 4 | [way 704443264](https://www.openstreetmap.org/way/704443264) |
| 九州 | 66 kV | 伊都の杜一丁目変電所~周船寺一丁目変電所線 | 2 | 4 | [way 266307475](https://www.openstreetmap.org/way/266307475) |
| 九州 | 66 kV | 住吉須崎線・住吉天神線 | 3 | 4 | [way 959987536](https://www.openstreetmap.org/way/959987536) |
| 九州 | 66 kV | 北佐賀変電所~九州電力 神埼変電所線 | 2 | 3 | [way 742261820](https://www.openstreetmap.org/way/742261820) |
| 九州 | 66 kV | 南熊本松橋線 | 2 | 4 | [way 334797653](https://www.openstreetmap.org/way/334797653) |
| 九州 | 66 kV | 南福岡上白水線 | 2 | 4 | [way 180133891](https://www.openstreetmap.org/way/180133891) |
| 九州 | 66 kV | 名島二丁目変電所~九州電力箱崎浜変電所線 | 2 | 4 | [way 967125741](https://www.openstreetmap.org/way/967125741) |
| 九州 | 66 kV | 四山町変電所~大牟田市変電所線 | 4 | 1 | [way 244326289](https://www.openstreetmap.org/way/244326289) |
| 九州 | 66 kV | 多の津箱崎線 | 2 | 3 | [way 405904108](https://www.openstreetmap.org/way/405904108) |
| 九州 | 66 kV | 多良木変電所~人吉変電所線 | 2 | 4 | [way 405705595](https://www.openstreetmap.org/way/405705595) |
| 九州 | 66 kV | 多良木変電所~木上変電所線 | 1 | 2 | [way 694619704](https://www.openstreetmap.org/way/694619704) |
| 九州 | 66 kV | 大分上野線 | 2 | 7 | [way 140772081](https://www.openstreetmap.org/way/140772081) |
| 九州 | 66 kV | 大分製鉄線・東大分大分線 | 4 | 1 | [way 187901842](https://www.openstreetmap.org/way/187901842) |
| 九州 | 66 kV | 大分製鉄線・東大分大分線 | 4 | 1 | [way 187901842](https://www.openstreetmap.org/way/187901842) |
| 九州 | 66 kV | 大字和気変電所~杵築市変電所線 | 2 | 3 | [way 660345813](https://www.openstreetmap.org/way/660345813) |
| 九州 | 66 kV | 大字和気変電所~杵築市変電所線 | 2 | 3 | [way 1364683705](https://www.openstreetmap.org/way/1364683705) |
| 九州 | 66 kV | 大牟田市変電所~大黒町四丁目変電所線 | 4 | 1 | [way 203776443](https://www.openstreetmap.org/way/203776443) |
| 九州 | 66 kV | 大牟田市変電所~大黒町四丁目変電所線 | 4 | 1 | [way 203776443](https://www.openstreetmap.org/way/203776443) |
| 九州 | 66 kV | 大野町小倉木変電所~竹田変電所線 | 2 | 3 | [way 761529565](https://www.openstreetmap.org/way/761529565) |
| 九州 | 66 kV | 宇土JR九州熊本総合車両所線 | 1 | 3 | [way 640661956](https://www.openstreetmap.org/way/640661956) |
| 九州 | 66 kV | 宇部高千帆線 | 2 | 3 | [way 620412138](https://www.openstreetmap.org/way/620412138) |
| 九州 | 66 kV | 宇部高千帆線 | 2 | 3 | [way 620412138](https://www.openstreetmap.org/way/620412138) |
| 九州 | 66 kV | 安瀬東邦チタニウム線 | 2 | 4 | [way 680183971](https://www.openstreetmap.org/way/680183971) |
| 九州 | 66 kV | 富士見分岐線 | 2 | 4 | [way 1521189659](https://www.openstreetmap.org/way/1521189659) |
| 九州 | 66 kV | 小倉旦過線/小倉東陶線 | 3 | 6 | [way 1511565319](https://www.openstreetmap.org/way/1511565319) |
| 九州 | 66 kV | 小倉旦過線/小倉東陶線 | 3 | 6 | [way 1511565319](https://www.openstreetmap.org/way/1511565319) |
| 九州 | 66 kV | 小郡変電所~山口市変電所線 | 1 | 2 | [way 319371109](https://www.openstreetmap.org/way/319371109) |
| 九州 | 66 kV | 小郡変電所~山口市変電所線 | 1 | 2 | [way 319371109](https://www.openstreetmap.org/way/319371109) |
| 九州 | 66 kV | 山川地熱線 | 1 | 2 | [way 607919424](https://www.openstreetmap.org/way/607919424) |
| 九州 | 66 kV | 港町大阪ソーダ線 | 1 | 2 | [way 1517852075](https://www.openstreetmap.org/way/1517852075) |
| 九州 | 66 kV | 港町大阪ソーダ線 | 1 | 2 | [way 1517852075](https://www.openstreetmap.org/way/1517852075) |
| 九州 | 66 kV | 港町日明浄化線 | 1 | 3 | [way 1517853217](https://www.openstreetmap.org/way/1517853217) |
| 九州 | 66 kV | 港町日明浄化線 | 1 | 3 | [way 1517853217](https://www.openstreetmap.org/way/1517853217) |
| 九州 | 66 kV | 熊本上椎葉線 | 4 | 2 | [way 772765631](https://www.openstreetmap.org/way/772765631) |
| 九州 | 66 kV | 王子板紙大分分岐線 | 2 | 3 | [way 711688970](https://www.openstreetmap.org/way/711688970) |
| 九州 | 66 kV | 神水保田窪線 | 3 | 5 | [way 1520395454](https://www.openstreetmap.org/way/1520395454) |
| 九州 | 66 kV | 穴生分岐線 | 2 | 4 | [way 711568285](https://www.openstreetmap.org/way/711568285) |
| 九州 | 66 kV | 竹下変電所~板付変電所線 | 2 | 3 | [way 971068451](https://www.openstreetmap.org/way/971068451) |
| 九州 | 66 kV | 竹下変電所~板付変電所線 | 2 | 3 | [way 971068451](https://www.openstreetmap.org/way/971068451) |
| 九州 | 66 kV | 篠原変電所~西大分変電所線 | 2 | 3 | [way 90806459](https://www.openstreetmap.org/way/90806459) |
| 九州 | 66 kV | 苅田雨窪線 | 2 | 4 | [way 1510219794](https://www.openstreetmap.org/way/1510219794) |
| 九州 | 66 kV | 苅田雨窪線 | 2 | 4 | [way 1510219794](https://www.openstreetmap.org/way/1510219794) |
| 九州 | 66 kV | 荘園分岐線 | 1 | 2 | [way 1517998758](https://www.openstreetmap.org/way/1517998758) |
| 九州 | 66 kV | 蓮台寺二丁目変電所~日吉変電所線 | 1 | 2 | [way 768562489](https://www.openstreetmap.org/way/768562489) |
| 九州 | 66 kV | 西大分田の湯線 | 2 | 4 | [way 90806451](https://www.openstreetmap.org/way/90806451) |
| 九州 | 66 kV | 西大分田の湯線 | 2 | 4 | [way 90806453](https://www.openstreetmap.org/way/90806453) |
| 九州 | 66 kV | 西谷前田線 | 2 | 3 | [way 1511553341](https://www.openstreetmap.org/way/1511553341) |
| 九州 | 66 kV | 西谷前田線 | 2 | 4 | [way 710479455](https://www.openstreetmap.org/way/710479455) |
| 九州 | 66 kV | 西谷前田線 | 2 | 4 | [way 710479455](https://www.openstreetmap.org/way/710479455) |
| 九州 | 66 kV | 豊前市変電所~大字畠中変電所線 | 2 | 3 | [way 216809822](https://www.openstreetmap.org/way/216809822) |
| 九州 | 66 kV | 通谷分岐線 | 2 | 4 | [way 764455379](https://www.openstreetmap.org/way/764455379) |
| 九州 | 66 kV | 都城鷹尾線・都城川東線 | 4 | 6 | [way 609212601](https://www.openstreetmap.org/way/609212601) |
| 九州 | 66 kV | 金の手変電所~犬飼変電所線 | 2 | 4 | [way 91681077](https://www.openstreetmap.org/way/91681077) |
| 九州 | 66 kV | 長与分岐二号線 | 1 | 2 | [way 255404964](https://www.openstreetmap.org/way/255404964) |
| 九州 | 66 kV | 長与分岐二号線 | 1 | 2 | [way 255404964](https://www.openstreetmap.org/way/255404964) |
| 九州 | 66 kV | 長尾七隈線 | 2 | 1 | [way 952512577](https://www.openstreetmap.org/way/952512577) |
| 九州 | 66 kV | 霧島隼人線 | 2 | 4 | [way 672642136](https://www.openstreetmap.org/way/672642136) |
| 九州 | 66 kV | 飯塚嘉穂線 | 2 | 4 | [way 205494375](https://www.openstreetmap.org/way/205494375) |
| 沖縄 | 132 kV | 美里六丁目変電所~うるま市変電所線 | 4 | 5 | [way 516695280](https://www.openstreetmap.org/way/516695280) |
| 沖縄 | 132 kV | 西原幹線;前田線 | 3 | 2 | [way 516775961](https://www.openstreetmap.org/way/516775961) |
| 沖縄 | 66 kV | namebind | 2 | 3 | [way 516775945](https://www.openstreetmap.org/way/516775945) |
| 沖縄 | 66 kV | 与那原変電所~西原変電所線 | 3 | 1 | [way 516695293](https://www.openstreetmap.org/way/516695293) |
| 沖縄 | 66 kV | 伊佐一丁目変電所_2~牧港五丁目変電所線 | 4 | 1 | [way 516775940](https://www.openstreetmap.org/way/516775940) |
| 沖縄 | 66 kV | 南風原変電所~与那原変電所線 | 3 | 1 | [way 169214772](https://www.openstreetmap.org/way/169214772) |
| 沖縄 | 66 kV | 友寄変電所~南風原変電所線 | 3 | 1 | [way 169214771](https://www.openstreetmap.org/way/169214771) |
| 沖縄 | 66 kV | 港川変電所~曙変電所線 | 2 | 3 | [way 516801172](https://www.openstreetmap.org/way/516801172) |
| 沖縄 | 66 kV | 瑞慶覧変電所~伊佐一丁目変電所_2線 | 4 | 1 | [way 516775937](https://www.openstreetmap.org/way/516775937) |
| 沖縄 | 66 kV | 美里六丁目変電所~うるま市変電所線 | 4 | 1 | [way 516695280](https://www.openstreetmap.org/way/516695280) |
| 沖縄 | 66 kV | 美里六丁目変電所~瑞慶覧変電所線 | 4 | 1 | [way 516775953](https://www.openstreetmap.org/way/516775953) |
| 沖縄 | 66 kV | 西原変電所~渡口変電所線 | 3 | 1 | [way 516695292](https://www.openstreetmap.org/way/516695292) |
| 沖縄 | 66 kV | 西原変電所~渡口変電所線 | 3 | 1 | [way 516695292](https://www.openstreetmap.org/way/516695292) |
| 沖縄 | 66 kV | 西原幹線;前田線 | 3 | 1 | [way 516775961](https://www.openstreetmap.org/way/516775961) |
| 四国 | 187 kV | 受電所~讃岐変電所線 | 2 | 7 | [way 87538343](https://www.openstreetmap.org/way/87538343) |
| 四国 | 187 kV | 受電所~讃岐変電所線 | 2 | 7 | [way 87538343](https://www.openstreetmap.org/way/87538343) |
| 四国 | 187 kV | 高松線 | 2 | 4 | [way 87538235](https://www.openstreetmap.org/way/87538235) |
| 四国 | 187 kV | 高松線 | 2 | 4 | [way 87538235](https://www.openstreetmap.org/way/87538235) |
| 四国 | 110 kV | leadin | 2 | 3 | [way 181574385](https://www.openstreetmap.org/way/181574385) |
| 四国 | 110 kV | leadin | 2 | 3 | [way 181574385](https://www.openstreetmap.org/way/181574385) |
| 四国 | 110 kV | leadin | 2 | 3 | [way 1334462854](https://www.openstreetmap.org/way/1334462854) |
| 四国 | 110 kV | leadin | 2 | 3 | [way 1334462854](https://www.openstreetmap.org/way/1334462854) |
| 四国 | 110 kV | leadin | 4 | 5 | [way 317570288](https://www.openstreetmap.org/way/317570288) |
| 四国 | 110 kV | namebind | 2 | 4 | [way 996557890](https://www.openstreetmap.org/way/996557890) |
| 四国 | 110 kV | namebind | 2 | 4 | [way 996557890](https://www.openstreetmap.org/way/996557890) |
| 四国 | 110 kV | 中津町三丁目変電所~藤生町一丁目変電所線 | 2 | 3 | [way 1018441699](https://www.openstreetmap.org/way/1018441699) |
| 四国 | 110 kV | 中津町三丁目変電所~藤生町一丁目変電所線 | 2 | 3 | [way 1018441699](https://www.openstreetmap.org/way/1018441699) |
| 四国 | 110 kV | 大三島支線 | 2 | 4 | [way 59277248](https://www.openstreetmap.org/way/59277248) |
| 四国 | 110 kV | 大三島支線 | 2 | 4 | [way 59277248](https://www.openstreetmap.org/way/59277248) |
| 四国 | 110 kV | 大州四丁目変電所~広島補助き電区分所線 | 2 | 3 | [way 178675917](https://www.openstreetmap.org/way/178675917) |
| 四国 | 110 kV | 東広島変電所~吉和変電所線 | 2 | 1 | [way 151708915](https://www.openstreetmap.org/way/151708915) |
| 四国 | 110 kV | 西広島変電所~古市四丁目変電所線 | 2 | 1 | [way 105107504](https://www.openstreetmap.org/way/105107504) |
| 四国 | 77 kV | 松帆西路変電所~撫養変電所線 | 4 | 1 | [way 724287149](https://www.openstreetmap.org/way/724287149) |
| 四国 | 77 kV | 松帆西路変電所~撫養変電所線 | 4 | 1 | [way 724287149](https://www.openstreetmap.org/way/724287149) |
| 四国 | 77 kV | 松帆西路変電所~撫養変電所線 | 4 | 1 | [way 724287149](https://www.openstreetmap.org/way/724287149) |
| 四国 | 77 kV | 松帆西路変電所~撫養変電所線 | 4 | 1 | [way 724287149](https://www.openstreetmap.org/way/724287149) |
| 四国 | 66 kV | 三津支線 / 吉田浜北線 | 2 | 1 | [way 619437956](https://www.openstreetmap.org/way/619437956) |
| 四国 | 66 kV | 上天神線 | 1 | 2 | [way 87491653](https://www.openstreetmap.org/way/87491653) |
| 四国 | 66 kV | 上天神線 | 1 | 2 | [way 87491653](https://www.openstreetmap.org/way/87491653) |
| 四国 | 66 kV | 中国電力ネットワーク 66.0kV線 | 2 | 4 | [way 1037121583](https://www.openstreetmap.org/way/1037121583) |
| 四国 | 66 kV | 保内線 | 2 | 3 | [way 1022461182](https://www.openstreetmap.org/way/1022461182) |
| 四国 | 66 kV | 北条線 | 1 | 2 | [way 1352329374](https://www.openstreetmap.org/way/1352329374) |
| 四国 | 66 kV | 北条線 | 1 | 2 | [way 1352329374](https://www.openstreetmap.org/way/1352329374) |
| 四国 | 66 kV | 四国電力送配電 187.0kV線 | 6 | 1 | [way 1037463548](https://www.openstreetmap.org/way/1037463548) |
| 四国 | 66 kV | 四国電力送配電 66.0kV線 | 1 | 2 | [way 1022253581](https://www.openstreetmap.org/way/1022253581) |
| 四国 | 66 kV | 四国電力送配電 66.0kV線 | 2 | 1 | [way 1022749392](https://www.openstreetmap.org/way/1022749392) |
| 四国 | 66 kV | 四国電力送配電 66.0kV線 | 2 | 4 | [way 1037121583](https://www.openstreetmap.org/way/1037121583) |
| 四国 | 66 kV | 坂出連絡線 | 2 | 4 | [way 90301253](https://www.openstreetmap.org/way/90301253) |
| 四国 | 66 kV | 坂出連絡線 | 2 | 4 | [way 90301253](https://www.openstreetmap.org/way/90301253) |
| 四国 | 66 kV | 宇和島線 | 1 | 2 | [way 1022467762](https://www.openstreetmap.org/way/1022467762) |
| 四国 | 66 kV | 志度変電所~三木変電所線 | 2 | 4 | [way 190195500](https://www.openstreetmap.org/way/190195500) |
| 四国 | 66 kV | 志度変電所~三木変電所線 | 2 | 4 | [way 190195500](https://www.openstreetmap.org/way/190195500) |
| 四国 | 66 kV | 関西電力送配電 187.0kV線 | 6 | 1 | [way 1037463548](https://www.openstreetmap.org/way/1037463548) |
| 四国 | 66 kV | 需要家線 | 1 | 2 | [way 1235604145](https://www.openstreetmap.org/way/1235604145) |
| 四国 | 66 kV | 需要家線 | 1 | 2 | [way 1235604145](https://www.openstreetmap.org/way/1235604145) |
| 四国 | 66 kV | 高松坂出線 | 2 | 4 | [way 88478983](https://www.openstreetmap.org/way/88478983) |
| 四国 | 66 kV | 高松坂出線 | 2 | 4 | [way 88478983](https://www.openstreetmap.org/way/88478983) |
| 四国 | 66 kV | 高松坂出線 | 2 | 4 | [way 88478983](https://www.openstreetmap.org/way/88478983) |
| 四国 | 66 kV | 高松坂出線 | 2 | 4 | [way 88478983](https://www.openstreetmap.org/way/88478983) |
| 四国 | 0 kV | 阿南紀北直流幹線(海底ケーブル区間) | 2 | 1 | [way 217885659](https://www.openstreetmap.org/way/217885659) |
| 東北 | 500 kV | 福島東幹線 | 2 | 4 | [way 104392604](https://www.openstreetmap.org/way/104392604) |
| 東北 | 275 kV | 南相馬市変電所~南相馬変電所線 | 2 | 1 | [way 104058147](https://www.openstreetmap.org/way/104058147) |
| 東北 | 275 kV | 名取変電所~西仙台変電所線 | 2 | 3 | [way 201966023](https://www.openstreetmap.org/way/201966023) |
| 東北 | 275 kV | 喜多方市変電所~本名変電所線 | 2 | 3 | [way 242012095](https://www.openstreetmap.org/way/242012095) |
| 東北 | 275 kV | 東北電力ネットワーク 275.0kV線 | 1 | 3 | [way 233174203](https://www.openstreetmap.org/way/233174203) |
| 東北 | 275 kV | 蔵王幹線;秋柴線 | 4 | 2 | [way 250462659](https://www.openstreetmap.org/way/250462659) |
| 東北 | 154 kV | JR東日本 酒田変電所~酒田変電所線 | 3 | 4 | [way 830289314](https://www.openstreetmap.org/way/830289314) |
| 東北 | 154 kV | 下北線 | 1 | 2 | [way 1172465314](https://www.openstreetmap.org/way/1172465314) |
| 東北 | 154 kV | 中西線;山木戸線 | 4 | 2 | [way 170197079](https://www.openstreetmap.org/way/170197079) |
| 東北 | 154 kV | 中西線;山木戸線 | 4 | 2 | [way 170197079](https://www.openstreetmap.org/way/170197079) |
| 東北 | 154 kV | 中西線;紫竹線 | 4 | 2 | [way 170016147](https://www.openstreetmap.org/way/170016147) |
| 東北 | 154 kV | 仙台港変電所~舟入一丁目変電所線 | 2 | 4 | [way 103746689](https://www.openstreetmap.org/way/103746689) |
| 東北 | 154 kV | 会津変電所~喜多方市変電所線 / 喜多方市変電所~会津変電所線 | 2 | 1 | [way 231185542](https://www.openstreetmap.org/way/231185542) |
| 東北 | 154 kV | 六ヶ所変電所~尾駮変電所線 | 1 | 5 | [way 797759487](https://www.openstreetmap.org/way/797759487) |
| 東北 | 154 kV | 六ヶ所線 | 3 | 5 | [way 318193034](https://www.openstreetmap.org/way/318193034) |
| 東北 | 154 kV | 喜多方市変電所~会津若松市変電所線 | 2 | 4 | [way 231192715](https://www.openstreetmap.org/way/231192715) |
| 東北 | 154 kV | 喜多方市変電所~会津若松市変電所線 | 2 | 4 | [way 1087517521](https://www.openstreetmap.org/way/1087517521) |
| 東北 | 154 kV | 姫神線 | 2 | 4 | [way 316824394](https://www.openstreetmap.org/way/316824394) |
| 東北 | 154 kV | 字下園変電所~会津変電所線 | 2 | 4 | [way 252836949](https://www.openstreetmap.org/way/252836949) |
| 東北 | 154 kV | 岩盛線 | 2 | 4 | [way 316824394](https://www.openstreetmap.org/way/316824394) |
| 東北 | 154 kV | 新仙台火力線 | 4 | 1 | [way 103671668](https://www.openstreetmap.org/way/103671668) |
| 東北 | 154 kV | 新仙台火力線 | 4 | 1 | [way 103671668](https://www.openstreetmap.org/way/103671668) |
| 東北 | 154 kV | 新仙台火力線 | 4 | 1 | [way 103746719](https://www.openstreetmap.org/way/103746719) |
| 東北 | 154 kV | 新仙台火力線 | 4 | 1 | [way 103746719](https://www.openstreetmap.org/way/103746719) |
| 東北 | 154 kV | 新仙台火力線 | 4 | 1 | [way 1052190116](https://www.openstreetmap.org/way/1052190116) |
| 東北 | 154 kV | 東港一丁目変電所_2~北新潟変電所線 | 4 | 1 | [way 170016139](https://www.openstreetmap.org/way/170016139) |
| 東北 | 154 kV | 秋田変電所~阿仁変電所線 | 2 | 4 | [way 1066930221](https://www.openstreetmap.org/way/1066930221) |
| 東北 | 154 kV | 秋田火力線;秋田臨海線 | 4 | 1 | [way 318152340](https://www.openstreetmap.org/way/318152340) |
| 東北 | 154 kV | 羽後線 | 2 | 3 | [way 785572520](https://www.openstreetmap.org/way/785572520) |
| 東北 | 154 kV | 蔵王幹線;秋柴線 | 4 | 2 | [way 250462659](https://www.openstreetmap.org/way/250462659) |
| 東北 | 154 kV | 飯坂変電所~北福島変電所線 | 2 | 4 | [way 1017577752](https://www.openstreetmap.org/way/1017577752) |
| 東北 | 66 kV | 0547線;第一大釜線 | 2 | 1 | [way 721658977](https://www.openstreetmap.org/way/721658977) |
| 東北 | 66 kV | 0547線;第一大釜線 | 2 | 1 | [way 721658977](https://www.openstreetmap.org/way/721658977) |
| 東北 | 66 kV | 0547線;第一大釜線 | 2 | 1 | [way 721658979](https://www.openstreetmap.org/way/721658979) |
| 東北 | 66 kV | 0547線;第一大釜線;第二大釜線 | 3 | 1 | [way 721658978](https://www.openstreetmap.org/way/721658978) |
| 東北 | 66 kV | JR東日本 羽前千歳変電所~大野目変電所線 | 1 | 2 | [way 404965846](https://www.openstreetmap.org/way/404965846) |
| 東北 | 66 kV | leadin | 1 | 2 | [way 721144756](https://www.openstreetmap.org/way/721144756) |
| 東北 | 66 kV | leadin | 2 | 3 | [way 343505355](https://www.openstreetmap.org/way/343505355) |
| 東北 | 66 kV | leadin | 2 | 3 | [way 785286715](https://www.openstreetmap.org/way/785286715) |
| 東北 | 66 kV | namebind | 2 | 4 | [way 770377144](https://www.openstreetmap.org/way/770377144) |
| 東北 | 66 kV | 下北線 | 3 | 1 | [way 318193034](https://www.openstreetmap.org/way/318193034) |
| 東北 | 66 kV | 中西線;山木戸線 | 4 | 2 | [way 170197079](https://www.openstreetmap.org/way/170197079) |
| 東北 | 66 kV | 中西線;紫竹線 | 4 | 2 | [way 170016147](https://www.openstreetmap.org/way/170016147) |
| 東北 | 66 kV | 仙台変電所~鶴ヶ谷北二丁目変電所線 | 3 | 4 | [way 103821128](https://www.openstreetmap.org/way/103821128) |
| 東北 | 66 kV | 六ヶ所変電所~尾駮変電所線 | 4 | 1 | [way 607269366](https://www.openstreetmap.org/way/607269366) |
| 東北 | 66 kV | 刈和野支線 | 2 | 3 | [way 785523029](https://www.openstreetmap.org/way/785523029) |
| 東北 | 66 kV | 前沢変電所~平泉変電所線 | 1 | 2 | [way 783616469](https://www.openstreetmap.org/way/783616469) |
| 東北 | 66 kV | 北台変電所~新福島変電所線 | 4 | 1 | [way 103837316](https://www.openstreetmap.org/way/103837316) |
| 東北 | 66 kV | 北工業団地変電所~柳原変電所線 | 1 | 2 | [way 721786410](https://www.openstreetmap.org/way/721786410) |
| 東北 | 66 kV | 南仙台変電所~東若林変電所線 | 4 | 1 | [way 104055765](https://www.openstreetmap.org/way/104055765) |
| 東北 | 66 kV | 南仙台変電所~東若林変電所線 | 4 | 1 | [way 104055765](https://www.openstreetmap.org/way/104055765) |
| 東北 | 66 kV | 大久保線 | 2 | 4 | [way 322132737](https://www.openstreetmap.org/way/322132737) |
| 東北 | 66 kV | 大字夏茂変電所~福沢南変電所線 | 2 | 3 | [way 782986795](https://www.openstreetmap.org/way/782986795) |
| 東北 | 66 kV | 宮古線;東盛岡線 | 4 | 2 | [way 795857963](https://www.openstreetmap.org/way/795857963) |
| 東北 | 66 kV | 宮城変電所~高清水変電所線 | 2 | 6 | [way 106076899](https://www.openstreetmap.org/way/106076899) |
| 東北 | 66 kV | 小国小坂町三丁目変電所~北変電所線 | 1 | 2 | [way 79367962](https://www.openstreetmap.org/way/79367962) |
| 東北 | 66 kV | 平五丁目変電所~中越変電所線 | 2 | 3 | [way 199655562](https://www.openstreetmap.org/way/199655562) |
| 東北 | 66 kV | 新福島変電所~楢葉町変電所線 | 4 | 1 | [way 104422180](https://www.openstreetmap.org/way/104422180) |
| 東北 | 66 kV | 新福島変電所~楢葉町変電所線 | 4 | 1 | [way 104422180](https://www.openstreetmap.org/way/104422180) |
| 東北 | 66 kV | 東北電力ネットワーク 154.0kV線 | 4 | 1 | [way 783593579](https://www.openstreetmap.org/way/783593579) |
| 東北 | 66 kV | 東北電力ネットワーク 154.0kV線 | 4 | 1 | [way 829088620](https://www.openstreetmap.org/way/829088620) |
| 東北 | 66 kV | 東北電力ネットワーク 154.0kV線 | 4 | 1 | [way 1017577778](https://www.openstreetmap.org/way/1017577778) |
| 東北 | 66 kV | 東北電力ネットワーク 275.0kV線 | 6 | 1 | [way 829088680](https://www.openstreetmap.org/way/829088680) |
| 東北 | 66 kV | 東北電力ネットワーク 66.0kV線 | 1 | 2 | [way 722192406](https://www.openstreetmap.org/way/722192406) |
| 東北 | 66 kV | 東北電力ネットワーク 66.0kV線 | 1 | 2 | [way 768281375](https://www.openstreetmap.org/way/768281375) |
| 東北 | 66 kV | 東北電力ネットワーク 66.0kV線 | 1 | 2 | [way 794859500](https://www.openstreetmap.org/way/794859500) |
| 東北 | 66 kV | 東北電力ネットワーク 66.0kV線 | 1 | 2 | [way 814188477](https://www.openstreetmap.org/way/814188477) |
| 東北 | 66 kV | 東北電力ネットワーク 66.0kV線 | 1 | 2 | [way 828817657](https://www.openstreetmap.org/way/828817657) |
| 東北 | 66 kV | 東北電力ネットワーク 66.0kV線 | 1 | 2 | [way 902179410](https://www.openstreetmap.org/way/902179410) |
| 東北 | 66 kV | 東北電力ネットワーク 66.0kV線 | 2 | 3 | [way 891443200](https://www.openstreetmap.org/way/891443200) |
| 東北 | 66 kV | 東北電力ネットワーク 66.0kV線 | 4 | 6 | [way 326125857](https://www.openstreetmap.org/way/326125857) |
| 東北 | 66 kV | 東北電力ネットワーク 66.0kV線 / 巣子変電所~日戸変電所線 | 2 | 1 | [way 781188566](https://www.openstreetmap.org/way/781188566) |
| 東北 | 66 kV | 東白石変電所~丸森変電所線 | 2 | 3 | [way 318286883](https://www.openstreetmap.org/way/318286883) |
| 東北 | 66 kV | 東裏変電所~初森変電所線 | 2 | 1 | [way 1070373189](https://www.openstreetmap.org/way/1070373189) |
| 東北 | 66 kV | 東通変電所~東通村変電所線 | 2 | 1 | [way 1025405618](https://www.openstreetmap.org/way/1025405618) |
| 東北 | 66 kV | 東通変電所~東通村変電所線 | 2 | 1 | [way 1025405618](https://www.openstreetmap.org/way/1025405618) |
| 東北 | 66 kV | 松神線 | 1 | 2 | [way 721144754](https://www.openstreetmap.org/way/721144754) |
| 東北 | 66 kV | 柳原線 | 2 | 4 | [way 659514646](https://www.openstreetmap.org/way/659514646) |
| 東北 | 66 kV | 水沢線 | 2 | 4 | [way 659514633](https://www.openstreetmap.org/way/659514633) |
| 東北 | 66 kV | 河東町広田変電所~会津若松市変電所線 | 1 | 2 | [way 239890910](https://www.openstreetmap.org/way/239890910) |
| 東北 | 66 kV | 泉変電所~飯坂変電所線 | 4 | 1 | [way 151229877](https://www.openstreetmap.org/way/151229877) |
| 東北 | 66 kV | 牡丹山六丁目変電所~大形変電所線 | 4 | 1 | [way 170016149](https://www.openstreetmap.org/way/170016149) |
| 東北 | 66 kV | 田沢線 | 2 | 3 | [way 293797365](https://www.openstreetmap.org/way/293797365) |
| 東北 | 66 kV | 神代線 | 2 | 3 | [way 323343995](https://www.openstreetmap.org/way/323343995) |
| 東北 | 66 kV | 秋田中央線 | 3 | 1 | [way 176001096](https://www.openstreetmap.org/way/176001096) |
| 東北 | 66 kV | 秋田中央線;352A;岩谷線 | 5 | 2 | [way 782083334](https://www.openstreetmap.org/way/782083334) |
| 東北 | 66 kV | 笹山開閉所~北新潟変電所線 | 3 | 1 | [way 1028585723](https://www.openstreetmap.org/way/1028585723) |
| 東北 | 66 kV | 笹山開閉所~北新潟変電所線 | 3 | 1 | [way 1028585723](https://www.openstreetmap.org/way/1028585723) |
| 東北 | 66 kV | 置賜変電所~鮎貝変電所線 | 2 | 1 | [way 766612854](https://www.openstreetmap.org/way/766612854) |
| 東北 | 66 kV | 西福島変電所~泉変電所線 | 4 | 1 | [way 835186100](https://www.openstreetmap.org/way/835186100) |
| 東北 | 66 kV | 豊栄変電所~笹山開閉所線 | 6 | 1 | [way 1028585690](https://www.openstreetmap.org/way/1028585690) |
| 東北 | 66 kV | 豊里線 | 2 | 3 | [way 104945168](https://www.openstreetmap.org/way/104945168) |
| 東北 | 66 kV | 酒田市変電所~升田変電所線 | 1 | 2 | [way 769954059](https://www.openstreetmap.org/way/769954059) |
| 東北 | 66 kV | 重吉線 | 4 | 1 | [way 325433632](https://www.openstreetmap.org/way/325433632) |
| 東北 | 66 kV | 重吉線 | 4 | 1 | [way 325433632](https://www.openstreetmap.org/way/325433632) |
| 東北 | 66 kV | 重吉線 | 4 | 1 | [way 325433632](https://www.openstreetmap.org/way/325433632) |
| 東京 | 500 kV | 安曇幹線2号線 | 1 | 2 | [way 618344843](https://www.openstreetmap.org/way/618344843) |
| 東京 | 500 kV | 新吾妻線 | 2 | 4 | [way 66319631](https://www.openstreetmap.org/way/66319631) |
| 東京 | 500 kV | 新坂戸線（只見幹線）/新新田東毛線 | 4 | 2 | [way 1030329130](https://www.openstreetmap.org/way/1030329130) |
| 東京 | 500 kV | 新所沢線 | 2 | 4 | [way 672346305](https://www.openstreetmap.org/way/672346305) |
| 東京 | 500 kV | 新茂木~益子町変電所線 | 2 | 3 | [way 340290782](https://www.openstreetmap.org/way/340290782) |
| 東京 | 500 kV | 東京電力パワーグリッド 500.0kV線 | 1 | 3 | [way 287954362](https://www.openstreetmap.org/way/287954362) |
| 東京 | 500 kV | 東京電力パワーグリッド 500.0kV線 | 1 | 8 | [way 518993020](https://www.openstreetmap.org/way/518993020) |
| 東京 | 500 kV | 東北送電線_67 | 2 | 1 | [way 105432590](https://www.openstreetmap.org/way/105432590) |
| 東京 | 275 kV | 上尾線 / 東埼玉線 | 4 | 2 | [way 92462916](https://www.openstreetmap.org/way/92462916) |
| 東京 | 275 kV | 中沢線3・4L | 2 | 4 | [way 152937151](https://www.openstreetmap.org/way/152937151) |
| 東京 | 275 kV | 京浜線3・4号線 | 2 | 4 | [way 91829530](https://www.openstreetmap.org/way/91829530) |
| 東京 | 275 kV | 京浜線3・4号線 | 2 | 4 | [way 91829530](https://www.openstreetmap.org/way/91829530) |
| 東京 | 275 kV | 佐久間東幹線（山線） | 2 | 6 | [way 150065046](https://www.openstreetmap.org/way/150065046) |
| 東京 | 275 kV | 北熊谷線;新田線;豊里線 | 6 | 2 | [way 883880674](https://www.openstreetmap.org/way/883880674) |
| 東京 | 275 kV | 北総線/佐倉線 | 4 | 2 | [way 151374771](https://www.openstreetmap.org/way/151374771) |
| 東京 | 275 kV | 北葛飾線/野田線 | 4 | 2 | [way 138427965](https://www.openstreetmap.org/way/138427965) |
| 東京 | 275 kV | 千葉火力線1・2L | 2 | 4 | [way 704195151](https://www.openstreetmap.org/way/704195151) |
| 東京 | 275 kV | 南狭山線 / 日高線 | 4 | 2 | [way 1149033975](https://www.openstreetmap.org/way/1149033975) |
| 東京 | 275 kV | 南狭山線 / 日高線 | 4 | 2 | [way 1149033975](https://www.openstreetmap.org/way/1149033975) |
| 東京 | 275 kV | 南狭山線 / 日高線 | 4 | 2 | [way 1149033975](https://www.openstreetmap.org/way/1149033975) |
| 東京 | 275 kV | 南狭山線 / 笠幡線 | 4 | 2 | [way 152937156](https://www.openstreetmap.org/way/152937156) |
| 東京 | 275 kV | 原研那珂線 | 2 | 3 | [way 762291175](https://www.openstreetmap.org/way/762291175) |
| 東京 | 275 kV | 天竜区変電所~鳳来変電所線 / （新）佐久間東幹線【建設中】 / 佐久間東幹線（山線）2L【増強後廃線】 / 東清水線【 | 2 | 1 | [way 192656410](https://www.openstreetmap.org/way/192656410) |
| 東京 | 275 kV | 姉崎線3・4L | 2 | 6 | [way 168782035](https://www.openstreetmap.org/way/168782035) |
| 東京 | 275 kV | 新坂戸線（只見幹線）/新新田東毛線 | 4 | 2 | [way 1030329130](https://www.openstreetmap.org/way/1030329130) |
| 東京 | 275 kV | 新座線 / 狭山線 | 4 | 2 | [way 159523420](https://www.openstreetmap.org/way/159523420) |
| 東京 | 275 kV | 新座線 / 狭山線 / 脇田線 | 6 | 2 | [way 159503131](https://www.openstreetmap.org/way/159503131) |
| 東京 | 275 kV | 東京中線;川島町線 | 4 | 2 | [way 315425114](https://www.openstreetmap.org/way/315425114) |
| 東京 | 275 kV | 東京南線3,4号線 | 2 | 4 | [way 161967904](https://www.openstreetmap.org/way/161967904) |
| 東京 | 275 kV | 東京南線3,4号線 | 2 | 4 | [way 161967904](https://www.openstreetmap.org/way/161967904) |
| 東京 | 275 kV | 東京南線3,4号線 | 2 | 4 | [way 161967904](https://www.openstreetmap.org/way/161967904) |
| 東京 | 275 kV | 東京南線3,4号線 | 2 | 4 | [way 161967904](https://www.openstreetmap.org/way/161967904) |
| 東京 | 275 kV | 樋口変電所~西毛変電所線 | 4 | 1 | [way 192447472](https://www.openstreetmap.org/way/192447472) |
| 東京 | 275 kV | 沼原線 | 2 | 4 | [way 519435378](https://www.openstreetmap.org/way/519435378) |
| 東京 | 275 kV | 港北線 / 平台線 | 4 | 2 | [way 119049775](https://www.openstreetmap.org/way/119049775) |
| 東京 | 275 kV | 港北線 / 鴨志田線 | 4 | 2 | [way 85961906](https://www.openstreetmap.org/way/85961906) |
| 東京 | 275 kV | 神栖火力線 | 1 | 2 | [way 1081326554](https://www.openstreetmap.org/way/1081326554) |
| 東京 | 275 kV | 秦浜線;中綾線;綾瀬線 | 6 | 2 | [way 162844694](https://www.openstreetmap.org/way/162844694) |
| 東京 | 275 kV | 秦浜線;中綾線;綾瀬線 | 6 | 2 | [way 162844694](https://www.openstreetmap.org/way/162844694) |
| 東京 | 275 kV | 秦浜線;湘南線 | 4 | 2 | [way 80204571](https://www.openstreetmap.org/way/80204571) |
| 東京 | 275 kV | 西越谷線 / 白岡線 | 4 | 2 | [way 194528837](https://www.openstreetmap.org/way/194528837) |
| 東京 | 275 kV | 鹿島第二火力線 | 2 | 4 | [way 300345935](https://www.openstreetmap.org/way/300345935) |
| 東京 | 275 kV | 鹿島線 | 1 | 2 | [way 340659465](https://www.openstreetmap.org/way/340659465) |
| 東京 | 275 kV | 鹿島線 / 船津線 | 4 | 2 | [way 340647454](https://www.openstreetmap.org/way/340647454) |
| 東京 | 275 kV | 鹿島線/船津線 | 4 | 2 | [way 340644804](https://www.openstreetmap.org/way/340644804) |
| 東京 | 154 kV | namebind | 4 | 2 | [way 1140699317](https://www.openstreetmap.org/way/1140699317) |
| 東京 | 154 kV | 上毛幹線 | 2 | 3 | [way 518992987](https://www.openstreetmap.org/way/518992987) |
| 東京 | 154 kV | 上毛幹線 | 2 | 3 | [way 518992987](https://www.openstreetmap.org/way/518992987) |
| 東京 | 154 kV | 上毛幹線 | 2 | 4 | [way 518992987](https://www.openstreetmap.org/way/518992987) |
| 東京 | 154 kV | 上群線/野中旧線 | 4 | 1 | [way 250626620](https://www.openstreetmap.org/way/250626620) |
| 東京 | 154 kV | 中富線;北歳線 | 4 | 2 | [way 40214356](https://www.openstreetmap.org/way/40214356) |
| 東京 | 154 kV | 亀戸線 | 2 | 4 | [way 146486522](https://www.openstreetmap.org/way/146486522) |
| 東京 | 154 kV | 亀戸線 / 鶴ヶ曽根線 | 6 | 2 | [way 195071836](https://www.openstreetmap.org/way/195071836) |
| 東京 | 154 kV | 京北線 | 2 | 4 | [way 1149772119](https://www.openstreetmap.org/way/1149772119) |
| 東京 | 154 kV | 伊原線;草加青柳線 | 4 | 2 | [way 195085031](https://www.openstreetmap.org/way/195085031) |
| 東京 | 154 kV | 佐波線/八斗島線 | 4 | 2 | [way 195615140](https://www.openstreetmap.org/way/195615140) |
| 東京 | 154 kV | 佐野線 / 友沼線 | 4 | 2 | [way 1083112320](https://www.openstreetmap.org/way/1083112320) |
| 東京 | 154 kV | 佐野線 / 板倉線 | 4 | 2 | [way 1083109198](https://www.openstreetmap.org/way/1083109198) |
| 東京 | 154 kV | 佐野線 / 板倉線 | 4 | 2 | [way 1083109198](https://www.openstreetmap.org/way/1083109198) |
| 東京 | 154 kV | 佐野線 / 赤麻線 | 4 | 2 | [way 1083109198](https://www.openstreetmap.org/way/1083109198) |
| 東京 | 154 kV | 北五井火力線 | 2 | 4 | [way 168782019](https://www.openstreetmap.org/way/168782019) |
| 東京 | 154 kV | 北堀線 | 2 | 6 | [way 37572970](https://www.openstreetmap.org/way/37572970) |
| 東京 | 154 kV | 北多摩線 / 吉武線 | 4 | 2 | [way 106092298](https://www.openstreetmap.org/way/106092298) |
| 東京 | 154 kV | 北葛飾線/野田線 | 4 | 2 | [way 138427965](https://www.openstreetmap.org/way/138427965) |
| 東京 | 154 kV | 北鳩線 | 4 | 8 | [way 134023497](https://www.openstreetmap.org/way/134023497) |
| 東京 | 154 kV | 南川崎南大田線 | 2 | 3 | [way 1156486627](https://www.openstreetmap.org/way/1156486627) |
| 東京 | 154 kV | 南川崎南太田線 | 2 | 3 | [way 1156486627](https://www.openstreetmap.org/way/1156486627) |
| 東京 | 154 kV | 南川崎南太田線 | 2 | 3 | [way 1156486627](https://www.openstreetmap.org/way/1156486627) |
| 東京 | 154 kV | 南武線 / 南崎線 | 4 | 2 | [way 81837955](https://www.openstreetmap.org/way/81837955) |
| 東京 | 154 kV | 南武線 / 南崎線 | 4 | 2 | [way 81837955](https://www.openstreetmap.org/way/81837955) |
| 東京 | 154 kV | 南武線 / 南崎線 | 4 | 2 | [way 81837955](https://www.openstreetmap.org/way/81837955) |
| 東京 | 154 kV | 南葛線;武南線 | 4 | 2 | [way 133354822](https://www.openstreetmap.org/way/133354822) |
| 東京 | 154 kV | 同一敷地タイ(同定) | 2 | 1 | [way 639813544](https://www.openstreetmap.org/way/639813544) |
| 東京 | 154 kV | 小北線 / 間々田線 | 4 | 2 | [way 1086574979](https://www.openstreetmap.org/way/1086574979) |
| 東京 | 154 kV | 小北線 / 間々田線 | 4 | 2 | [way 1086574979](https://www.openstreetmap.org/way/1086574979) |
| 東京 | 154 kV | 小北線 / 間々田線 | 4 | 2 | [way 1086578359](https://www.openstreetmap.org/way/1086578359) |
| 東京 | 154 kV | 小松川線 / 一之江線 | 4 | 2 | [way 1139076631](https://www.openstreetmap.org/way/1139076631) |
| 東京 | 154 kV | 川世線;千南線 | 4 | 2 | [way 36962359](https://www.openstreetmap.org/way/36962359) |
| 東京 | 154 kV | 川世線;千南線 | 4 | 2 | [way 47366032](https://www.openstreetmap.org/way/47366032) |
| 東京 | 154 kV | 成瀬線 | 2 | 4 | [way 84159476](https://www.openstreetmap.org/way/84159476) |
| 東京 | 154 kV | 新座線 / 狭山線 / 脇田線 | 6 | 2 | [way 159503131](https://www.openstreetmap.org/way/159503131) |
| 東京 | 154 kV | 新鶴見線 | 2 | 4 | [way 44779309](https://www.openstreetmap.org/way/44779309) |
| 東京 | 154 kV | 旭ヶ丘線 | 2 | 4 | [way 159523492](https://www.openstreetmap.org/way/159523492) |
| 東京 | 154 kV | 旭ヶ丘線 / 日高線 | 4 | 2 | [way 152991092](https://www.openstreetmap.org/way/152991092) |
| 東京 | 154 kV | 木下線 / 印西線 | 4 | 2 | [way 1039813495](https://www.openstreetmap.org/way/1039813495) |
| 東京 | 154 kV | 木下線 / 印西線 / 千葉新線 | 6 | 2 | [way 891316398](https://www.openstreetmap.org/way/891316398) |
| 東京 | 154 kV | 村松線 / 孫目線 | 4 | 2 | [way 1139127272](https://www.openstreetmap.org/way/1139127272) |
| 東京 | 154 kV | 東京電力パワーグリッド 154.0kV線 | 2 | 3 | [way 1140712967](https://www.openstreetmap.org/way/1140712967) |
| 東京 | 154 kV | 東京電力パワーグリッド 154.0kV線 | 2 | 4 | [way 1295836701](https://www.openstreetmap.org/way/1295836701) |
| 東京 | 154 kV | 東京電力海瀬発電所~小海町変電所線 / 小海町変電所~新羽変電所線 / 新羽変電所~新秩父開閉所線 / 黒部幹線 | 2 | 1 | [way 236238142](https://www.openstreetmap.org/way/236238142) |
| 東京 | 154 kV | 東富士線 | 6 | 4 | [way 726559377](https://www.openstreetmap.org/way/726559377) |
| 東京 | 154 kV | 東富士線;富士岡線 | 6 | 4 | [way 150065040](https://www.openstreetmap.org/way/150065040) |
| 東京 | 154 kV | 栃山線 / JR宝積寺線 | 4 | 2 | [way 104527977](https://www.openstreetmap.org/way/104527977) |
| 東京 | 154 kV | 栃山線 / 河宮線 | 4 | 2 | [way 1093731871](https://www.openstreetmap.org/way/1093731871) |
| 東京 | 154 kV | 栃山線 / 河宮線 | 4 | 2 | [way 1093731871](https://www.openstreetmap.org/way/1093731871) |
| 東京 | 154 kV | 栃那線 / 喜連川線 | 4 | 2 | [way 1148738172](https://www.openstreetmap.org/way/1148738172) |
| 東京 | 154 kV | 栃那線 / 喜連川線 | 4 | 2 | [way 1148738172](https://www.openstreetmap.org/way/1148738172) |
| 東京 | 154 kV | 横浜火力北線 / 保土ヶ谷線 | 4 | 2 | [way 111667549](https://www.openstreetmap.org/way/111667549) |
| 東京 | 154 kV | 横浜火力北線 / 保土ヶ谷線 | 4 | 2 | [way 111667549](https://www.openstreetmap.org/way/111667549) |
| 東京 | 154 kV | 横浜火力北線 / 妙蓮寺線 | 4 | 2 | [way 111667549](https://www.openstreetmap.org/way/111667549) |
| 東京 | 154 kV | 横浜火力南線 / 子安線 | 4 | 2 | [way 127627970](https://www.openstreetmap.org/way/127627970) |
| 東京 | 154 kV | 武蔵赤坂線 | 2 | 4 | [way 159502470](https://www.openstreetmap.org/way/159502470) |
| 東京 | 154 kV | 猪苗代新幹線 | 2 | 4 | [way 340868153](https://www.openstreetmap.org/way/340868153) |
| 東京 | 154 kV | 田代幹線 | 2 | 3 | [way 1062593936](https://www.openstreetmap.org/way/1062593936) |
| 東京 | 154 kV | 白石線 | 2 | 6 | [way 1156486627](https://www.openstreetmap.org/way/1156486627) |
| 東京 | 154 kV | 石岡線;岩間線 | 4 | 2 | [way 1150604659](https://www.openstreetmap.org/way/1150604659) |
| 東京 | 154 kV | 秦浜線;湘南線 | 4 | 2 | [way 80204571](https://www.openstreetmap.org/way/80204571) |
| 東京 | 154 kV | 秦浜線;湘南線 | 4 | 2 | [way 80204571](https://www.openstreetmap.org/way/80204571) |
| 東京 | 154 kV | 笹目線 / 新倉線 | 4 | 2 | [way 700128349](https://www.openstreetmap.org/way/700128349) |
| 東京 | 154 kV | 笹目線;朝霞線 | 4 | 2 | [way 1148425894](https://www.openstreetmap.org/way/1148425894) |
| 東京 | 154 kV | 筑南線 / 筑館線 | 4 | 2 | [way 1150587604](https://www.openstreetmap.org/way/1150587604) |
| 東京 | 154 kV | 筑南線 / 筑館線 | 4 | 2 | [way 1150587607](https://www.openstreetmap.org/way/1150587607) |
| 東京 | 154 kV | 群馬幹線 | 2 | 4 | [way 1083433278](https://www.openstreetmap.org/way/1083433278) |
| 東京 | 154 kV | 群馬幹線/上武線 | 4 | 2 | [way 1085754103](https://www.openstreetmap.org/way/1085754103) |
| 東京 | 154 kV | 群馬幹線;キヤノン美里線 | 4 | 2 | [way 887614679](https://www.openstreetmap.org/way/887614679) |
| 東京 | 154 kV | 群馬幹線;キヤノン美里線 | 4 | 2 | [way 887614679](https://www.openstreetmap.org/way/887614679) |
| 東京 | 154 kV | 群馬幹線;キヤノン美里線 | 4 | 2 | [way 887614687](https://www.openstreetmap.org/way/887614687) |
| 東京 | 154 kV | 群馬幹線;坂戸線 | 4 | 2 | [way 884459800](https://www.openstreetmap.org/way/884459800) |
| 東京 | 154 kV | 群馬幹線;脇田線 | 4 | 2 | [way 190932271](https://www.openstreetmap.org/way/190932271) |
| 東京 | 154 kV | 群馬幹線;脇田線 | 4 | 2 | [way 190932271](https://www.openstreetmap.org/way/190932271) |
| 東京 | 154 kV | 芳賀線 / 氷室線 | 4 | 2 | [way 1138527645](https://www.openstreetmap.org/way/1138527645) |
| 東京 | 154 kV | 芳賀線 / 氷室線 | 4 | 2 | [way 1138527645](https://www.openstreetmap.org/way/1138527645) |
| 東京 | 154 kV | 菖蒲線 / NHK菖蒲線 | 4 | 2 | [way 1145571327](https://www.openstreetmap.org/way/1145571327) |
| 東京 | 154 kV | 藤沢線;湘南東線 | 4 | 2 | [way 167412001](https://www.openstreetmap.org/way/167412001) |
| 東京 | 154 kV | 西厚木線;湘南北線 | 4 | 2 | [way 41912085](https://www.openstreetmap.org/way/41912085) |
| 東京 | 154 kV | 西越谷線 / 白岡線 | 4 | 2 | [way 194528837](https://www.openstreetmap.org/way/194528837) |
| 東京 | 154 kV | 都留線 | 2 | 4 | [way 341226139](https://www.openstreetmap.org/way/341226139) |
| 東京 | 154 kV | 都留線 | 2 | 5 | [way 202441414](https://www.openstreetmap.org/way/202441414) |
| 東京 | 154 kV | 鹿島南共発線 / 東深芝線 | 4 | 2 | [way 210729109](https://www.openstreetmap.org/way/210729109) |
| 東京 | 77 kV | JR 西相模-平塚線 / JR 西相模-平塚線 / JR 西相模-平塚線 | 2 | 1 | [way 972597135](https://www.openstreetmap.org/way/972597135) |
| 東京 | 66 kV | JR 湯河原-来宮線 | 2 | 3 | [way 377731217](https://www.openstreetmap.org/way/377731217) |
| 東京 | 66 kV | JR二宮線 | 2 | 4 | [way 278236701](https://www.openstreetmap.org/way/278236701) |
| 東京 | 66 kV | JR勝山線 | 1 | 2 | [way 518902609](https://www.openstreetmap.org/way/518902609) |
| 東京 | 66 kV | JR大船田浦線 | 2 | 4 | [way 200583340](https://www.openstreetmap.org/way/200583340) |
| 東京 | 66 kV | JR太海線 | 2 | 3 | [way 1132618166](https://www.openstreetmap.org/way/1132618166) |
| 東京 | 66 kV | JR栗橋1号線 | 2 | 4 | [way 1064803825](https://www.openstreetmap.org/way/1064803825) |
| 東京 | 66 kV | leadin | 1 | 2 | [way 190935735](https://www.openstreetmap.org/way/190935735) |
| 東京 | 66 kV | leadin | 1 | 2 | [way 1084572310](https://www.openstreetmap.org/way/1084572310) |
| 東京 | 66 kV | leadin | 2 | 3 | [way 519448057](https://www.openstreetmap.org/way/519448057) |
| 東京 | 66 kV | leadin | 2 | 3 | [way 1065372797](https://www.openstreetmap.org/way/1065372797) |
| 東京 | 66 kV | leadin | 2 | 3 | [way 1065385355](https://www.openstreetmap.org/way/1065385355) |
| 東京 | 66 kV | leadin | 2 | 3 | [way 1065424922](https://www.openstreetmap.org/way/1065424922) |
| 東京 | 66 kV | leadin | 2 | 3 | [way 1083398351](https://www.openstreetmap.org/way/1083398351) |
| 東京 | 66 kV | leadin | 2 | 3 | [way 1133019004](https://www.openstreetmap.org/way/1133019004) |
| 東京 | 66 kV | leadin | 2 | 3 | [way 1135008596](https://www.openstreetmap.org/way/1135008596) |
| 東京 | 66 kV | leadin | 2 | 3 | [way 1145571335](https://www.openstreetmap.org/way/1145571335) |
| 東京 | 66 kV | leadin | 2 | 3 | [way 1150633960](https://www.openstreetmap.org/way/1150633960) |
| 東京 | 66 kV | leadin | 2 | 4 | [way 1011387288](https://www.openstreetmap.org/way/1011387288) |
| 東京 | 66 kV | leadin | 2 | 4 | [way 1133347161](https://www.openstreetmap.org/way/1133347161) |
| 東京 | 66 kV | leadin | 2 | 4 | [way 1156510550](https://www.openstreetmap.org/way/1156510550) |
| 東京 | 66 kV | leadin | 4 | 6 | [way 128364785](https://www.openstreetmap.org/way/128364785) |
| 東京 | 66 kV | namebind | 2 | 4 | [way 211356727](https://www.openstreetmap.org/way/211356727) |
| 東京 | 66 kV | namebind | 4 | 2 | [way 1140699317](https://www.openstreetmap.org/way/1140699317) |
| 東京 | 66 kV | ウェーブロック総和線 | 2 | 4 | [way 1065382217](https://www.openstreetmap.org/way/1065382217) |
| 東京 | 66 kV | クリーンセンター常陸那珂線 / 常陸那珂工団線 | 2 | 1 | [way 1074453053](https://www.openstreetmap.org/way/1074453053) |
| 東京 | 66 kV | クリーンセンター筑波線 | 1 | 2 | [way 1074397762](https://www.openstreetmap.org/way/1074397762) |
| 東京 | 66 kV | クリーンパーク茂原線 | 2 | 4 | [way 199419207](https://www.openstreetmap.org/way/199419207) |
| 東京 | 66 kV | ソニー鹿沼線 | 2 | 4 | [way 1065427276](https://www.openstreetmap.org/way/1065427276) |
| 東京 | 66 kV | ニコン相模原線 | 2 | 3 | [way 1389292743](https://www.openstreetmap.org/way/1389292743) |
| 東京 | 66 kV | ニコン相模原線 | 2 | 4 | [way 1389292743](https://www.openstreetmap.org/way/1389292743) |
| 東京 | 66 kV | パピヨン | 4 | 5 | [way 191634127](https://www.openstreetmap.org/way/191634127) |
| 東京 | 66 kV | 三菱相模原線 | 2 | 6 | [way 1385201238](https://www.openstreetmap.org/way/1385201238) |
| 東京 | 66 kV | 三郷線 | 2 | 3 | [way 628814321](https://www.openstreetmap.org/way/628814321) |
| 東京 | 66 kV | 上信線 | 2 | 4 | [way 520108668](https://www.openstreetmap.org/way/520108668) |
| 東京 | 66 kV | 上信線 / 上信線 / 上信線 / 上信線 / 上信線 / 上信線 | 2 | 1 | [way 1085004994](https://www.openstreetmap.org/way/1085004994) |
| 東京 | 66 kV | 上柴線;三ヶ尻線 | 4 | 2 | [way 192430382](https://www.openstreetmap.org/way/192430382) |
| 東京 | 66 kV | 上柴線;小川線 | 4 | 2 | [way 886710669](https://www.openstreetmap.org/way/886710669) |
| 東京 | 66 kV | 上柴線;小川線 | 4 | 2 | [way 886710669](https://www.openstreetmap.org/way/886710669) |
| 東京 | 66 kV | 上毛幹線/片品川線 | 4 | 2 | [way 520126263](https://www.openstreetmap.org/way/520126263) |
| 東京 | 66 kV | 中之条線 / 吾妻川線 / 川戸線 / 榛名線 / 榛名線 / 碓氷線 | 2 | 1 | [way 520108670](https://www.openstreetmap.org/way/520108670) |
| 東京 | 66 kV | 中富線;北歳線 | 4 | 2 | [way 40214356](https://www.openstreetmap.org/way/40214356) |
| 東京 | 66 kV | 丸一鋼管線 | 2 | 3 | [way 1137454399](https://www.openstreetmap.org/way/1137454399) |
| 東京 | 66 kV | 久喜線 / 東洋製罐久喜線 | 4 | 2 | [way 194542654](https://www.openstreetmap.org/way/194542654) |
| 東京 | 66 kV | 久喜線 / 東洋製罐久喜線 / 東久喜線 | 6 | 2 | [way 194528829](https://www.openstreetmap.org/way/194528829) |
| 東京 | 66 kV | 亀戸線 / 鶴ヶ曽根線 | 6 | 4 | [way 195071836](https://www.openstreetmap.org/way/195071836) |
| 東京 | 66 kV | 二ツ塚処分場線 | 2 | 3 | [way 915600127](https://www.openstreetmap.org/way/915600127) |
| 東京 | 66 kV | 二度栗山線 | 2 | 3 | [way 1147834405](https://www.openstreetmap.org/way/1147834405) |
| 東京 | 66 kV | 京換 39号~保土ヶ谷変電所線 | 2 | 3 | [way 1157129541](https://www.openstreetmap.org/way/1157129541) |
| 東京 | 66 kV | 伊原線;草加青柳線 | 4 | 2 | [way 195085031](https://www.openstreetmap.org/way/195085031) |
| 東京 | 66 kV | 伊草線 / 横堀線 | 4 | 6 | [way 133358062](https://www.openstreetmap.org/way/133358062) |
| 東京 | 66 kV | 住友金属線 / 鹿島西部環線 | 4 | 2 | [way 1082496941](https://www.openstreetmap.org/way/1082496941) |
| 東京 | 66 kV | 佐波線/八斗島線 | 4 | 2 | [way 195615140](https://www.openstreetmap.org/way/195615140) |
| 東京 | 66 kV | 佐野線 / 友沼線 | 4 | 2 | [way 1083112320](https://www.openstreetmap.org/way/1083112320) |
| 東京 | 66 kV | 佐野線 / 友沼線 | 4 | 2 | [way 1083112320](https://www.openstreetmap.org/way/1083112320) |
| 東京 | 66 kV | 佐野線 / 板倉線 | 4 | 2 | [way 1083109198](https://www.openstreetmap.org/way/1083109198) |
| 東京 | 66 kV | 佐野線 / 板倉線 | 4 | 2 | [way 1083109198](https://www.openstreetmap.org/way/1083109198) |
| 東京 | 66 kV | 佐野線 / 赤麻線 | 4 | 2 | [way 1083110508](https://www.openstreetmap.org/way/1083110508) |
| 東京 | 66 kV | 児玉線;キヤノン美里線 | 4 | 2 | [way 887614680](https://www.openstreetmap.org/way/887614680) |
| 東京 | 66 kV | 八幡環線 / 市原環線 | 4 | 7 | [way 315461236](https://www.openstreetmap.org/way/315461236) |
| 東京 | 66 kV | 六和線 | 2 | 4 | [way 191072910](https://www.openstreetmap.org/way/191072910) |
| 東京 | 66 kV | 内房線 | 2 | 3 | [way 1060169195](https://www.openstreetmap.org/way/1060169195) |
| 東京 | 66 kV | 函南町変電所~須雲川変電所線 | 4 | 1 | [way 409754433](https://www.openstreetmap.org/way/409754433) |
| 東京 | 66 kV | 加納線 | 2 | 4 | [way 195432093](https://www.openstreetmap.org/way/195432093) |
| 東京 | 66 kV | 北多摩線 / 吉武線 | 4 | 2 | [way 106092298](https://www.openstreetmap.org/way/106092298) |
| 東京 | 66 kV | 北平変電所~小川町塩田変電所線 | 1 | 2 | [way 631783783](https://www.openstreetmap.org/way/631783783) |
| 東京 | 66 kV | 北浦線 | 2 | 3 | [way 1074716751](https://www.openstreetmap.org/way/1074716751) |
| 東京 | 66 kV | 北熊谷線;新田線;豊里線 | 6 | 2 | [way 883880674](https://www.openstreetmap.org/way/883880674) |
| 東京 | 66 kV | 北総線/佐倉線 | 4 | 2 | [way 151374771](https://www.openstreetmap.org/way/151374771) |
| 東京 | 66 kV | 北総線/佐倉線 | 4 | 2 | [way 151374771](https://www.openstreetmap.org/way/151374771) |
| 東京 | 66 kV | 千葉新線 | 2 | 6 | [way 708222717](https://www.openstreetmap.org/way/708222717) |
| 東京 | 66 kV | 南共発線 | 2 | 3 | [way 619284825](https://www.openstreetmap.org/way/619284825) |
| 東京 | 66 kV | 南武線 / 南崎線 | 4 | 2 | [way 81837955](https://www.openstreetmap.org/way/81837955) |
| 東京 | 66 kV | 南武線 / 南崎線 | 4 | 2 | [way 81837955](https://www.openstreetmap.org/way/81837955) |
| 東京 | 66 kV | 南武線 / 南崎線 | 4 | 2 | [way 81837955](https://www.openstreetmap.org/way/81837955) |
| 東京 | 66 kV | 南狭山線 / 日高線 | 4 | 2 | [way 1149033975](https://www.openstreetmap.org/way/1149033975) |
| 東京 | 66 kV | 南狭山線 / 日高線 | 4 | 2 | [way 1149033975](https://www.openstreetmap.org/way/1149033975) |
| 東京 | 66 kV | 南狭山線 / 笠幡線 | 4 | 2 | [way 152937156](https://www.openstreetmap.org/way/152937156) |
| 東京 | 66 kV | 南葛線;武南線 | 4 | 2 | [way 133354822](https://www.openstreetmap.org/way/133354822) |
| 東京 | 66 kV | 南葛線;武南線 | 4 | 2 | [way 133354822](https://www.openstreetmap.org/way/133354822) |
| 東京 | 66 kV | 南葛線;武南線 | 4 | 2 | [way 133354822](https://www.openstreetmap.org/way/133354822) |
| 東京 | 66 kV | 南袖ヶ浦線 | 2 | 3 | [way 280980106](https://www.openstreetmap.org/way/280980106) |
| 東京 | 66 kV | 反町線 | 1 | 2 | [way 1083920986](https://www.openstreetmap.org/way/1083920986) |
| 東京 | 66 kV | 吾妻川線 | 2 | 4 | [way 1084983564](https://www.openstreetmap.org/way/1084983564) |
| 東京 | 66 kV | 和田堀線;北烏山線 | 4 | 2 | [way 38072848](https://www.openstreetmap.org/way/38072848) |
| 東京 | 66 kV | 国分寺線;車返線 | 2 | 6 | [way 51558349](https://www.openstreetmap.org/way/51558349) |
| 東京 | 66 kV | 国分寺線;車返線 | 4 | 6 | [way 36957677](https://www.openstreetmap.org/way/36957677) |
| 東京 | 66 kV | 城山線・GLP相模原線 | 4 | 1 | [way 1220965557](https://www.openstreetmap.org/way/1220965557) |
| 東京 | 66 kV | 塩浜南線 | 2 | 4 | [way 202490124](https://www.openstreetmap.org/way/202490124) |
| 東京 | 66 kV | 境八王子線;貝取線 | 4 | 5 | [way 1381611979](https://www.openstreetmap.org/way/1381611979) |
| 東京 | 66 kV | 多摩橋線 | 2 | 4 | [way 111139190](https://www.openstreetmap.org/way/111139190) |
| 東京 | 66 kV | 大-勝 線 | 2 | 5 | [way 202013050](https://www.openstreetmap.org/way/202013050) |
| 東京 | 66 kV | 大みか線 | 2 | 4 | [way 600773666](https://www.openstreetmap.org/way/600773666) |
| 東京 | 66 kV | 大和線;高倉線 | 4 | 3 | [way 184149513](https://www.openstreetmap.org/way/184149513) |
| 東京 | 66 kV | 大子線 | 2 | 3 | [way 1035281081](https://www.openstreetmap.org/way/1035281081) |
| 東京 | 66 kV | 大子線 | 2 | 3 | [way 1078135583](https://www.openstreetmap.org/way/1078135583) |
| 東京 | 66 kV | 大砂線 | 2 | 4 | [way 1074397767](https://www.openstreetmap.org/way/1074397767) |
| 東京 | 66 kV | 大総線 | 2 | 4 | [way 1083086232](https://www.openstreetmap.org/way/1083086232) |
| 東京 | 66 kV | 大谷原線 | 2 | 4 | [way 641619510](https://www.openstreetmap.org/way/641619510) |
| 東京 | 66 kV | 大類線 | 2 | 4 | [way 172576703](https://www.openstreetmap.org/way/172576703) |
| 東京 | 66 kV | 天野変電所~立花二丁目変電所線 / 大仁線 | 2 | 1 | [way 203113716](https://www.openstreetmap.org/way/203113716) |
| 東京 | 66 kV | 奈良線 | 2 | 3 | [way 147429649](https://www.openstreetmap.org/way/147429649) |
| 東京 | 66 kV | 学園中線 | 2 | 3 | [way 905109895](https://www.openstreetmap.org/way/905109895) |
| 東京 | 66 kV | 宇宙研線 | 2 | 3 | [way 1389275061](https://www.openstreetmap.org/way/1389275061) |
| 東京 | 66 kV | 宇都宮変電所~馬場通変電所線 | 2 | 4 | [way 1154899763](https://www.openstreetmap.org/way/1154899763) |
| 東京 | 66 kV | 守谷線 | 2 | 4 | [way 202589899](https://www.openstreetmap.org/way/202589899) |
| 東京 | 66 kV | 安食線 | 2 | 4 | [way 1081992141](https://www.openstreetmap.org/way/1081992141) |
| 東京 | 66 kV | 宝永工業線 | 2 | 3 | [way 1061379122](https://www.openstreetmap.org/way/1061379122) |
| 東京 | 66 kV | 宮原線 | 2 | 4 | [way 849100114](https://www.openstreetmap.org/way/849100114) |
| 東京 | 66 kV | 富士ファイバーグラス線 | 2 | 4 | [way 1061369360](https://www.openstreetmap.org/way/1061369360) |
| 東京 | 66 kV | 富池線 | 2 | 4 | [way 104706934](https://www.openstreetmap.org/way/104706934) |
| 東京 | 66 kV | 富池線 | 2 | 4 | [way 104706934](https://www.openstreetmap.org/way/104706934) |
| 東京 | 66 kV | 小北線 / 南古河線 | 4 | 2 | [way 1086581776](https://www.openstreetmap.org/way/1086581776) |
| 東京 | 66 kV | 小北線 / 間々田線 | 4 | 2 | [way 1086574979](https://www.openstreetmap.org/way/1086574979) |
| 東京 | 66 kV | 小北線 / 間々田線 | 4 | 2 | [way 1086574979](https://www.openstreetmap.org/way/1086574979) |
| 東京 | 66 kV | 小松川線 / 一之江線 | 4 | 2 | [way 1139076631](https://www.openstreetmap.org/way/1139076631) |
| 東京 | 66 kV | 小松横倉線 | 2 | 4 | [way 1065387052](https://www.openstreetmap.org/way/1065387052) |
| 東京 | 66 kV | 小比企線 | 2 | 3 | [way 192161240](https://www.openstreetmap.org/way/192161240) |
| 東京 | 66 kV | 山方線 | 2 | 3 | [way 1139110316](https://www.openstreetmap.org/way/1139110316) |
| 東京 | 66 kV | 岩波線 | 2 | 3 | [way 1205952756](https://www.openstreetmap.org/way/1205952756) |
| 東京 | 66 kV | 川世線;千南線 | 4 | 2 | [way 36962359](https://www.openstreetmap.org/way/36962359) |
| 東京 | 66 kV | 川世線;千南線 | 4 | 2 | [way 47366032](https://www.openstreetmap.org/way/47366032) |
| 東京 | 66 kV | 川茂線 | 1 | 2 | [way 1088486710](https://www.openstreetmap.org/way/1088486710) |
| 東京 | 66 kV | 常陸太田線 | 1 | 2 | [way 762291169](https://www.openstreetmap.org/way/762291169) |
| 東京 | 66 kV | 影森線 | 1 | 2 | [way 519643057](https://www.openstreetmap.org/way/519643057) |
| 東京 | 66 kV | 愛鷹線 | 4 | 1 | [way 154140782](https://www.openstreetmap.org/way/154140782) |
| 東京 | 66 kV | 愛鷹線 | 4 | 1 | [way 154140782](https://www.openstreetmap.org/way/154140782) |
| 東京 | 66 kV | 愛鷹線 | 4 | 1 | [way 154140782](https://www.openstreetmap.org/way/154140782) |
| 東京 | 66 kV | 愛鷹線 | 4 | 1 | [way 154140782](https://www.openstreetmap.org/way/154140782) |
| 東京 | 66 kV | 我孫子線 | 2 | 6 | [way 1141927423](https://www.openstreetmap.org/way/1141927423) |
| 東京 | 66 kV | 拝島線 | 2 | 3 | [way 130285005](https://www.openstreetmap.org/way/130285005) |
| 東京 | 66 kV | 新座線 / 狭山線 / 脇田線 | 6 | 2 | [way 159503131](https://www.openstreetmap.org/way/159503131) |
| 東京 | 66 kV | 新治線 / 鉾田線 / 高浜線 | 6 | 1 | [way 1150585334](https://www.openstreetmap.org/way/1150585334) |
| 東京 | 66 kV | 新都市鉄道柏線 | 2 | 4 | [way 1141927432](https://www.openstreetmap.org/way/1141927432) |
| 東京 | 66 kV | 日本ペイント線 | 2 | 4 | [way 1132104909](https://www.openstreetmap.org/way/1132104909) |
| 東京 | 66 kV | 日本酸素小山線 | 2 | 3 | [way 1065387056](https://www.openstreetmap.org/way/1065387056) |
| 東京 | 66 kV | 旭ヶ丘線 / 日高線 | 4 | 2 | [way 152991092](https://www.openstreetmap.org/way/152991092) |
| 東京 | 66 kV | 春日部線;岩白線;鷲宮線 | 6 | 2 | [way 1144989529](https://www.openstreetmap.org/way/1144989529) |
| 東京 | 66 kV | 木下線 / 印西線 | 4 | 1 | [way 891316400](https://www.openstreetmap.org/way/891316400) |
| 東京 | 66 kV | 木下線 / 印西線 | 4 | 1 | [way 1039813495](https://www.openstreetmap.org/way/1039813495) |
| 東京 | 66 kV | 木下線 / 印西線 | 4 | 1 | [way 1039813495](https://www.openstreetmap.org/way/1039813495) |
| 東京 | 66 kV | 木下線 / 印西線 / 千葉新線 | 6 | 4 | [way 891316398](https://www.openstreetmap.org/way/891316398) |
| 東京 | 66 kV | 木下線 / 印西線 / 千葉新線 | 6 | 4 | [way 891316398](https://www.openstreetmap.org/way/891316398) |
| 東京 | 66 kV | 本牧線 / 妙蓮寺線 | 4 | 8 | [way 191502314](https://www.openstreetmap.org/way/191502314) |
| 東京 | 66 kV | 村松線 / 孫目線 | 4 | 2 | [way 1139127272](https://www.openstreetmap.org/way/1139127272) |
| 東京 | 66 kV | 村松線 / 東海線 | 4 | 2 | [way 519316636](https://www.openstreetmap.org/way/519316636) |
| 東京 | 66 kV | 東セロ化学線 | 2 | 4 | [way 1065380200](https://www.openstreetmap.org/way/1065380200) |
| 東京 | 66 kV | 東京中線;川島町線 | 4 | 2 | [way 315425114](https://www.openstreetmap.org/way/315425114) |
| 東京 | 66 kV | 東京電力パワーグリッド 66.0kV線 | 1 | 2 | [way 755443825](https://www.openstreetmap.org/way/755443825) |
| 東京 | 66 kV | 東京電力パワーグリッド 66.0kV線 | 1 | 2 | [way 1136904878](https://www.openstreetmap.org/way/1136904878) |
| 東京 | 66 kV | 東京電力パワーグリッド 66.0kV線 | 2 | 1 | [way 1085227948](https://www.openstreetmap.org/way/1085227948) |
| 東京 | 66 kV | 東京電力パワーグリッド 66.0kV線 | 2 | 3 | [way 154140777](https://www.openstreetmap.org/way/154140777) |
| 東京 | 66 kV | 東京電力パワーグリッド 66.0kV線 | 2 | 4 | [way 1078714433](https://www.openstreetmap.org/way/1078714433) |
| 東京 | 66 kV | 東京電力パワーグリッド 66.0kV線 | 2 | 4 | [way 1084983552](https://www.openstreetmap.org/way/1084983552) |
| 東京 | 66 kV | 東京電力パワーグリッド 66.0kV線 | 4 | 1 | [way 1064411015](https://www.openstreetmap.org/way/1064411015) |
| 東京 | 66 kV | 東北電力ネットワーク 154.0kV線 | 4 | 1 | [way 834618060](https://www.openstreetmap.org/way/834618060) |
| 東京 | 66 kV | 東北電力ネットワーク 66.0kV線 | 2 | 4 | [way 658988161](https://www.openstreetmap.org/way/658988161) |
| 東京 | 66 kV | 東北電力ネットワーク 66.0kV線 | 2 | 4 | [way 658988161](https://www.openstreetmap.org/way/658988161) |
| 東京 | 66 kV | 東千葉外房線 / 千葉大網線 | 4 | 2 | [way 191072903](https://www.openstreetmap.org/way/191072903) |
| 東京 | 66 kV | 東千葉外房線 / 千葉大網線 | 4 | 2 | [way 191072903](https://www.openstreetmap.org/way/191072903) |
| 東京 | 66 kV | 東取手線 | 2 | 4 | [way 202589904](https://www.openstreetmap.org/way/202589904) |
| 東京 | 66 kV | 東太田線/毛里田線 | 4 | 2 | [way 202714078](https://www.openstreetmap.org/way/202714078) |
| 東京 | 66 kV | 東太田線/毛里田線 | 4 | 2 | [way 202714078](https://www.openstreetmap.org/way/202714078) |
| 東京 | 66 kV | 東太田線/藪塚線 | 4 | 1 | [way 519989103](https://www.openstreetmap.org/way/519989103) |
| 東京 | 66 kV | 東富士線;富士岡線 | 6 | 2 | [way 150065040](https://www.openstreetmap.org/way/150065040) |
| 東京 | 66 kV | 東富士線;富士岡線 | 6 | 2 | [way 150065040](https://www.openstreetmap.org/way/150065040) |
| 東京 | 66 kV | 東富士線;富士岡線 | 6 | 2 | [way 150065040](https://www.openstreetmap.org/way/150065040) |
| 東京 | 66 kV | 東富士線;富士岡線 | 6 | 2 | [way 1205952762](https://www.openstreetmap.org/way/1205952762) |
| 東京 | 66 kV | 東武鷲宮線 / 鷲宮線(上尾) | 2 | 1 | [way 1283544000](https://www.openstreetmap.org/way/1283544000) |
| 東京 | 66 kV | 東海小形山線、谷村線 | 4 | 1 | [way 341222389](https://www.openstreetmap.org/way/341222389) |
| 東京 | 66 kV | 東葉高速村上線 | 2 | 4 | [way 1135006763](https://www.openstreetmap.org/way/1135006763) |
| 東京 | 66 kV | 栃山線 / 河宮線 | 4 | 2 | [way 1093731871](https://www.openstreetmap.org/way/1093731871) |
| 東京 | 66 kV | 栃山線 / 河宮線 | 4 | 2 | [way 1093731871](https://www.openstreetmap.org/way/1093731871) |
| 東京 | 66 kV | 栃山線 / 河宮線 | 4 | 2 | [way 1093731871](https://www.openstreetmap.org/way/1093731871) |
| 東京 | 66 kV | 栃山線/河宮線 | 4 | 2 | [way 1093998786](https://www.openstreetmap.org/way/1093998786) |
| 東京 | 66 kV | 栃山線/河宮線 | 4 | 2 | [way 1093999664](https://www.openstreetmap.org/way/1093999664) |
| 東京 | 66 kV | 栃木ビデオ線 | 2 | 4 | [way 199419204](https://www.openstreetmap.org/way/199419204) |
| 東京 | 66 kV | 栃那線 / JR宝積寺線 | 4 | 2 | [way 199402889](https://www.openstreetmap.org/way/199402889) |
| 東京 | 66 kV | 栃那線 / 喜連川線 | 4 | 2 | [way 1148738172](https://www.openstreetmap.org/way/1148738172) |
| 東京 | 66 kV | 栃那線 / 喜連川線 | 4 | 2 | [way 1148738172](https://www.openstreetmap.org/way/1148738172) |
| 東京 | 66 kV | 栃那線 / 喜連川線 | 4 | 2 | [way 1148738172](https://www.openstreetmap.org/way/1148738172) |
| 東京 | 66 kV | 栃那線 / 西那須野線 | 4 | 1 | [way 682558624](https://www.openstreetmap.org/way/682558624) |
| 東京 | 66 kV | 栃那線 / 西那須野線 | 4 | 1 | [way 682558624](https://www.openstreetmap.org/way/682558624) |
| 東京 | 66 kV | 栃那線 / 西那須野線 | 4 | 1 | [way 682558624](https://www.openstreetmap.org/way/682558624) |
| 東京 | 66 kV | 栃那線 / 西那須野線 | 4 | 1 | [way 682558624](https://www.openstreetmap.org/way/682558624) |
| 東京 | 66 kV | 栃那線 / 西那須野線 | 4 | 1 | [way 682558624](https://www.openstreetmap.org/way/682558624) |
| 東京 | 66 kV | 栃那線 / 西那須野線 | 4 | 1 | [way 682558624](https://www.openstreetmap.org/way/682558624) |
| 東京 | 66 kV | 栃那線 / 西那須野線 | 4 | 1 | [way 682558624](https://www.openstreetmap.org/way/682558624) |
| 東京 | 66 kV | 栃那線 / 西那須野線 | 4 | 1 | [way 682558624](https://www.openstreetmap.org/way/682558624) |
| 東京 | 66 kV | 栃那線 / 西那須野線 | 4 | 1 | [way 682558624](https://www.openstreetmap.org/way/682558624) |
| 東京 | 66 kV | 栃那線 / 西那須野線 | 4 | 1 | [way 682558624](https://www.openstreetmap.org/way/682558624) |
| 東京 | 66 kV | 桂町線 | 2 | 4 | [way 752326302](https://www.openstreetmap.org/way/752326302) |
| 東京 | 66 kV | 桐生線 | 2 | 4 | [way 294893578](https://www.openstreetmap.org/way/294893578) |
| 東京 | 66 kV | 桐生線 | 2 | 4 | [way 519964406](https://www.openstreetmap.org/way/519964406) |
| 東京 | 66 kV | 梅沢線 | 2 | 4 | [way 1061925445](https://www.openstreetmap.org/way/1061925445) |
| 東京 | 66 kV | 椿本線 / 高麗川線 | 2 | 1 | [way 891064456](https://www.openstreetmap.org/way/891064456) |
| 東京 | 66 kV | 榛名線 / 榛名線 / 榛名線 / 碓氷線 | 2 | 1 | [way 520108670](https://www.openstreetmap.org/way/520108670) |
| 東京 | 66 kV | 横浜火力北線 / 保土ヶ谷線 | 4 | 2 | [way 111667549](https://www.openstreetmap.org/way/111667549) |
| 東京 | 66 kV | 横浜火力北線 / 保土ヶ谷線 | 4 | 2 | [way 111667549](https://www.openstreetmap.org/way/111667549) |
| 東京 | 66 kV | 横浜火力北線 / 保土ヶ谷線 | 4 | 2 | [way 111667549](https://www.openstreetmap.org/way/111667549) |
| 東京 | 66 kV | 横浜火力北線 / 保土ヶ谷線 | 4 | 2 | [way 111667549](https://www.openstreetmap.org/way/111667549) |
| 東京 | 66 kV | 横浜火力北線 / 妙蓮寺線 | 4 | 2 | [way 1156843259](https://www.openstreetmap.org/way/1156843259) |
| 東京 | 66 kV | 横浜火力南線 / 子安線 | 4 | 2 | [way 127627970](https://www.openstreetmap.org/way/127627970) |
| 東京 | 66 kV | 横瀬線;大和線 | 4 | 3 | [way 152203758](https://www.openstreetmap.org/way/152203758) |
| 東京 | 66 kV | 横瀬線;大和線 | 4 | 3 | [way 152203758](https://www.openstreetmap.org/way/152203758) |
| 東京 | 66 kV | 毛里田線/藪塚線/金山線 | 6 | 2 | [way 168905336](https://www.openstreetmap.org/way/168905336) |
| 東京 | 66 kV | 水道小雀線 | 2 | 6 | [way 171543443](https://www.openstreetmap.org/way/171543443) |
| 東京 | 66 kV | 沼南給水線 | 2 | 3 | [way 1141832655](https://www.openstreetmap.org/way/1141832655) |
| 東京 | 66 kV | 波崎線 / 土合線 | 4 | 6 | [way 485369469](https://www.openstreetmap.org/way/485369469) |
| 東京 | 66 kV | 浦安東線 | 2 | 4 | [way 1137488337](https://www.openstreetmap.org/way/1137488337) |
| 東京 | 66 kV | 海神線 | 2 | 6 | [way 291647557](https://www.openstreetmap.org/way/291647557) |
| 東京 | 66 kV | 港北線 / 平台線 | 4 | 2 | [way 119049775](https://www.openstreetmap.org/way/119049775) |
| 東京 | 66 kV | 港北線 / 鴨志田線 | 4 | 2 | [way 85961906](https://www.openstreetmap.org/way/85961906) |
| 東京 | 66 kV | 港北線;生田線 | 4 | 2 | [way 43046360](https://www.openstreetmap.org/way/43046360) |
| 東京 | 66 kV | 港北線;生田線 | 4 | 2 | [way 43046360](https://www.openstreetmap.org/way/43046360) |
| 東京 | 66 kV | 潮見線 | 2 | 4 | [way 172414446](https://www.openstreetmap.org/way/172414446) |
| 東京 | 66 kV | 熊の木ポンプ線 | 2 | 3 | [way 1150055306](https://www.openstreetmap.org/way/1150055306) |
| 東京 | 66 kV | 牛久線 / 筑波南線 | 2 | 1 | [way 211356727](https://www.openstreetmap.org/way/211356727) |
| 東京 | 66 kV | 生浜線 | 2 | 4 | [way 156332176](https://www.openstreetmap.org/way/156332176) |
| 東京 | 66 kV | 田方線 | 4 | 1 | [way 519448078](https://www.openstreetmap.org/way/519448078) |
| 東京 | 66 kV | 田方線 | 4 | 1 | [way 640531389](https://www.openstreetmap.org/way/640531389) |
| 東京 | 66 kV | 田方線 | 4 | 1 | [way 737747219](https://www.openstreetmap.org/way/737747219) |
| 東京 | 66 kV | 矢場線 | 2 | 3 | [way 1021949672](https://www.openstreetmap.org/way/1021949672) |
| 東京 | 66 kV | 石岡線;岩間線 | 4 | 2 | [way 1150604659](https://www.openstreetmap.org/way/1150604659) |
| 東京 | 66 kV | 石岡線;岩間線 | 4 | 2 | [way 1150604659](https://www.openstreetmap.org/way/1150604659) |
| 東京 | 66 kV | 碓氷線 / 碓氷線 / 碓氷線 | 2 | 1 | [way 177452543](https://www.openstreetmap.org/way/177452543) |
| 東京 | 66 kV | 秋留線 | 2 | 4 | [way 903583918](https://www.openstreetmap.org/way/903583918) |
| 東京 | 66 kV | 秦浜線;中綾線;綾瀬線 | 6 | 2 | [way 162844694](https://www.openstreetmap.org/way/162844694) |
| 東京 | 66 kV | 秩父変電所~昭電秩父変電所線 | 1 | 2 | [way 602937916](https://www.openstreetmap.org/way/602937916) |
| 東京 | 66 kV | 秩父変電所~昭電秩父変電所線 | 1 | 2 | [way 602937916](https://www.openstreetmap.org/way/602937916) |
| 東京 | 66 kV | 秩父太平洋セメント線 | 2 | 4 | [way 1131420206](https://www.openstreetmap.org/way/1131420206) |
| 東京 | 66 kV | 秩父石灰線 | 2 | 4 | [way 1131420219](https://www.openstreetmap.org/way/1131420219) |
| 東京 | 66 kV | 積水武蔵線 | 2 | 4 | [way 133384942](https://www.openstreetmap.org/way/133384942) |
| 東京 | 66 kV | 笹目線 / 新倉線 | 4 | 2 | [way 700128349](https://www.openstreetmap.org/way/700128349) |
| 東京 | 66 kV | 笹目線;和光線 | 4 | 2 | [way 1148427951](https://www.openstreetmap.org/way/1148427951) |
| 東京 | 66 kV | 笹目線;朝霞線 | 4 | 2 | [way 682204510](https://www.openstreetmap.org/way/682204510) |
| 東京 | 66 kV | 笹目線;朝霞線 | 4 | 2 | [way 1148425894](https://www.openstreetmap.org/way/1148425894) |
| 東京 | 66 kV | 筑南線 / 筑館線 | 4 | 2 | [way 1150587604](https://www.openstreetmap.org/way/1150587604) |
| 東京 | 66 kV | 筑波南線 | 2 | 4 | [way 340366827](https://www.openstreetmap.org/way/340366827) |
| 東京 | 66 kV | 箱根町変電所~須雲川変電所線 / 東京電力パワーグリッド 66.0kV線 | 2 | 1 | [way 409754428](https://www.openstreetmap.org/way/409754428) |
| 東京 | 66 kV | 網戸線 | 2 | 3 | [way 151764962](https://www.openstreetmap.org/way/151764962) |
| 東京 | 66 kV | 総社町線 | 2 | 4 | [way 519412833](https://www.openstreetmap.org/way/519412833) |
| 東京 | 66 kV | 練馬線 / 板橋線 | 4 | 6 | [way 132704893](https://www.openstreetmap.org/way/132704893) |
| 東京 | 66 kV | 群馬幹線;キヤノン美里線 | 4 | 2 | [way 887614679](https://www.openstreetmap.org/way/887614679) |
| 東京 | 66 kV | 群馬幹線;坂戸線 | 4 | 2 | [way 884459800](https://www.openstreetmap.org/way/884459800) |
| 東京 | 66 kV | 群馬幹線;脇田線 | 4 | 2 | [way 190932271](https://www.openstreetmap.org/way/190932271) |
| 東京 | 66 kV | 群馬幹線;脇田線 | 4 | 2 | [way 190932271](https://www.openstreetmap.org/way/190932271) |
| 東京 | 66 kV | 群馬幹線;脇田線 | 4 | 2 | [way 190932271](https://www.openstreetmap.org/way/190932271) |
| 東京 | 66 kV | 花王線 | 2 | 4 | [way 1065753046](https://www.openstreetmap.org/way/1065753046) |
| 東京 | 66 kV | 花総線 | 2 | 4 | [way 150740952](https://www.openstreetmap.org/way/150740952) |
| 東京 | 66 kV | 花総線 | 2 | 4 | [way 150740952](https://www.openstreetmap.org/way/150740952) |
| 東京 | 66 kV | 芳賀線 / 氷室線 | 4 | 2 | [way 1138527645](https://www.openstreetmap.org/way/1138527645) |
| 東京 | 66 kV | 芳賀線 / 氷室線 | 4 | 2 | [way 1138527645](https://www.openstreetmap.org/way/1138527645) |
| 東京 | 66 kV | 若松町線;大矢部線 | 4 | 6 | [way 258627962](https://www.openstreetmap.org/way/258627962) |
| 東京 | 66 kV | 草津変電所~大津変電所線 | 2 | 3 | [way 755445896](https://www.openstreetmap.org/way/755445896) |
| 東京 | 66 kV | 菅生線 | 2 | 4 | [way 81646270](https://www.openstreetmap.org/way/81646270) |
| 東京 | 66 kV | 菅谷線 | 3 | 1 | [way 762059409](https://www.openstreetmap.org/way/762059409) |
| 東京 | 66 kV | 菖蒲線 / NHK菖蒲線 | 4 | 2 | [way 1145571327](https://www.openstreetmap.org/way/1145571327) |
| 東京 | 66 kV | 蓮田線 / 大針線 | 4 | 5 | [way 133481853](https://www.openstreetmap.org/way/133481853) |
| 東京 | 66 kV | 蕨線 | 2 | 3 | [way 1036833505](https://www.openstreetmap.org/way/1036833505) |
| 東京 | 66 kV | 蘇我線 | 2 | 4 | [way 315461233](https://www.openstreetmap.org/way/315461233) |
| 東京 | 66 kV | 西厚木線;湘南北線 | 4 | 2 | [way 41912085](https://www.openstreetmap.org/way/41912085) |
| 東京 | 66 kV | 西平山線 | 2 | 3 | [way 891108162](https://www.openstreetmap.org/way/891108162) |
| 東京 | 66 kV | 西武鉄道株式会社 66.0kV線 | 2 | 4 | [way 1131420221](https://www.openstreetmap.org/way/1131420221) |
| 東京 | 66 kV | 西湘線 / ＪＲ東海 66.0kV線 | 4 | 1 | [way 278228877](https://www.openstreetmap.org/way/278228877) |
| 東京 | 66 kV | 西窪線 / 上信線 | 2 | 1 | [way 1085004994](https://www.openstreetmap.org/way/1085004994) |
| 東京 | 66 kV | 谷塚線 | 2 | 4 | [way 195071841](https://www.openstreetmap.org/way/195071841) |
| 東京 | 66 kV | 軽磯線 | 1 | 2 | [way 1086566677](https://www.openstreetmap.org/way/1086566677) |
| 東京 | 66 kV | 那須ニコン線 | 2 | 4 | [way 1072889518](https://www.openstreetmap.org/way/1072889518) |
| 東京 | 66 kV | 長沼線;由木線 | 4 | 2 | [way 37276775](https://www.openstreetmap.org/way/37276775) |
| 東京 | 66 kV | 長浦変電所~中袖変電所線 | 2 | 3 | [way 1059871161](https://www.openstreetmap.org/way/1059871161) |
| 東京 | 66 kV | 阿武隈線 / 大子線 | 4 | 2 | [way 1150638423](https://www.openstreetmap.org/way/1150638423) |
| 東京 | 66 kV | 青柳環線 | 2 | 4 | [way 1059871175](https://www.openstreetmap.org/way/1059871175) |
| 東京 | 66 kV | 飯山線 | 2 | 3 | [way 41925986](https://www.openstreetmap.org/way/41925986) |
| 東京 | 66 kV | 飯山線 | 2 | 4 | [way 161450370](https://www.openstreetmap.org/way/161450370) |
| 東京 | 66 kV | 高浜線 / 神立線 | 4 | 2 | [way 210868164](https://www.openstreetmap.org/way/210868164) |
| 東京 | 66 kV | 高浜線 / 神立線 | 4 | 2 | [way 210868164](https://www.openstreetmap.org/way/210868164) |
| 東京 | 66 kV | 高浜線 / 神立線 | 4 | 2 | [way 761506920](https://www.openstreetmap.org/way/761506920) |
| 東京 | 66 kV | 高浜線 / 神立線 | 4 | 2 | [way 761506920](https://www.openstreetmap.org/way/761506920) |
| 東京 | 66 kV | 高浜線 / 神立線 | 4 | 2 | [way 761506920](https://www.openstreetmap.org/way/761506920) |
| 東京 | 66 kV | 鬼怒川線 | 2 | 4 | [way 308574177](https://www.openstreetmap.org/way/308574177) |
| 東京 | 66 kV | 鹿島南共発線 / 東深芝線 | 4 | 2 | [way 210729109](https://www.openstreetmap.org/way/210729109) |
| 東京 | 66 kV | 鹿島線 / 船津線 | 4 | 2 | [way 340647454](https://www.openstreetmap.org/way/340647454) |
| 東京 | 66 kV | 鹿島線/船津線 | 4 | 2 | [way 340644804](https://www.openstreetmap.org/way/340644804) |
| 東京 | 66 kV | 鹿島西部環線 | 2 | 4 | [way 1082496940](https://www.openstreetmap.org/way/1082496940) |

## 電力会社の公表の回線数との一致（集計だけ）

公表値（`data/reference/circuit_counts.jsonl`、各社の系統情報の公表）は検証にだけ使い、ここには一致の割合だけを書く（線ごとの公表値は載せない。NOTICE・docs/VALIDATION_SOURCES.md）。地図の線の名前と地域で突き合わせた。

| 比べたもの | 比べた線 | 一致 | 一致率 |
|---|---:|---:|---:|
| OSM の回線数 | 2,173 | 1,559 | 72% |
| 推定の回線数（導体数 ÷ 3 など） | 90 | 57 | 63% |
| 正典の回線数 | 3,490 | 2,374 | 68% |

公表値と名前で突き合わせられた地図の線は 3,490 本。名前だけで突き合わせているので、同じ名前で区間によって回線数の違う線（途中で 1 回線になる線など）は、正しくても不一致に数えている。一致率は目安で、どの線が違うかは公表値を見て線ごとに確かめる（その結果も値は載せない）。

