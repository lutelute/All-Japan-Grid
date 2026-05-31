# Technical FAQ — All-Japan-Grid

技術的な「なぜ?」をまとめた Q&A です。モデルの設計判断と限界を率直に説明します。

---

## Q1. 電気的パラメータ (R/X/B) はどこから来ているのか?

**A.** 実測値ではなく、**電圧クラス別の標準参照値から合成**しています。
`config/line_types.yaml` に 500/275/220/187/154/132/110/77/66 kV 各クラスの
`r_ohm_per_km` / `x_ohm_per_km` / `b_s_per_km` / `max_i_ka` / 標準導体が定義され、
線の長さ(ジオメトリから算出)を掛けて pu 値に変換します。出典は OCCTO 広域系統
計画資料・TEPCO/KEPCO 設計標準の標準値です。

- 周波数依存(50 Hz 東 / 60 Hz 西)があるため、サセプタンス `b_s_per_km` →
  pandapower の `c_nf_per_km` への変換は実行時に
  `src/converter/line_parameters.py` が行います。
- MATPOWER 側の pu 変換は `src/matpower/exporter.py` の `_LINE_OHM_KM` が
  同じ電気的前提を共有します。

**含意**: 相対的な merit order やトポロジ的な傾向は妥当ですが、絶対値は
計画レベルの近似です。個別線の運用可否判断には使えません。

---

## Q2. データソースは何か?

**A.** 2 つの公開ソースを使っています:

1. **OpenStreetMap (OSM)** — 送電線・変電所・発電所のジオメトリ。
   Overpass API 経由で取得 (`power=line/substation/plant` 等)。
2. **OCCTO 地域間連系線** — `data/reference/interconnections.yaml`。
   10 エリアをまたぐ連系線(AC / HVDC / FC)を、容量・電圧・両端変換所名つきで定義。

OSM 由来のため、データ欠落・誤接続・電圧未記載が一定数あります。これが
断片化や弱い地域の主因です(Q7 参照)。

---

## Q3. スナップ済みトポロジ・ビルダー (snapped topology builder) とは?

**A.** `examples/build_snapped_topology.py` の `build_network_snapped()` が、
OSM の生ジオメトリから電気的に意味のあるグラフを組み立てます。手順:

1. **頂点グラフ (vertex graph)**: 各線を頂点列に分解。各辺は長さ・電圧・実ルート
   座標を保持。
2. **トレランス・スナップ (tolerance snap)**: 線の頂点を `snap_km`(既定 1.5 km)
   以内の変電所に束ねる。変電所が無い頂点は `vertex_prec`(既定 4 桁 ≒ 11 m)で
   近接頂点同士をジャンクションとして統合。
3. **degree-2 collapse**: degree-2 のジャンクション連鎖を 1 本の枝に潰す
   (実ルート座標は保持して描画に使える)。
4. **keep_stubs**(既定 True): degree-1 の行き止まり(spur / dead-end)枝を残す。
   `False` にすると末端スタブを落とす。

これが旧「最近傍変電所マッチ」方式(大半の線を破棄・直線化)を置き換え、
断片化を大幅に減らしました(`docs/compare.html` 参照)。

---

## Q4. なぜ multi_slack(複数スラック)なのか?

**A.** OSM 由来のネットワークは多くの地域で複数の連結成分に分かれます。
従来は「最大成分以外を全部無効化」していましたが、これは実在の OSM 線を捨てます。
`multi_slack=True`(`examples/run_powerflow_all.py: fix_topology`)では、
**2 バス以上の各成分に独自のスラックバス(ext_grid)を与えてその場で解きます**。

- スラックは成分内の最大発電機を載せたバスを優先。無ければ任意のバス。
- 単一バスのみの成分(線なし)は無効化。

これにより、離島や実在のギャップを**隠さず・架空線を作らず**正直に可視化できます。
`n_components` がその断片化の指標です。

---

## Q5. 無効電力補償 (reactive compensation) は何をしているのか?

**A.** フラットスタート(V=1 pu, θ=0)での無効電力不均衡が NR の発散を招くため、
**シャント補償**を加えています (`src/matpower/exporter.py: _add_shunt_compensation`,
潮流側は `n_shunt_comp` として集計)。

- 各 PQ バスの「フラットスタート無効注入」`Q_flat = imag(ΣYbus[i,j])` を評価。
- `Q_flat > 0`(長距離 EHV 線の容量性余剰)→ リアクトル(BS<0)。
- `Q_flat < 0`(変圧器主体の誘導性不足)→ **キャパシタ(容量性シャント, BS>0)**。
- `alpha=0.9` で 90% だけ補償し、10% 残してヤコビアンの特異化を回避。

疎な地域(北海道など)では補償後も無効電力が不足し、低 vm_min が残ります。

---

## Q6. MATPOWER エクスポートには 2 つの経路がある?

**A.** はい。`src/matpower/exporter.py: build_matpower_case()` は 2 通り:

1. **snapped 経路**(推奨): `build_matpower_case(network=net)` に
   `build_network_snapped(region)` の `GridNetwork` を渡す。地域単位の最新トポロジ
   から BUS/BRANCH/GEN/GENCOST を生成。
2. **legacy 経路**(既定, 約 2189 バス): GeoJSON 由来の dynamics ネットワーク
   (`[500,275,154,110,77,66] kV`)から構築。北海道は HVDC 連系のため既定で分離。
   公開マップの「全国基幹 (national_backbone)」概観 (psdat-python NR, 2189 バス)
   はこの粗い別モデルです。

両経路とも **GENCOST(発電コスト表)を生成**するようになり、OPF (`runopf`) 対応に
なりました(以前は plain power flow のみ)。詳細は `docs/MATPOWER_EXPORT_GUIDE.md`。

---

## Q7. なぜ特定の地域が弱い(断片化・低電圧)のか?

**A.** **OSM のデータ被覆の差**がそのまま出ています。四国・北陸・中国などは
OSM の送電網データが疎で、OCCTO の実系統に比べて欠落が多く、結果として連結成分が
多く・末端電圧が低くなります。これは**モデルが事実を歪めず正直に欠落を反映している
証拠**であり、合成で埋めて見栄えを良くする方針は採っていません(同一陸塊 5 km 以内の
ギャップ補完のみ例外)。

---

## Q8. 50/60 Hz 分割と同期島 (synchronous islands) はどう扱っている?

**A.** 日本は単一の同期系統では**ありません**。`examples/build_national_snapped.py`
の `ISLANDS` 定義に基づき、同期 AC 島は次の 4 つです:

| 島 (island) | 構成エリア | 周波数 |
|-------------|-----------|--------|
| `hokkaido` | 北海道(単独) | 50 Hz |
| `east` | 東北 + 東京 | 50 Hz |
| `west` | 中部 + 北陸 + 関西 + 中国 + 四国 + 九州 | 60 Hz |
| `okinawa` | 沖縄(単独) | 60 Hz |

島内はエリア間 AC 連系線(OCCTO `ic_002`, `ic_004..009`)で同期結合されています。
島**間**は非同期リンクで、潮流の同期計算からは分離して扱います:

- **HVDC**: 北本連系線 (`ic_001`, 北海道↔東北, 250 kV / 900 MW)。
- **FC (周波数変換)**: 東京中部間連系設備 (`ic_003`, 50↔60 Hz 境界, 2100 MW)。

これら非同期リンクは AC 線として解くと角度が発散するため、`build_island_networks()`
が `async_links` として別途返します。沖縄は完全に孤立した島です。

---

## Q9. 「収束 OK」なら信用してよいか?

**A.** いいえ。NR の収束フラグは「数値的に解が見つかった」だけを意味し、
**物理的妥当性は別問題**です。`docs/js/powerflow.js` の `pfValidityWarnings` が、
断片化・低電圧 (<0.80 pu)・過負荷 (>100%)・位相角 ±180° 超過を検知して赤い警告
バナーを出します。`docs/WHAT_TO_CHECK.md` の手順で必ず併読してください。
