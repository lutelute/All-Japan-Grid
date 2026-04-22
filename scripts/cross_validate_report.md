# Cross-Validation Report: AGJ ↔ JRP
Generated: 2026-04-22 20:57

## 1. Substations 整合性チェック

| Region | AGJ count | JRP count | 一致 |
|--------|-----------|-----------|------|
| hokkaido | 471 | 471 | ✓ |
| tohoku | 901 | 901 | ✓ |
| tokyo | 1726 | 1726 | ✓ |
| chubu | 1163 | 1163 | ✓ |
| hokuriku | 267 | 267 | ✓ |
| kansai | 902 | 902 | ✓ |
| chugoku | 531 | 531 | ✓ |
| shikoku | 258 | 258 | ✓ |
| kyushu | 684 | 684 | ✓ |
| okinawa | 59 | 59 | ✓ |

一致: 10 リージョン / 不一致: 0 リージョン

## 2. Lines 整合性チェック

| Region | AGJ count | JRP count | 一致 |
|--------|-----------|-----------|------|
| hokkaido | 4136 | 4136 | ✓ |
| tohoku | 6628 | 6628 | ✓ |
| tokyo | 8295 | 8295 | ✓ |
| chubu | 6589 | 6589 | ✓ |
| hokuriku | 2296 | 2296 | ✓ |
| kansai | 3994 | 3994 | ✓ |
| chugoku | 3176 | 3176 | ✓ |
| shikoku | 1532 | 1532 | ✓ |
| kyushu | 3314 | 3314 | ✓ |
| okinawa | 117 | 117 | ✓ |

一致: 10 リージョン / 不一致: 0 リージョン

## 3. Plants fuel 不一致詳細

| Region | AGJ plants | JRP plants_lite | fuel不一致(一意名) | mw→output補完済 |
|--------|-----------|-----------------|-------------------|----------------|
| hokkaido | 436 | 436 | 4 | 78 |
| tohoku | 1311 | 1311 | 2 | 151 |
| tokyo | 7207 | 7207 | 4 | 226 |
| chubu | 3792 | 3792 | 1 | 153 |
| hokuriku | 432 | 432 | 1 | 37 |
| kansai | 1518 | 1518 | 2 | 56 |
| chugoku | 1173 | 1173 | 6 | 52 |
| shikoku | 688 | 688 | 2 | 29 |
| kyushu | 2549 | 2549 | 0 | 0 |
| okinawa | 32 | 32 | 0 | 0 |

**mw→output 補完済み合計: 782 件**

### fuel 不一致リスト (一意名のみ。同名重複はスキップ)

  - [hokkaido] **Ветродизельная электростанция в с. Головнино**: AGJ=`wind` / JRP=`wind;diesel`
  - [hokkaido] **苫小牧発電所**: AGJ=`gas` / JRP=`gas;oil`
  - [hokkaido] **Nippon Paper Shiraoi Mill Power Station**: AGJ=`https://www.nipponpapergroup.com/about/branch/factory/npi/shiraoi/` / JRP=`https://www.nipponpapergroup.com/about/branch/factory/npi/shiraoi/;https://www.gem.wiki/Shiraoi_Mill_Co-fired_Biomass_power_station`
  - [hokkaido] **Nippon Paper Industries Power Generation**: AGJ=`coal` / JRP=`https://www.nipponpapergroup.com/news/year/2018/news180907004219.html;https://www.gem.wiki/Kushiro_Mill_Npi_power_station`
  - [tohoku] **広野火力発電所**: AGJ=`oil` / JRP=`oil;coal`
  - [tohoku] **石巻雲雀野発電所**: AGJ=`coal` / JRP=`coal;biomass`
  - [tokyo] **君津共同発電所**: AGJ=`gas` / JRP=`gas;coal`
  - [tokyo] **鹿島共同発電所**: AGJ=`coal` / JRP=`coal;gas;oil`
  - [tokyo] **ENEOS根岸製油所**: AGJ=`gas` / JRP=`https://www.power-technology.com/marketdata/negishi-refinery-power-station-japan/`
  - [tokyo] **KSC Chiba IPP**: AGJ=`coal` / JRP=`https://global.kawasaki.com/en/energy/solutions/energy_plants/ccpp.html`
  - [chubu] **富山新港火力発電所**: AGJ=`coal` / JRP=`coal;oil`
  - [hokuriku] **富山新港火力発電所**: AGJ=`coal` / JRP=`coal;oil`
  - [kansai] **Wakayama Gas power plant**: AGJ=`gas` / JRP=`gas;oil`
  - [kansai] **T-Point (Tomoni) Power Plant**: AGJ=`https://www.gem.wiki/t-point_2_power_station` / JRP=`https://www.gem.wiki/T-Point_2_power_station;https://power.mhi.com/products/gasturbines/technology/validate`
  - [chugoku] **下関火力発電所**: AGJ=`coal` / JRP=`coal;oil`
  - [chugoku] **戸畑共同火力発電所**: AGJ=`gas` / JRP=`gas;coal`
  - [chugoku] **水島火力発電所**: AGJ=`gas` / JRP=`gas;coal`
  - [chugoku] **坂出火力発電所**: AGJ=`gas` / JRP=`gas;oil`
  - [chugoku] **Marusumi Paper Ohe Mill**: AGJ=`biomass` / JRP=`https://www.marusumi.co.jp/sp/en/about/gaiyo.html;https://www.gem.wiki/Marusumi_Paper_Ohe_Mill_power_station`
  - [chugoku] **Tokuyama Shunan Power East Power Plant**: AGJ=`biomass` / JRP=`biomass;coal`
  - [shikoku] **坂出火力発電所**: AGJ=`gas` / JRP=`gas;oil`
  - [shikoku] **Marusumi Paper Ohe Mill**: AGJ=`biomass` / JRP=`https://www.marusumi.co.jp/sp/en/about/gaiyo.html;https://www.gem.wiki/Marusumi_Paper_Ohe_Mill_power_station`

### 同名重複によりスキップ (上位10件)

  - [kyushu] 都城市発電所: 205 件
  - [kyushu] 霧島市発電所: 132 件
  - [kyushu] 曽於市発電所: 124 件
  - [tokyo] 鉾田市発電所: 112 件
  - [chubu] 大町市発電所: 81 件
  - [hokuriku] 大町市発電所: 81 件
  - [chubu] 中津川市発電所: 77 件
  - [chubu] 舞阪町舞阪浜松市発電所: 70 件
  - [tokyo] 高崎市発電所: 56 件
  - [chubu] 高崎市発電所: 56 件

## 4. 欠落データ確認 (restore後)

全リージョンのplantsが揃っています ✓

