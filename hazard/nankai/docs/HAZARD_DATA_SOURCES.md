# 南海トラフ巨大地震 ハザードデータの出典と取得記録

作成: 2026-09-13 / 対象: `hazard/nankai/`
目的: 南海トラフ巨大地震 (M9 クラス) の **メッシュ震度場** と、GMPE フォールバック用の
**表層地盤増幅率メッシュ** を、ログイン不要で入手できる源泉から取得し、取得可否・形式・
規約・変換手順を記録する。

## 0. 結論 (要約)

| 項目 | 結果 |
|---|---|
| 震度メッシュ (M9 クラス) | **取得済**。J-SHIS 条件付超過確率地図データ `C-V3-ANNKI-AN177` = 「南海トラフ沿いで発生する大地震（最大クラス）」Mw 9.1、250m メッシュ 3,704,994 行、列 `AVE_SI`(地表計測震度の平均値) と震度 5弱/5強/6弱/6強 以上となる確率 |
| PGV | **無し**。C データには最大速度列が無い (AVE_SI と超過確率のみ) |
| 地盤増幅率メッシュ | **取得済**。J-SHIS 表層地盤 `Z-V4-JAPAN-AMP-VS400_M250` (2020年版・全国 6,224,800 行) → 西日本 bbox で 3,462,062 行 |
| 内閣府 (G空間情報センター) 震度分布・浸水深 | **未取得 (ユーザ登録+ログイン必須)**。24 データセットの一覧を §4 に記録 |
| 派生ファイル | `data/derived/jshis_nankai_intensity.parquet` (57 MB), `data/derived/jshis_amp_vs400.parquet` (13 MB), `data/derived/jshis_an177_fault_points.parquet` (92 KB) |

いずれも `hazard/nankai/.gitignore` (`data/external/`, `data/derived/jshis_*.parquet`) により **git 追跡外**。
再取得・再生成は §5 の手順で行う。

---

## 1. 試した URL と結果 (時系列)

| # | URL | 結果 |
|---|---|---|
| 1 | https://www.j-shis.bosai.go.jp/map/JSHIS2/download.html?lang=jp | ExtJS 製の SPA。HTML 自体にはリンク無し。`download-all.js` (packer 圧縮) を展開してファイル命名ロジックを特定 (§2.2) |
| 2 | https://www.j-shis.bosai.go.jp/download | ダウンロード可能データの一覧ページ。「条件付超過確率 地図データ CSV/シェープ」「表層地盤 CSV/シェープ/KML」の存在を確認。規約 PDF へのリンク (`/map/JSHIS2/data/DOC/DataFileRule/Z-RULES.pdf`) |
| 3 | https://www.j-shis.bosai.go.jp/api-list | Web API 一覧 (§3)。条件付超過確率・想定地震のメッシュ API は掲載無し |
| 4 | https://www.j-shis.bosai.go.jp/tag/api | API 関連記事タグ。新情報なし |
| 5 | https://www.j-shis.bosai.go.jp/faq-nankai-trough-shindo | FAQ「南海トラフの地震の震度分布を表示できますか」→ 条件付超過確率タブ → 計測震度の期待値 → 海溝型地震震源断層 → 南海トラフ → 最大クラス。J-SHIS Map のレイヤ名 `C-V3-AN177-MAP-CASE1-AVE_SI2` (epoch Y2020) |
| 6 | https://www.j-shis.bosai.go.jp/faq-sesm-subduction | 「想定地震地図 (S-データ)」は主要活断層帯のみで **海溝型は無い** → S- 系列に南海トラフは存在しない |
| 7 | https://www.j-shis.bosai.go.jp/nankai2020-pattern-and-weight | 2020年版の南海トラフ 177 発生パターンと重み。最大クラス(パターン177) = 長期評価対象領域全体を震源域、重み 1/50、残り 176 パターンに 49/50 を配分 |
| 8 | https://www.j-shis.bosai.go.jp/cgi-bin/JSHIS2/LteTable.cgi?EPOCH=Y2020&GROUP=PME&DLL=1 | 海溝型震源断層の一覧 XML (198 件)。`AN001`〜`AN176` (Mw 7.6–9.0) と `AN177` 最大クラス Mw 9.1 を確認 |
| 9 | https://www.j-shis.bosai.go.jp/cgi-bin/JSHIS2/hasFile.cgi?FILE=data/C/V3/ANNKI/C-V3-ANNKI-AN177.zip | `{"hasfile":1}` → 実在確認 |
| 10 | **https://www.j-shis.bosai.go.jp/map/JSHIS2/data/C/V3/ANNKI/C-V3-ANNKI-AN177.zip** | **取得 (63,407,090 B, Last-Modified 2021-06-05)** |
| 11 | **https://www.j-shis.bosai.go.jp/map/JSHIS2/data/Z/V4/JAPAN/AMP/Z-V4-JAPAN-AMP-VS400_M250.zip** | **取得 (30,501,271 B, Last-Modified 2022-05-30)** |
| 12 | https://www.j-shis.bosai.go.jp/map/JSHIS2/data/DOC/DataFileRule/A-RULES.pdf | 地震動予測地図データ記述ファイル規約 (全規約合冊, 2023-12) 取得 |
| 13 | https://www.j-shis.bosai.go.jp/map/JSHIS2/data/DOC/DataFileRule/Z-RULES.pdf | 表層地盤データ記述ファイル規約 取得 |
| 14 | https://www.j-shis.bosai.go.jp/map/JSHIS2/data/C/V3/ANNKI/C-V3-ANNKI-AN177-SHAPE.zip | 404 (シェープ版は無い) |
| 15 | https://www.j-shis.bosai.go.jp/agreement , /map/JSHIS2/text/yakkan_main.html | 利用規約・利用約款 (§6) |
| 16 | https://www.j-shis.bosai.go.jp/map/api/sstrct/V4/meshinfo.geojson?position=138.38,34.98&epsg=4326 ほか 3 点 + pshm 1 点 | Web API 動作確認 (§3)。メッシュ座標式の検算に使用 |
| 17 | https://www.geospatial.jp/ckan/api/3/action/package_search?fq=organization:naikakufu-01&rows=100 | 内閣府データセット 24 件のメタデータ (§4)。実データは要ログイン |
| 18 | https://www.jishin.go.jp/main/chousa/20_yosokuchizu/yosokuchizu2020_{gaiyo2,tk_2,tk_3}.pdf | 全国地震動予測地図2020年版 概要・技術報告書 (手法の裏取り, §2.4) |

ログインや API キーは **一切不要** だった (J-SHIS はサーバ側 `hasFile.cgi` で存在確認するだけの静的配信)。
サーバは低速で、63 MB に約 8 分、30 MB に約 5 分かかった。

---

## 2. J-SHIS 条件付超過確率地図データ `C-V3-ANNKI-AN177`

### 2.1 シナリオ定義

| 項目 | 内容 |
|---|---|
| 名称 | 南海トラフ沿いで発生する大地震（最大クラス） / Large Earthquakes along the Nankai Trough (Maximum class) |
| 地震コード / 発生パターンコード | `PLE_ANNKI` / `AN177` (発生パターンは AN001〜AN177) |
| マグニチュード | **Mw 9.1** (FAULT ファイルの構成地震ブロック: `1,-9.1, 20.0,5690, 80` = 構成地震 1、Mw 9.1(負値は Mw の意)、代表深さ 20 km、構成点 5,690、震源域番号 80) |
| 震源域 | 地震調査委員会「南海トラフ沿いで発生する大地震の確率論的津波評価 (2020)」の長期評価対象領域全体 (日向灘〜駿河湾)。構成点の範囲: 経度 131.5–138.6、緯度 31.1–35.5、深さ 0–39.6 km |
| 位置づけ | 2020年版全国地震動予測地図で新設。確率論的津波評価では対象外だった最大クラスに重み 1/50 を与え、他 176 パターンに 49/50 を配分 (J-SHIS 記事 #7) |
| 計算主体 | 地震調査研究推進本部 地震調査委員会「全国地震動予測地図 2020年版」の計算を防災科学技術研究所 (NIED) が実施し J-SHIS で公開 |
| バージョン | `V3` (断層パラメータ・計算条件が変わると +1。2020年版以降の南海トラフは V3) |
| ケース | `CASE1` のみ (zip 内に CASE2 以降は無い) |
| ファイル作成日 | MAP: 2021-05-26 / FAULT: 2021-03-26 (ヘッダ `# DATE`) |

**この地図が示すもの**: 「想定した地震が発生した場合に予測される震度の平均値の分布」(J-SHIS 使用方法・条件付超過確率)。
すなわち **発生を条件とした期待値**であり、発生確率は掛かっていない。内閣府 (2012) の「基本ケース／陸側ケース」等の
決定論的震度分布 (§4) とは別物である点に注意。

### 2.2 ファイル命名規則とダウンロード URL の組み立て (download-all.js から特定)

```
root = https://www.j-shis.bosai.go.jp/map/JSHIS2/data
filename = C-{version}-ANNKI-{pattern}.{zip|tar.gz}          # 南海トラフ 2020年版以降
path     = root + '/' + filename を '-' で分割した末尾以外を '/' で連結
例: C-V3-ANNKI-AN177.zip → .../data/C/V3/ANNKI/C-V3-ANNKI-AN177.zip
表層地盤: Z-V4-JAPAN-AMP-VS400_M250.zip → .../data/Z/V4/JAPAN/AMP/Z-V4-JAPAN-AMP-VS400_M250.zip
1次メッシュ別: Z-V4-JAPAN-AMP-VS400_M250-5236.zip → .../data/Z/V4/JAPAN/AMP/VS400_M250/…
存在確認: https://www.j-shis.bosai.go.jp/cgi-bin/JSHIS2/hasFile.cgi?FILE=data/C/V3/ANNKI/C-V3-ANNKI-AN177.zip
```

- 他パターン (例 `AN081` Mw 9.0、`AN001` Mw 8.7) も同じテンプレートで存在確認済 (`hasfile:1`)。
- zip 版は Shift_JIS、tar.gz 版は UTF-8 (J-SHIS 使用方法)。本件の CSV は ASCII のみで差は無い。
- `_EN` 付き (英語版 CSV) は表示言語 en のときに選ばれる。

### 2.3 zip の中身と列定義 (A-RULES.pdf「条件付超過確率地図データ記述ファイル規約」)

```
AN177/MAP/C-V3-ANNKI-AN177-MAP-CASE1.csv     266,759,671 B  3,705,001 行 (コメント 7 行 + データ 3,704,994 行)
AN177/FAULT/C-V3-ANNKI-AN177-FAULT-CASE1.csv     250,448 B  5,696 行
```

MAP (CRLF, `#` コメント行の後にデータ):

| 列 | 列名 | 書式 | 意味 |
|---|---|---|---|
| 1 | `CODE` | %11c | 250m メッシュコード (本ファイルは 10 桁。規約上は末尾 `N` 付き 11 桁の版もある) |
| 2 | `AVE_SI` | %7.5e | **地表の計測震度 (平均値)** |
| 3 | `I45_PS` | %7.5e | 震度 5弱 以上となる確率 (発生を条件) |
| 4 | `I50_PS` | %7.5e | 震度 5強 以上となる確率 |
| 5 | `I55_PS` | %7.5e | 震度 6弱 以上となる確率 |
| 6 | `I60_PS` | %7.5e | 震度 6強 以上となる確率 |

FAULT (南海トラフ用の非矩形断層形状; 規約 p.20–22):

```
PLE_ANNKI,AN177,   1                      # ファイル情報: 地震コード, 発生パターン, 構成地震数
   1,-9.1, 20.0,5690,  80                 # 構成地震: 通番, M(負=Mw), 代表深さ km, 構成点数, 震源域番号
   1,131.678, 31.622,131.677, 31.620, 25.9 # 構成点: 通番, 経度(日本測地系), 緯度(日本測地系), 経度(世界測地系), 緯度(世界測地系), 深さ km
```

### 2.4 地震動の評価手法 (出典: 全国地震動予測地図2020年版 技術報告書 解説編 p.33–34, 概要)

- 海溝型地震の震度分布は **簡便法** (距離減衰式による)。「地震規模（マグニチュード）と距離（例えば断層最短距離等）を与え、距離減衰式により地震動の最大振幅を計算する」「距離減衰式により工学的基盤の地震動最大振幅を計算した上で表層地盤増幅率を乗じて地表の最大振幅と震度を計算」。
- ばらつき: 「距離減衰式による地震動強さは対数正規分布に従ってばらつくと仮定」「±3σ を超える値の確率をゼロ」(解説編)。`I45_PS` 等はこのばらつきを含めた超過確率、`AVE_SI` はその平均値。
- 表層地盤増幅率は §2.6 の `Z-V4` (2020年版・微地形区分見直し、関東は浅部・深部統合地盤構造モデル) と同じ世代 (概要 p.5「増幅率の計算に用いる浅部地盤構造モデルの改良」)。
- 具体的な距離減衰式 (最大速度) と最大速度→計測震度の換算式は本調査で一次資料からは確認できなかったため、ここでは特定しない。必要なら技術報告書「作成条件・計算結果編」(`yosokuchizu2020_jk.pdf`, 12 MB) を参照。

### 2.5 派生ファイル `data/derived/jshis_nankai_intensity.parquet`

| 列 | 型 | 内容 |
|---|---|---|
| `meshcode` | int64 | 10 桁 250m メッシュコード |
| `lat`, `lon` | float64 | メッシュ**中心** (度, 世界測地系) |
| `jma_intensity` | float32 | `AVE_SI` 計測震度の平均値 |
| `p_ge_5lower`, `p_ge_5upper`, `p_ge_6lower`, `p_ge_6upper` | float32 | `I45_PS`〜`I60_PS` |
| `scenario_id` | category | `JSHIS_C-V3-ANNKI-AN177-CASE1` |
| `source_file` | category | `C-V3-ANNKI-AN177.zip!AN177/MAP/C-V3-ANNKI-AN177-MAP-CASE1.csv` |

- 行数 3,704,994、範囲 緯度 28.46–38.23、経度 128.35–141.04 (計算対象メッシュのみ。範囲外は行が無い = 震度情報なし)。
- `pgv_cm_s` 列は **無い** (源泉に最大速度が無いため。全 NULL 列は作らない)。
- 計測震度→震度階級 (JMA): 5弱 4.5≤I<5.0, 5強 5.0≤I<5.5, 6弱 5.5≤I<6.0, 6強 6.0≤I<6.5, 7 6.5≤I の区分で数えた分布:

| 階級 | 2 | 3 | 4 | 5弱 | 5強 | 6弱 | 6強 | 7 |
|---|---|---|---|---|---|---|---|---|
| メッシュ数 | 1 | 148,367 | 901,567 | 1,031,810 | 1,050,238 | 464,586 | 104,388 | 4,037 |

- 検算 (メッシュコード→座標を Web API のポリゴンと照合、誤差 <1e-5 度):

| 地点 | meshcode | 中心 (lat, lon) | AVE_SI | P(≥6弱) | P(≥6強) | 増幅率 ARV | AVS30 |
|---|---|---|---|---|---|---|---|
| 静岡 (34.98,138.38) | 5238337032 | 34.98021, 138.37969 | 6.28 | 1.00 | 0.86 | 1.29 | 297.6 |
| 高知 (33.56,133.53) | 5033247212 | 33.55937, 133.52969 | 6.31 | 1.00 | 0.88 | 1.75 | 207.5 |
| 大阪 (34.69,135.50) | 5235042033 | 34.69062, 135.50156 | 5.58 | 0.60 | 0.11 | 1.44 | 260.2 |

`data/derived/jshis_an177_fault_points.parquet` (5,690 点; `sub_event, magnitude_mw, depth_rep_km, region_no, point_no, lon, lat, depth_km, scenario_id`) は FAULT ファイルの世界測地系座標を抜いたもの。GMPE フォールバックで断層最短距離を出すのに使える。

### 2.6 表層地盤 `Z-V4-JAPAN-AMP-VS400_M250` と派生 `data/derived/jshis_amp_vs400.parquet`

zip 内: `Z-V4-JAPAN-AMP-VS400_M250/Z-V4-JAPAN-AMP-VS400_M250.csv` (219,912,617 B, `# DATE = 2022-05-30`, 6,224,800 行)。
ヘッダ `# CODE, JCODE, AVS, ARV, AVS_EB, AVS_REF`。V3 規約 (Z-RULES.pdf) の 4 列に 2020年版で 2 列追加。

| 列 | 意味 (Z-RULES.pdf + J-SHIS「2020年版の表層地盤データ」) |
|---|---|
| `CODE` | 250m メッシュコード (世界測地系) |
| `JCODE` | 微地形分類コード 1–24 (若松・松岡 2020; 0 = 海域・欠測) |
| `AVS` | 表層 30m の平均 S 波速度 AVS30 (m/s) |
| `ARV` | **工学的基盤 (Vs=400 m/s) から地表に至る最大速度の増幅率** (藤本・翠川 2006 系の関係式) |
| `AVS_EB` | 「詳細法工学的基盤面 30m の平均 S 波速度」— 関東 7 都県の浅部・深部統合地盤構造モデル使用メッシュのみ、他は `-` |
| `AVS_REF` | 「表層 30m の平均 S 波速度出典分類番号」 0 = 微地形分類由来、1 = 統合地盤構造モデル由来 (本データでは 1 の行 494,957 = `AVS_EB` 非欠測行数と一致) |

派生 parquet (bbox 経度 129–142、緯度 30–37.5 かつ `JCODE>0 & ARV>0`):

| 列 | 型 | 内容 |
|---|---|---|
| `meshcode` | int64 | 250m メッシュコード |
| `lat`, `lon` | float64 | メッシュ中心 |
| `amp` | float32 | `ARV` 増幅率 (0.50–3.84) |
| `avs30` | float32 | AVS30 m/s |
| `jcode` | int8 | 微地形分類コード |
| `avs_eb` | float32 | `AVS_EB` (NaN = 非対象) |
| `avs_ref` | int8 | `AVS_REF` |

行数: bbox 内 3,603,252 → 有効 3,462,062 (13 MB)。震度メッシュ 3,704,994 行のうち 3,462,062 行が増幅率と結合可能 (残りは海域等で増幅率無し)。

引用時の義務 (利用約款 第1条): 表層地盤データを転載・引用する場合は Z-RULES.pdf の参考文献を明記する:
若松・松岡 (2013) 地震工学会誌 18; Wakamatsu & Matsuoka (2013) J. Disaster Res. 8(5); 松岡・若松 (2008) 産総研 H20PRO-936; 藤本・翠川 (2006) 日本地震工学会論文集 6(1)。2020年版は微地形分類が若松・松岡 (2020) に更新されている。

### 2.7 メッシュコード体系 (JIS X 0410 地域メッシュ + 1/2・1/4 分割 = 10 桁)

| 桁 | 内容 | 大きさ |
|---|---|---|
| 1–2 `pp` | 1次メッシュ緯度部 = floor(緯度×1.5) | 40′ (≈ 80 km) |
| 3–4 `uu` | 1次メッシュ経度部 = floor(経度) − 100 | 1° |
| 5 `q` / 6 `v` | 2次 (1次を 8×8 分割) 緯度/経度番号 0–7 | 5′ × 7.5′ (≈ 10 km) |
| 7 `r` / 8 `w` | 3次 (2次を 10×10 分割) 緯度/経度番号 0–9 | 30″ × 45″ (≈ 1 km) |
| 9 `d1` | 1/2 メッシュ (2×2) 1=南西 2=南東 3=北西 4=北東 | 15″ × 22.5″ (≈ 500 m) |
| 10 `d2` | 1/4 メッシュ (2×2) 同上 | 7.5″ × 11.25″ (≈ 250 m) |

南西隅:
```
lat_sw = pp/1.5 + q/12 + r/120 + ((d1-1)//2)/240 + ((d2-1)//2)/480
lon_sw = 100 + uu + v/8 + w/80 + ((d1-1)%2)/160 + ((d2-1)%2)/320
中心 = (lat_sw + 1/960, lon_sw + 1/640)
```
例: `5238337032` → 南西隅 (34.97917, 138.37813)、中心 (34.98021, 138.37969)。Web API の返すポリゴン `[138.37813,34.97917]–[138.38125,34.98125]` と一致。
実装: `data/external/jshis/convert_jshis_to_parquet.py::meshcode_to_center` (numpy ベクトル化)。

---

## 3. J-SHIS Web API (参考・今回の主経路ではない)

一覧: https://www.j-shis.bosai.go.jp/api-list (ログイン/キー不要)。ベース `https://www.j-shis.bosai.go.jp/map/api/`。

| API | パターン | 用途 |
|---|---|---|
| 確率論的地震動予測地図 メッシュ情報 | `pshm/{Y2020}/{AVR|MAX}/{TTL_MTTL…}/meshinfo.geojson?position=lon,lat&epsg=4326` | 30/50 年超過確率・SI/BV/SV |
| 表層地盤 メッシュ情報 | `sstrct/V4/meshinfo.geojson?position=lon,lat&epsg=4326` | JCODE, AVS, **ARV**, AVS_EB, AVS_REF (増幅率の点取得) |
| 深部地盤 | `dstrct/*/*/meshinfo.*` | |
| 地震・断層検索 | `fltsearch?meshcode=…`, `fltsearch?areacode=…`, `meshsearch?…` | |

**条件付超過確率 (C-) や想定地震 (S-) のメッシュ値を返す API は一覧に無い** (J-SHIS Map のタイル/内部 CGI のみ)。
点取得のサンプル (2026-09-13 実行, sstrct V4):

```json
{"meshcode":"5238337032","JNAME":"扇状地","JCODE":"11","AVS":"297.6","ARV":"1.29","AVS_EB":"-","AVS_REF":"0",
 "geometry":[[138.37813,34.97917],[138.37813,34.98125],[138.38125,34.98125],[138.38125,34.97917]]}
{"meshcode":"5033247212","JNAME":"三角州・海岸低地","JCODE":"15","AVS":"207.5","ARV":"1.75"}   // 高知
{"meshcode":"5235042033","JNAME":"砂州・砂礫州","JCODE":"16","AVS":"260.2","ARV":"1.44"}     // 大阪
```

---

## 4. 内閣府 南海トラフの巨大地震モデル検討会 データ (G空間情報センター) — 未取得

- 組織ページ: https://www.geospatial.jp/ckan/dataset?organization=naikakufu-01 (24 データセット、CKAN API `package_search?fq=organization:naikakufu-01` で一覧取得)
- **取得条件**: 各データセット説明に「データのダウンロードは、ユーザ登録の後、ログイン状態で行ってください」。ライセンスは「独自利用規約」(各データセット同梱 `license.pdf`)。
- 内容: 内閣府「南海トラフの巨大地震モデル検討会」(2012 第二次報告) の震度分布・浸水域等に係るデータ。**震度は決定論 (ケース別)** で、J-SHIS の期待値地図とは性格が異なる。

震度分布 (強震断層モデル):

| ID (dataset slug) | タイトル | 内容 | 形式 |
|---|---|---|---|
| `1201` | 強震断層モデル(1)データセットA | 工学的基盤以浅の表層地盤モデル (AVS30・震度増分)、**計測震度**、液状化指標 PL 値、沈下量 | PDF, XYZ, ZIP |
| `1202` | 強震断層モデル(2)データセットB | 深い地盤構造モデル (修正一次モデル) の物性値 | PDF, ZIP |
| `1203` | 強震断層モデル(3)強震断層パラメータ | 小断層の緯度経度・深さ・走向・傾斜・すべり角等 | PDF, ZIP |
| `1204` | 強震断層モデル(4)工学的基盤における強震動波形 | Vs=350–700 m/s 相当層の加速度波形。**基本ケース 45–56 / 陸側ケース 45–…** (26 リソース) | PDF, TXT, ZIP |

津波 (津波断層モデル):

| ID | タイトル | 内容 |
|---|---|---|
| `1205` / `1206` / `1207` | 津波断層モデル(5)地形 / (6)粗度 / (7)堤防データ | 第01–09・14–17 系 (平面直角座標系別) |
| `120801`…`120809`, `120814`…`120817` | 津波断層モデル(8)初期水位データ_NN系_0810-99 | 津波断層ケース 01–11 のコサイスミック上下変動 (系ごとに 1 データセット、計 13) |
| `1209` | 津波断層モデル(9)津波断層パラメータ (H240829ver) | ケース 01–11 の小断層パラメータ |
| `1210` | 津波断層モデル(10)設定満潮位・海岸における津波高・津波到達時間・波形 | ケース 01–11 (堤防破堤) の波形・海岸メッシュ |
| `1211` | 津波断層モデル(11)津波浸水深データ(ケース1) | **陸域の浸水深**。ケース 01–11 × 堤防破堤 / 堤防03分破壊 |
| `dataset` (slug がそのまま) | 津波断層モデル(12)陸域における津波浸水深データ(4パターン)(再計算)(令和元年6月) | ケース 01, 03, 04, 05 (堤防破堤) を堤防・潮位データ更新で再計算 |

(データセット URL は `https://www.geospatial.jp/ckan/dataset/{ID}`。個々のリソース URL は `.../resource/{uuid}/download/NN.zip` 形式で、ログイン無しでは取得できない。)

代替 (ログイン不要) としては国土数値情報 A40 津波浸水想定 (都道府県公表値) が別担当で取得済 (`data/.gitignore` コメント参照)。

---

## 5. 再取得・再生成手順

```bash
cd hazard/nankai/data/external/jshis
B=https://www.j-shis.bosai.go.jp/map/JSHIS2
curl -L -A "Mozilla/5.0" -o C-V3-ANNKI-AN177.zip            $B/data/C/V3/ANNKI/C-V3-ANNKI-AN177.zip
curl -L -A "Mozilla/5.0" -o Z-V4-JAPAN-AMP-VS400_M250.zip   $B/data/Z/V4/JAPAN/AMP/Z-V4-JAPAN-AMP-VS400_M250.zip
curl -L -A "Mozilla/5.0" -o A-RULES.pdf $B/data/DOC/DataFileRule/A-RULES.pdf
curl -L -A "Mozilla/5.0" -o Z-RULES.pdf $B/data/DOC/DataFileRule/Z-RULES.pdf
python3 convert_jshis_to_parquet.py            # --intensity / --fault / --amp で個別実行可 (全体 ~10 s)
```

SHA-256 (2026-09-13 取得分):

```
9c17f3fa3f93ec9b29a943d7075df2b698d065766b407990e5b5a3535d6e7d64  C-V3-ANNKI-AN177.zip
292a652f168bc2ba77c1afba367b1b14674cae310823d788a3f6d759feb1d28c  Z-V4-JAPAN-AMP-VS400_M250.zip
5d77100d56ef381b21c8acbe9f3fe6444298a092501d3a820ce852cfb5f8589b  A-RULES.pdf
8122ae308812cdfeb2201f4e83ddb761fc77e679d8e3b4f2724e8e877698db56  Z-RULES.pdf
```

`convert_jshis_to_parquet.py` は `data/external/` 配下にあるため .gitignore で追跡外になる。追跡したければ `hazard/nankai/build/` 等へ移す。

---

## 6. ライセンス・利用条件 (J-SHIS)

- 利用規約: https://www.j-shis.bosai.go.jp/agreement
- 地震動予測地図データの利用約款 (ダウンロード画面の初期表示): https://www.j-shis.bosai.go.jp/map/JSHIS2/text/yakkan_main.html
- 要点 (約款):
  - 第1条 転載・引用した場合は **その旨を明記**。表層地盤データは Z-RULES.pdf 記載の参考文献を明記。学術論文・報告書等の印刷物は NIED J-SHIS 担当へコピー送付 (予稿集含む)。
  - 第3条 編集・加工した成果物の頒布・譲渡・貸与は自由。成果物の**販売**は要問い合わせ (申請が必要な場合あり)。**データをそのまま複製 (形式変換を含む) して第三者に頒布・譲渡することは禁止** → 本リポジトリでも zip / 素の parquet を公開配布しないこと (git 追跡外にしている理由の一つ)。
  - 第2条 250m メッシュ内は一様。パラメータ推定精度には限界があり誤差を含む。
  - 第5条 免責 (地震調査研究推進本部・防災科研は一切の責任を負わない)。
- 出典表記例: 「防災科学技術研究所 地震ハザードステーション J-SHIS『全国地震動予測地図2020年版』条件付超過確率地図データ (C-V3-ANNKI-AN177) および表層地盤データ (Z-V4-JAPAN-AMP-VS400_M250) を加工して作成」

---

## 7. 注意点 (caveat)

1. **AVE_SI は発生条件付きの平均値**であり、ばらつき (対数正規, ±3σ 打ち切り) を平均した値。個々の実現 (シナリオ震度場) が欲しい場合は `p_ge_*` の分位や `p_ge_6lower` 等を閾値に使うか、GMPE フォールバックでサンプリングする。
2. **PGV は無い**。速度が必要なら (a) 簡便法の再現 (断層最短距離 × 距離減衰式 × `amp`)、(b) 確率論的地図 API (`pshm`) の `T50_P02_SV` 等 (ただし全地震統合値) のいずれか。
3. J-SHIS の最大クラス (Mw 9.1、長期評価領域全体) と内閣府 2012 の強震断層モデル (Mw 9.0、基本/東側/西側/陸側ケース等) は **震源モデルが異なる**。両者を混ぜて比較する場合は明記する。
4. 海域・一部離島は震度メッシュが無い (行が存在しない)。増幅率も `JCODE=0` を落としたため海域は無い。結合は `meshcode` 完全一致で行うこと (座標の丸めで結合しない)。
5. 250m メッシュのため、変電所などの点資産への割り当てはメッシュ中心最近傍ではなく **メッシュコード計算 (§2.7 の逆変換)** で行うのが正確。
6. 3,704,994 行 × float32 の parquet で 57 MB。GitHub 50 MB 制限を超えるので追跡外のまま。必要なら bbox や `jma_intensity>=4.5` で間引いた副本を作る。
