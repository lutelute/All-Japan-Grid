# 改善台帳 — モデル別セッション記録

セッション単位の改善記録。**モデル名は記録がある場合のみ記載**（推測で埋めない）。
KPIは `ajgrid validate --topology --all --solve` の計測値
（ベースライン: `docs/reports/topology_baseline_*.json`）を根拠とする。
2026-06-10以降のエントリはモデル名の記録を必須とする。

---

## 2026-06-19 — **Claude Opus 4.8** — DB7 統合検索＋地名ズームを本番化・3新JSの ?v 更新（152）

①②③(149-151)の本番反映に伴い、保全されていた DB7 検索ドラフト(オーナー「DB7も一緒に本番化」)を検証して本番化。

- **?v 更新**: `index.html` の grid_map(31→32)/powerflow(33→34)/sld(31→32) を更新し、①②③の新JSを GitHub Pages で即時配信(従来は ?v 据置でキャッシュ期限待ちだった)。
- **DB7 本番化**: `docs/js/grid_search.js`(445行・統合検索: (A)変電所/送電線/発電所の `_display_name` オフライン部分一致→候補クリックで map.flyTo+一時マーカー、(B)Nominatim 地名ジオコーディング=Enter/デバウンス・規約配慮で静かにフォールバック)・`docs/css/style.css`(`.gs-*`)・`index.html`(検索UI+script)。系統図サイドバー上部に検索ボックスを挿入(既存の一覧/zoom と独立 DOM)。
- **検証**: 隔離headless(:8901 read-only・MCP不使用)。検索ボックス存在・`searchDb('嶺南')`→「嶺南変電所 500kV」等10件・全タブ巡回(map→pf:national_backbone→sld→map)で **console error 0**・①属性(subs `_attr_source`)と検索 `_display_name` 両立・**PASS**。
- **不変**: okinawa/" 2"複製は非commit保全。①の属性結合で検索候補のメタ(kv/region)も充実。

## 2026-06-19 — **Claude Opus 4.8** — DB③ SLD(単線結線図)を正典 built+powerflow_full 由来へ（151）

[評価148](2026-06-19_opus4.8_pages_db_canon_audit.md)の③(SLDが旧縮約取り残し)を是正。オーナー選択「全電圧(フィルタ制御)」。これで①②③着手対象すべて完了。

- **問題**: SLDタブ(`sld.js`=force-directed グラフ)が `powerflow/sld_data.json`(psdat縮約由来)を読み、per-region/"all"/national_backbone 正典化後も旧世代に取り残されていた。
- **是正**: `scripts/gen_sld_from_built.py` 新設。正典トポロジ `built/all.json`(17,333ノード)から bus/branch を生成。loading は `powerflow_full` line の端点突合で付与(実潮流率・hit 14,161/18,619=76%)、変圧器枝 1,925(同一地点異電圧)、gen 72(generators 座標突合)。中間電圧(220/187/132kV)は表示帯 `tier`(500/275/154/110/77/66/不明0)へ丸めて付与(実 kv は tooltip 用に `bus.kv` 保持・grid_map 同様)。出力 `powerflow_full/sld_data.json`(4.0MB・全電圧収録)。
- **`sld.js`**: fetch を正典へ・フィルタ/色/半径/Y を `tier` ベースに(tooltip は実 kv)・**force-sim repulsion を O(N²)→spatial-grid 近似(実効 O(N))** に置換し全電圧(下位帯ON で数千ノード)でも耐えるよう最適化。vm/Pd は built に無く非表示(既存方針)。
- **不変**: index.html ?v 据置(後方互換・DB7保全)。旧 `powerflow/sld_data.json` は残置(⑤掃除で後送り)。national_zonal/発電所(④)は別課題。
- **検証**: 隔離headless(:8900 read-only・MCP不使用)。SLDタブ→force-sim 3.5s 走行・console error 0・`powerflow_full/sld_data.json` のみ fetch・旧 fetch 0・bus tier 有り・canvas 描画・**PASS**。

## 2026-06-19 — **Claude Opus 4.8** — DB② 全国基幹概観を正典(powerflow_full)由来へ・旧2189縮約を追放（150）

[評価148](2026-06-19_opus4.8_pages_db_canon_audit.md)の②(潮流タブ3世代同居)を是正。オーナー選択「正典由来へ再生成」。

- **問題**: 潮流タブで per-region/"all" は正典(17,333バス)なのに "national_backbone"(全国基幹500/275概観)だけ psdat 縮約 **2,189バス**(`powerflow/all_ac_buses`+`routes_*`+`backbone_ring`)を表示。選択で正典度がサイレント後退していた。
- **是正(再solveなし)**: `scripts/gen_national_overview_from_full.py` 新設。全規模AC(powerflow_full)の **既存結果** を集計して電圧帯別 geojson(`national_overview_{500..66}kv.geojson`+`_buses.geojson`)を生成。各 line への kv 付与=端点→bus vn_kv 99% + built edge 名 100%(nokv=0)。`powerflow.js` の `ROUTE_TIERS` 参照先を `powerflow/routes_*`→`powerflow_full/national_overview_*` に差替(tier UI=下位電圧 on-demand は温存)、`loading`→`loading_pct`、bus ソースを正典へ。リング(backbone_ring=縮約特有)は正典に対応物が無く廃止(連系線は各線 tie フラグで識別)。
- **結果**: national_backbone が正典17,333バス由来に。buses 4,213(≥154kV)・実 Vm range[0.74,1.13]pu(縮約でない実AC)・500/275/154 eager + 110/77/66 on-demand。**旧2189縮約の3世代同居を解消**(per-region/"all"/national_backbone すべて正典)。national_zonal(同期島)は有用ゆえ残置。
- **不変**: index.html ?v 据置(後方互換=旧JS×残存旧データ/新JS×新データ両立・DB7ドラフト保全)。旧 `powerflow/{all_ac_buses,routes_*,backbone_ring}` は当面残置(⑤掃除で後送り・sld/other_freq が `powerflow/` を併用中)。
- **検証**: 隔離headless(:8899 read-only・MCP不使用)。national_backbone 選択→`national_overview_*` のみ fetch・旧縮約 fetch 0・console error 0・パネル「正典 full 由来」・**PASS**。

## 2026-06-19 — **Claude Opus 4.8** — DB① 変電所属性をDB正典(D層)へ一元化・詳細カバー 8%→56%（149）

[評価148](2026-06-19_opus4.8_pages_db_canon_audit.md)で同定した本丸①(属性の正がDB外)を是正。オーナー選択の着手対象①。

- **問題の定量化**: 系統図の変電所クリック属性は `grid_map.js` が別fetch(`substations.geojson`)+4桁座標突合で引いていたが、built再スナップで座標がずれ **798/8994=8%しか当たっていなかった**(92%は属性popup空)。評価148の「約2,000件欠落」は過小で、実測は約8,200件。
- **是正(D層一元化)**: `export_map_tiers_from_built.py` に**名前優先+座標(2km妥当性チェック=誤接続防止)**の属性結合を追加。built sub に旧`substations.geojson`の属性(operator/category_ja/voltage_source 等15列)を結合し `subs_*.geojson`(D層生成物)へ焼き込み。`_attr_source`∈{coord,name}で出所明示・供給元不在は焼かない(捏造なし)。**カバー 8%→56%(5,051/8,994 = coord 798 + name 4,253)**。
- **`grid_map.js`**: クリックハンドラを feature内属性直読み(`p._attr_source?p:null`)に変更、`loadEnrichedData` の `substations.geojson` 別fetchを廃止(=二重fetch・8%座標接着の解消)。CSVは全属性の `substations.geojson` を明示直読みで残置。
- **不変性**: lines/regions.json は不変(line側未変更・件数 old=new 一致)。`index.html` ?v 据置(後方互換=旧JS×新データ/新JS×旧データ両立ゆえ安全・DB7ドラフト保全)。残44%は供給元(旧6,962件)に不在=本来④発電所/P03権威データで埋める後送り課題。
- **検証**: 隔離headless(:8898 read-only・MCP不使用)。console error 0・`buildSubPopup` が operator/category 描画・`substations.geojson` のマップ再fetch無し・**PASS**。

## 2026-06-19 — **Claude Opus 4.8** — Pages各タブの「DB正典忠実度」監査（148・評価のみ）

オーナー「DBを統合した。それを正とした時に、今のpagesのツールへの違和感があちこちある。評価してほしい」。`docs/data/built/`(6-18・17,333ノード/変電所8,994)を唯一の正典とする規範に対し、各タブが実際に `fetch()` するソースの出自を読取専用で監査した。**是正は未着手**（評価レポートの正本化のみ）。

- **判断レポート**: [2026-06-19_opus4.8_pages_db_canon_audit.md](2026-06-19_opus4.8_pages_db_canon_audit.md)
- **核心**: 表示の正は built に移ったが、**属性とモデルの正はまだDB外の旧世代ファイルに残る**二層構造が違和感の根。エディタ・Ybus は正典追従済み、負債は系統図の属性・潮流タブ・SLD に集中。
- **同定した違和感（一次根拠つき）**: ①属性の正がDB外（built変電所は4フィールドのみ／運用属性は旧`substations.geojson` 6,962件 `grid_map.js:692`、built表示8,994件と座標一致で接着＝約2,000件は詳細欠落） ②潮流タブが3世代同居（`full`正/`national_backbone`旧縮約2,189/`national_zonal`別モデル、選択で正典度がサイレント後退 `powerflow.js:288,573,858`） ③SLDが旧縮約由来 `sld.js:185` ④発電所がbuilt外（`plants_*.geojson` 4-23・19,138件） ⑤死蔵5ディレクトリ（`powerflow_snapped`+`legacy×4`） ⑥`MODEL_VERSION` 形骸化（92eb0f6/6-16/dirty）。
- **オーナー選択（着手対象）**: ①属性をDB正典へ（本丸）・②潮流タブ正典統一・③SLD built由来化。④⑤⑥は今回見送り。
- **不変条件**: 派生レポートのみ（基底extract不変・捏造禁止・スコアカード不可触・okinawa supplement非commit）。

## 2026-06-18 — **Claude Opus 4.8** — 全機能の監査と是正(捏造除去・正典化を全タブへ横展開)（147）

オーナー「すべての機能をどんどん改善するように続けて」。Ybus正化(146)で得た「正典=docs/data/built・近似/捏造を疑う」をサブエージェント3並列で全タブ監査し、発見順に是正。

- **監査(3並列・読取専用)**: 系統図/エリア・潮流/比較・単線図/横断 を監査 → Ybusと同型(捏造/正典非由来)の欠陥を多数発見。
- **捏造・誇張除去**(`67e2068`): 潮流タブ全国パネルが存在しない`summary["all"]`→ハードコード定数(2189バス/20%/V[0.78,1.18]/148%)を表示 → 実データ`all_ac_buses`集計(14,486バス・Vm[0.61,1.07])に置換。単線図が全バスvm=1.0(flat未計算)を「Vm x.xxxx pu」と計算結果のように表示 → 除去。系統図のOSM多値タグ連結ミス(770006.6kV等)が偽500kV級で既定ビューに混入 → >1100kVを不明扱い+「不明(タグ異常)」表示。誇張文言(電力会社管轄断定・10/10収束)を正直化。
- **hokkaido NaN是正**(`2b857c4`): 潮流geojson(hokkaido_{ac,dc}_{buses,lines})の`NaN`(JSON仕様外→parse失敗)を`null`化 → 全国概要9/10→**10/10**。未収束バス(758/799)を「健全緑/低電圧紫」でなく灰「未収束」と正直表示(vmColor/vmRadius/busPopup)。
- **単線図の縮約モデル明示**(`e88daff`)・**比較タブのBEFORE線欠落注記**(`95adf80`)。
- **系統図/エリアの正典化+線名両立(オーナー選択「上流修正」)**(`c7d636d`): 最も見られるタブが2ヶ月stale・正典非由来(東京変電所1726 vs 正典4215)。`build_editor_data.py`で built_view 既付与のOSM線名を保持するよう上流修正 → built全再生成(構造は現行と**完全一致**=nodes/edges順序・stats不変、+線名+date)。新設 `scripts/export_map_tiers_from_built.py` で built→tier geojson を grid_map.js のフィールド契約厳密一致で生成。結果: 東京変電所2232(正典一致)・**線名100%復活**(道南幹線等)・**異常電圧0**(源泉解消)。座標[lon,lat]・JSON妥当。
- **検証**: 各是正を隔離headless(localhost・read-only・MCP不使用)で実描画確認、全タブ**コンソールerror0**・undefined無し。built再生成は名前+date以外committedと厳密一致を照合。不変条件維持(捏造禁止・物理接続=真・基底extract不変・スコアカード不可触・okinawa supplement非commit/99維持)。
- **残(低優先)**: 単線図の縮約PFモデル(2189バス)を正典から再生成する経路(深い・別系統)、N-1図の暗テーマ再生成、v1.1.0バナーの範囲。

## 2026-06-18 — **Claude Opus 4.8** — Ybus可視化をDB更新モデル正化＋エリア間連系線を明示（146・重要な正化）

オーナー指摘「YbusはDB更新した内容になっている?」「エリア間結合もあるしちゃんと変電所で繋がっている?」。**検証の結果、私のYbus図(145周回)は誤っていた**ことが判明し、正化した。

- **欠陥の特定(正直な記録)**: 145までのYbus図は `build_ybus_sparsity`(生GeoJSONを**最近傍マッチで近似**=記憶上「大半の線を捨てる旧手法」)で生成し、**DB更新済み建造モデル `docs/data/built/`(2026-06-17)を使っていなかった**。さらに national は `block_diag`=**エリア間連系線ゼロ**だった。オーナーの懸念は妥当だった。
- **正典モデルの検証**: `docs/data/built/all.json` を精査 → 17,333ノード(うち**変電所8,994**)/19,031エッジ、**全エッジが実ノードに100%突合**(unmatched=0)、**エリア間連系線829本が実在**(北海道-東北6・中部-東京103・中部-北陸226・中国-四国129…と現実的)。「真の物理接続」はDBモデルに正しく入っていた。
- **`scripts/gen_ybus_from_db.py`(新設・正典化)**: Ybusタブの全アセット(地域別10/大元/Spy/ギャラリー/組立アニメ)を**DBモデルの実接続グラフ**から生成。national は地域順に並べ **intra(地域色)/inter(連系線=赤#ff3b6b)を分離**して描画 → spy/national/組立アニメで**赤=エリア間連系線が非対角に明示**。地域別は `{region}.json` から(東京=4,215ノード/変電所2,232/結線4,216=エディタ統計と一致)。
- **index.html**: stats.json新スキーマ(`n_sub`追加・`n_offdiag`廃止)に統計表示/compare表を更新(「変電所」列追加)。大元/Spy/組立/ギャラリー各キャプションを「DB更新モデル・赤=エリア間連系線」に正直化(旧「連系線は実モデルで考慮」=誤を撤回)。`_national`サマリ(ノード/変電所/連系線数)をstats.jsonに同梱しUIが動的表示。
- **回帰防止**: 誤ソースの `gen_ybus_interactive.py` `gen_ybus_app_dark.py` を削除(同一出力先に最近傍近似を書き戻す危険を排除)。`gen_ybus_white.py`/`gen_ybus_national.py` は論文/README用(白・`papers/figs`)として明記分離。
- **検証**: 隔離headless(localhost・read-only・MCP不使用)で全5モード描画・統計に**undefined無し・compare表健全・コンソールerror0**。不変条件維持(物理接続=真・捏造禁止・基底extract不変・スコアカード不可触・okinawa supplement非commit)。

## 2026-06-17〜18 — **Claude Opus 4.8** — :8088とPagesの統合・kv表示バグ・分析タブ暗テーマ統一・Ybus視覚改善ループ（145）

オーナー「元のページ(:8088の/)はどこ?統合してきていい・DBも統合できた」「あちこち1000除算バグ」「全タブ検証した?」「テーマというより機能」「テーマは統一していい・タブの方法を目で見てループでどんどん改善」「ybusが並んでいくさまを見たい・図を貼り付けてるだけでよくわからない」。144(UI大改修merge)後の仕上げ＝**正を1つに**の継続と視覚改善ループ。

- **メインページ統合**: `src/server/app.py` が `docs/` を `/`(html=True)にマウント → :8088の `/` が正典Pagesアプリを配信。`/editor`(templates・実backend)+`/api/*` は温存。旧2タブ地図 `templates/index.html` は撤去(docs/index.html に一本化)。`@app.get("/")` index ルート削除。
- **kv /1000 表示バグ**: built モデルの `node.kv`/`edge.kv` は既にkV単位(例66.0)なのに表示側が `/1000`(V扱い)→ 0.066kV と誤表示。editor.html ポップアップ+ shim issue本文を修正(`/1000`除去・`kv>=1000`時のみ換算)。snapPts内部の `/1000`↔`*1000` は往復(内部・表示非関与)ゆえ据置。
- **分析タブのテーマ統一**(`041ec7f`): Ybus/潮流/単線図/エリアの白基調UIを系統図と同じ暗テーマ(`#0f1419`/`#5dade2`)に統一(`style.css` !important上書き・`.ybus-mode-btn`/`#ybus-stats-panel`/`.pf-controls`/`.btn-primary`/`.result-item`)。
- **Ybus視覚改善ループ**(オーナー「目で見てループで」を実践・3周):
  - **R1 動的既定化**(`37290c4`): 「▶全国アニメ」モード追加=暗テーマの全国ツアー`ybus_tour.gif`を**既定**に。静的貼付→動的「並んでいくさま」で理解しやすく。
  - **R2 地域別10枚 暗化+自己説明化**(`24c0e7b`): `gen_ybus_interactive.py`を暗パレット化。**対角(橙=自己)/非対角(シアン=結合)を色分け+凡例**で「何の点か図中で分かる」に。`ybus-img`背景 `#fff`→`#0f1419`(白フラッシュ防止)。統計不変(同一トポロジ)。
  - **R3 大元/Spy/ギャラリー 暗化**(`334a513`): 旧白PNG3枚は清潔な生成元が現行scriptsに無く、`gen_ybus_app_dark.py`を新設し**地域別と同一の `build_ybus_sparsity`+`block_diag`**で一貫生成。**指標を地域別モードと同一定義(nnz=結線数, density=結線/バス²)に統一**=沖縄1.523%等がモード間で一致(整合バグ解消)。大元キャプションを「連系線の弱対角要素が見える」→**ブロック対角の実態に正直化**(連系線は動的ツアー/実モデルで考慮)。→ 全5モード暗統一。
  - **R4 「並んでいく」組立アニメ**: 既定の `ybus_tour.gif` は冒頭から完成形を表示しパンするだけで「組み上がる」が見えないと判明(目視)。`gen_ybus_app_dark.py --build` で**地域ブロックが対角に1つずつ出現して全国Ybusが組み上がる**フレーム群を生成→ffmpeg で `ybus_build.gif`(720px/97KB/15.6s)。既定アニメをこれに差替(ボタン「▶組立アニメ」・北海道→沖縄の順に積上・各地域色+橙対角)。オーナー要望「ybusが並んでいくさま」の直球回答。tour gif は生成器ごと保持(非参照・無害)。
- **検証**: 全変更を隔離headless(localhost専用・read-only・dialog dismiss・**MCP Playwright不使用**)で実描画確認、各モード img読込済・**コンソールerror 0**。Python変更は viz生成器+app.py のみ(モデル/テスト非依存)。不変条件維持(物理接続=真・捏造禁止・基底extract不変・スコアカード不可触・okinawa supplement非commit)。push済(`334a513`)。

## 2026-06-17 — **Claude Opus 4.8** — UI大改修 提案版(編集+表示) を別URLで公開・反復中（144）

オーナー「大改修・UIを何周もかけて・煩雑にせずスタイリッシュに・提案htmlがあれば報告」。本番(editor.html/index.html/style.css/templates)は**無改変**のまま、提案版を別URLで公開して合意形成する方式(編集タブ=`editor.proposal.html`、系統図=`index.proposal.html`+`style.proposal.css`)。生成器=`/tmp/make_proposal.py`(editor.html→editor.proposal.html へ panel/CSS刷新+機能注入を再適用・JSロジック温存)。全機能 隔離headless で検証・**コンソールerror0**・本番ドリフトテスト維持。

- **接続編集 提案版**(`editor.proposal.html`・全ID/ハンドラ温存): ①パネルHTML+CSS刷新(カード化/モード3×2アイコングリッド/凡例・issue折りたたみ/固定ステータスバー/モデル状態カード)。②**🔒編集ロック(閲覧)**トグル(setMode/postEditガード・既定OFF=本番挙動不変)。③**📍地点メモ→GitHub issue**(任意地点にピン+メモ・localStorage・編集と別系統の注釈・バックエンド不要)。④**変電所を明示**(白縁青=変電所/小=鉄塔分岐)+接続線(水)を既定ON+衛星/OSM maxZoom 19→21。⑤**クリック→単線結線図(SLD draft)**(substation_scope.py方式をbuildモデルから自動導出: 電圧階級ごと母線+引込線+隣接カスケード変圧器、引込先は鉄塔網BFSで接続先変電所名まで解決し回線集約。例: 川尻=154kV+66kV+T154/66。Pages/8088両対応)。
- **データ検証(クリック疑義の解明)**: オーナー「線は本当に変電所に繋がっているのか/点が見えない」→ 東京2232変電所の**96%が次数≥1**(線接続)、川尻=11線が端点座標一致で接続を実証。「見えない」原因=既定で モデル本系統(青)/接続線(水) がOFF だった表示設定 → 既定ONに是正。孤立105件の近接線3件中、日進(8m)は**通過線**で未接続が正しい(捏造しない)。**重要バグ修正**: built の kv は既にkV単位(/1000不要)。
- **系統図(見る)表示UI刷新 提案版**(`index.proposal.html`+`docs/css/style.proposal.css`): 表示(エリア色/発電所/電圧/スコア/地形)の母艦=系統図サイドバーを接続編集提案版と同トーンに上書き(機能/ID/JS不変)。**「見る=系統図 / 編集=接続編集」で分離改修**(オーナー選択)。
- `build_pages_editor.py` に `--template` 追加(任意テンプレ派生)。**→ オーナー「merge」で本番反映済(`b6cd5a4`/`8c85623`)**: 提案版を本番昇格(`templates/editor.html`刷新→docs再生成・iframe?v=8、系統図サイドバー+一覧パネル+凡例を`style.css`に統合?v=32、提案ファイル/生成器撤去)。ドリフトテスト4 passed・本番headless error0・full pytest 1134 passed・:8088も刷新版(shim非混入)。
- **追補(同日)**: README全面改修→**論文図入れすぎ是正**(代表2枚+GIF・著作権配慮で論文詳細図は`papers/`へ・`104a83d`)、**編集風景GIF**(Playwright録画→ffmpeg・接続→切断のslow版・`aed14cc`)、系統図サイドバー完全改修(電圧最上部/レイヤ横並び/オーバーレイ折りたたみ・`569c03d`)。
- **据え置き③ 複母線SLD 実装済(`1961868`)**: `substation_scope.build_sld()` + `app.py GET /api/sld/{region}/{name}`(PNG) + エディタSLDモーダルの「🔬詳細SLD(OSM忠実層)」ボタン。**:8088で複母線/ベイ/カスケード変圧器の正確なSLD**(例 川尻=154/66/6)、Pagesは簡易draft+shim 501案内。build_sld実データ検証・Pages headless error0・pytest 1134 passed。**全タスク消化**。

## 2026-06-17 — **Claude Opus 4.8** — edit/review分離: 候補レビューを専用タブに(統合しすぎない原則)（143）

オーナー指示「アカデミックでは見たいものが違う・**あまり統合しすぎはよくない**・統合しても機能が見える/確認できるならやっていい」+「**editとreviewは明確に分けたい**/ボタンで編集をロックして見れるなら可」。Phase5フル統合で消してしまった「一つずつレビュー」を**見える形で復活**。

- **原則の確定**([[feedback_view_separation]]): 「正を1つに」は**データ/モデルの源泉**に適用するが、**ビュー(見え方)は用途別に保つ**(統合してビューが消えるのは不可)。源泉統合(Pages=:8088派生・台帳142)は維持。
- **`docs/review.html`(新規・閲覧専用)**: A島接続候補(`docs/data/island_candidates.json` 379件)を1件ずつ確認(島=橙/接続先=青/提案線=金・**OSM⇔衛星**で実在確認)。承認/却下/スキップ/◀前・進捗 localStorage 再開(`agj_rev_idx`/`agj_rev_done`)・⚠(電圧階級違い/距離大/地域校正不一致)。**編集パレットを持たない=構造的にedit-lock**(edit/review分離)。色は共有 `editor_core.js`(AGJ_COLORS)。
- **データ統合・ビュー分離**: 承認は接続編集と**同じ下書きストア**(`localStorage agj_edits_{region}`)へ `source=review` で記録 → 接続編集タブで確認・GitHub issue 化。レビューという**活動は別タブ**に分離しつつ、承認の下流(下書き→issue)は1本に統合。
- **タブ配線**: `docs/index.html`「候補レビュー」タブ(iframe遅延 `?v=1`)、`grid_map.js` initTabs・`style.css` フルスクリーン規則に `tab-review` 追加。**`editor.html`/templates は無改変**(ドリフトテスト維持)。隔離headless 3経路(review単体/承認→エディタ下書き統合/タブ埋め込み)PASS・error0。`e09619b`。

## 2026-06-17 — **Claude Opus 4.8** — 全面改修 Phase5 フル統合: Pagesエディタを:8088の正から派生(静的shim方式)（142）

オーナー「Phase5のフル統合を一緒にやろう」。Pages編集タブが:8088から分岐したlossyコピー(見た目/データ/連結性ズレ)だった問題の**最終解決**。確定設計=`docs/OVERHAUL_PLAN.md`「静的shim方式」。

- **正は1つ = `src/server/templates/editor.html`(フル機能の:8088エディタ)。:8088は無改修**(git でテンプレ unchanged を証明=作り込み完全保存)。Pages版は**ビルドで派生**する構成に一本化 → 二度と分岐しない。
- **`docs/js/editor_static_shim.js`(新規)**: backend無し(Pages)で `window.fetch` を上書きし `/api/*` を静的等価へ振替。**肝=レスポンス正規化**: 事前生成 `data/built/{region}.json` は counts を `stats` 内包だがフロントはトップレベルで読む(L274/L358)→ shim が `stats` を展開(これが「全国undefined/無茶苦茶接続」級バグの構造的解消)。per-region生OSMは公開済 `built/{region}.json` から**軽量合成**(変電所リング+回廊線=fit復活・snap点6万・基底extract非静的化)、全国概観は既存tier(`subs/lines_all.geojson`+min_kv)。下書きCRUD=localStorage、verify/adopt=backend専用ゆえDOM非表示、issue=GitHubプレフィルURL(捏造せず人間がGitHubで作成)。`__AGJ_STATIC__=true`。
- **`scripts/build_pages_editor.py`(新規)**: テンプレを copy + 絶対パス(`/js/`)→Pages相対 rewrite + shim を本体inline script直前に inject → `docs/editor.html`(723行=フルエディタ)生成。`docs/data/built/regions_bbox.json`(shim の `/api/regions`=regionAt用・全10地域bbox+island_classマニフェスト)も生成。アンカー不検出で fail-fast(壊れた版を出さない)。`regenerate_all.py` STEPS と `deploy-pages.yml`(再生成step+trigger)に組込=CI が常にテンプレから再生成(drift不能)。
- **検証(隔離headless・localhost専用・read-only・ダイアログdismiss・MCP不使用)**: ①全国 ②地域(tokyo) ③統合経路(index→タブ→iframe `?v=7`) の**3経路すべてPASS・コンソールエラー0**。stats正規化で `main_size:11423/n_island_nodes:2161/成分1096` 正常表示、地域は合成subs2232/lines4670・tokyo中心fit・snap60493、下書きCRUD往復・issue下書き生成 OK。旧 hand-rolled docs/editor.html(420行・review-mode)を置換(候補機能は:8088の `toggleCandidates` が継承)。
- **不変条件のテスト固定** `tests/test_pages_editor_build.py`(4件): shim注入+相対パス化、**docs/editor.html ≡ テンプレ派生(ドリフト禁止)**、テンプレに shim 不混入(無改修原則)、regions_bbox マニフェスト。**full pytest 1134 passed/3 skipped/0 failed**(okinawa supplement退避時)。不変条件維持(物理接続=真・捏造禁止・基底extract不変・スコアカード不可触)。**全面改修 Phase1-5 完全完了**。

## 2026-06-17 — **Claude Opus 4.8** — 全面改修 一気通貫: Phase1(破壊封鎖)/Phase4(出力統一)/Phase5(共有エディタコア)（141）

オーナー「あとは一気通貫で」(残Phase1/4/5)。`docs/OVERHAUL_PLAN.md`。

- **Phase1 破壊enrich封鎖**: `scripts/enrich_*.py`(in-place 6本)+`fix_plant_capacity`/`restore_missing_plants`/`slim_geojson` の**9本**に `__main__` fail-fast ガード(`data/*.geojson` 直書きを拒否し `ajgrid db enrich`=DB-native へ誘導・`AGJ_ALLOW_BASE_WRITE=1` で解除)。削除でなくガード(docs/tests が関数 import=不破壊・91 passed)。**基底extract不変を構造保証**(実行時ガード+`test_db_source_unified` の drift 検知の二重)。
- **Phase4 出力の単一オーケストレーション**: `scripts/regenerate_all.py`(build_editor_data→powerflow→matpower→cim→build_static_site を1コマンド・重い段は `--skip-*`/`--light`)+ `docs/data/MODEL_VERSION.json`(git HEAD刻印=skew可視化)。`deploy-pages.yml` trigger に builder/connectivity/built_view/build_editor_data/regenerate_all を追加。OSM地図4/23 vs built6/16 の7週間skewを「一括再生成+版可視化」で解消。
- **Phase5 共有エディタコア(部分)**: `docs/js/editor_core.js`(`AGJ_COLORS`+`agjNodeColor`=島/本系統の色分けの単一の正)。app.py が `/js`→`docs/js` を mount し **:8088 も Pages も同一物理ファイル**を参照(drift不能)。両 editor.html が採用・**:8088 は値不変=見た目不変**(read-only headless 検証: AGJ_COLORS=#388bfd・error0)。本質的乖離はPhase2/3で解消済。フルDataSource1本化は設計済・deferred(:8088ライブ書込みの安全検証要)。
- pytest 1127 passed(既知okinawa pin3除く)。不変条件維持(物理接続=真・捏造禁止・基底extract不変・スコアカード不可触)。全面改修 Phase1-5 一巡完了(Phase5フル統合のみ hands-on 残)。

## 2026-06-17 — **Claude Opus 4.8** — 全面改修: 正を1つに(Phase2 DB正化=既達の固定 / Phase3 連結性一本化)（140）

オーナー「全面改修(エディタ以外も含め全体見直し)」→「DB正化を核に先に」→「Phase3」。核心=正(source of truth)を1つに。`docs/OVERHAUL_PLAN.md`(3並列調査の実コード根拠)。

- **Phase 2(DB正化)— 着手して判明: ソースの正は既に統一済み**。永続 `data/grid.db` build ≡ files build が**全10地域で完全同値**(subs/lines/gens署名 ALL MATCH)、committed `data/*.geojson` は全10地域で DB(R⟕C)の忠実なD層export(roundtripクリーン)。→ 正はDBに一本化済み・files はその検証済 reproducible export。`tests/test_db_source_unified.py`(CI-safe全地域roundtrip+ローカルgrid.db build同値)で不変条件化。grid.dbはgitignore(CIはfiles=DB-exportでbuild)ゆえ build既定のDB切替は保留(driftリスクのみ)。**重要: 今回の不統一の真因はソースDBでなく下流(出力生成)**。
- **Phase 3(連結性一本化)— 本丸**。`built_view_all`(表示)と `national.py`(潮流)で連結性計算が**2系統**(前者=全国一枚・任意階級stitch・タイ無し / 後者=4周波数島・同階級融合・OCCTO ACタイ)→ **Pages島色 ≠ 潮流の島**だった。`src/powerflow/connectivity.py`(共有・軽量・pandapower非依存)を新設: `compute_connectivity` = **4周波数同期島ごと**(東50/西60を別)・**越境同電圧階級stitch~110m**・**OCCTO ACタイ7本**(`national.load_interconnections`=定義の単一の正)。`built_view_all`/`build_editor_data.build_national` が同一権威を消費 → **Pages島色=潮流の島が構造的に一致**。被覆率 national.diagnose 一致(hok90/east88/west85/oki93%)。all.json: 島{hok37/east328/west725/oki6}・main 11423(旧10922)・タイ7・島2161(旧2644)。エディタでACタイを紫破線表示。`tests/test_connectivity.py` 6件。**pytest 1127 passed**(既知okinawa pin3=working-tree supplement由来)。
- 不変条件維持: 物理接続=真・計算は検証器・捏造禁止・基底extract不変・committedスコアカード不可触。残: Phase1(破壊enrich封鎖)/Phase4(出力の単一オーケストレーション+鮮度統一)/Phase5(エディタ1本化)。

## 2026-06-16 — **Claude Opus 4.8** — A島接続の「一つずつレビュー」: 候補worklist + レビューUI（139）

オーナー「一つずつ表示してほしい。100くらいなら確認できる」= A島接続を1件ずつ人手で承認する導線。

- **候補worklist** `scripts/build_island_candidates.py` → `docs/data/island_candidates.json`(**379件**・電圧降順): 各A島(kv≥66・非鉄道=HV連系方針)に **(c)校正後の地域**の最寄り main 変電所を接続先候補に。**同階級(target_kv≥島kv×0.9)を50km以内で優先**(HV系統は疎なので近すぎる別階級より同階級・本巣市→越前500kV)、無ければ最寄りany(階級違い54件はflag)。校正の成果でtargeting補正(新信濃→tokyo・下北→tohoku)。電圧帯=500:9/275-220:30/187-154:40/110:57/66-77:243。接続先は**機械推定=確証でない**(レビューで人手確認)。
- **レビューUI**(`docs/editor.html` のモード): 候補を1件ずつ地図にズーム→**島(橙)+接続先(青)+提案線(黄破線)**を表示→**✅承認(connect下書き記録)/❌却下/⏭スキップ/◀前**・進捗`#rank/379`・承認数・**localStorageで再開**(`agj_rev_idx`/`agj_rev_done`)。距離大(>10km)/電圧階級違いは**⚠警告**。承認分は既存のJSONLエクスポート/issue提案でローカル:8088採用へ。
- 非破壊: 下書き(localStorage)のみ・採用/潮流検証は:8088。**OSM下地で実在確認してから承認**(物理接続=真・偽接続3,365の教訓を回避)。Pages配信(タブ内で完結)。

## 2026-06-16 — **Claude Opus 4.8** — Pages接続編集タブ統合 + 島データ校正(region/voltage)（138）

オーナー指示「編集ツールもpagesにタブとして実装してほしい。mainに統合していく」+「(c)が先がいい(データ校正先行)」。

- **Pages接続編集タブ**(`docs/editor.html` + `scripts/build_editor_data.py`): Pagesは静的配信なのでフル版エディタの`/api`依存は持てない。`built_view`を**事前レンダ**した静的JSON(`docs/data/built/{region,all}.json`・計14MB・遅延ロード)を読む構成で **閲覧(島=橙孤立/紫連結サブクラスタ・本系統=青・回線数で線幅)** は完全動作。**編集**はlocalStorage下書き→**JSONLエクスポート/GitHub issue提案**(connect/disconnectを2点スナップ)。採用・潮流検証はローカルサーバ(:8088)に委ねる(物理接続=真・計算は検証器・捏造禁止)。タブはiframe遅延ロード(`grid_map.js` initTabs・v=30)。**公開JSON=コミット済みmain状態**(未コミットのokinawa supplementを除いて再生成: okinawa=99節点)。`183e7dc`・Pagesデプロイ成功。
- **島データ校正(c)** (`scripts/calibrate_islands.py` → `island_calibration_2026-06-16.{json,md}`): レポートL18のupstream問題を定量化。855島をOSM変電所6962件に突合し —
  - **region誤タグ32件**(operator根拠・高確度): tohoku→tokyo 9(群馬栃木TEPCO)・hokkaido→tohoku 4(下北半島=青森の東北電力)・shikoku→chugoku 3(広島山口の中国電力)・hokuriku→tokyo 1(新信濃275kV)等。operator無(黒瀬等)は出ない=**下限**。
  - **電圧不一致60件**(名称/census vs OSM): 黒瀬・廿日市 名称220kV→OSM110kV 等。解決は**Web検証[verified]>OSM既定>flag**(例: 東通村は名称154kV・OSM66kVだが検証済154kVが正)。検出に徹し権威値は断定しない。
  - **基底extract不変**(派生レポートのみ)。region remapはbuildに適用せず(全国ビュー`built_view_all`は座標キーで越境連結=接続性は地域タグ非依存)。効果=A島接続の**targeting(地域)と優先度(電圧)を正す**前処理(A/B反転は稀)。
- 不変: モデル本体・committedスコアカード・supplement/cuts。次段=refined worklistでA島接続(high確度95件優先: 都心275kV地中網/大間500kV/中国220kV/下北154kV)。

## 2026-06-16 — **Claude Opus 4.8** — Phase2 越境stitch: AC本土8地域を全国一体に連結（137）

branch `model-source-unification`。設計R2(越境stitch)。地域別buildが県境で線を切り島化させていた問題を、**全国を一枚のグラフ**にして解消(`built_view_all`)。
- **機構**: 全地域builtを座標キー(round5)で一枚に。地域をまたいで同一物理点(~100mセル)にある節点(境界の変電所/鉄塔=重複extract)を stitch して全国でグローバルに連結性を再計算。証拠=同一座標(捏造でない)。
- **結果**: **stitch 2543点**で AC本土8地域(tohoku/tokyo/chubu/hokuriku/kansai/chugoku/shikoku/kyushu)が**1つの全国本系統に連結**(本土AC ~89%が1連結網)。hokkaido(北本=DC連系)・okinawa(離島)は正しく分離。
- **意義**: 「全国の生OSMは繋がって見えるのに buildモデルは島」の乖離を解消 → **全国ビューが真の全国AC連結を描く**(オーナー指摘「全国は繋がって見えたがDBの正は?」への回答=Phase1で正を一本化・Phase2で正自体を全国連結)。
- 残: 各地域内の小島(OSM接続欠落=編集ツールの対象)・DC/海峡越え(別機構)。本番モデル/スコアカード不変(全国ビューの連結計算のみ・建設はbuild_network_snappedで地域別のまま)。

## 2026-06-16 — **Claude Opus 4.8** — 接続編集プラットフォームの資産化(オーナー実機編集で磨き「記録しておいて」)（136）

branch `model-source-unification`。オーナーが嶺南変電所・京北開閉所・金武火力等を実機で手編集しながら磨いた確定資産(「編集はかなりやりやすくなった/点が押しやすい」)。要点:
- **単一の正(設計R1)**: 全国も `built_view_all()`(全地域build合成・編集込み・`/api/built/all`)を描く → 「地域で繋いだ編集が全国に反映されない/どれが正か不明」を解消。設計doc `MODEL_SOURCE_UNIFICATION.md`。
- **✂セグメント切断**: `build_network_snapped(cuts=)` を**隣接点間(セグメント)**に適用 → 「点と点の間の1区間だけ」消す(線が割れる・長距離枝は無傷)。オーナー指摘「長距離始点-終点がカットされる」を修正。UI=2点クリック→**連続切断**(Escで終了)・スナップ点プレビュー・線ホバー強調。`{region}_cuts.json`(absent=本番不変・可逆)。test 8件・1111緑。
- **発電所連系点(switchyard)欠落の検出器** `scripts/plant_switchyard_gaps.py`: 発電所点はOSMにあるが連系変電所が無く発電機が遠方subへ(金武火力600MW→伊芸5km)。**線終端<0.6km=連系点の物理証拠**でsupplement補完→自分のswitchyardに接続。okinawa 6件(金武/石川/牧港/Gushikawa/Ishikawa/つきしろ/松本)。捏造回避(距離一律でなく線終端証拠)。
- **間引きバグ**: `geojson_loader._simplify_coords` step 3→1。全国緑線が `coords[::3]` で鉄塔無視→全点保持(伊芸~松田 14→40点)。
- **メモリ**: [[project_agj_connection_editor]] に全機能を記録。本番モデル/スコアカード不変(編集は supplement/cuts=可逆キュレーション)。

## 2026-06-16 — **Claude Opus 4.8** — E8b: disconnect→builder cut機構(誤接続の切断をモデルに反映)（135）

- オーナー指示「Eトラックのエディタ強化に進める」。接続編集の**切断(disconnect)経路**が未実装だった(connect=supplement+adoptは完成、cutは件数報告のみskip)を完成。
- **builder cut機構**: `build_network_snapped(cuts=)` を新設。post-build で各枝の端点座標(変電所/junction位置を round5=built_viewと同一精度)で照合し、誤接続枝を生成しない。**捏造の逆操作(加算でなく抑制)**・基底extract/supplement不変・可逆(編集取消→次build で枝復活)。
- **永続化(supplementと対称)**: `{region}_cuts.json`(加算専用・git追跡・来歴つき)を builder が自動読込。**absent-by-default=本番モデル完全不変**(切断をadoptして初めてファイルが生まれ反映)。`edit_apply` の verify(一時)/adopt(永続)が disconnect を honor。
- **UI連結**: `built_view` が各枝に端点 `a`/`b`(round5)を添付 → editor の✂切断モードで**水色のモデル枝をクリック→`disconnect{a,b}`** を記録(builder cutが同精度で照合)。検証/反映ダイアログに✂切断件数を表示。
- **テスト新設** `tests/test_edit_cut.py`(7件): _normalize_cuts(list/dict/順序非依存/不正skip)・指定枝のみ除去・無関係枝不変・cuts.json自動読込・**absent=no-op**(安全性)・座標必須・verify適用。
- **pytest 1110緑**(1103+7)。okinawa exact pin不変=`cuts=None`は完全no-op(本番不変)を回帰で保証。**モデル/スコアカード不変**(cutsファイル不在)。
- 残(E8b): set_attr→enrichments・verifyにρ13b比/AC収束・status自動判定(adopted/rejected)・before/after図自動送付。E11=島クリック→AI候補ハイライト。接続編集ループが connect/cut 両方向で対称に完成。

## 2026-06-16 — **Claude Opus 4.8** — 標準ツール(osmnx)で接続を独立検証: 我々の座標スナップが優位・取りこぼし無し（134）

- オーナー質問「点と線をつなぐpythonツールは無いのか / もしくは全てAI判断」への実証回答(`scripts/osmnx_ab.py`)。
- **既存ツールの棚卸し(インストール済)**: osmnx 2.1(OSMノード/ウェイ構造を直接グラフ化=node-sharing標準API)・shapely 2.1(`ops.snap`/`unary_union`/`linemerge`)・geopandas 1.1+rtree(最近傍空間結合)・pandapower 3.4(`topology`連結性)。電力特化はPyPSA-Eur `build_osm_network`/GridKit/osmTGmod(未インストール・参考)。
- **管理されたA/B(交絡ゼロ)**: osmnx 2.1で関西フルOSMの power line を node-sharing 取得(38,368ノード)→**同一ノード集合**に prec4 座標丸めを適用して成分数比較(=台帳131の管理再現を標準ツールで):
  - node-sharing(osmid共有): **383成分** / 座標丸めprec4(我々): **339成分**(−44)
  - = 我々の座標スナップは node-sharing の接続を**全て捕捉+近接~11mで44組多く橋渡し**。largest 26,390→26,603。**標準ツールが見つけて我々が取りこぼす接続はゼロ**。
- **台帳131(四国 座標128/node131)を、標準ライブラリ×関西フルOSMで独立再確認**。「目がない/ショートカット」の原因はアルゴリズムでない(再々確認)。
- **決定**: 連結性目的で osmnx/GridKit へ乗り換えても島は減らない(ボトルネック=OSMデータ欠落)。乗り換えの価値はコード再利用・エッジケースの堅牢性のみ。**「全てAI判断」は候補提案・ランク付け(Eトラック編集ツール)としてのみ採用=証拠でゲート**、AI判断を真にするのは捏造(3,365の教訓)で不可。
- 注: 383/339は**線頂点(鉄塔含む)成分**=モデルの「島」とは別物(モデルview=build_network_snapped 152成分/カバー85%)。本番モデル/スコアカード不変・pytest 1103緑・`osmnx_ab.py`は分析ツールとして保持。

## 2026-06-16 — **Claude Opus 4.8** — geojson再生成(電圧伝播+鉄塔fetch)は不採用: 伝播は冗長・raw再取得は越境断片を再導入(負の結果)（133）

- ブランチ `geojson-rebuild-noderef` の決着(オーナー「とにかく走り切って」)。狙い=生OSM(node参照・鉄塔fetch由来)から lines geojson を作り直し、**共有ノードで繋がる既知電圧を無タグ線へ伝播**して充填(`scripts/rebuild_geojson.py`)。
- **再生成自体は成功**: kansai 線4198・**無タグ1351→513(838本=62%に電圧伝播充填)**。node参照を `properties.osm_nodes` に保持。
- **A/B(他層固定・linesのみ差替・`scripts/rebuild_ab.py`)**: 現行 vs 再生成 → 成分**152→207(+55)**・カバー**85.0%→80.5%(−4.5pp)**・最大成分1949→1988・孤立実変電所85→86。**接続は改善せず悪化。**
- **電圧伝播の隔離(決定的)**: builder内部伝播(`propagate_voltage`)のON/OFFで —
  - 現行geojson: ON 152成分 / OFF 162成分 = **builder内部伝播が10成分ぶん効いている**
  - 再生成(事前充填)geojson: ON 207 / OFF 207 = **完全に同一**。事前充填済で builder伝播が「やることが無い」
  - → **geojsonレベルの電圧伝播は builder内部伝播と冗長**(同じ機構を前段でやるだけ・端的な負の結果)。台帳131(node-sharing=接続利得ゼロ)を機構面から裏付け
- **悪化の真因(成分サイズ分布で確定)**: Δ成分の内訳は **極小(size2-3)+43・小(4-10)+10・実体(11+)+1のみ**。主系統は無傷(最大成分むしろ+39)。
  = raw 3×3 bbox再取得が**越境/周縁の極小断片を再導入**(現行curated extractがterritory-clipで除いていたノイズ)。接続を失ったのではなくノイズを足しただけ
- **結論**: 本番geojsonは**現行(curated extract + builder内部伝播)が既に最適**。再取得では真のボトルネック(OSMデータgap)は埋まらない → 正攻法は **supplement機構(I3)で個別欠落線を証拠付き追記**。**本番モデル/スコアカード不変**(再生成は不採用)。
- 残す資産: `tower_connectivity.py`/`build_topology_dataset.py`(全国トポロジ接続データ=監査用・台帳済)・`rebuild_geojson.py`/`rebuild_ab.py`(分析ツールとして保持)。pytest 1103緑・モデル変更なし(before/after図は対象外=本番不変)

## 2026-06-16 — **Claude Fable 5** — join_untagged_tips: 無タグ鉄塔tipの近接吸着(検証通過・初の有効改修)（132）

- オーナー指摘「点(=鉄塔)が数mで繋がっているのに無視される」の真因=**tap_snap/tip_jointのクラスガードが untagged(own_kv=0)を弾く**(`own_kv>0`必須)。kansaiは点66%・線37%が無タグ。
- 実装 `join_untagged_tips`(opt-in・既定off): **degree-1のleaf tip(untagged)**を近接の既知ノード/segに吸着しクラス継承。
  leafは片側のみ接続=クラス間ブリッジ無し(154/66誤融合の主因=経路中untagged segmentとは別)。tap_snap+tip_joint両方を緩和。
- **島A/B(off→on)**: 四国306→298・中部550→492(−58)・関西343→314・**東京526→494(−32)**・北陸178→158。全テスト地域で減・線追加は僅少(+2〜21)
- **ρ A/B(tokyo 13b・誤融合検証)**: interior 0.451→**0.454** / trunk 0.574→**0.576** / 154 0.251→**0.252** / 66 0.208(不変)・matched451不変。
  **ρ悪化なし(微改善)=物理的に正しい接続**(誤融合なら下がる)。AC収束維持(ρ計算成功)
- pytest 1103緑(既定off)。`build_and_solve`/`match_flows`/`external_flow_metrics`にも引数を貫通。
- **node-sharing(台帳131)と対照的に検証を通過**。次=全地域AC確認→default-on化(本番反映・新日付スコアカード)はオーナー確認後

## 2026-06-15 — **Claude Fable 5** — B Phase3検証: 大改修は不要(座標丸めが既にnode-topology捕捉)（131）

- 大改修(線接続を座標スナップ→node-sharing置換)の前に、四国で**同一way集合(power=line 1429)**で両方式の連結分割を照合:
  - 座標丸めprec4: **128成分** / node-sharing: **131成分**
  - **node共有なのに座標丸めで別成分になるペア = 0**。むしろ座標丸めの方が3組多く繋ぐ(近接~11m橋渡し)
- **結論(重要・負の結果)**: 現builderの座標スナップは**OSMノードトポロジを既に完全捕捉**(共有ノード=同一lat/lon→prec4丸めで同一頂点→連結)。
  **node-sharingへの置換は接続利得ゼロ**=900行の大改修は無意味。Phase2でBが多く繋いだのは**minor_line/cable包含＋Phase2束縛差**であって接続方式ではない。
- **オーナーの「ショートカット」知覚の真因**(再確認): 嶺南モデル線は実幾何242点で追従済(builderは正確)。直線に見えるのは①手動connect(a→b直線)②合成橋③旧キャッシュ。**builderの接続方式ではない**
- **島削減の真の梃子(確定済)**: OSM接続欠落(編集ツール+OSM還元)・鉄道(繋がない)・線種包含。**node-sharing builder書換は梃子でない**ので不採用
- 価値: Phase1の全国node-refデータ(`data/osm_raw/`)は監査/検証用に保持。大改修を**検証で回避**(捏造的価値を作らない=方法論)。本番モデル不変

## 2026-06-15 — **Claude Fable 5** — B Phase2: node-topology+変電所束縛で島A/B(全国)（130）

- `scripts/b_phase2_analyze.py`: node-topology(共有ノード=正確な線接続)+変電所束縛(point-in-polygon)で島数を測り現モデルとA/B。結果 `docs/reports/b_phase2_2026-06-15.json`
- **全国ネット −291島(B優位)**。だが一様でない:
  - **B圧勝**: 四国 99 vs 306(−207)・中部 352 vs 550(−198)・北陸 96 vs 178(−82)・東京 516 vs 526(−10) = **現スナップが線接続を取りこぼしていた所をnode-topologyが正確化**
  - **B悪化**: 関西 438 vs 343(+95)・中国(+45)・沖縄(+42)・九州(+18)・東北(+5)・北海道(+1)
- **悪化の原因(重要)**: Phase2の変電所束縛が **point-in-polygon+150mのみ**=現モデル(半径2.5km endpoint_snap+名前束縛)より**厳しすぎる**。
  線が変電所の少し外で終わる所をB島と誤判定。**node-topology自体の欠点でなく束縛方式の差**。沖縄は離島散在で特に不利
- **結論**: node-topologyの線接続は明確に有効(四国/中部で大幅島減)。正しいB = **node-sharing線 + 現モデルの寛容な変電所束縛**の組合せ。
  → **Phase3** = snapped_topologyの線-線接続(座標スナップ)をnode-sharingに置換し、**変電所束縛は現行維持**→ρ13b比/AC/島でA/B。大改修につき慎重に(夜間の盲目置換はしない)
- 本番モデル/スコアカード不変(分析のみ)。pytest対象外(standalone)

## 2026-06-15 — **Claude Fable 5** — B Phase1完了: 全国を生OSM(ノード参照)で取得・連結性測定（129）

- オーナー指示「サーバー等で一晩かけてB実施」→ `scripts/b_overnight.py` で全国10地域を夜間取得(tile失敗0)。
- **全国: 生OSM power way 50,039 / 共有ノード接続点 37,050(=座標推測なしの正確な接続)**。生データは `data/osm_raw/`(gitignore)・サマリ `docs/reports/b_phase1_summary_2026-06-15.json`
- 地域別(node-topology最大連結塊way / 現モデル島節点): 東京5888/526・中部2911/550・東北5487/170・北海道3439/76・関西2868/343・中国984/207・四国944/306・九州1042/199・北陸1650/178・沖縄37/5
- node-topology成分が多い(東京2031等)のは**変電所束縛を未適用**だから(線同士の正確接続のみ)。Phase2で変電所(point-in-polygon)を足し島A/Bへ
- 可視化: 北陸 node-topology接続図をLINE送付(青=最大連結網・赤=接続点・灰=小片)。「愚直に一つずつ繋ぐ」をOSM共有ノードで実現
- 本番モデル/スコアカード不変(取得・測定のみ)。次=Phase2(変電所束縛+島A/B)→Phase3(builder統合・ρ/AC検証)

## 2026-06-15 — **Claude Fable 5** — B路線実証: 生OSM(ノード参照)で正確接続トポロジ（128）

- オーナー指摘「点と線が明確にあるのに愚直に繋がない/ショートカット/目がないのか/人間と同じに繋ぐのは無理か」への根本対応(B)。
- **真因の確定**: 現GeoJSONは**OSMのノード参照を落としている**(tokyo 8295線中0本がnode参照)→ビルダーは座標一致で接続を推測→時々ショートカット/取りこぼし。
  一方OSM自体(人間が見る図)は**way同士が共有するノードで接続が正確に決まっている**。「目がない」のではなくデータから接続情報が削られていた。
- **実証(嶺南bbox)**: Overpass `out body;`(node参照保持)で取得 → `scripts/osm_node_topology.py` が共有ノード=接続で構築。
  **189線・197の正確な接続点・連結成分17(最大172線が1成分)**。1ノードを7線が共有=母線接続点が座標推測なしで正確。生レスポンスは `data/osm_raw/` にキャッシュ
  - 注: 嶺南モデル線は既に実幾何242点等で**追従済**(ショートカットは合成橋/手動connect/変圧器スタブのみ)。Bは「接続の有無」を正確化する(幾何でなくトポロジ)
- **Bの正攻法が確立**: 生OSM(ノード参照)→共有ノードで接続=人間と同じ精度・推測/ショートカット消滅。フォールバックEP=maps.mail.ru(private.coffee/overpass-api.de過負荷時)
- **残(段階的)**: 全国を node参照つきで再取得 → node-topologyビルダー(座標スナップ置換) → 現builderとA/B(島・ρ13b比・AC) → 統合。大規模抽出のためOverpassエチケット(sleep≥20s)とキャッシュで段階実行
- pytest 1103緑・本番モデル不変(プロトタイプは別経路・取得のみ)

## 2026-06-15 — **Claude Fable 5** — 編集の「反映(adopt)」: supplement永続適用→モデル再構築（127）

- オーナー指摘「編集→検証→issueまでやったのにモデルに反映されない」。**adopted編集を実データに永続適用する経路が欠けていた**(verifyは一時tempdirで捨てていた)
- `edit_apply.adopt(region)`: pending/verifiedのconnect/add_pointを **実 `data/{region}_*_supplement.geojson` に同期**(editor由来=edit_id付きを除去→現編集で再構築=**冪等・可逆**。編集取消→再反映で消える)。書込後の島数を返す
- `POST /api/adopt/{region}`: 反映後 built キャッシュ無効化→次の `/api/built` で再構築。エディタに **「⬇反映(モデルに適用)」ボタン**+`adoptEdits()`(確認→反映→loadRegionで再表示)
- 3経路の役割を明確化: **検証=一時計算 / 反映=supplement永続→モデル反映 / issue=レビュー記録**(UIに明記)
- 実地: tokyo pending19接続を反映→supplement 218→237・島263→263/本系統+2(可逆確認後に復元)。本番反映はオーナーがボタンで地域別に判断(experimental編集の無差別本番化を回避)
- pytest 1103緑。supplementは加算チャネル(builderが`_layer`で取込)=設計どおりの「adopted接続のsupplement統合」

## 2026-06-15 — **Claude Fable 5** — 島分類器: 「なぜ繋がらないか」で仕分け→編集ツール/OSM還元へ（126）

- 台帳125の結論(自動束縛は捏造)を運用化。`scripts/island_classify.py`: 島変電所を6バケツに分類。
  `PYTHONPATH=. python scripts/island_classify.py --region tokyo --out data/db --stamp 2026-06-15`
- **tokyo実測(島変電所173件)**:
  - **isolated 106**(線なし孤立・方針A) / **osm_gap 50**(連系線OSM未整備) / **railway 13**(鉄道・別網) = **169件は自動修正不可**(繋ぐと捏造)→ 人間/OSM/編集ツール
  - **vsplit 2**(清水・宇都宮=同名別電圧ヤードが離在・変圧器未連結) / **reachable 2**(乙黒等・要精査) = 候補4件のみ。**phantom 0**(幽霊節点なし=抽出健全)
  - 宇都宮は66kVヤードと154kVヤードが**2607m離在**=安全に自動連結不可(154/66変圧器がOSM未マップ)
- **確定**: tokyoの島に安全な自動接続はほぼ無い(候補4件も危険)。**島削減の正道=GridStitch編集ツール(人間が実態で連系)+OSM還元**。分類器JSONが編集候補/OSM貢献対象の提示材料
- 出力 `data/db/island_classify_tokyo_2026-06-15.json`(committedスコアカードに非接触)。pytest 1103緑・モデル不変

## 2026-06-15 — **Claude Fable 5** — P1b前提の再評価: 島の大半はOSM欠落/鉄道=ブランケット束縛は捏造（125）

- P1b(母線束縛)実装の前に、tokyoの非鉄道島(本線2本+届くのにdeg<2)を**届く線が主系統の別変電所へ達するか**で分類:
  - **真の束縛バグ(繋ぐべき)= 実質1〜2件**: 宇都宮(鹿沼線/壬生線/西宇都宮線154 等が鹿沼・徳次郎・西宇都宮へ実到達なのに島)。乙黒は無タグ0m線で誤検出
  - **OSM接続欠落= 16件**: NEC府中(日電府中線695m構内のみ)・椿本チエイン(椿本線530m)・清水 等。**系統連系線がOSM未整備**の顧客/局所変電所。届く線も自分の構内で完結
- **結論(方法論的に重要)**: 「線は届くのに島」の内訳 = 鉄道7 + OSM欠落16 + 真バグ1〜2。
  **ブランケットな母線束縛は16件のOSM欠落を捏造接続する**=「物理接続=真・捏造禁止」に反する → **ブランケットP1bは不採用**
- **島削減の真の梃子**: OSM貢献(欠落feederのマッピング)+ **GridStitch編集ツール**(人間が実態で連系線を引く)。自動束縛ではない。= 編集ツール路線の正当性を裏付け
- 残す手: 真の束縛バグ(宇都宮型・OSM上feederが主系統に実到達)だけを**狭く**繋ぐ targeted fix(低件数・低リスク)。OSM欠落は編集/OSM還元へ回す
- pytest 1103緑・モデル不変(調査のみ)

## 2026-06-15 — **Claude Fable 5** — 嶺南の正確化 完了 + 清水で島パターン確定（124）

- **嶺南変電所 正確化(参照例 完成)**: OSM接続トレースで確定(推測なし):
  - **無印母線34本の電圧**: 接続先から 500kV×20 / 275kV×13 / 境界1 → **77kV母線は無い**(無印は全て500/275)
  - **77kV終端確認(自律判断)**: 77kV本線7本すべて嶺南の77kVベイに **0〜1mで終端** → **77kVは実在3次側**(通過でない)
  - **回線**: 引込本線(京北/八乙女/湖東/色浜/白木)は**全て2回線**(OSM `circuits=2, cables=6`)
  - 確定モデル: 500母線 ─T1(500/275)─ 275母線 ─T2(275/77)─ 77。SubScopeのSLDと一致
- **清水変電所で島パターン確定**: 清水は **77kVバス(島・deg1)と66kVバス(本系統)に分裂し変圧器で未連結** → 77が島。
  別feature(sub_198 v77 / sub_1359 v66)に分かれ階級間スタブが生成されないのが真因。**非鉄道11件の典型**=「同一変電所の電圧バスが変圧器で繋がっていない」。嶺南(正しく連結)と対照的
- → **P1bの確定仕様**: 同一変電所(同名/近接の複数feature含む)の各電圧バスを**カスケード変圧器で必ず連結**し、届く同一網本線を電圧別busbarへ束縛。鉄道除外。A/B(島・ρ13b比・AC)・committed不可触
- SubScopeの引込線名は「~X変電所線」型のみ自動取得(清水は未命名で空)=軽微改善余地

## 2026-06-15 — **Claude Fable 5** — SubScope: 変電所構造ビューア(OSM実構造+単線結線図)を命名・再現可能化（123）

- オーナー指示「この写真(嶺南の構造図)使い勝手いい・出し方記録・名前つけて」→ **SubScope**(GridStitch機能・変電所構造ビューア)として実装
- `scripts/substation_scope.py`: 変電所名(部分一致)から2図を生成。`PYTHONPATH=. python scripts/substation_scope.py --region kansai --name 嶺南`
  - **(A) OSM実構造図**: 母線(busbar)太線/ベイ(bay)破線/本線を電圧で色分け(500赤/275橙/154紫/77緑/無印灰)。構内結線と引込方向が一目で分かる
  - **(B) 単線結線図(SLD draft)**: 電圧階級ごと1母線・隣接をカスケード変圧器(1次HV/2次LV・**飛び越し無し**=500/77直結作らない)。bus-branchビューに対応・忠実層(母線/ベイ/端点)は保持し展開可
- **嶺南で検証**: SLD導出モデル=500kV{京北/八乙女/色浜/白木}・275kV{京北/湖東/白木}・77kV(カスケード500-275-77)。手動設計版を完全再現
- 設計方針(オーナー): 潮流は単線+単位法で難しくない・回線が本質・**電圧は接続先から辿って埋める**・畳んでも展開余地を残す
- pytest 1103緑(新規standaloneスクリプト・package非依存)。LINE送付運用に有用

## 2026-06-15 — **Claude Fable 5** — GridStitch P1a: 分割変電所の統合(group_substations) + 島真因の再診断（122）

- 全面改修=GridStitch(計画 `docs/GRIDSTITCH_PLAN.md`)。P1(母線束縛A/B)の第一歩。
- **P1a `group_substations` opt-in**(snapped_topology・既定off): OSMが1変電所を電圧別/分割ポリゴンで表す
  (沼津=66kV+77kVの2ポリゴン)場合に、同名(接尾辞除去)かつ `group_km`(1km)内のポリゴンを1 canonical sid へ統合。
  A/B(tokyo): bus **4215→4194**(分割変電所21件統合)、線 4670→4642。**島は 263→263(Δ0)**。全地域smoke緑・pytest 1103緑。
- **正直な結果**: 多ポリゴン統合は faithful(沼津は1変電所が正)だが**島削減の梃子ではない**。新鮮ビルドで再診断したところ、
  島の真因は別: **島変電所173件中、OSM本線2本以上が届くのに degree<2 = 29件**(清水9本/沼津9本/NEC府中5本/富士市5本…)。
  これは「線が変電所busに束縛されていない」(束縛距離 or 母線が別ノード)状態。**P1b=到達線を電圧別busbarへ束縛**が本丸。
- 方針: group_substations はボトムアップ計画(P3 STEP1の変電所統合)の土台として保持。committed/スコアカード不変(opt-in)。
- **P1b診断(重要・122b)**: 「本線2本+届くのにdeg<2の島変電所」を実測=tokyo **18件 = 鉄道/JR系7 + 非鉄道11**。
  沼津77kVヤードに届く5本は全て「JR 西相模-沼津線」=**鉄道変電所**(物井=1500V DCも同様)。鉄道/別事業者網は利用系統から
  **正当に分離**(busbar束縛は捏造接続=台帳99の territory/frequency discipline と整合)。**P1bは鉄道除外が前提**。
  真の対象=非鉄道11件(清水77kV/NEC府中/椿本チエイン/牛久/国分寺…)。方針A/分類に種別C(鉄道)追加(GRIDSTITCH_PLAN §8)。

## 2026-06-14 — **Claude Fable 5** — 嶺南変電所の検証(接続は正常)+母線/ベイの分離表示（121）

- オーナー指摘「嶺南変電所はOSMでは素晴らしい構成なのに系統図ではダメ、終点が宙に浮いて繋がっていないのでは」
- **検証(計算で物理接続を確認=方法論どおり)**: 嶺南は**モデル上で正しく接続**されていた。
  `kansai_sub_601` が電圧別に4 bus(@500 次数7 / @275 次数6 / @77 次数2 / @u 次数1)・**全て本系統**、
  京北/八乙女/色浜/湖東/白木/小浜/上中の13線が両端本系統で接続、変圧器スタブ 500↔275↔77 で電圧階層も連結。
  → オーナーの推測「繋がっていない」は**実際には外れ**。「終点が宙に浮く」原因は**OSMの母線/ベイ154本の生geometry**(見た目の毛玉)
- **母線/ベイは既に自己ループとして畳まれている**: A/B(kansai)で `drop_busbar_bay` しても送電線2537→2531(−6)・連結成分152→151(Δ−1)。
  builderは既に母線/ベイをbus内部に収容済み(送電線集合にはほぼ非寄与)。`drop_busbar_bay`(opt-in・既定off)は @u 等の微小残渣を消す任意オプションとして追加
- **真の改善=エディタ表示**: OSM線を「送電回廊」と「母線/ベイ(変電所内部)」に分離し、母線/ベイを**既定OFFの薄い破線レイヤ**に。
  右上トグルで嶺南の内部構成を必要時のみ表示 → 送電系統図がクリアに(「系統図としてダメ」の解消)
- pytest 1103緑・**本番モデル/スコアカード不変**(drop_busbar_bay既定off・表示分離のみ)

## 2026-06-14 — **Claude Fable 5** — E13: 保留編集の操作(undo/反映前の切断・スナップ)+連続接続（120b/c）

- オーナー要望「連続接続できるように/戻るも作らないと編集できない/追加した点や線も反映前から切断・認識できるように」
- **連続接続(chain)モード**(120b・c291109): 点を順クリックで隣接ペアを次々connect(回廊を一気に辿る)。確認無し・Esc終了・連投はloadEdits抑制で高速
- **undo/保留編集の操作**(120c): `edit_log.remove_edit_by_id` + `DELETE /api/edits/{region}/{id}`・GET に submitted(issue送信済み=取消不可)を追加。
  エディタ: ↩直前を取消(⌘Z)・✂️切断モードで**保留の接続線/追加点をクリック→個別取消**・追加点と接続端点を `pendingPts` として**反映前からスナップ対象**に(=新規点に繋げる/誤接続を消せる)
  - 検証: テストedit追加→DELETE取消OK・**issue#28送信済み12件はDELETE 400で保護**。pytest 1103緑・モデル不変
  - **バグ修正(121b)**: chainの仮線/addPointの点を生mapに直描き→`Ctrl+Z`で消えなかった。chainMarkers管理+loadEdits描画に統一して解消。
    `line=substation` も母線/ベイレイヤのフィルタに追加(kansai 28・hokuriku 12)

## 2026-06-14 — **Claude Fable 5** — E12: 接続編集を GitHub issue 化(メモ・レビュー・OSM還元の土台）（120）

- **オーナー方針**: 「接続はGitHub issueとして送られるようにしたい。メモも入れられるように。こういうツールにしたい」
- `src/server/issue_submit.py` 新設 + `POST /api/issue/{region}`: pending接続を**まとめて1 issue**化(オーナー選択)。
  本文=各接続のチェックリスト(座標・電圧・evidence・OSMリンク)+検証(島A/B)+メモ。`gh issue create --label connection,data-quality`。
  送信済みは `data/db/connection_submissions.jsonl` で管理し二重送信防止(edit_logは append専用のまま不変)
- エディタにメモ欄+「本文プレビュー(dry-run)」「issue送信」ボタン。送信前に件数確認ダイアログ
- **実地: オーナーの手動接続12本(武蔵野付近)→ issue [#28](https://github.com/lutelute/All-Japan-Grid/issues/28) を実生成**(connectionラベル新設)。
  人間が編集→ログ→検証→**GitHub issueでレビュー/採用** の協働ループが繋がった。E9(多ユーザー)の実体的な第一歩
- pytest 1103緑・モデル/スコアカード不変

## 2026-06-14 — **Claude Fable 5** — E10追補: モデル接続線を実OSM幾何で描画+鉄塔の扱いを明文化（119b）

- **オーナー指摘**: 「東京でモデル接続線が1本もOSM線上に載っていない、絶対おかしい」。原因=`built_view`が
  edgeを変電所間の**直線(a→b)**で返していた → 曲がった回廊を突っ切り、OSM線に載らないように見えた(座標は正常)
- 修正: `built_view`のedgeに `TransmissionLine.coordinates`(鉄塔を通る実折れ線)を `path` として格納。
  tokyo 3335/4670本が多点path化 → エディタでモデル線(水)がOSM線(灰)に重なる。**オーナー確認「想像通りのモデル」**
- `GET /api/built/{region}` に**メモリキャッシュ**+`?fresh=1`バイパス(再構築〜2秒の体感改善)。
  エディタは**OSM先行描画→モデル非同期後乗せ**(loadToken で地域切替レース防止)で初回操作が速くなった
- **鉄塔(tower)の扱いを明文化(オーナー質問への回答)**: ビルダー(`snapped_topology` docstring 14-19)は
  ①全線頂点(=鉄塔位置)を一旦グラフ節点化 ②変電所近傍は束ねる ③**次数2の鉄塔(線が素通り)はchainを畳む**
  (電気的に透過=零注入なので結果不変) ④**次数≥3のジャンクション(分岐鉄塔)のみ合成bus**。
  → 鉄塔は無視されておらず、幾何(path)も保持。「全鉄塔を零負荷bus化」は次数2では電気的に冗長かつbus数〜16倍(tokyo 68977頂点 vs 4215節点)で過大。
  真の改善余地は**共有鉄塔ジャンクションの検出精度**(座標一致)と上記の実幾何描画であって、全鉄塔bus化ではない
- pytest 1103緑・モデル/スコアカード不変(可視化と幾何返却のみ)

## 2026-06-14 — **Claude Fable 5** — 接続編集プラットフォーム E10: OSM⇄系統モデルの並列表示・接続性可視化（119）

- **動機(オーナー指示)**: 「OSMのデータと今現状の系統のデータが並列で見えないと確認ができない。
  つながっているかどうか確認できない」。従来エディタはOSM(変電所・線)だけを表示し、
  **build後の系統モデルがどう繋がっているか(=島か本系統か)が見えなかった**
- `src/server/built_view.py` 新設: `build_network_snapped` の結果(snapped topology)を
  節点(本系統/島で色分け)+モデル接続線+連結性サマリとして返す。`networkx`連結成分で main(最大)/island判定
- FastAPI `GET /api/built/{region}` 追加(app.py)。tokyo=4215節点/4670接続線/263成分/本系統3689/**島526**(正準263成分と一致)・約2秒
- `editor.html` 全面改修(並列レイヤ):
  - **OSM層**(実在=編集対象): 送電線(灰)・変電所(中空リング・全点スナップ可)
  - **モデル層**(build後=接続確認): 本系統(青)・**島(橙=未接続・要確認)**・モデル接続線(水)
  - `L.control.layers`で各層を独立トグル → 「OSMに線があるのにモデルでは島(橙)」を直接比較できる
  - パネルに「モデル状態(島N/本系統M/成分K)」常時表示・島クリックで未接続理由をポップアップ・`preferCanvas`で大規模描画
- **バグ修正(丁寧化)**: 旧`centroid()`は`.flat()`1段のみでMultiPolygon変電所(tokyo 1件)を`[NaN,NaN]`化→
  `L.circleMarker`例外で**全レンダリング停止**していた。座標ペアまで再帰平坦化+`isFinite`ガードで堅牢化
  (1件の不正geometryで全体が止まらない)。これが「微妙に使いづらい」の一因
- full pytest 1103 passed(3 skipped)・回帰なし。**モデル/スコアカード不変**(可視化のみ・潮流計算に非接触)
- 残: 島クリック→近接OSM線ハイライト(接続候補提示)・接続後の自動再検証UI・E8b(builder cut)・E9(多ユーザー)

## 2026-06-14 — **Opus 4.8** — 接続編集プラットフォーム E8: 検証→判定(編集適用→島削減A/B)・核心ループ完成（118）

- `src/server/edit_apply.py`: pending編集を一時data_dirに適用(connect→lines_supplement / add_point→subs_supplement・
  symlinkで他層温存)→`build_network_snapped`で島数 before/after。disconnect/set_attrは別経路(E8b)で件数報告
- FastAPI `POST /api/verify/{region}` + エディタ「検証(島削減A/B)」ボタン配線
- **実地検証**: strong候補2件(福島500kV)をPOST→verify→**島263→261(Δ-2)**。
  **編集→ログ→検証→島削減A/B の核心ループが端から端まで動作**
- これでプラットフォーム E1-E8 完成: 候補生成→エディタ(全OSM点選択・接続/切断/点追加/属性)→編集ログ→検証判定。
  残=E8b(builder cut機構でdisconnect反映・set_attr→enrichment反映)・E9(多ユーザー)・OSM ODbL還元

## 2026-06-14 — **Opus 4.8** — 接続編集プラットフォーム E7: 本格エディタ(全OSM点選択+接続/切断/点追加/属性)（117）

- `src/server/templates/editor.html` + `/editor` ルート。FastAPI配信(`uvicorn src.server.app:app --port 8088`)・OSMタイル下地
- **全OSM点を選択可能**: 変電所(赤点・クリック)+**全線頂点をスナップ点に登録**(クリックで最寄り点に~120mスナップ)。送電線はクリックで切断対象
- モード: 🔗接続(2点)/✂️切断(線)/➕点追加(地図クリック→**緯度経度自動**+名称・電圧フォーム)/✎属性編集/閲覧。各操作→`POST /api/edits`
- 編集ログを地図に色分け描画(pending橙点線/adopted緑実線)+一覧+status件数。検証→判定(E8)はボタン枠のみ
- **実地検証**: /editor 200・/api/geojson 200・POST connect記録成功(id発行)・GET一覧。端から端まで動作確認
- 次=E8検証→判定(`/api/verify`: 編集をsupplement/cut/enrichmentに適用→潮流/島削減/ρ13b比→status更新)

## 2026-06-14 — **Opus 4.8** — 接続編集プラットフォーム E5-E6: 設計doc+編集ログ基盤+編集API（116）

- **E5 設計doc** `docs/CONNECTION_EDITOR_DESIGN.md`: アーキ(Leafletエディタ↔FastAPI↔編集ログjsonl↔適用層↔潮流/DB検証→判定)、
  データモデル(action=connect/disconnect/add_point/set_attr・status pending→verified→adopted/rejected)、
  適用先(connect→lines_supplement / disconnect→cuts / add_point→subs_supplement / set_attr→enrichments)、多ユーザー段階(E9)
- **E6 編集ログ基盤** `src/server/edit_log.py`(append専用 `data/db/connection_edits.jsonl`・validate・list・counts)
  + FastAPI `POST /api/edits`(記録)・`GET /api/edits/{region}`(一覧)。round-trip/validation/import 検証済
- 物理接続=真・捏造禁止・全編集を記録し検証して判定の原則。次=E7本格エディタ(全OSM点選択+接続/切断/点追加/属性)

## 2026-06-14 — **Opus 4.8** — 接続編集ツール③: 接続適用+島削減A/B(apply_connections.py)・プラットフォーム要件追加（115）

- `scripts/apply_connections.py`: 編集ツールのエクスポート(or strong候補)を `data/{region}_lines_supplement.geojson`
  に加算統合(source=manual・dedup)→島数A/B。**既定は書き込まず検証のみ**(`--apply`で採用)
- strong5候補でパイプライン検証: **島263→258(Δ-5)**。追加→supplement→builder取込→島削減が端から端まで通ることを確認。
  物理接続=真・捏造禁止: 採用は人間がOSM地図で実在確認したもののみ
- **ユーザー新要件(2026-06-14・プラットフォーム化)**: ①全OSM点をもれなく選択可能に ②点追加(地図クリックで
  緯度経度自動+属性入力) ③誤接続の切断(点-点を切る) ④全編集をログ記録→⑤潮流計算+DB検証→判定 ⑥多ユーザー入力の
  プラットフォーム。→ 候補承認MVPを超える本格GISエディタ+バックエンド(FastAPI `src/server/app.py`拡張)が必要

## 2026-06-14 — **Opus 4.8** — 接続編集ツール②: 地図編集UI(OSM下地で候補承認→supplement書き出し)（114）

- `docs/connection_editor.html` 新設。**Leaflet + OSMタイル下地**で、E1の候補JSON
  (`reports/connection_candidates_tokyo.json`)を読み、島側端点(赤)・主系統候補(青)・候補線(strength色)を表示
- 人間が候補線を**クリックで承認/解除**→「承認済みをエクスポート」で supplement GeoJSON
  (LineString・source=manual)をダウンロード。**OSM下地で実在確認してから承認**(物理接続=真・捏造禁止)
- `ajgrid map`(docs/配信)で `http://localhost:8080/connection_editor.html?region=tokyo`。strong/medium/weakフィルタ付き
- 次手: ③`scripts/apply_connections.py` でエクスポートを `data/{region}_lines_supplement.geojson` に統合→A/B(島削減・ρ13b比・AC収束)

## 2026-06-14 — **Opus 4.8** — 接続編集ツール①: 接続候補ジェネレータ — 東京79島に候補(strong5/medium33)（113）

- **オーナー新方向(接続編集ツール)に着手**。統合点を調査確定: 人間が承認した接続は
  `data/{region}_lines_supplement.geojson` に追記(加算専用)→`build_network_snapped`の`_layer()`が
  既に取込(snapped_topology.py:391-421)。地図UIは`docs/national_map.html`(Leaflet)を足場。
  enrichments.jsonl(source=manual最優先)はフィールド補完用で、新規ジオメトリはsupplementが自然
- 候補ジェネレータ `scripts/connection_candidates.py` 新設(**自動では繋がない・捏造禁止の材料提示**):
  島端点(degree-1 tip)/孤立変電所→方位連続性・同電圧・距離で主系統への候補をランク+strength付与
- 東京262島→**候補あり79(strong5/medium33/weak41)**。evidence: line_tip_continuation55/isolated_sub_nearest24。
  strongは福島500kV基幹系(161m align3°/248m align21°)等=これまでのweld候補と整合
- 次手: ②地図UI(national_map.html拡張=島強調+候補表示+人間が接続を描く→supplement保存) ③builder取込→A/B検証(13b比)

## 2026-06-14 — **Opus 4.8** — I6-5: 孤立変電所105の真因 — 85島はOSMに送電線なし・吸着漏れは10島（112）

- 孤立変電所(degree-0)105島の最寄りOSM線頂点までの距離: <50m(吸着漏れ濃厚)**10** / 50-150m 7 / 150-500m 3 /
  **>500m(OSMに近接送電線なし)85**
- **105島の81%(85島)はOSMに繋がるべき送電線が存在しない**(配電変電所 or 送電線が未描画)=繋ぎようがない(捏造禁止)。
  OSM編集(W5)で線を追加するか、負荷バス化/除外で正直に開示するしかない
- 確実に繋げるのは**吸着漏れ10島(<50m)**=近くに線があるのに吸着されていない → 吸着ロジック
  (polygon_bind/snap/_bind_vertex)の改善で捏造ゼロに繋がる
- **「島を無くす」の最終的な現実**: 東京262島で主系統に繋がる候補は僅か(weld3 + 吸着漏れ10 + 中距離の一部)、
  大半はOSMの接続情報欠如(線なし85 + 遠隔72等)。物理接続が真である以上、OSMにない接続は作れない →
  **OSM編集が本質的な道**(W5キュレーション/OSMコミュニティ貢献)
- 次手: ①吸着漏れ10島の吸着改善(確実) ②weld候補3島(福島500kV)の接合 ③残りはOSM編集提案/負荷バス化として開示

## 2026-06-14 — **Opus 4.8** — I6-5: 診断器をbuild後実態で正確化 — 東京島の真の姿は孤立変電所105/繋ぐ候補3（111）

- 台帳110のline_centric誤判定を受け、build後実態(degree・近傍build後ノード・同電圧)で分類する
  `scripts/d4_island_classify.py` を新設(診断器の正確化・line_centric座標照合を排除)
- **東京262島**: 孤立変電所(線なし)**105** / weld候補(端点近接<300m・同電圧)**3** / 中距離82 / 遠隔72
- **島の最大要因は孤立変電所105島**(変電所だけあって線が1本も繋がっていない=線の吸着漏れ or OSMに66kV+線なし)。
  真に繋ぐべき(端点近接・同電圧)はわずか**3島**(福島500kV基幹系2島=161/248m + 千葉1)
- 前回「near same21」は孤立変電所を線ありと誤判定し不正確だった。build後実態で正確化したのが本反復の成果
- 次手: ①weld候補3島(特に福島500kV基幹系)を同電圧近接の証拠で接合→潮流検証(13b比) ②孤立変電所105の真因
  (吸着漏れ vs OSM線なし)を究明→吸着漏れは吸着ロジック改善・線なしは負荷バス化/除外。診断JSON=`island_classify_tokyo.json`

## 2026-06-13 — **Opus 4.8** — I6-5: same島の正確判定 — sub_1354は孤立変電所・診断器のline_centric座標が不正確（110）

- 元OSM頂点50m照合で same21島を再判定すると「同一feature分断1(sub_1354)・端点未接合20・JR饋電0」と**見えた**
- だが **build後グラフで検証 → sub_1354は degree-0 の孤立変電所**(線に1本も繋がらず、80m内に他のbuild後ノードも無い)。
  「三橋線/井戸木線が島側8m」は生OSM頂点が build で jct化/吸着/line_centric移動して離れたアーティファクトだった
- **結論: line_centric座標ベースの診断ではsame島を正確に分類できない**。確実に繋げる同一feature分断は**実質0**、
  大半は ①孤立変電所(線の吸着漏れ/OSMに線なし) ②別線の端点近接(接続証拠なし)。「島を無くす」の障害は
  **OSMの接続情報欠如＋診断器の座標アーティファクト**の二重構造
- **次手(I6-5核心)**: 診断器を **build後の実態(degree・近傍build後ノード)** で正確化 → 真に繋げる島(線端点が
  近接・同一feature)だけ特定 → 証拠ベース接合。それ以外は孤立変電所/OSM編集として開示。
  「おかしい所を計算で確かめる」を診断器自身に適用し、line_centric座標の限界を確定した

## 2026-06-13 — **Opus 4.8** — I6-5: tip_joint距離拡張は偽接続で不採用・同一feature分断はJR饋電絡みで慎重に（109）

- **オーナー指示「基本接続されていないのがないように接続していく」を、偽接続を作らず実現する検討**
- **tip_joint距離拡張のA/B(東京・負の結果)**: `tip_joint_km` 0.12→0.3で n_comp 263→256(-7)だが
  **最大成分3689→3620・線4670→4583と減少=tipが誤接合され線が消える「過剰マージ」**。0.5/1.0kmで非単調(259/258)。
  距離の一律拡張は偽接続(3,365の教訓)→**不採用**
- **正攻法=同一OSM線の分断を繋ぐ(実在線=捏造ゼロ)**。sub_1354島を調査: feat「三橋線/井戸木線」(66kV)が
  島側8m・main側0mで繋ぐべきだが分断。ただし**島側にJR宮原線(JR饋電)が7m近接**=饋電と一般送電の判別が必要
  (I2でJR自営網は誤診=越境流入が真因だった前例)
- **次手(I6-5続)**: ①診断器を元OSM頂点照合に改善し同一feature分断を正確検出 ②JR饋電(traction)を除外しつつ
  実在送電線の同一feature連結を保証→潮流検証。距離拡張でなく**証拠(同一feature)ベース**で島を減らす

## 2026-06-13 — **Opus 4.8** — I6②③診断: same21島の精密分類と「座標ずれ」誤分類の発見（108）

- expand on後の東京 same 21島(near≤1.5km・同電圧)をOSM実在線照合で分類:
  **同一feature分断1 / 端点未接合9 / 座標ずれ・構内11**(`docs/reports/island_audit_tokyo_expand.json`)
- **「座標ずれ11」を計算で確かめて診断器の限界を発見**: `d4_island_audit` の島側点は
  **line_centric座標**(母線=線終端クラスタ平均, 台帳95)で、元のOSM生線頂点から100m+ずれることがあり、
  OSM照合(100m)が外れて「座標ずれ」と誤分類していた(=計測アーティファクト)
- 例: **福島500kV島2つ(各2ノード, ~30kmの500kV線)は実際は端点未接合** — build後グラフで確認すると、
  島の500kV線の端が主系統500kV jct(`37.1398:140.7232`等)の**~300m先**で切れている。
  `tip_joint_km`=120mを超えるギャップ。500kV基幹系の未接合が「座標ずれ」に隠れていた
- **接続方針(次反復)**: `tip_joint`一律拡大は偽接続リスク(3,365の教訓) → 「島端点と主系統ノードが
  **同電圧 かつ OSM上で同一feature/連続線の証拠**」がある場合のみ接合。福島500kVは同電圧500の~300m近接で証拠あり候補
- 診断器の次の改善: 島側点を build後座標でなく**元OSM頂点**で照合し、端点未接合を正確に数える

## 2026-06-13 — **Opus 4.8** — I6-4: 正準スコアカード13b確定 — circ_eff修正込みで全層ρ改善（107）

- expand on(本番デフォルト)+circ_eff修正(105)の正準ρを `external_flows_tokyo_full_2026-06-13b.json`
  に保存(13aは不可触・13bを新正準として追加)
- **13a(off)→13b(本番) 全層改善**: interior 0.441→**0.451**・trunk 0.552→**0.574**・
  154 0.220→**0.251**・66 0.197→**0.208**・n_matched 429→451(実測マッチ増)
- 特に**154は台帳104(circ_eff=1)で0.211(誤差帯内の微減)だったが、circ_eff修正(105)で0.251に改善** —
  主クラスのcircuits維持で容量が正しくなり潮流が実測に近づいた。混在電圧線展開の物理的正しさが
  実測相関の全層改善として確証された(オーナー方針「物理接続を潮流計算で検証」の最終確認)
- 今後の正準比較基準は13b。残=I6②③(端点未接合・座標ずれ ~14ずつ)

## 2026-06-13 — **Opus 4.8** — I6-3: 混在電圧線展開をデフォルトon化(採用) — 全国で実在併架回線を復元（106）

- **オーナー承認**「全混在線で採用」。`expand_mixed_voltage` を全経路デフォルトTrue化
  (snapped_topology/pipeline/topology_metrics/external_flow_metrics/match_flows)。`154;66` 等の
  併架線を各電圧クラスの独立回線として展開=OSM実在回線の物理的復元(33→66 cleanスナップ含む)
- **全国効果**: 連結成分 全10地域で減or不変・計-64島(東京299→263)。全地域AC収束維持
  (tohokuは元から非収束=expand無関係)。合成橋(捏造)減: 東京368→291・九州175→169等
- **東京ρ改善**: trunk 0.552→0.561・66 0.197→0.206・interior 0.441→0.443・n_matched 429→451
  (実測マッチ増)。154は0.220→0.211(誤差帯内・母集団変化)
- **関西/九州vmin**: 0.930→0.905・0.937→0.905(健全>0.9)。展開低電圧回線が末端電圧降下を
  顕在化(正直な物理、オーナー承認で受容)。circ_eff修正(105)で過負荷は緩和済(関西maxld 185→122%)
- **pin更新**: okinawa builder(real 76→78/jct 20→21/枝98→114・multi_circuit/max_parallelは不変=
  circ_eff(105)が主クラスcircuits維持)・pipeline smoke(buses 96→99/lines 84→98/trafos 16→18)。計測値+コメント付き(規約遵守)
- 残: 新日付スコアカード13b追加・before/after系統図LINE(モデル変更)

## 2026-06-13 — **Opus 4.8** — I6-2: 関西/九州の過負荷はcircuits配分の近似と確定(偽接続でない)・主クラスcirc維持で緩和（105）

- **I6①(104)で見つけた関西/九州の悪化を潮流計算で切り分け**(オーナー方針「おかしい所は接続方法や計算で確かめる」):
  関西の最悪過負荷=`国府支線;岩中国府線`(voltage `77000;33000`・circuits=3)が184.7%。展開で77kV側が
  3→1回線に減り容量1/3=過負荷。過負荷線は全て実在の関電送配電変電所間(加美区西脇・上滝野・和田山町玉置等)
  =**偽接続でない・circuits配分の近似が主因**と確定
- **修正**: Pass Bの回線数配分を「主クラス(max電圧=従来kv)は元のcircuitsを維持、追加で展開する
  低電圧クラスのみ1回線」に変更。主送電容量を保つ
- **効果(off/on再検証)**: 関西 maxld **185→122%**・九州 **145→96%**(過負荷増ゼロ)・
  東京 vmin 0.911→**0.923**(さらに改善)・maxld 133維持。AC全収束
- **残る論点**: 関西/九州 vmin は 0.930→0.905・0.937→0.905 で依然低下(健全範囲>0.9)。展開した低電圧
  回線(33→66 cleanスナップ等)が末端電圧降下を顕在化(正直な物理の可能性)。全地域再検証(circ_eff修正後)→
  デフォルトon化判断は**I6-3**。本番opt-in維持(デフォルトoff)

## 2026-06-13 — **Opus 4.8** — I6①: 混在電圧線の各クラス展開を実装・物理検証 — 東京改善も関西/九州で要確認（104）

- **オーナー指示**「全部進めて・物理接続的に正しいものをくっつけて・検証は潮流計算で物理的にできる」
  に基づき I6①(混在電圧併架線の各クラス展開)を実装。`expand_mixed_voltage`(opt-in/デフォルトoff)。
  `_parse_voltage_classes`で `154;66` 等を各標準クラスに分解、Pass A(coord_cls播種)/Pass B(ノード列+edge)
  を各クラスでループ。circuits配分は各クラス1回線(証拠なき配分は回避=D2の慎重さ)
- **物理検証(東京)**: AC収束維持・**vmin 0.892→0.911**・過負荷ほぼ不変・**合成橋(捏造)368→291(-77)**・
  合成線率8.38→6.43%。ρ: **trunk 0.552→0.561・66 0.197→0.206**改善・interior+0.002・
  154 0.220→0.211(誤差帯内/n_matched 429→451で実測マッチ母集団増)。連結成分299→263(-36島)
- **全国connectivity**: 全10地域で島が減or不変(増加ゼロ)・計-64島=OSM実在の併架回線の復元
- **全地域AC(off/on)**: 7地域で収束維持+vmin改善/横ばい。tohokuはoff/on両方非収束(expand無関係=
  フルモデルtohokuの既知)。**関西 vmin 0.930→0.904・過負荷110→185% / 九州 vmin 0.937→0.905・96→145%**で悪化
- **判断=デフォルトoff維持**(本番不変・テスト緑): 関西/九州の悪化が ①circuits配分の近似(各クラス
  1回線で容量過小→過負荷・電圧降下) か ②偽接続(展開66kV側が別系統と誤接続=捏造) かを潮流計算で
  **確かめてから**採用(I6-2)。物理接続自体は正しい(実在回線・合成橋減・島削減)が「おかしい所は確かめる」
  原則を遵守。okinawa新pin(枝98→114・multi_circuit37→27・max_parallel5→3)計測済=デフォルトon化時に更新

## 2026-06-13 — **Opus 4.8** — D4/I: 島は計算でなく物理接続で判定 — near87島の根本原因3分類と混在電圧線分断の機構特定（103）

- **オーナー方針の確立**(2026-06-13)「真や正は計算ではなく物理接続。そこから
  おかしいと判断されるところは接続方法や計算で確かめる」+「孤立も基本ネットワーク
  がislandになっているのは稀。小規模islandを判定して物理接続に基づく系統構築を」。
  誤差相殺の罠(台帳100/102)への処方箋として feedback_osm_trust を一般化
- **配電層A/B(負の結果)**: `min_voltage_kv` 22→6.6 で東京 n_components **299→299不変**
  (追加線+4は主成分吸収のみ)。現OSMデータに配電層が存在しない(22kV未満12本のみ)
  ことを定量確認 — 「電圧フィルタを下げるだけ」では島は減らず、島ごとの実在線取得が要る
- **島判定診断器** `scripts/d4_island_audit.py`(計測のみ・本番不変): 各島の主系統最寄り
  距離+電圧ペアで層別。東京298島 = near(≤1.5km)**87** / mid 107 / far 104。
  near87 = same(同電圧近接)**30** / cross(異電圧)24 / unk(不明絡み)33(最多 66→66=24)
- **再現性バグを発見・修正**: `nx.connected_components` の set順序依存でタイブレークが
  ぶれ same が 27↔32 で揺れた → `main_ids` ソートで決定化(2回実行で一致確認)。
  オーナー不可侵条件「再現性を崩すな」に直結する自前ツールの欠陥
- **same島の根本原因3分類**(OSM実在線との照合): ①別々の線の端点が近接未接合 ~14
  ②100m内にOSM線なし(line_centric座標ずれ/変電所内吸収) ~14 ③同一OSM線が
  電圧クラス分割で分断 ~4(うち混在電圧`;`線3)
- **③の機構を特定**: `_parse_voltage_kv` は **max-voltage parser** のため混在電圧線
  (例「東富士線;富士岡線」154000;66000)は **154kVに丸められ**、Pass Bで全頂点が
  `S|sid|154` ノード化 → 66kV単独線(富士岡線)とは `|66` で繋がらず66kV島が残る。
  物理的に実在する66kV回線の接続が max丸めで喪失している
- **本番不変・修正は次反復(I6)へ**: 混在電圧線の各クラス展開(D2のインピーダンス
  二重計上回避を維持)/端点未接合のOSM続き確認/座標ずれ診断を**慎重なA/Bで**。
  過去の3,365誤接続の教訓から接合距離の安易な拡大はしない。
  診断JSON `docs/reports/island_audit_tokyo_2026-06-13.json`

## 2026-06-13 — **Fable 5** — T1: メリット順グリーディはトレードオフで非採用(負の結果) — ループ終了総括（102）

- **T1実験**: バンドスケールアップを「余力比例」→「メリット順グリーディ(大型優先・
  銘板内充填)」に変更 — 仮説=実運用は少数ユニット高負荷であり、合法的集中が
  trunkを回復するはず
- **計測結果(トレードオフ)**: trunk 0.552→**0.637(+0.085回復)** だが
  **154 0.220→0.111(-0.109崩落)**。154は「肝」(オーナー宣言)であり、
  物理的根拠なしのブレンド係数は誤差相殺への退行 → **非採用・revert**(13a維持)
- **真の解をキュー化**: 発電所別の実稼働率(電力調査統計の年間CF等)でユニット
  可用性を実証ベース化する — 集中度を「合わせる」のでなく「測る」(T1b)
- **ループ終了**(オーナー許可): 台帳83〜102の20反復・26時間。最終状態 —
  正準13a(interior 0.441/trunk 0.552/154 0.220/**66 0.197=史上最高**)・
  4島AC・銘板超過0・誤接続0・名前マッピング完備・西側実測帯32本・
  孤立: 東京4.72%(0.1%プログラムはI3続き/I5 floor宣言が残課題)。
  負の結果6件を正直記録(chase/JR誤診/T1ほか) — 誤差相殺を3箇所で検出・解体
  したことが本ループの最大の方法論的成果

## 2026-06-13 — **Fable 5** — MATPOWER名前マッピング完備(issue #26)+時系列DB計画起票(#27)（101）

- **オーナー要望**「.csvに発電所名・ブランチ名…DBにするための機械処理」=issue #26の実装:
  `_pd2ppc_lookups`で行整合した3サイドカー — `{island}_busname.csv`(BUS_I,name,
  base_kv,zone,lat,lon)・`{island}_branchname.csv`(row,F_BUS,T_BUS,kind=line|trafo,
  name,parallel)・`{island}_genname.csv`(row,GEN_BUS,kind=slack|gen,name,fuel,PG,PMAX)
  +**mpc.bus_name**(MATPOWER公式オプションのcell array、loadcase互換)。
  補償スラックと実発電機が名前で区別可能に(PV含む全電源が出力される)
- 全国再エクスポート: 4島AC・roundtrip維持(east dVA 0.30°/west 0.43°)。
  沖縄検証例: 金武火力(coal600)・那覇高安線(parallel=2)・leadin来歴も名前列で追跡可能
- **時系列DB化を計画起票(#27)**(オーナー指摘「まだ時系列DBになっていない」):
  DuckDB/Parquet層+既存コネクタ(nas03/jepx)のシンク+帯値の一致再現を受け入れ基準に
- **伊豆PV論点**(オーナー「PVも入れた方が?」): 伊豆・静岡東部のモデル内電源2,670MW
  (solar 820/hydro 550/coal表記1,300=誤帰属疑い)。#6(P03エンリッチ)へ
  「伊豆を最優先適用地域に」コメント — 分散注入が放射先端vmを直接持ち上げる

## 2026-06-13 — **Fable 5** — 銘板218%バグの発見と修正 — 千葉の幻12.4GWを解消、66kV ρ史上最高/trunkの誤差相殺が露呈（100）

- **オーナー質問**「千葉は発電所もあるからこんなに電圧落ちる?」の調査で発見:
  千葉湾岸の母線vmは実は健全(min 0.978)・地図の橙は都心内陸・最低域は静岡(伊豆)。
  しかし**富津が銘板の218%(12,423/5,693MW)で単独運転・姉崎/千葉/袖ヶ浦/KSCが0%**
  という非物理ディスパッチが発覚
- **真因**: _apply_fuel_bandsの**乗算スケールアップ** — coal>p95の余剰をgasスイングが
  吸収する際、満杯ユニットも比例倍率で銘板を突き抜けた。**修正**: スケールアップは
  余力(headroom)比例配分+ユニット銘板クリップ(_scale_units、ダウンは従来の乗算)
- **効果**: 銘板超過0・千葉艦隊が物理分担(富津51%・姉崎/千葉/袖ヶ浦23%ずつ)・
  正準最大ミスマッチの**新袖ヶ浦線 7,770→2,098MW**(幻の貫流が消滅)
- **正直な代償の記録**: 新正準13a = interior 0.441/**trunk 0.552(0.669から急落)**/
  154 0.220/**66 0.197(史上最高)**。trunkの旧高値は幻集中が**誤差相殺**で支えていた
  ことが露呈 — 銘板は物理の絶対制約のため修正維持、trunkの次レバー
  (ユニット可用性・効率順メリット)をキュー化
- 地図のvm色階調を細分化(<0.80深紅/0.85/0.90/0.95 — オーナー要望「0.9一律赤は
  見づらい」、national_map/uc_map両方)。**1103 passed**

## 2026-06-13 — **Fable 5** — I2/R6: 「JR自営網」は誤診 — 真因は越境流入、縄張り+周波数規律で浄化（99）

- **I2の検証で仮説が訂正**: 信濃川系断片(長野・新潟)のoperatorは**中部電力PG(60Hz)・
  東北電力NW・無タグ**であり、JR自営網ではなかった — bulk取得が供給区域外まで
  取り込んだ**越境流入**が真因(JR説は撤回・除外フィルタ不要と判明)
- **規律の実装**: bulk受理に①地域の同期網テスト(_freq_excluded同基準)
  ②縄張り規律=「他地域extractに既在 かつ 自網基底から>2km遠」のみ除外
  (一律除外版は県境の正当な東電設備まで削り192本へ悪化 — 精密化で訂正)。
  既存サプリへ遡及浄化: 線489→218(周波数142+深部縄張り129除去)・変電所170→77
- **正直な再評価**: 東京孤立=**189本/4.72%** — R5の164は誤周波数ブリッジ(60Hz線が
  断片を偽接続)込みの過小だったと判明。現値は規律済みの誠実な基準
- 0.1%への残り工程の見取り図更新: ①タイル4,4回収(Overpass不調継続中)
  ②残135断片の最終分類(名称ペア/クラム/真のOSMギャップ) ③kansai/chubu以下への
  bulk同型展開 ④クラムfloor宣言(I5)。**1103 passed**

## 2026-06-13 — **Fable 5** — I3ラウンド5: 東京孤立 270→164本 — 名称由来クラス採用+発電所アンカー+変電所追補の複合で率が基準割れ（98）

- **緑区~川尻型の解錠**: 両変電所は基底に存在、孤立の真因は線がkv不明で
  namebindの own>0 ガードに弾かれること → **名称が主張する変電所のクラス(66kV)を
  名称由来のクラス証拠として採用**して束縛(unknown→unknownは引き続き禁止 —
  west病理ガードは維持)。沖縄でも1先端が救済(ピン更新: junctions 21→20・
  buses 97→96・components 7→6、計測値コメント付き)
- **bulk拡張**: 5×5細分+同タイルで power=substation(+56追補、計170)と
  **power=plant** を取得(`{region}_plants_supplement.geojson`、_layerの汎用
  マージで自動取込 — 発電所アンカー断片の解消)。1タイル(4,4)はOverpass不調で
  スキップ(再実行で回収可と記録)
- **東京孤立: 270→164本(3.96%)** — カバレッジを線436本・変電所170箇所ぶん
  拡大した上で、率は元の4.03%(153本)を**下回った**。断片141→119
- 残119断片の見取り図: JR信濃川系自営水力網(新潟・長野=I2系統外判定へ)・
  西フリンジの残り(タイル4,4回収+もう1ラウンド)・kv不明クラム(I5 floor宣言へ)
- **1103 passed**・基底extract不変

## 2026-06-13 — **Fable 5** — I3ラウンド2-4: バルク補完で「フリンジ地帯の丸ごと欠落」を発見 — 線436本+変電所114箇所を回収（97）

- **chase(端点300mホップ)は棄却**: 3ラウンドで+44ウェイ/完結8端のみ・孤立162→192と
  逆効果(長い回廊を300m刻みで追うのは遅すぎ、横の断片を増やすだけ) — 正直記録
- **バルク補完が正解**: 地域bbox 3×3タイルで power=line|cable 全量→幾何差分。
  **+436本が西側カラムに集中**(+84/+132/+95 vs 中央+0〜1) = **山梨・静岡フリンジ
  (東電50Hzエリア)が元抽出から地帯ごと欠落**していたと確定。コア東京は完全
- **線だけでは孤立悪化(453本/11%)→変電所の同時補完を追加**: 同タイルで
  power=substation(way+node)を取得、+114変電所(`{region}_substations_supplement
  .geojson`、_layerの汎用サプリマージで自動取込) → 孤立453→**270本(6.5%)**。
  残141断片=西フリンジ92+「緑区~川尻」型の名称ペア+**JR信濃川系の自営水力送電網**
  (新潟・長野、系統外候補)+kv不明クラム227本
- 重要な再解釈: 孤立率の上昇(4.0→6.5%)は**カバレッジ拡大による分母質の変化** —
  モデルは実在の線436本・変電所114箇所ぶん「日本に近づいた」。0.1%への残り工程=
  フリンジ完結ラウンド+JR自営網の系統外判定(I2)+クラムのfloor宣言(I5)
- 1103 passed・基底extract不変・サプリは追加専用(ODbL帰属付き)

## 2026-06-13 — **Fable 5** — I1-I3: 孤立0.1%プログラム開始 — 全数センサス+サプリメント機構+第1ラウンドの正直な過渡増（96）

- **オーナー指示**「孤立が0.1%になるまでループ」(現状4.8%=783本→目標≤16本)。
  方針=**接続が先・除外は最後**(灰色線指示と整合)・捏造禁止
- **I1 全数センサス**(`orphan_census_2026-06-13.json`): 487断片の内訳 —
  kv不明クラム373本(48%)/kv不明断片228/近接(3km内)102/遠隔61/鉄道系19。
  支配的なのは「電圧も接続も証拠が無い小破片」
- **I3 試掘で抽出漏れを実証**: 東京断片の周囲400mに**真の未取得ウェイ21本**
  (275kV佐久間東/西幹線・154kV東千葉房総線・早一線・笹目線等の幹線級!) —
  元extractのbbox/フィルタ漏れが孤立の実因の一つと確定
- **サプリメント機構を実装**: `data/{region}_lines_supplement.geojson`
  (追加専用・来歴付き・ODbL帰属、ビルダーが自動マージ — 基底extractは不変=
  データ規約遵守) + `scripts/fetch_orphan_supplements.py`
  (around試掘+名称回廊補完の2パス・wayIDでdedupe・再実行安全)
- **第1ラウンドの正直な結果**: 東京+9ウェイで孤立153→**162本(過渡増)** —
  400m一発では「断片が伸びるだけで系統に届かない」。連鎖完結には
  端点追跡ラウンドの反復が必要(設計どおりの中間状態として記録)。
  深夜のOverpassスロットル(private.coffee 3/5チャンク失敗)も制約 —
  夜間wakeupで礼儀正しい間隔の取得ラウンドへ移行
- 1103 passed(サプリ機構はopt-in的: ファイル不在地域は完全無変化=沖縄ピン不変)

## 2026-06-12 — **Fable 5** — D10: 線中心座標の採用 — 母線を「線が収束する点」へ(オーナー指示「線を基準に」の具体化・95)

- **オーナー指示**「物理的に線と点はOSMがいい。潮流計算基本というよりは**線を基準に
  している方がかなりいい**」の直接実装: 線頂点を束縛した変電所の母線座標を
  **ポリゴン重心→束縛点群の平均(線終端クラスタ)**へ(`line_centric_coords=True`)。
  束縛なしの変電所(leadin/namebind給電・孤立)は重心を保持
- 効果の構造: 描画と電気が**同一座標**を共有(吸着区間の視覚ズレが原理的に消滅)・
  境界配置(位置フォールバック)も線実態に寄る
- **ゲート全層クリア**: interior ρ 0.454→**0.458** / trunk .669→.671 / 154 .216→.214
  (誤差帯内) / 66 .168→**.175**。recall 57.7→57.6%(ノイズ内)。**1103 passed**・
  沖縄ピン不変(カウント非依存=座標のみの変更)。電気解は座標非依存のため4島ACは
  namebind世代の検証がそのまま有効
- 全国図の vm注記をライブ値(summary.json集約)へ — 台帳63のハードコードが同日中に
  陳腐化していた正直性修正。最新全国図(16,242本・4島AC・east0.61/west0.67)をLINE納品
- 本日の孤立線全国計測(ユーザー依頼): **783本/16,242 (4.8%)・487断片** —
  東1〜4% vs 西6〜8%のマッピング非対称を定量化

## 2026-06-12 — **Fable 5** — F5/X3: UC時系列の帯判定intakeを実演しHANDOFF文書化 — UCの断面ビンテージ差を独立検出（94）

- **X3実演**: 隣UCの実出力(fy2025r1・2023-12-13関西断面、PR #23の検証JSON)から
  日量→時平均MWでintake CSVを生成し `ajgrid reconcile --uc-csv` に通した —
  demand帯内・**nuclear 6,578MW >p95(4,883/5,636)**・hydro/thermal_combined <q50。
  nuclear帯外はfy2025r1の原子力断面(6.6GW)と検証日実勢(4.9GW平均)の
  **ビンテージ違いを正しく検出**(UC側ledger 22と同結論に独立到達=計器の交差検証)
- **F5文書化**(docs/UC_HANDOFF.md): 3列契約(area,metric,value_mw)・metric語彙に
  `thermal_combined`を正式追加(関西・中国は合算公表)・帯の出典3系統
  (東京=TSO 12ヶ月/西3=nas03/需要=OCCTO)・「帯外=エラーでなく前提差を述べよの
  シグナル」という読み方を明記
- **HANDOFF鮮度修正**: 「westはAC不成立・ゾーナルDC推奨」の旧記述を
  全島AC(63/85/91)の現状+vm品質注意へ更新
- F/X/Sトラックの未完了[ ]はこれで**全消化**(残=D4/D5の配電層のみ+P凍結)

## 2026-06-12 — **Fable 5** — S3: 連系線±20%感度スイープ — 東京=輸入が混雑を単調緩和/関西=非感応の構造差を計測（93）

- **方法**: 実測interconnect統計(p95/signed_q50)をローダパッチで×0.8/1.0/1.2して
  DCソルブ(関西・東京×3、本番コード無変更)。過負荷/負荷率は実在線のみ
  (`s3_interconnect_sensitivity_2026-06-12.json`)
- **東京: 輸入緩衝構造** — 輸入4,925→7,387MWで実過負荷18→9本・超過計165→80pp
  (単調)。混雑は域内発電の送出回廊にあり、+1.2GWの輸入が4本/-60ppの限界価値。
  逆に-20%は+5本/+25pp — 連系線停止時の東京の混雑リスクの定量初値
- **関西: 非感応** — ±20%で過負荷2〜3本・max≈119%・超過23〜40ppとフラット。
  関西の残存混雑は連系線経路から独立した局所ボトルネック(=設備対策/キュレーション
  対象であり運用(融通)では解けない)
- 共通: p95負荷率は両域80%で不変 — 全体ストレスではなく回廊特異の混雑。
  関西の地域単体ACは3係数とも不成立(島ソルブではAC=OK — 地域スライスの既知性質、
  スイープはDC計器)
- UCは別開発のためDC感度まで(PLAN記載どおり)。混雑「コスト」化(¥/MWh)はJEPX
  接続済みのUC側資産と将来結合可能と注記

## 2026-06-12 — **Fable 5** — 新模型(12e)での計器再計測 — recall全帯改善、関西連結率は「偽接続込みの旧値」を訂正（92）

- **接続recall(東京・対東電開示1,057対)**: attachment 56.3→**57.7%**、帯別 154
  61.3→**66.4%(+5.1pp)** / trunk 60.8→62.6% / 66 53.1→53.6%。line exact 54.9→58.1%・
  loose 74.7→75.8%。OSM忠実束縛+名称束縛は**真実比較でも一様に正方向**
  (`external_match_tokyo_tepco_banded_2026-06-12.json`)
- **関西上位網連結率の正直な訂正**: 再現定義で**91.1%**・真の孤立ポケット66
  (旧94.6%/12)。見かけ悪化だが、**旧値は盲目半径の偽接続(3,365本クラス)が
  ポケットを上位網へ偽連結していた数字** — de-fuse後の91.1%が誠実な現在地。
  W gate(95%)までの3.9ppは本物のキュレーション/OSM編集課題(W5リスト続行)。
  注: 旧計測はインラインで方法未コミットのため厳密同一定義ではない(越境box除外で再現)
- **健全性証明書12b再発行**(`national_health_2026-06-12b.json`): 関西の燃料帯が
  新実測帯で判定可能に — nuclear/solar/hydro/biomass帯内・thermal合算とinterconnectは
  p95縁(p95需要断面として整合)・wind過少。境界util 9本DB導出は維持
- 教訓の追記: **「良い数字」が偽構造に支えられていないかは、構造を直すまで分からない** —
  ρ(154 2.3倍)とrecall(+5.1pp)が上がりながら連結率が下がる組み合わせこそ、
  de-fuseが正しく働いた証拠

## 2026-06-12 — **Fable 5** — east vm究明→**名称証拠束縛の採用** — 伊豆チェーン回復・west vmin 0.57→0.67・66kV ρ 史上最高0.168（91）

- **east vm_min 0.671の帰属(出発点)**: 沈下は**伊豆半島に局在し既存バスの悪化**
  (安良里0.891→0.667、共通3,520バス中785が-0.05超) — 「新規の正直な放射」ではなかった。
  消えたエッジを精査すると線名が「三島変電所~函南町変電所線」等**接続を明言する命名** —
  山岳部はOSM描画が1.1〜2.3km手前で止まり(=「山の中は薄い」の実体)、旧盲目半径は
  これを偶然拾い、ポリゴン束縛が落としていた
- **名称証拠束縛**: 未接続のdeg-1先端に対し、入射エッジの線名が主張する変電所
  (正規化完全一致・≤5km)へ"namebind"エッジで束縛。**2つの失敗から学んだ設計**:
  ①頂点ループ全終端版は回廊中間セグメント(同名連続ウェイ)が両端を同一所へ束ね
  **トランク短絡**(trunk ρ .666→.623)→ deg-1限定で解消(中間端はdeg≥2)
  ②kv不明先端の束縛が0クラスノードを生み**west AC崩壊**(旧変圧器病理の再生産、
  6°プルーンでも不可) → own>0ガードで治癒(リードインと同じ規約)
- **最終ゲート(全層クリア)**: 新正準 `external_flows_tokyo_full_2026-06-12e.json` —
  interior **0.454**(+.017) / trunk **0.669**(+.003) / 154 0.216(±0) / **66 0.168**
  (+.035、12a比では0.137→0.168)。4島AC=OK・**west vmin 0.568→0.668に改善**
  (正名称接続が放射を短縮)・沖縄vmin 0.908→0.922。namebindは東京48本の外科的追加
- east vmin 0.626(安良里)は接続回復後も残る**実在の西伊豆放射の弱さ**(島ゾーン配分との
  複合、S2先例の正直な物理)として記録。ピン更新(沖縄76/21/98/7/37/5・smoke97/85/16、
  prop 1→0=最後の未タグ区間が名称束縛経由でタグ回廊へ併合)。**1103 passed**

## 2026-06-12 — **Fable 5** — D7: ライブマップ国家ビューを現行モデルへ移行+ybus gateリトライ還流 — 接触率81.3%→**98.0%**（90）

- **国家ビューの正体と移行**: index.htmlの国家ズームはレガシー2189バスpsdat座標
  (all_ac_buses)+作者不明のroutes_*タイルだった。viewer(powerflow.js)の期待スキーマ
  (vm_pu/vn_kv、routes側kv/name/region/loading)は現行スライスと互換と確認 →
  **JS無改修でデータ置換**: ①`gen_all_ac_buses.py`(powerflow_national 10地域の合併、
  1,732→**14,698バス**=全島ACモデル) ②`gen_route_tiers.py`(routes_500〜66kvを
  build_network_snappedから再生成、計16,345本。タグ無し線は66層=台帳89整合)
- **接触率の往復で規約を再確認**: 旧81.3%→新バスだけ置換66.8%(タイルが旧世代)→
  タイル再生成63.6%(生OSM端点のまま)→**端点ノード吸着で98.0%**。
  「経路の端点はノード座標に吸着して初めて接触=接続として読める」(82/85の規約)が
  タイル生成にも必須という教訓
- **ybus gateリトライ還流**(UC⑮main還流①の解、隣の--gate-retriesパターン):
  `gate_region(retries=2)` — 閾値際の1ノルム推定ゆらぎ(同一入力で4.84e8/1.13e9実測)
  はFAIL時のみ再構築・再計測、全attemptのcondを記録(正直性)。PASS側DCは保守的
  (gate PASSなら収束実証済み)なので信号でなくノイズの除去
- Playwright実画面検証: 国家ズームに14,698バスが描画(レガシー比8.5倍の密度=実態)。
  **1103 passed**。worktree(8765)問題はD7移行で本質解消(正データはmain配信側)

## 2026-06-12 — **Fable 5** — D8: 灰色線の階級確定 — 証拠ベース伝搬は既に飽和と判明、「66kV扱い」の開示描画を採用（89）

- **全国計測**(生feature段): kv不明5,932本 → 端点分析で「両端一致160/片端1,968/
  証拠ゼロ3,703(62%)/曖昧101」。ただし**片端パターンと両端一致の大半は既存Pass A.5
  (頂点和集合=1クラス)が回収済み**と判明 — 当初の「回収可能2,128(36%)」は
  和集合=1クラスのケースとの重複計上で、実増分はごく僅か
- **v2(a)実装**(和集合が多クラスでも両端の見えるクラスが一致すれば採用、kv_src=prop2):
  東京の灰色182→**180**(-2)。曖昧(多クラス端)は引き続き不採用=捏造禁止。
  prop2を_KV_RANKに登録(prov正直化)
- **本質の発見と開示描画の採用**: kv不明線は**ソルバ内で既に66kVパラメータとして参加**
  (ビルダのfallback)。灰色描画は「66扱いの現実」を隠していた → 系統図で
  **66kV色+点線「66kV扱い(タグ無し)」**に変更(ユーザー指示「灰色線が必ず送配電線に
  なるように」の実態整合的な充足 — 模型は変えず開示を直す)
- 残る灰色の正体: 証拠ゼロの孤立断片(東京180/関西227/中部423本) — 隣接クラスに
  触れないミニ網で、地域既定クラスのguess付与は**見送り**(捏造境界。これらは
  W2ポケット分類と同族でOSM編集/キュレーション行き)
- ゲート: ρ(12d比)4層維持〜微増(interior .440/trunk .667/154 .216/66 .139)・
  **1103 passed**・多電圧回帰なし

## 2026-06-12 — **Fable 5** — D9: 経路ジオメトリ「再キー化」仮説の棄却 — 実在線は経路100%忠実、真因は閲覧側の旧データ（負の結果・88）

- **オーナーQA**(富浜→梁川→八ツ沢「線が線上にない」「不一致は追えば大量」)の系統調査。
  仮説「ポリゴン束縛でgeomルックアップのキーが外れ直線増」は**計測で棄却**:
  tokyo地域90.7%/east島90.2%のヒット率の残り≈10%は**全て構内スタブ(393本)** —
  実在線のミスは**0本**。前回の「44%フォールバック」は2頂点の本物ルートの誤計上だった
  (計測の自己訂正)
- **大月bbox実査**: 実在線17本中15本が多頂点実経路を追従。2点直線2本のみ
  (東電PG66kV 0.58km1本=OSM側2頂点疑い→キュレーション対象)。八ツ沢線群/富浜線/
  駒橋線/梁川分岐線は全て66kVタグ取得済み・梁川=分岐線T分岐(本線東抜け)も正
  ・道志川線77kVはOSM直接タグ=幻ではない
- **ユーザー観察の真因=閲覧データの鮮度**: localhost:8765はworktree(隣セッション)配信で
  powerflow_nationalが**台帳82時点のまま**(セッション終結により更新停止)。現行正準は
  8766。ズーム検証画像をLINE納品し8766での再確認を依頼
- 残る実精度課題の整理: D8(灰色線182本/245kmの階級確定)・山岳部のOSM頂点粗さ
  (W5編集リスト行き)・0.58km直線チョードのような個別キュレーション
- 教訓: **「どの画面のどのデータか」を最初に確定する** — モデルの欠陥と配信の鮮度は
  別問題で、混ぜると誤った修正(再キー化)に走るところだった

## 2026-06-12 — **Fable 5** — X2-2: 境界注入の実測正味再スケール採用 — 関西7倍輸入を解消し、東京正準ρも4層全改善（87）

- **真因**: 回廊中央値由来のutilisation(ic_006=-1.0等)が**ループフローを正味と誤読** —
  関西の回廊和+6,160MWに対し実測正味(nas03 TSO需給表)は+865MW(中央値)。
  関西-中国(東2,756+西2,266)の~5GWは通過流で、エリアが呑む量ではなかった
- **実装**(`apply_boundary_imports` net_rescale、既定ON・fail-soft): per-IC比率
  (配置証拠)は保存し、**正味だけを実測の需要条件付きp95**へ一係数で再スケール。
  目標がp95なのは、パイプラインの断面=設計ピーク×LF≒実測p95需要であり、
  輸入は需要と相関するため(中央値目標のA/Bでは解放5.3GWが火力に流れ込み
  14.2GW>p95帯と過補正 — 分位整合の教訓)。符号反転は捏造として拒否し記録のみ
- **A/B判定(採用)**: 関西 interconnect 6,160→**2,714=実測p95丁度**・thermal合算
  4,377→**12,359(p95+5%、p95需要断面として整合)**。東京は正味3,405→6,156
  (実測p95)で**正準ρが4層全部改善**: interior .429→**.437**/trunk .647→**.666**/
  154 .215→.216/66 .131→.133 → 新正準 `external_flows_tokyo_full_2026-06-12d.json`
- **X2最終判定材料**: 輸入過多の半分は境界較正で解消。残る火力の**gas/coal構成比**は
  関西実測が合算のみで審判不在 → capacity_bridge採用は引き続き保留(計器待ち)が正直
- テスト: 既存3箇所にnet_rescale=False明示(生値ピン)+再スケール単体テスト新設。
  **1103 passed**。島ソルブ(国家)はboundary不使用のため影響なし
- オーナーQA対応(富浜・梁川・八ツ沢、台帳88候補): 当該線は全て66kVタグ取得済み・
  梁川は「分岐線」T分岐として正しい・八ツ沢77kVはOSM直接タグ(道志川線)。
  **本丸=D9**: ポリゴン束縛でバス座標が変わり経路ルックアップのキーが外れ
  直線フォールバック増(「線が線上にない」の正体)→geom再キー化。
  **D8**: 灰色線182本/245km(東京4.8%)の階級確定(「灰色線が必ず送配電線になるように」)

## 2026-06-12 — **Fable 5** — F7: nas03西側燃料別較正 — 関西/中国/北陸の実測帯がDBに入り、関西の「輸入過多・火力過少」を初の実測根拠で特定（86）

- **在庫の実地確定**(ssh調査): chugoku=月次2016〜(独自列名)・kansai=月次〜2023-12
  (隣PR#23のlegacyパーサ対応済)・hokuriku=**202404以降**(FY2023指定では空振り→FY2024で取得)・
  **chubu=需要のみ**(`dt,MW`、燃料別なし=正直に不可)・**kyushu=H29(2017)四半期のみ**
  (8年前の帯は運用較正に不適=不可)。西側の燃料別カバレッジ上限は関西/中国/北陸と確定
- **chugoku方言を最小差分で追加**(`nas03.py` _FUEL_COLUMNS拡張のみ): 需要/火力(合算)/
  太陽光(実績)/連系線潮流 — 長キー優先照合で既存6社の挙動不変(テスト8 passed)。
  「火力出力制御量」キーを先置きしhokkaido変種の誤マップも予防
- **intake実装**(`calibrate.py --nas03 <companies> --nas03-months`): dataspaceコネクタ経由
  (キャッシュ+来歴)で月次を取得し、**30分/1時間生値のプール分布からq50/p95**(tso_jukyu
  と同一統計量=帯の互換性)。DB搭載: **関西9+中国9+北陸14=32帯**(gen_by_fuel:*、
  source=nas03_demand_raw)。北陸はwest島初のper-fuelフル帯
- **reconcileに火力合算チェック**: gas/coal/oil個別が無くthermal_combinedがある社は
  モデルのgas+coal+oil合計を帯に通す(関西・中国向け)
- **F4関西の初実測判定**(reconcile_kansai_nas03_2026-06-12.json): 帯内4(nuclear=p95丁度
  =F6クランプ作動・hydro=q50丁度・solar・biomass) / **構造的な対の歪みを特定**:
  interconnect 6,160MW(帯[980,2,714]**超過**) × thermal合算4,377MW(帯[7,276,11,741]
  **未満**) = モデルは輸入に頼りすぎ火力を焚かなすぎ。wind微小(10vs26)
- **X2 west採用の判定材料**: 関西の歪みは容量配置(capacity_bridgeの守備範囲)と
  境界利用率の両方に跨る — bridgeのwest補正(-35.3GW)単独では輸入過多を説明できず、
  **境界キャリブレーションとの同時A/Bが採用条件**(次反復候補)
- **1101 passed**(nas03テスト+2)。生データ非コミット(キャッシュはdata/cache、gitignore)

## 2026-06-12 — **Fable 5** — D6-2: west AC回復→**OSM忠実束縛をデフォルト昇格** — 4島AC維持×154kV ρ 2.3倍を両立（85）

- **真因=プルーン梯子の不足(仮説bが正解)**: 84のwest AC非収束は (45,30,20)°の梯子が
  浅すぎた — de-fuse後の島は正直な長い放射を含み角度広がりが20°超。**12°段を追加**
  (23本プルーン)で収束。仮説a(joint/leadinの極短エッジ特異性)は**棄却**: 長さフロア
  0.05km のA/Bで vmin がビット一致(0.56777229 = 0.56777236)=無関係
- **新しい谷の帰属確認**: vm<0.7 は9バスのみ(四国7+北陸2)、接続線は**全てnormal**
  (leadin/recon起因ゼロ) — S2で確定済みの島ゾーン配置×放射の正直な物理。west maxload
  は226.6%→**190.2%に改善**(偽並列経路の除去で実在線への集中が緩和)
- **デフォルトON**(polygon_bind=True, tip_joint_km=0.12, leadin_km=1.5)+梯子拡張は
  pipeline.py / solve_island の両方(旧モデルは20°で収束済みのため拡張は休眠)
- **4島フル検証: 全島AC=OK** — hokkaido[0.819,1.028] east[0.671,1.054]
  west[0.568,1.066] okinawa[0.908,1.010]。不可侵資産(台帳63)を新束縛下で再達成
- 正準スコアカード更新: `external_flows_tokyo_full_2026-06-12c.json` —
  interior 0.429 / **trunk 0.647 / 154kV 0.215 / 66kV 0.131**(12aから trunk+0.032・
  154 **+0.120**・66 -0.006誤差帯内)。ピン更新(沖縄74/28/98/10/35・smoke102/92/14・
  evidenced床0.38、いずれも計測値コメント付き)。**1099 passed**
- 成果物再生成: powerflow_national(全島AC状態)・after系統図(孤児162/スパー627の
  2クラス+並列幅初適用、cable捕捉47→166km)。before(84)/after(85)ペアをLINE納品
- 残課題キュー: east vm_min 0.89→0.671 の沈下帯の地理特定・recall/W連結率の新模型での
  再計測・国家ビューのpowerflow_national移行(D7)

## 2026-06-12 — **Fable 5** — OSM忠実束縛(polygon_bind)の実装とA/B — **154kV ρ 2.3倍**、ただしwest AC非収束でopt-in退避（84）

- **オーナー指示**「まずはOSMにちゃんと忠実に系統作ってほしい」「物理的に明らかに存在する線を
  繋げばいいだけ」「再処理みたいなこと考えて」を受けた本丸改修。3部構成で実装
  (`snapped_topology.py`, いずれもopt-in引数):
  ①**polygon_bind**: 頂点束縛を盲目半径(内部1.5/端2.5km)→**変電所ポリゴン内/縁150m**
  (端点はポリゴン縁0.6kmまで)へ ②**tip_joint_km**: deg-1先端→同クラス最近ノード(120m)の
  点間ジョイント(並走回線は対象外=融合しない) ③**leadin_km**: それでも未給電の変電所へ
  最寄り通過セグメント近端から**明示"leadin"エッジ**(1.5km・kv整合・線名で監査可能 —
  旧盲目半径が暗黙にやっていた給電主張の可視化)
- **オーナー報告の3クラスを全て確認・対処**: (a)誤接続=実在3,365本(経路が変電所に1km未満
  接近せず)→**0本** (b)近接未接続=4-6mの丸め分割ペア実在→tip_joint (c)「北総で全部無視」=
  **取り込み済みの並列集約だった**(275kV 4回線+66kV 6回線×2回廊→3エッジ。OSM 14ストローク
  vs 描画3本の知覚差)→系統図の線幅にnum_parallel反映で対処
- **tokyo A/B(scorecard: external_flows_tokyo_polygon_bind_AB_2026-06-12.json)**:
  trunk ρ .615→**.647** / **154kV ρ .095→.215(2.3倍 — ユーザー宣言「154が肝」の層)** /
  66kV .137→.131(誤差帯内) / interior混合 .454→.429(階級混合効果)。物理変電所の喪失ゼロ
  (1,705=1,705)・偽クラスノード414剥離・tokyo AC/DC収束・Ybus gate 4.66e8 PASS
- **ブロッカー(正直記録)**: 国家4島ソルブで **west島 AC=FAIL**(DC=OK)。全島AC=不可侵の
  再現性資産(台帳63)のため、**デフォルトOFFへ退避**(既定動作=旧来と沖縄ピン一致・1097緑)。
  east AC=OKだがvm_min 0.89→0.67の悪化も要因分析対象。**D6-2**=west AC をpolygon_bind下で
  究明・治癒→デフォルト昇格(154の改善は重大で放置しない)
- 副修正: 系統図の並列回線幅(render_grid_figure)・沖縄vmin 0.647→0.908(opt-in時、
  北部スパー接続の改善)

## 2026-06-12 — **Fable 5** — D6: 浮き端の再分類 — 87%は接続済みスパーと判明、延長スナップ機構は不要（前提が覆った負の結果・83）

- **設計前の診断で前提が崩壊**: 「浮き端=未接続」586箇所(東京)をBFS到達可能性で再分類 →
  **接続済みスパー512(87%)/真の孤児74(13%)**。shikoku 156/48(76%スパー)・chugoku 334/87(79%)。
  スパー=頂点スナップの無害な残骸(端点2.5km/内部1.5kmの非対称が、変電所へ収束するウェイの
  「半径外の中間頂点」を行き止まり支線として残す — 木内線で機構を実証: J(1.65km地点)の
  唯一の対端は木更津変電所そのもの=接続済み)
- **発端の2例も解決**: 木更津=スパー(ウェイは変電所内に到達済み)・**江東500kVケーブルも
  スパー**(チェーン他端が系統に到達)。「OSM上で繋がって見える」というオーナー直感は正しく、
  モデルは見かけより遥かに健全だった
- **真の孤児の中身**: ≤3km回収候補は tokyo 8/shikoku 4/chugoku 11 — ただし中身は
  kv不一致(筑館線66→下妻154等)・鉄道/工場フィーダ(小田急松田・エムエーパッケージング)・
  kv不明の2-4ノード欠片。**証拠級の接続候補はほぼゼロ → 延長スナップ機構は実装しない**
  (捏造禁止規約。残りはW2ポケット分類=ノイズ/OSM欠落と同族でW5キュレーション行き)
- **台帳79の増幅要因説を撤回**: 「未接続放射化が低電圧を増幅」のループ閉鎖候補(25/68)は
  スパーだった=閉じるべきループは既に変電所経由で閉じている。西の深い沈下は
  **島ゾーン配置起因(S2)に一本化**
- **traction設計判断(③)**: JR饋電線はスパー(系統側で接続済み・潮流ゼロ)として現状維持。
  traction変電所の負荷バス化は需要配分への影響A/Bが必要なため別反復へ(物理的には保持が忠実)
- 計器の正直化: `--mark-dangles` を2クラス表示に(真の孤児=赤×/スパー=灰×)。
  **before(586無差別)/after(74孤児+512スパー)ペアをLINE納品** — 初回before図の8倍過大計上を訂正
- 教訓: **可視化の係数(マーカー数)を構造欠陥と同一視しない**。到達可能性が先、距離は後

## 2026-06-12 — **Fable 5** — 比較検証と採否確定 — 座標二重系統の修正をmain系へ移植、国家スライス接触48-53%→**100%**（82）

- ユーザー指示「あなたと比較していい方を採用。自身で検証してから判断」への裁定:
  ①診断=両セッション**収束**(「座標の二重系統」と「描画ギャップ」は同一真因の別表現)
  ②uc_map修正=**隣を採用**(台帳81で独立検証済み) ③「mainライブマップも同じはず」(隣の推測)
  は実測で**半分のみ正**: per-region live mapは既に健全(接触100% — `export_powerflow_pages.py`
  に端点吸着+trafo線出力が先行実装済み。隣はmainの既存規約を再発見) / **powerflow_national
  は欠陥実在(接触48-53%)→隣パターンを移植**(`run_national_powerflow.export_region_slices`)、
  再生成で**全リージョン接触100.0%**+trafo線描画(tokyo19/tohoku12/kansai49/shikoku5)。
  4島AC維持(west vm[0.656,1.053]/maxload226.6%不変=エクスポートのみの変更)
- **正直な負の結果**: 国家ズーム点レイヤ(all_ac 81.3%)は端点問題ではない —
  装飾OSMルートタイル(routes_*)+レガシー2189バス座標(psdat case)の**別アーキテクチャ**。
  `gen_pf_geojson.py` への端点吸着は pf_branches には正しいが all_ac は**81.3%のまま不動**
  と実測(初手の見立て違いを記録)。正道=国家ビューの powerflow_national 移行(キュー)
- 還流採用キュー: ①ybus_gateのリトライ機械化(隣の `--gate-retries`、UC⑮main還流①への解)
  ②国家ビューのpowerflow_national移行 ③**現象②=証拠つき延長スナップ**(次反復本命。
  ユーザー新原則「地図データ上で繋がって見える=強い判断材料」をメモリ恒久化済み)
- 計器の標準化: 帯計測(全点×最寄り描画線距離・接触≤0.1km)を浮き点の受け入れ判定に確立
  (79/81/82で3適用)

## 2026-06-12 — **Fable 5** — PR #16(uc_map浮き点修正)の独立検証 — 現象①クローズ（81）

- 並行セッションの修正(端点をバス座標へスナップ、west自己申告438→2)を**台帳79と同一計器**
  (全点×最寄り描画線の距離帯)で独立再計測: east **接触100.0%**(3,867/3,867)・
  west 5,474/5,475(残1箇所のみ)。before=接触50.0%/0.5-1.5km浮き38.5% → **完全解消を確認**
- これで台帳79の現象①(描画ギャップ)はクローズ。残り=現象②(真の浮き端586/204/421 —
  attachment改修待ち、before図586箇所は送付済み)・現象③のtraction設計判断

## 2026-06-12 — **Fable 5** — D3: 実変圧器ノードの密度評価 — 標準ラダー置換は不可（負の結果・80）

- 取得の顛末: フルbbox2連敗→4タイル分割でも kumi 3/4 スロットル → **overpass.private.coffee
  で回収**(tile1 216/tile3 31/tile4 107、tile2=kumi 56)。計410ノード(重複ID除去)。
  教訓: kumi単独依存は脆い — private.coffee が第二経路として実証
- 密度(対 変電所ポリゴン1,687 / モデル多電圧変電所614): ノード保有=103ポリゴン
  (多電圧比の上限16.8%)・**devices保有=9(1.5%)**・voltage:primary=40(6.5%)・
  rating=**1変電所のみ**(0.2%)
- **解釈の罠を記録**: devices分布は"1"×36・"3"×5で、"3"は**新岡部変電所の単相器3台=1バンク**
  (500kV級の三相分単相構成)。バンク数は devices ではなく**ノード多重度**(329ノード/
  103変電所≈3.2基)で読む必要があり、しかもマッピング完全性は検証不能
- **判定: 負の結果 — 標準ラダー(クラス典型容量×並列回線数, transforms.insert_transformers)
  の置換には証拠が薄すぎる**(D3受け入れ規則どおり正直記録)。ただしスポット較正の宝が2箇所:
  **東清水FC**(rating 160-275 MVA×8ノード+275/77kV対 — ic_003変換所モデルの較正材料)・
  新岡部(5バンク×500kV級)→ 個別キューへ
- 計器: `scripts/analyze_transformer_nodes.py`(committed、台帳79のポリゴン基盤を再利用)。
  スコアカード: `docs/reports/d3_transformer_nodes_2026-06-12.json`。次反復=D4(minor_line)

## 2026-06-12 — **Fable 5** — 浮き端・低電圧・地図の浮き点の三者分解 — オーナー質問への計測回答（79・診断のみ/改修は並行セッション）

- **オーナー質問**(木更津・江東の未接続/低電圧/uc_mapの緑点浮遊/「OSMをもっと信頼していい」)に
  計測で回答。**改修は並行セッションが担当 — 本反復はモデル無変更・記録のみ**
- **現象①: uc_mapの「緑点が浮く」= 描画ギャップで構造欠陥ではない**。east_after全3,867点の
  最寄り描画線距離: 接触50.0%/0.5-1.5km帯38.5%/**線皆無0%** — ズレが1.5kmで打ち切られる=
  snap_km=1.5の写像。OSMルート描画(2,619本)だけが浮き、直線フォールバック(2,374本)は接触
  → 吸着区間「最後の0.5-1.5km」を誰も描いていないのが原因。処方=コネクタ線分1本/吸着点へ打点
- **現象②: 真の浮き端(行き止まり線端)**: tokyo 586(1.5-3km帯345)/shikoku 204(浮き端率35%)/
  chugoku 421(32%) — 東京の~3倍の率で**低電圧ゾーンと一致**。kv一致ループ閉鎖候補(<3km)
  shikoku 25/chugoku 68 → 延長スナップが当たれば放射化緩和=**電圧の谷も浅くなる見込み**
  (低電圧の一次要因はwest島ゾーン配置(S2確定)、未接続放射化は増幅要因。UC無関係 —
  merit-order解とUC断面解(UC⑯: shikoku 0.663/chugoku 0.68)が同じ谷=配分非依存の構造性)
- **現象③: 「OSMを信頼」の検証 — ポリゴン仮説は東京では2%**: 浮き端586のうち変電所ポリゴン
  内側/縁150m=11件(2%)・**>500m=575件(98%)=OSM側の真のデジタイズ途切れ**。信頼の上限は
  OSMの完成度(処方=方位延長スナップ/キュレーション/W5編集リスト)。ただし11件が
  **取り込み境界の盲点**を暴露: JR饋電変電所(`substation=traction`, voltage=1500)は閾値で
  正当除外されるが、そこへ至る**66kV饋電線は取り込まれて孤児化**(鵜原/和田浦/安房勝山/太海
  +物井縁150m)。要設計判断=tractionを66kV負荷バスとして保持 or 饋電線も除外
- 取り込み自体は非損失と確認: OSM生1,726 vs モデル物理変電所1,705(差21=traction等)。
  ポリゴン形状は生データに健在(1,686/1,726)で**重心に潰すのは吸着・描画段** — 「点より面を
  信頼」はattachment面(point-in-polygon優先→重心半径フォールバック)と打点位置の改修で実装可
- 改修先(並行セッション向け): 吸着=`src/powerflow/snapped_topology.py`/uc_map描画=
  `scripts/uc_to_pf_national.py` export部/コネクタ・ポリゴン打点・方位延長・traction判断の4点

## 2026-06-12 — **Fable 5** — N7: MATPOWER仕様変換の確認 — 4島.matケース化+往復再ソルブ検証（78）

- **ユーザー指示**「matpower仕様に変換もしくは自動変換できるかも確認」への回答=**可能・自動変換を実装**。
  経路: 正準 `solve_island`(AC) → `to_mpc` → `canonical_mpc` → `.mat`(case v2)
- **`canonical_mpc`** (`src/converter/matpower_exporter.py`): pandapower 3.x の `to_mpc` は
  FACTS/DC表(bus_dc/svc/vsc…)と `internal` 簿記を同梱し loadcase の期待形と異なる →
  正準5フィールド(baseMVA/version/bus/branch/gen)・loadcase入力幅(13/13/21列)へ剥離。
  1始まり連番は to_mpc が保証済みを確認。MBASE の NaN は **MATPOWER仕様自身の
  デフォルト「baseMVA」** を適用(沖縄実ケースで22件、捏造ではなく仕様準拠)
- **基底の正直性修正**: 旧 meta.json は `base_mva: 100.0` と記載しつつ実 ppc は
  sn_mva=1.0 基底だった(虚偽記載)。sn_mva=100 への再基底は結果不変(ΔVA~1e-6°実証)
  を確認した上で再ソルブ→表と埋込VM/VAが一致する100 MVA基底で出力
- **4島すべて往復検証 ok**(`.mat`→`from_mpc`→再ソルブ→元解と比較):
  ΔVM max = hokkaido 9.0e-5 / east 1.4e-4 / west 6.6e-4 / okinawa 1.5e-6 pu、
  ΔVA max = 0.09 / 0.50 / 0.60 / 0.002°。機械精度ではなく再インポート時の
  モデル写像(shunt/trafo再構成)の量子化で、運用差≪1% — ケースファイルとして完全・可解
- 規模: east 5,010バス/6,472枝/7,482gen、west 6,998/10,899/7,485(REF 72=成分毎
  1スラック、MATPOWER合法)。gencost は**非出力**(費用を捏造しない —
  runpf-ready/runopf非対応と meta に明記)。MATLAB実機での loadcase は未検証
  (本機にMATLAB/Octaveなし)— 構造は loadcase 仕様に一致、from_mpc/loadmat で確認
- 既存資産の役割分担を確認: `src/matpower/exporter.py`(gencost付きOPF用・psdat向け)
  と `MATPOWERExporter`(汎用to_mpcラッパー)は健在のまま、国家出力は本経路に一本化
- テスト9件新設(`tests/test_matpower_canonical.py`: 正準形・1始まり・解状態埋込・往復一致)。
  **1086 passed / 3 skipped**
- 副記録: D3変圧器ノードは関東コアbboxで245件取得成功(devices=並列バンク数タグは34件
  と薄い)。フル東京bboxは Overpass 2連続失敗 — 次反復でタイル分割

<!-- ── UC改善シリーズ（worktree uc-improvements） ── -->


## 2026-06-12 — **Fable 5** — UC改善㉔: 連系線突合+ティルトJEPX較正 — 自己改善ループ総括（/goal達成）

- **連系線フロー突合**（uc_validateにinterconnector_check追加、シェアL1とは
  別枠・符号規約=受電正を開示）: **tohokuの大量送出はUC-107 vs 実績-121
  GWh/日で方向・規模一致** — coal過大の相当部分は域外送出として実態整合。
  hokkaidoはUCが送出側（実際は微輸入）=北海道coal過大の連系線転化を特定。
  形状相関は低い（0.26〜-0.58）=時間配分は市場スケジュールの領分
- **ティルト幅のJEPX較正**: coal[5500,9500]/lng[9500,13500]へ拡大
  （JEPX p5-p95=7.5-20円との整合）→ 平均L1 37.9→**37.2pp**、shikoku-3.1
- **総括（/goal「計画の実現と精度担保」）**: UC_VALIDATION_PLAN §4に
  達成水準と残差の構造を文書化。8巡の推移: **47.0→37.2pp（ピーク日）/
  32.6pp（天気正規化）/ 最良kyushu 18.5pp**。外部妥当性4点（地熱549MW=公表
  一致・JEPX価格整合・北陸coal一致・東北送出一致）。残差は**市場結合運用
  （coal部分負荷・連系線時間配分）=現UCのスコープ外**と開示し、Phase C
  （月次自動検証）への接続を記録 — **自己改善ループはここで一区切り**

## 2026-06-12 — **Fable 5** — UC改善㉓: Phase B続 — chugoku/kyushu開通でカバレッジ8/10社

- **chugoku対応**: 「需給実績」形式（DATE,TIME+需要/火力合算/太陽光(実績)等の
  括弧表記・「－」欠測）を列名別名で吸収。**kyushu対応**: kansaiと同じ
  DATE_TIME形式+**四半期ファイル名解決**（202312→2023_3Q/2023_Q4等の
  FY・暦両解釈を自動試行。2023_1Qと2023_Q1の二重命名が混在する実態に対応）
- **3社同時検証（2023-12-13、実績需要+RE実績モード）**:
  **kyushu L1 18.5pp（全地域最良）** — 新大分・苓北・松浦等の九州容量パッチ
  22件の品質が実測で実証 / kansai 34.3（単独検証23.7との差=検証セット構成で
  全国解が変わるため、開示) / chugoku 46.3（開通が成果、内訳分析は次巡）
- **hokkaido前提差の結論**: re-actuals悪化(31.7→39.7)は固有の前提差ではなく
  **全国共通のcoal稼働率問題**（UC 2.07GW平均フル稼働 vs 実績1.18GW=57%）の
  強調 — tohoku/tokyoと同型。残る最大の系統的残差はこの「coal稼働率
  （休日・部分負荷運用）」一点に収斂しつつある
- カバレッジ: **8/10社**（残: chubu=年度別形式・okinawa）。テスト9 passed

## 2026-06-12 — **Fable 5** — UC改善㉒: Phase B — kansai検証の開通（旧形式パーサ+実績需要モード）

- **kansai旧形式パーサ**（nas03コネクタ）: DATE_TIME 1列・1時間値MWh・
  **火力合算**の関西独自形式をフォールバック実装（列位置固定、テスト7 passed）。
  uc_validate側は thermal(combined)=UC lng+coal+oil 合算で突合（語彙開示）
- **--demand-from-measured**: OCCTO実測需要の**保持窓~14ヶ月**の外の日付
  （kansai月次在庫は2023-12まで）に対応 — 検証地域のグロス需要を実績demand
  系列で与え、他地域は合成フォールバック（metaに開示）。
  kansai/2024.csvはHTML破損（NAS側のdemand_update取得失敗、要修繕と開示）
- **kansai 2023-12-13(水) 検証**: **L1 23.7pp**（良好圏）。乖離主因=
  **原子力断面差**（UC=fy2025断面6.6GWフル vs 実績4.9GW平均=当時定検中）
  +40.7GWh/日、その分thermal -31.3 — 検証機構が断面不一致を正しく検出
- 検証カバレッジ: 5社（2025-08新形式）+kansai（〜2023-12旧形式）=**6社開通**。
  残り: chubu（年度別形式）/chugoku/kyushu（旧形式）/okinawa
- ループ累計: ピーク日37.9pp / 天気正規化32.6pp / kansai初値23.7pp

## 2026-06-12 — **Fable 5** — UC改善㉑: 地熱の坑井重複集約 — 全国549MW=公表値一致

- **真因**: 葛根田地熱がOSMの坑井・設備ポイントで**10重複**（530MW計上 vs
  実サイト1号80+2号30=110MW）— 東北geo 6.5倍過大（⑰）の正体
- **対処**: ①ローダーに**地熱限定の同名サイト集約**（同(region,name)は最大
  容量1機へ、決定論。地熱はサイト=発電所が通例、他燃料は同名複数ユニットが
  正当にあり得るため不適用）②葛根田をサイト計110MWへパッチ（公表値）
- **結果**: tohoku geothermal 729→**309MW**（8機、公表サイト構成と一致）、
  **全国geothermal 549MW = 公表の国内地熱~550MW級とほぼ一致**（強い妥当性）。
  検証L1: tohoku 58.8→**52.2pp**(-6.6)、平均**37.9pp**（ピーク日最良）
- **全国coal設備の調査結果（仮説の整理）**: UC全国coal **48,673MW** vs 公表
  ~53GW級 — **設備総量は過大でない**。残るcoal乖離は稼働率（休日抑制=経済
  停止の残り）と地域配分（tokyo 9.9GW/tohoku 8.8GW）の問題と整理
- ループ累計（ピーク日L1）: 47.0→39.4→39.2→**37.9pp** / 天気正規化32.6pp

## 2026-06-12 — **Fable 5** — UC改善⑳: 天気正規化検証（--re-actuals）— tokyo日曜悪化の真因は天気

- **tokyo日曜52.6ppの分解**: 主因は休日運用ではなく**天気** — 8/10のsolar実績
  16.0GWh vs UC想定78.1GWh（雨曇の日曜、形状相関0.968=形は完璧で量1/5）。
  太陽光不足分が実績側で lng+109/oil+42GWh の追い焚きとなりUCと乖離
- **--re-actuals**（uc_validate）: 検証地域のsolar/windを**当日実績系列で置換**
  してUCを解く=天気を所与にして**運用だけを比較**する検証モード
  （NationalScenario.net_demand_rはpropertyなので置換だけで純需要も追従）
- **結果（8/10）**: tokyo 52.6→**28.9pp** / hokuriku 21.0 / shikoku 21.8 /
  平均36.6→**32.6pp**。残るtokyo 28.9はcoal+64GWh（休日のcoal抑制を
  UCが知らない=経済停止の残り）等の純粋な運用差
- 教訓: **単日検証は天気正規化が必須**（手法の進化）。hokkaidoは31.7→39.7と
  悪化=実績RE置換で別の前提差（wind実績の少なさ→coal流れ込み）が露出
- 残差更新: ①coal休日抑制（tokyo+64GWh、全国coal設備過大と同根の可能性）
  ②hokkaidoの前提差 ③地熱個別機 ④kansai旧形式（Phase B）

## 2026-06-12 — **Fable 5** — UC改善⑲: 効率ティルト — 経済停止の決定論表現（人工CF上限なし）

- **apply_fuel_cost_tilt**(`src/uc/scenario.py`): 同一燃料グループへ実在の
  効率差（coal USC~6.5↔亜臨界~8.5円/kWh、lng GTCC~10↔汽力~13円）を
  **容量ランクで決定論的に**割当て。容量加重平均はシナリオ基準値を維持
  （JEPX 2025-08クラスタ7-8/11-12円との整合は⑱で確認済み）。乱数・人工CF
  上限なし。`fuel_cost_tilt:` キーでシナリオごとにオプトイン（fy2025r1に設定、
  fy2023凍結系は不変）。テスト2件（単調順序+加重平均保存）
- **検証（uc_validateに代表日差し替え機能を追加）**:
  - ピーク日 2025-08-06: tohoku 61.4→**58.8pp**(-2.6)、平均39.4→**39.2pp**（最良）
  - 閑散日 2025-08-10(日): 平均**36.6pp**、hokuriku 22.4/shikoku 24.3 —
    ただし **tokyoが14.1→52.6ppへ急悪化 = 休日運用の乖離を新発見**
    （日曜昼の実態: 火力深い抑制+揚水動力+域外送出をUCが表現しない）
- 残差の構造（更新）: ①休日の運用乖離（tokyo、新規）②全国coal設備量の
  過大（r7 41.5% vs 統計~28%の本体）③地熱個別機（東北6.5倍）
  ④kansai等の旧形式パーサ（Phase B）

## 2026-06-12 — **Fable 5** — UC改善⑱: JEPX価格分析 — 「燃料費が誤り」仮説を棄却、帰属修正でL1最良値

- **JEPXプロバイダ**: 契約 `jepx_spot` + コネクタ（nas03同居の
  `price_raw/jepx/spot_summary_{年度}.csv`、エリアプライス9地域・48コマ、
  月/エリア指定のzero-copy取得、テスト3+）
- **価格仮説の棄却（今巡最大の確定事項）**: 2025年8月東北エリアプライスの
  クラスタ = **7-8円（夜間下位）と11-12円（支配的、407/1488コマ）** —
  UCの fuel_cost（coal 7円 / lng 11円/kWh）は**市場実勢と整合**。
  tohoku coal/lngスワップの原因は価格ではなく**設備量・エリア帰属**と確定
- **帰属修正**: 福島復興IGCC2機（広野543+勿来525MW）は地理=福島（東北bbox）
  だが売電先・系統とも東京電力EP（公知）→ region: tokyo パッチ。
  検証L1: **tohoku 69.0→61.4pp（-7.6）**、tokyo 12.9→13.6（+0.7、想定内）、
  **平均39.4pp（過去最良）**
- 残差の次の分解: tohoku coal なお+60GWh/日級（全国coal総量の過大が地域に
  投影 — r7のcoal 41.5% vs 統計~28%と同根）/ tokyo oil -52GWh/日
  （UCのoil 18円が8月実勢p95=20円に対し焚かれない構造、「火力(その他)」
  混在も）。**次巡候補: coal機の効率ティルト**（USC 6.5円〜亜臨界8.5円の
  実在効率差を決定論的に割当て→夜間の限界coal停止=経済停止の自然表現、
  人工CF上限は使わない方針に適合）
- 再現: `ds.fetch("jepx_spot", {fiscal_year: 2025, month: "202508", area: "tohoku"})`

## 2026-06-12 — **Fable 5** — UC改善⑰: 検証ループ稼働（Phase A-1）— UC vs 発電実績の地域×燃料突合

- **nas03/PWS_DBコネクタ**(`e06d448`): エリア需給実績（10社・30分値・電源種別）を
  ssh zero-copyで月単位取得。列名マップでhokkaido変種（制御量+2列）を吸収、
  制御量列の本体上書きバグ修正、**tepcoのUTF-8-SIG**対応（CP932固定だと
  列名が化けdemand列消失→全行棄却=tokyoが空に見えた。多段デコードで解決）
- **uc_validate.py**: 代表日2025-08-06のfy2025r1 UC解 vs 5社実績
  （hokkaido/tohoku/tepco/hokuriku/shikoku — 202508新形式在庫のある社）。
  地域×燃料の日エネルギー・シェアL1・時間形状相関・抑制量を出力、
  uc_runs(kind=validation)記録
- **ベースラインL1**: tokyo **12.7pp**（最良）/ hokuriku 33.1 / shikoku 41.3 /
  hokkaido 44.0 / tohoku 69.7（平均40.2pp）
- **実測で立証されたこと**: ①hokuriku coal **61.2 vs 62.0 GWh/日でほぼ一致** —
  七尾大田・敦賀の容量パッチが実績と整合（⑮の検証）②solar形状相関0.89-0.96 —
  実測needs+参照CFの時間形状は正確、バイアスは量側
- **自己改善1巡目**: 24h断面にRE/RoRの**月係数が未適用**だった（年平均CFのまま
  → 8月弱風期にtohoku windが実績の3倍）→ 代表日の月で季節係数を適用
  （年間経路と整合化）。ただし**平均L1は40.2→40.8ppとほぼ不変** — windを
  正すと浮いた分をcoalが受けて相殺。**L1残差の支配項はcoal/lngスワップ
  （tohoku +85/-105 GWh/日 = 経済停止の構造、タスク#12）に集約**と確定
- 残課題の地域分解: tohoku geothermal 6.5倍過大（UC 729MW vs 実績132MW、
  個別機調査=Phase A-2）/ tepco実績は全日あり（欠測ではなかった）/
  kansai・chugoku・kyushuは202508在庫なし（Phase Bで旧形式対応）
- 再現: `AJGRID_NAS03_ROOT=ssh://… python3 scripts/uc_validate.py
  --scenario fy2025r1 --date 2025-08-06`（コネクタテスト6+15 passed）

## 2026-06-12 — **Fable 5** — UC改善⑯: west島UC断面の初AC収束 + before/afterマップ（merit-order vs UCコミットメント）

- **west島がUC注入断面でAC収束（本プロジェクト初）**: mainのmulti-voltage builder
  進化（ledger 63「stale assumption」）のマージに加え、**bridgeの停止操作を
  in_service=False→容量0化（_zero_out: max_p_mw/p_mw/q上限=0、PVノード温存）に
  変更**したことで gate が閾値際（1.13e9 FAIL）から **4.84e8 PASS** に復帰。
  vm zone別: chubu[0.981,1.038] hokuriku[0.92,1.038] kansai[0.824,1.034]
  chugoku[0.68,1.053] shikoku[0.663,1.048] kyushu[0.969,1.047]
  （chugoku/shikokuの深い放射状はmain ledger 63/77の既知性質と一致）。
  0化済み行に後続パッチが再容量化するバグはzeroed集合ガードで修正
- **before/afterエクスポート機械化**(`--export`): base網を**1回だけ構築し
  deepcopyで2分岐**（before=merit-order/after=UC注入、需要は両方UC断面=
  「同一網・同一需要・配分のみ差」）→ 地域別GeoJSON+差分（dvm/dloading）を
  docs/data/uc_powerflow/ へ出力（east+west 8ファイル+summary、20MB）。
  別buildにしない理由=網構成のハッシュ順ゆらぎを差分に混ぜない（gateゆらぎの教訓）
- **uc_map.html**（単独ページ、mainのマップ無改変）: before/after/差分の3モード
  ×島切替×バス(vm)/線(loading)レイヤ。Playwrightで描画検証済み
- **east差分の計測**: dvm/dloading 100%有効。dvm median -0.0015/min -0.077、
  **|Δloading|>10ppが1,322本** — UCコミットメントはmerit-orderと大きく異なる
  潮流パターンを作る（tohoku→tokyo輸入経路の混雑増が地図上で可視）
- 開示: 線×バス点の視覚ズレ（線=OSM実形状端点、点=変電所代表座標、snapped
  1.5km吸着分）は描画上の課題で電気的接続とは別（オーナー質問への確認 2026-06-12）
- **浮きバス問題の真因と解消（オーナー指摘起点、同日追記)**: 「OSMでは接続
  されているのに緑（バス）だけ浮く」（east 375/west 438バス、8割が66-110kV帯）。
  調査の確定事実: ①全浮きバスが活線を持ち電気的孤立は皆無（大田原=活線12本）
  ②「大田原変電所~稲沢変電所線」の描画端点がバス点から3.08km — **線=OSM実形状
  （正しい位置）、バス点=スナップクラスタ代表座標（実変電所から数kmズレうる）の
  座標二重系統**が真因。途中仮説の「trafo未描画」は部分要因（同一座標構内trafoが
  大半で可視化効果は30本のみ）。**解消=線端点をfrom/toバス座標へ吸着**（中間は
  OSM形状のまま）→ east浮きバス **373→0**。trafoも紫点線で描画
  （`変圧器（異電圧接続 — OSM線の潮流モデル上の置換）`とツールチップ明示）
- **mainライブマップへの共通知見**: index.html系も同じ座標二重系統+trafo未描画の
  はず — 同種の「浮き」が出ている場合は端点吸着+trafo描画で解消可能（還流④）
- **gate二値ゆらぎの機械的対処**: cond は構築プロセスのハッシュ順で
  4.84e8(PASS)/1.13e9(FAIL) の二値に振れる（5回再現で確認、onenormest内ゆらぎ
  ではない）→ `--gate-retries N` で島網を作り直してPASSを引くまで再試行
- 再現: `python3 scripts/uc_to_pf_national.py --islands east --export` /
  `--islands west --try-ac --export --gate-retries 4` → docs/uc_map.html

## 2026-06-12 — **Fable 5** — UC改善⑮: capacity_bridge — 容量の正の一元化（⑫の二重管理解消）

- **橋渡し層**(`19ea474`, `src/uc/capacity_bridge.py`): DB（uc_scenario_generators、
  YAMLフォールバック）の capacity_patches + nuclear_status を **PF側 net.gen へ適用**。
  UC側ローダーと同一意味論の4ステップ: ①bbox重複コピーのdedup（**≥100MW限定** —
  無差別dedupはeast島で同名ソーラー群4,492行/-59GWを誤停止しgate FAILを招いた）
  ②容量パッチ常時適用（PF側は-1.0欠損が燃料別デフォルトに置換済みで欠損が観測
  不能 → 出典付き公称値を正とする。regionのみのパッチはOSM容量維持）
  ③nuclear_status: 稼働サイト=site容量/リスト外=停止（east島で6炉停止
  =FY2023断面の東日本原発ゼロを正しく反映）④zone帰属表（注入側でgen単位上書き）
- **新パッチ2件 — 橘湾の誤帰属**: J-POWER橘湾2,100MW（徳島県阿南市）が
  kansai bbox重複の初出dedupでkansai帰属だった（敦賀火力と同構造、**UC側も同罪**）
  → region: shikoku。四電橘湾700MWはregionのみパッチ
- **west島の実測効果**: 注入ギャップ hokuriku **-77%→-16%** / kyushu **-31%→-7%** /
  shikoku -52%→-16%（四電パッチ後）。総注入 63.0→69.2GW（純需要の99.0%）。
  旧版の chugoku→kansai -7GW のtie潮流歪みも解消
- **負の結果（重要）**: kansai 24断面の昼間低電圧 vm 0.798 は bridge適用後も不変 —
  容量較正と独立の課題（原子力の北部偏在 vs 都市部昼ピークの地理乖離、
  注入の地理重み付けが次のテーマ）と確定
- **main還流事項**: ①ybus_gate の cond推定が閾値1e9際で実行ごとに揺れる —
  同一入力で 4.84e8 / 1.13e9 / 1.21e9(PYTHONHASHSEED=0) を実測。west島
  （bridge後）は「gate際の網」であり、判定の決定論化（推定の反復中央値 or
  シード固定）と閾値の余裕度設計が必要。**gate PASS時のDCは収束する**
  （p95 78.7%実測、19ea474）ので保守側には倒れている
  ②PF側GridNetworkローダーの「-1.0→燃料別デフォルト置換」は玄海/川内を
  1000MW扱いにする（実2360/1780）— DB容量の優先参照をビルダーへ昇格すべき
- **tokyo coal欠損2.3GWの真因確定（追記）**: 容量タグではなく **KSC Chiba IPP
  (1,440MW)と鹿島共同発電所(1,000MW)の2台がGridNetwork構築で未接続→不参加**
  （GeoJSONは11台11,454MW正値、GridNetworkは9台9,014MW）。容量パッチでは
  直らない=ビルダーの接続探索の問題（main還流事項③）

## 2026-06-12 — **Fable 5** — UC改善⑭: FY2025実測需要の年間UC完走（r7）— 合成需要の過大+12%を定量化

- **r7**(`950ce68`): fy2025r1（実測需要 via DataSpace profile_ref・annual_window +
  nuclear_status_fy2025 14基13,253MW）の8760h UC。pws-160core 13チャンク並列、
  389窓**全365日Optimal**・リトライ0・カバレッジギャップ0
- **実測needs化の効果（r6=fy2023r2maint比）**:
  - 総需要 **999.3 → 879.7 TWh（-12%）** — 合成需要（OCCTOピーク×形状の年間化）の
    過大が初めて定量化された。コスト ¥6.47兆 → **¥4.99兆/年（-23%）**
  - **LNG 30.7 → 21.7%（-9.0pp）**: 需要減を限界電源が吸収（メリットオーダー通り）
  - nuclear 7.6 → 9.9%（+2.3pp、女川2+島根2の14基断面）、揚水 0.10 → 0.56%
    （実測の夕方ピーク形状が揚水を稼働させる）
- **開示**: FY2025実績シェアは年度未了で正本なし（構造比較のみ）。RE容量は
  fy2023r2踏襲（FY2025導入増未較正=solar/windやや過小バイアス）。coal 41.5%は
  経済停止モデル外の既知過大と同根
- uc_runs索引: backfillで75件（r7チャンク13+マージ1を含む）

## 2026-06-12 — **Fable 5** — UC改善⑬: UC実行履歴のDB索引（uc_runs, migration v4）

- **UCRunテーブル**(`b4b32f1`): docs/reports/ のレポートJSONを正本としたまま、
  report_pathキーのupsertで機械検索可能な索引をgrid.dbに持つ（重複しない再実行）。
  `record_uc_run`/`list_uc_runs` + `src/uc/run_recorder.record_run`
  （**ベストエフォート**: DB欠如・ロックでも実行を失敗させない=サーバーチャンク並列安全）
- 4ドライバ（benchmark/annual merge/pf_link/pf_national）が保存後に自動記録、
  `scripts/db/backfill_uc_runs.py` で既存61レポートを一括索引化
  （benchmark 11 / annual 43 / pf_link 5 / pf_national 2、旧単一断面形式も対応）
- **DB統合方針との関係**: シナリオ(v3)+実行履歴(v4)でUC側のDB資産が完備。
  次は容量パッチ（uc_scenario_generators の kind='capacity_patch'、ingest済み）を
  PF側enrich（GeneratorAttributes）へ接続し容量の正を一元化 — ⑫の二重管理解消、
  mainマージ時の統合タスク
- tests/test_uc_runs_db.py 7件追加（1070 passed見込み）

## 2026-06-12 — **Fable 5** — UC改善⑫: 全国ゾーナルUC→PF（east AC/west DC 完走）— 容量二重管理の定量化

- **zone別注入**(`inject_dispatch_by_zone`): 多地域同期島ネット（bus.zone）へ
  地域ごとに load=UC純需要スケール+gen=燃料別容量比例注入。primitivesに
  gen_mask/load_mask追加（1063 passed）。ドライバ `uc_to_pf_national.py` は
  run_national_powerflow の島構築チェーンの balance_power_by_zone を
  UC断面に置換し、tie線潮流（zone跨ぎline）とUC連系線フローを地域対で比較
- **east（tohoku+tokyo, 5,024バス）t=17**: gate PASS → **AC収束**
  vm tohoku[0.96,1.037]/tokyo[0.817,1.03]（フルモデルは縮約版に無い弱バスを露出）
- **west（6地域, 7,082バス）t=17**: gate PASS → **DC収束 loading p95 79%**
  （AC不可は既知の確定事項=下位網変圧器。ローカルMacで完走、サーバー不要）
- **最重要の新事実 — UC↔PF間の容量二重管理を初めて定量化**:
  UC側の容量較正（capacity_patches 27件・参照リスト）はシナリオ層にのみ存在し、
  PF側のOSM由来GridNetworkへ届いていない。地域別ギャップ（t=17断面）:
  - **hokuriku gap 2,444MW (-77%)**: coal 1,949クリップ（敦賀火力等のregion/容量パッチ未反映）
  - **kyushu gap 4,452MW (-31%)**: nuclear 2,140 + lng 1,895（新大分2,295級）+ coal/geo
  - **shikoku gap 1,498MW (-52%)**: **coal 1,356がunmatched = 橘湾石炭がPF側に不在**
  - tokyo（east側）: coal 2,340クリップ → tie潮流乖離（PF 11.6GW vs UC 5.6GW）の主因
  - クリップ分はslack供給に化け、tie潮流をUC計画から大きく歪める（west連系線で顕著）
- **帰結（方針裏付け）**: 発電容量の正は R/C/D 層のDBで一元化し、UCシナリオ
  ローダーとPF側enrichが同一の正を引くべき — 「潮流側とのDB統合」の根拠データ
- 次: UC実行履歴のDB記録（uc_runs）/ 容量パッチのDB昇格 → PF側enrich接続

## 2026-06-12 — **Fable 5** — UC改善⑪: UC→PF 24断面スイープ（「流せない時間帯」の不在と電圧の質を計測）

- **--all-hours実装**(`scripts/uc_to_pf.py`): UC1回+PF網1回構築→24時刻を断面ごとに
  deepcopy注入+AC再ソルブ。時刻別 vm/slack/注入量をJSONに記録
  (`docs/reports/uc_pf_link_{region}_allhours_2026-06-12.json`)
- **結果（fy2023r2, backbone154）**: tokyo(1110バス)/kansai(714)/kyushu(358)とも
  **24/24断面AC収束 = 「UCは解けるがPFで流せない時間帯」は3地域に存在しない**
- **収束を超えた質の計測（本スイープの新事実)**:
  - **kansai 昼間帯(8-19時)に vm_min 0.799〜0.897 の低電圧**。slackは負(吸収側)なのに
    需要中心で電圧降下 → UC断面の地理配分（原子力6.6GW=若狭湾岸北部偏在）と
    昼ピーク需要分布の乖離を容量比例注入が埋められない（=次の深化対象。
    main側の既知性質「関西=PVノーズ」とも整合）
  - kyushu は時間帯によらず vm [1.017, 1.070] の高め電圧（軽負荷+充電容量の網特性、
    注入起因ではない）/ tokyo は全時間帯健全 vm[0.960,1.040]・slack平均+14.6%
- 次: 注入の地理重み付け（需要近接/ゾーン別）・全国ゾーナル断面（east AC / west DC、サーバー）

## 2026-06-12 — **Fable 5** — UC改善⑩: 実測需要のシナリオ統合（profile_ref稼働=データスペース実用第一号）

- **profile_ref実装**(`3bc6c04`, DATA_SPACE §5): シナリオの demand.profile_ref が
  DataSpace.fetch(occto_kohyo)で解決され、代表日の実測30分値（→1h平均）がグロス需要になる。
  取得データのsha256が NationalScenario.demand_profile_sha → ベンチmeta に連鎖
  （シナリオ指紋→取得データ指紋の再現性チェーン）
- **fy2025r1シナリオ**: 代表日=**2025-08-06（FY2025夏ピーク、実測7月中旬〜8月の走査で
  全国30分値max 163.1GWと特定）** + nuclear_status_fy2025（12基+女川2・島根2=**14基13,253MW**、
  柏崎刈羽は未反映と開示）。solar/wind容量はfy2023r2踏襲（FY2025導入増は未較正=純需要過大
  方向のバイアスをファイル内開示）。FY2025実績シェアは年度未了のため乖離KPI正本なし
- **結果**: 実測需要での全国24h UC = **Optimal 11.5s・¥202億/日・nuclear 10.2%（14基断面）**。
  合成需要という最大の近似が代表日断面で解消。1061 passed
- 次: 年間8760hの実測化（月別取得+キャッシュ、FY2025の365日）/ FY2025 RE容量較正 / nas03・MSM所在待ち

## 2026-06-11 — **Fable 5** — UC改善⑨: UC→潮流結合（タスク#6完了 = 全タスク完了）

- **mainマージ**(`7d989c4`): origin/main（M7-M9: PTDF需要推定・Ybus出荷ゲート・中間タップ
  スナップ等、+9,252行）を取り込み。衝突解消=IMPROVEMENT_LOG（両系列を区分保持）・
  schema.py（UC 2テーブル+main計測2テーブル共存、migrationはUC v3が単独で無衝突）。
  マージ後 **1053 passed**
- **結合実装**(`9224fd6`, `ajgrid uc to-pf`): main側のUC_HANDOFF契約を完全消費 —
  ①UC求解→②地域PF構築→③**ybus_gate（FAILなら注入しない契約を遵守）**→
  ④ピーク時刻断面を燃料別集計し容量比例で注入（UC'lng'⇔PF'gas'の語彙正規化、
  UC断面に無い燃料は0化=コミットメント反映、slack除外、loadはUC純需要へスケール）→
  ⑤AC再ソルブ。**mainのpipelineは無改変**（解き済みnetへの事後注入=並行開発安全）
- **実測結果**: tokyo backbone = gate PASS(5.6e7)・39.6GW注入・**AC収束 vm[0.960,1.036]**・
  slack 6.6GW（UC側の連系線輸入と整合）/ kansai = 19.5GW注入（2023年度断面の原子力6.6GW込み）・
  **AC収束**・unmatched 214MW=揚水のPF側欠如（開示）。
  **較正シナリオ上のUC運用断面が、OSM由来の実系統で流れることを初実証**
- 注入はv1=地域×燃料集計（UC機とPF機は別実体のため）。機別マッチ・多時刻連続検証・
  全国ゾーナル断面は次段階

## 2026-06-11 — **Fable 5** — UC改善⑧: 北陸実態化（オーナー指摘）+ OCCTO実疎通 + 機別図

- **北陸の精査**(`ce9f7ac`, 指摘「発電量が小さすぎ・2000MWもtielineない」→両方正しかった):
  域内2,960→**4,265MW** — 七尾大田1,200MW coal（OSMはbiomass誤タグ+容量-1.0で20MW扱い）/
  敦賀火力1,200MW（敦賀市がhokuriku bboxぎりぎり圏外でkansaiに帰属流出→regionパッチで固定）/
  富山新港 旧名板1,500→現役425MW LNG（石炭250×2は2018廃止）。
  capacity_patchesに fuel/region/override キーを拡張（正値名板の補正も可能に）
- **連系線**: ic_005北陸フェンス 1,900→300MW（安定度制約の運用容量オーダー）+ ic_010
  北陸関西間1,900MWを新設。**シナリオ側overrides/additions方式**で共有yamlは不変
  （本体改訂はmainマージ時にboundary.pyの容量比utilisationと整合させる、を台帳化）
- **OCCTOコネクタ実疎通**: main側の実証URL(download/downloadCsv, UA必須)を取り込み、
  実CSV（行指向・エリア名列）にパーサーを書き直し → **全10地域×48半時間点の実需要を
  取得・provenance記録**までend-to-end確認。「でんき予報」拡張の土台
- **nas03契約**（オーナー示唆「発電実績・でんき予報をnas03から参照」）: dataspaceカタログに
  所在ガード式で契約化（パス・形式の確認後にコネクタ実装）
- **機別グラデーション図**: 火力の単色塊→機単位の積層（基色±38%濃淡+白細線=台数可視化、
  「色味を失わない程度に」準拠）。LINE配信済み。24h fy2023r2 = Optimal・L1 21.3pp。1021 passed

## 2026-06-11 — **Fable 5** — UC改善⑦: データスペース層（zero-copy連携）+ 沖縄実態化

- **データスペース**(`d6aed8f`, オーナー指示「全て持ってくるはナンセンス、データスペース的連携を」):
  `docs/DATA_SPACE.md`（原則=データは源泉に留め、UCが要る地域×時間の集約断面のみ取得。
  集約は源泉近く=NASマウントのある160core側で実行）+ `config/dataspace.yaml`（契約カタログ:
  msm/occto_kohyo/p03/energy_stats、custodian・license・再配布可否を明文化）+
  `src/dataspace`（registry/sha256キャッシュ/provenance.jsonl=全取得の出所機械記録）。
  コネクタ: OCCTO（main側で疎通実証済みAPI、エンドポイント上書き可・寛容パース）/
  MSM（所在ガード: AJGRID_MSM_ROOT未設定は案内付き明示失敗=暗黙取得しない、Phase 2境界まで）。
  シナリオ接続（profile_ref→取得shaをシナリオsha256に連鎖）は仕様定義済み・Phase 2実装。
  10テスト、計1016 passed
- **沖縄実態化**(`e4991a8`): 図生成のfy2023r2適用で旧ハードコード（吉の浦350×2等）の
  不正確さが露呈しinfeasible → 2023年度実態（吉の浦LNG CC 251×2・金武220×2・具志川156×2・
  石川J-POWER 312・内燃合成400開示）に置換、Optimal回復。新旧全地域図をLINE配信
- **残**: MSMアーカイブのNAS所在確認→Phase 2（GRIB2→地域CF集約）/ OCCTO実測needsへの置換 /
  UC→PF連携（タスク#6）

## 2026-06-11 — **Fable 5** — UC改善⑥: 実勢較正fy2023r2+定検合成 — 年間L1乖離 33.6→23.5pp

- **fy2023r2シナリオ**(`e35d723`): 出典[S1-S5]構造化の較正版（fy2023は凍結=過去ベンチ再現性保持、
  scenario_sha256でベンチの断面を機械検証可能化、DB両版ingest）。wind 10.9→6.0GW・solar→70GW
  天候derate（年91.4TWh≒実績92.1）・中小水力RoR控除2.5GW(+22TWh)・燃料費2023年度実勢。
  実績シェア(エネ庁)をreference_shares_pctとして固定しベンチがL1乖離KPIを自動算出
- **較正が掘った追加バグ**: 九州30MW不足infeasible→jrp_lite欠損(-1.0)の主力火力（新大分2295/
  松浦2サイト3700/新小倉1200等）が100MW扱い。パッチ22件追補（廃止4件除外・沖縄OSM6件の
  合成火力二重計上解消）
- **定検合成**(`f791d14`→`8da4e0b`→`e1e42ee`): 3度の実測infeasibleを経て確定した設計 =
  **決定論的（乱数なし）・原子力スロット間隔≥duration・地域別同時停止上限25%のグリーディ配置**。
  失敗事例も台帳化: md5独立配置(秋重畳)→輪番(春の原発重畳)→上限付き(全地域21-25%で安定)。
  チャンク時間軸の変換漏れ（メンテが無作用でr2と同一結果=決定論の傍証）も修正
- **年間結果**(uc_annual_fy2023r2maint): **全365日Optimal・999.3TWh・¥6.47兆/年**。
  シェアvs実績: lng 30.7%(32.9)・nuclear 7.6%(8.5)・hydro計7.96%(7.6)・solar 9.1%(9.8)・
  wind 1.3%(1.1)・coal 38.9%(28.3)。**L1合計 23.5pp（メンテなし33.6から10.1pp改善）**
- **残差の開示**: coal +10.6pp（経済停止・市場運用はモデル外=人工CF上限は結果合わせになるため
  導入せず）/ oil -6.4pp（統計「石油等」がその他ガス込みの区分差）/ biomass -1.7pp（容量過小）

## 2026-06-11 — **Fable 5** — UC改善⑤: 8760h年間UC完走（ROADMAP P5達成）+ ajgrid uc CLI

- **rolling horizon実装**(`bdd41ca`): 窓間状態引き継ぎ3点セット = initial_commitment（幻の起動費防止）/
  initial_history_h（min up/down残置強制）/ SOC引き継ぎ。窓48h・step24h・lookahead24h。
  warm-start連鎖・gap緩和リトライ・確定部分の再計算コスト（lookahead重複排除）
- **160core実行**(ユーザー許可): 直列実測82s/窓=8.3hを**30日×13チャンク並列(warmup2日)**で~70分に。
  実戦バグ1件即修正(`851cd88`): 揚水「大森川12.2MW×6h=73.1999…MWh」のSOC境界丸めでPuLP
  setInitialValueが拒否→クランプ+その境界値の回帰テスト
- **結果** (`uc_annual_fy2023_parallel_2026-06-11.json`): **全365日・497窓 全Optimal**。
  年間1,005.6TWh（実績~985TWhと整合=合成需要の妥当性確認）・燃料費等¥3.71兆/年。
  年間シェア: coal 36.4%(実態~28、+8pt=一般水力欠損と2013年体系燃料価格が残差) /
  lng 25.4%(~33) / solar 14.3%(~10) / nuclear 10.1%(~9✓) / hydro 5.6%(~8) / wind 3.8%(~1)。
  揚水0.36%・蓄電池0.29%が年間で稼働（SOC連鎖の成立）
- **`ajgrid uc` CLI**(`f2b2a60`): benchmark/annual/merge/ingest-scenarios の薄いディスパッチ
- 997 passed。残: OCCTO実測時系列(Phase 2) / 燃料価格2023年度較正 / 一般水力容量 / UC→PF連携

## 2026-06-11 — **Fable 5** — UC改善④: 地域限界価格(LMP)+warm-start（負の結果込み）

- **双対値抽出**(`bfc864b`): `UCParameters.extract_duals` — コミットメント固定LP再解
  （MILPに双対なし、市場標準手法）でnodal balance制約のπ=地域限界価格を `UCResult.regional_lmp` に。
  手計算一致の単体テスト（限界機価格・混雑分離・非混雑収束）+全国検証:
  **60Hz西日本5地域が7,083円/MWhに完全収束（一物一価）**・北安値（北海道4,521/東北5,891=北本混雑）・
  沖縄9,000固定（孤立・石油限界機）= 物理的に妥当な価格構造。**オーバーヘッド+0.6s**。
  `uc_benchmark.py --duals` でLMP平均/ピークをKPI化
- **warm-start**(同): `_HiGHSWarmStart`（pulp.HiGHSはsetInitialValue無視→highspy setSolutionで
  MIP start注入）+ schedules→変数マッピング。**計測による負の結果**: 全国24hでは0.99x=効果なし。
  HiGHSログで根拠確定（**Nodes=1・LP 20,543反復9.8s/12.4s = root LP支配で分枝スキップ余地なし**）。
  タイトな窓（冬ピーク・rolling再解）の保険として保持
- タスク3の残り（LP丸め・時間窓境界）は8760h rolling実装（タスク4）に統合する判断。987 passed

## 2026-06-11 — **Fable 5** — UC改善③: HiGHS有効化+シナリオ第一級化+DBミラー

- **HiGHS有効化**(`30a8402`): highspy導入済みなのに_select_solverがCLI版のみ探索しCBCに
  フォールバックしていた。highspy API優先に修正、全国24h **27.8s→12.5s**（コストはgap内同等）。
  pws-160core側もhighspy確認済み（160C/231GB free）→ 8760h級はサーバー実行方針（ユーザー許可: 160core+GPU）
- **シナリオ第一級化**(`c1dd2c0`, ユーザー指示「発電機の選定はシナリオ依存」):
  `config/uc_scenarios/fy2023.yaml` を正本に、需要形状/地域ピーク/RE容量・CF/蓄電池/燃料費/
  起動費/容量既定値/参照リスト群を集約（旧ハードコード定数を全廃、二重管理解消）。
  `build_national_scenario(scenario="fy2023")` で断面切替可能。**KPI差分ゼロを確認**
  (uc_benchmark_scenario_yaml = uc_benchmark_highs)
- **DBミラー**(同): grid.db migration v3 = `uc_scenarios`+`uc_scenario_generators`。
  `scripts/db/ingest_uc_scenarios.py` でYAML→DB機械同期(nuclear 6/揚水44/パッチ2)。
  YAML=正本・DB=実行時ビュー（DB_ARCHITECTURE整合）。978 passed

## 2026-06-11 — **Fable 5** — UC改善②: 精度4連打（dedup・揚水・原子力・容量較正）

- 全て `scripts/uc_benchmark.py` のKPIスナップショットで段階計測（docs/reports/uc_benchmark_*_2026-06-11.json）
- **(1) osm_id重複除去**(`bc2668d`): スライス重なりの二重計上126機39.8GW(熱容量14.8%)を解消。
  帰属=operator→管内マップ+bbox内側マージン。636→510機
- **(2) 揚水storage化**(同): `data/reference/pumped_storage.yaml`(44箇所27.6GW、エレクトリカル・
  ジャパン由来の現況出力)。名前マッチで18機再分類(葛野川1600→1200の現況補正含む)+25機追加
  (奥多々良木1932等)。**165GWhがSOC制約付きstorageに**(従来=コスト0フリー電源)
- **(3) 原子力2023年度断面**(同): `nuclear_status.yaml`(再稼働12基11.6GW)。廃炉(福島第二・もんじゅ)
  と長期停止(柏崎刈羽・浜岡等)の31.8GW全数稼働扱いを是正。川内900→1780等の過小も補正
- **(4) 火力容量較正**(`b377455`): 容量欠損coal32機への一律600MW補完=19.2GW幻容量が真因と特定。
  実態は自家発(製紙・化学)が大半→既定100MW+大物2件は個別パッチ(苓北1400/福島ガス1180)
- **燃料シェアの実態(2023年度概数)への収束**: nuclear 24.3→**8.8%**(実態~9✓) / lng 10.1→**32.9%**
  (~33✓) / coal 22.9→33.0%(~28、+5pt残) / hydro 23.6→4.9%(~8、一般水力欠損で過小) /
  総コスト¥68→128億/日(フリー電源の幻が消えた結果)。全段Optimal 27-32s(CBC)。968 passed
- 残課題: 一般水力の容量欠損 / wind参照値10.9GW過大(実態~5.2GW) / oil過小 / 設定二重管理

## 2026-06-11 — **Fable 5** — UC改善①: ベースライン計測基盤（worktree分離セッション）

- **worktree `worktree-uc-improvements`** でUC機能改善シリーズを開始（main側の潮流改修と並行のため分離）
- **計測基盤**: `src/uc/scenario.py`（gen_uc_regional.pyのロード部を共通化、挙動不変を出力一致で確認:
  636機/268,361MW/沖縄¥206.9百万 一致）+ `scripts/uc_benchmark.py`（データ品質/求解/ディスパッチKPIの
  スナップショット、`--baseline` diff付き）+ 回帰ピン11テスト。**958 passed**
- **ベースライン確定** (`uc_benchmark_baseline_2026-06-11.json`): 全国24hノーダルUC =
  Optimal 31.9s(CBC)・¥68.0億/日。計測で確定した問題: **重複126機39.8GW(熱容量の14.8%)が二重計上** /
  **揚水storage 0機**（OSM抽出が`plant:method`を落とし全揚水が一般水力=コスト0のフリー電源扱い、
  葛野川・奥清津・玉原など名前同定は可能）/ 原子力27機35.9GWが全数稼働可能扱い /
  シェア乖離 hydro 23.6%・nuclear 24.3%・lng 10.1%（実態目安 ~8%・~9%・~33%）/ HiGHS未導入
- 評価・改善ロードマップ: `UC_BASELINE_ASSESSMENT_2026-06-11.md`（タスク②精度→③ソルバー→④8760h→⑤CLI→⑥PF連携）

<!-- ── main（潮流・トポロジ改修シリーズ） ── -->


## 2026-06-12 — **Fable 5** — S2: 四国放射端のPV余裕 — 崩壊なし(λ>1.6)・沈下は島ソルブ起因と確定（77）

- **計測**: 四国地域モデルで一様負荷+発電スケールスイープ(λ=1.0→1.6) —
  **全点AC収束・vm_min 0.958→0.874の緩やかな低下のみ、崩壊点なし**(掃引上限まで)
- **重要な切り分け**: 甲浦0.656等の深い沈下は**west島統合ソルブのゾーン需要配置**で
  発生し、地域モデル(境界注入つき)では再現しない → 放射端の電圧問題は
  「実測需要が無い地域の合成配分」問題(65の所見)であり、系統の固有脆弱性ではない
- 限界明記: 一様スケールのPVプロキシ・合成パラメータ → 余裕は指標的。
  pv_margin_shikoku_2026-06-12.json。1078 passed

## 2026-06-12 — **Fable 5** — F3: 西3社の燃料別実績URL探索 — 予測可能パスでは未達（76）

- **探索結果(正直)**: 中部PG=keito_jisseki(需要/総発電/再エネ計のみ・燃料別なし)・
  関西=jisseki-latest.json→juyo需要ファイルのみ(燃料別はJS導線の先)・
  九州=四半期形式は確認(area_jyukyu_jisseki_YYYY_QQ)も新しい期が非公開パス
- **帰結**: 西の燃料別検証計器は未整備のまま → **X2(capacity_bridge採用)の保留継続**。
  次アプローチ=手動ページナビ or OCCTO系統情報サービス。VALIDATION_SOURCES.md更新
- 探索はcurl実プローブのみ(推測を事実と書かない)。1078 passed

## 2026-06-12 — **Fable 5** — W5: OSM編集ターゲット集を公開文書化（75）

- `docs/reports/osm_edit_targets_2026-06-12.md` — 検証計器が**開示データ照合で**特定した
  編集候補を5節に集約: ①西の上位接続欠落疑い10ポケット(座標つき・**関西分の解消で
  ゲート95%到達**) ②都心154kV地中ケーブル20本(計器上限の正体) ③九州の道路説明可能
  ペア9件(座標つき・レビュー用) ④西厚木=岡田の名寄せ/重複ノード ⑤タップ・分節の統計
- 各節に再生成コマンド・「候補であり確定でない」注意書き・OSM例題台帳へのリンク。
  コミュニティ還元とW3ゲート達成の両方への道筋。1078 passed

## 2026-06-12 — **Fable 5** — X2: capacity_bridgeのPF側A/B — 互換確認・採用は西実測待ち（74）

- **東京**: パッチ29件全て不一致(対象は西の発電所)+**FY2023原子炉リストが実測帯と衝突**
  (柏崎刈羽試運転を含むFY2025-26窓ではnuclear帯0-1,317MW・モデル1,100は帯内 →
  橋を当てると-1,100で帯下限へ) → **東京は不採用**(実測帯が新しい)
- **west(設計対象)**: dedup**43機**(bbox重複の二重計上)・パッチ19・退役5・原子炉set6/stop11 —
  **mw_delta −35.3GW**の大規模補正。再バランス後もDC収束。ただし実在線最大負荷227→1031%
  (容量再配置で集中が変化)
- **判定**: 機械的互換✓・補正は証拠ベース(重複は客観的誤り)だが、**westには検証計器
  (燃料帯)が未整備** → PF既定採用は**F3(西TSO実績)で計測検証できるまで保留**。
  dedupのcurate層昇格(橋docstringの想定どおり)をキュー化。UC側の利用は従来どおり
- 1078 passed

## 2026-06-12 — **Fable 5** — F6: 実測帯によるdispatch較正を採用 — 燃料帯7/9・trunk ρ微改善（73）

- **実装**: `_apply_fuel_bands()` — stack配分後、実測帯(gen_by_fuel)超過燃料をp95へ・
  不足燃料をq50へ(設備上限内)クランプし、差分は**ガス(限界燃料)がスイング**。
  pipelineがDBから帯を自動読込(fail-soft・現状tokyoのみ較正データあり)
- **A/B(燃料帯)**: 4/9→**7/9帯内** — coal 10,014→7,716(=p95)・hydro 4,387→1,984(=p95)・
  oil 0→453(=q50)・gas 15,788→20,028(帯内スイング)。残るwind 12/biomass 352は
  **モデル設備容量自体が実測q50未満=容量データの限界**(dispatchでは直せないと明記)
- **A/B(流れρ)**: 全体0.456→0.454(誤差帯)・**trunk 0.598→0.615(+0.017)** —
  石炭過剰の是正が広域流の順序を僅かに改善。退行なし→**採用**。
  正準計器=external_flows_tokyo_full_2026-06-12a.json
- 1078 passed

## 2026-06-12 — **Fable 5** — W3/W4: 関西真の連結率94.6%(ゲートまで0.4pp)・㊶表現を訂正（72）

- **W3**: 越境断片(徳島・淡路=四国エリア写り込み34ノード)を除外した関西66帯の
  **真の連結率=94.6%**(849/897) — ゲート95%まで**あと約4ノード**。残りは関西固有の
  欠落疑い4ポケット(上位ヤード5km内・変圧器/上位線のOSM未収載) → **捏造で跨がず**、
  W5のOSM編集/enrichmentsキュレーションで越える方針を明記
- **W4**: ㊶の「重度断片」表現を訂正 — kv66品質台帳の読み方注記(カバー=東日本型KPI・
  西はポケット構造+上位網連結率で評価)をレポートに追記
- chubu/kyushuはゲート済(95/98%)。1078 passed

## 2026-06-12 — **Fable 5** — N5: 「日本としての系統」健全性証明書 初発行（71）

- **統合reconcile**(national_health_2026-06-12.json): (a)10エリア需要=**8帯内**
  (修正済みhokkaido 0.99・shikoku 0.99✓、hokuriku/chugoku 1.01=境界上のみ)
  (b)連系線9本=OCCTO実測のDB導出値 (c)東京燃料別=帯判定(較正ターゲット4件はF6へ)
- OCCTO窓が1ヶ月伸長(フェッチャ検証で2026-05追加)に伴いq50が微更新 — 「機械的に
  最新化される証明書」として機能している証左
- 全4島AC(63)+Ybus全島PASS(50/63)+本証明書で、「日本としての系統」の
  **解ける・健全・実測と整合**の三点が初めて同時に文書化された。1078 passed

## 2026-06-12 — **Fable 5** — S1: 国家N-1スクリーニング初実施 — 急所回廊を構造特定（70）

- **計器**: `scripts/n1_screening.py` — 島別ベースDC解→実在回廊(非物理除外=65・束定格=66適用)の
  loading上位50本を逐次停止→分裂は連結判定で即記録(偽解なし)・非分裂は再DC解で
  **新規過負荷数**を計数。screening限界(合成定格・単一断面)をJSONに明記
- **結果**: east=ok8/波及39/**分裂3** — 急所は**姉崎線(+42過負荷)・東京北線(+24)** /
  west=ok10/波及36/**分裂4** — 高雄一丁目~高津尾線の停止で**16バス孤立**、
  阿波~阿南FC線(+15)・中能登~上野線(+11)が波及上位
- **読み**: 上位回廊の~78%が波及を起こすのは合成定格の締まり(80%スケール)も寄与 —
  **順序(どこが急所か)と分裂(構造事実)が本スクリーニングの成果物**。
  実定格が入れば(D2束適用済み・将来は公開定格)マージンも語れる
- 1078 passed・スコアカード: n1_screening_2026-06-12.json

## 2026-06-12 — **Fable 5** — F4: 燃料別dispatch検証が稼働 — 石炭/水力過大・石油/風力過小を特定（69）

- **実装**: `ajgrid reconcile --solve-region tokyo` — フル解のgen typeを燃料へ正規化集計し
  DB実測帯(gen_by_fuel:*)で帯判定。境界注入=interconnectとして比較。
  注記明記: モデル=ピーク×LFの単一断面 vs 実測=通年帯 → 帯と順序で判断
- **初検証(東京)**: 帯内=gas 15,788(帯14.7-25.0GW)・solar 9,532・interconnect 4,780・
  nuclear 1,100(帯0-1,317=窓内の実稼働と整合)。**>p95: coal 10,014(p95 7,716)・
  hydro 4,387(p95 1,984)** / **<q50: oil 0(q50 453)・wind 3・biomass 352** —
  メリットオーダーのCF仮定(石炭・水力高すぎ/石油ゼロ扱い)の**実測較正ターゲット4件**が
  初めて数字で確定
- dispatch較正(CF調整)はρへのA/B必須のため次項目化(F6)。1078 passed・
  スコアカード: reconcile_fuel_tokyo_2026-06-12.json

## 2026-06-12 — **Fable 5** — F2: 東電燃料別実績をDB搭載 — 通年12ヶ月・13系列（68）

- **取得**: eria_jukyu 2025-05〜2026-04の12ヶ月をcurl取得(urllibはTLS指紋系403 →
  curl -A必須と記録)。data/external/tso_jukyu/tokyo/+meta.json
- **パーサ**: `tso_jukyu_rows()` — OCCTO共通様式の燃料13列(原子力/LNG/石炭/石油/他火力/
  水力/地熱/バイオ/太陽光/風力/揚水/蓄電池/連系線)→ metric=gen_by_fuel:<fuel> で
  measured_area_statsへ。calibrate `--tso-jukyu` 1コマンド統合
- **実測値(東京・q50)**: gas 14,652 / coal 5,646 / hydro 1,115 / oil 453 /
  interconnect 4,459 MW・**nuclear 0(柏崎刈羽未稼働の実態どおり)** — 燃料別dispatch
  検証(F4)の真値が揃った
- **バグ修正(正直記録)**: 多metric地域でローダがarea単独キーのため**燃料13系列が
  相互上書き**→無filter時は(area,metric)キーに変更(reconcile UC入口も追随)。
  1078 passed

## 2026-06-12 — **Fable 5** — X1: UC合流資産の採否判定 — 置換なし・役割分担を確定（67）

- **OCCTOコネクタ**: dataspace版は当方の実証エンドポイント(台帳⑲)を参照する**UC実行時
  データ層**(契約/キャッシュ) — 当方fetch_occto_kohyo=**アーカイブ+メタ+DB較正**。同源で
  役割分担、統合不要と判定
- **需要データ**: UCのprofile_ref=**エリア×年間時系列**(いつ) vs 当方measured_bus_loads=
  **変電所×断面p95**(どこ) — 直交軸で相互補完。置換なし。将来reconcileの時間分解に
  UCプロファイルを使う選択肢のみ記録
- X2(capacity_bridgeのPF側A/B)・X3(燃料別帯判定へのUC dispatch接続)は継続項目。
  1078 passed(合流後)

## 2026-06-12 — **Fable 5** — D1/D2: 詳細化開始 — wires束を定格へ反映（66）

- **D1棚卸し**: 未活用証拠の充足率 — **wires 13%(5,045本)**・circuits59%・cables67%(活用済)・
  voltage85%。変電所ratingタグは10/6,962で棄却。power=transformerノード/minor_lineは
  要再fetch(D3/D4へ)
- **D2実装**: wiresタグ(single/double/quad/sixfold/eightfold+数値・複合は最大)→
  `n_bundle`としてedge→TransmissionLineへ伝搬(マージ=max・縮約=max)。builderは
  **クラス典型束(500kV:4/275-187:2/以下:1)との比で定格max_i_kaのみ補正**[0.5,2.5]clamp —
  インピーダンスはクラス既定維持(典型値に束効果が織込済みのため二重計上回避を明記)
- 東京: 束証拠つき1,357枝(quad+ 224枝)。流れρ不変(定格はDC/AC流量に無影響) —
  効果はS1のN-1スクリーニング・loading KPIの精密化に現れる設計。981 passed

## 2026-06-12 — **Fable 5** — N6: west品質診断 — 「過負荷1631%」は架空定格の錯視、実態は健全（65）

- **診断**(west島AC解): 電圧沈下vm<0.85は**6,998バス中17バスのみ(0.24%)** —
  四国南東岸(甲浦0.656・牟岐等)の長距離66kV放射=**正直な物理**(実測需要が無い地域の
  合成配分も一因。修正根拠が無いため記録のみ)
- **過負荷の正体**: >200%は6本だけで、うち**5本は合成橋(recon_line)と所内50mスタブ** —
  物理実体のない要素に架空の熱定格(0.6-0.7kA)が付いていた錯視。1632%の主犯は0.1kmの
  77kV合成橋だった
- **正当な修正**: scale_line_ratingsで**非物理要素(所内スタブ・合成橋・≤60m区間)を
  定格非拘束(100kA)に** — loading KPIが実在線だけを測るようになる。
  A/B: west最大負荷 **1632%→227%**(最悪=実在の大田支線)・AC収束維持・vm不変
- 残る実在過負荷(大田支線227%・九州送電線200%)は需要配置/並列数の個別案件として記録。
  981 passed

## 2026-06-12 — **Fable 5** — N4完了: 全国一枚系統図+国家MATPOWERエクスポート（64）

- **全国一枚系統図**: `render_grid_figure.py --region national` — 10地域・枝14,138・
  変電所10,077を実OSM経路で1枚に(全4島AC収束の注記つき)。LINE+ユーザー納品済み
- **国家MATPOWER**: `scripts/export_national_matpower.py` → dist/matpower_national/ —
  4島別 bus/branch/gen CSV(p.u. on 100MVA・出典メタつき):
  hokkaido 778/878/358・east 5,024/6,124/7,506・west 7,082/10,388/7,448・okinawa 89/85/25。
  生成物は非コミット(スクリプトが再現レシピ)・別開発UCがそのまま読める形式
- 981 passed(64の「982」は誤記でここで訂正)。N4完了 — N残=N5国家reconcile・N6 west品質磨き

## 2026-06-12 — **Fable 5** — 🎉N1/N3: WEST統合島AC初収束 — 「日本としての系統」全島AC成立（63）

- **N1計測**: 同期4島の現状=hokkaido(778subs)/east(5,024)/west(7,082)/okinawa(89)。
  **west統合島のYbus条件数=4.42e8 — PASS(良品圏)**: 「既知不良アンカー」の前提が覆った。
  WEST_AC_ANALYSIS当時の悪条件(比率20の変圧器539台)は、その後の多電圧ビルダー
  (クラス別バス+標準ラダー変圧器)で構造的に解消されていたと判明
- **N3実行**: west島 **AC=OK**(3キャンペーン失敗の末の初収束)。続けて全島実行 —
  **hokkaido/east/west/okinawa 全てAC=OK** = 日本一体の系統が史上初めて全島ACで成立。
  ユーザーの「とにかく日本としての系統を完成させたい」の核が通った
- **正直な品質注記**: west vm_min 0.656(深い放射端の電圧沈下)・maxload 1631%
  (定格/合成線の見直し対象)・synth 511本 — 収束の壁は崩れたが磨き込みが次工程
- **N2(外科手術)は不要だった**と記録(ゲートが先に「壁は消えている」と教えた —
  計測駆動の価値の好例)。国家ライブマップ成果物(docs/data/powerflow_national)更新
- west島ybusスコアカード: `ybus_west_island_2026-06-12.json`。981 passed

## 2026-06-12 — **Fable 5** — P2: 検証図版5点を生成 — 全てcommitted scorecardから再現可能（62）

- `scripts/gen_paper_figs.py` → papers/figs/val_*.{pdf,png}: (A)3層ρ推移(計器改訂と
  モデル変更を区別注釈) (B)帯別recall+マッチ階層内訳 (C)reconcile帯(修正前検出の図化)
  (D)西日本ポケット構造(連結率+33件分類) (E)計器駆動閉ループ図
- 入力は全てdocs/reports/のcommitted JSON=**リポジトリだけからビット安定に再生成可能**
  (夜間規約の再現性条件に適合)。Hiragino+Type42でIEEJ組版互換
- 981 passed(図スクリプトのみ)。P3(ieej.tex新節ドラフト)の素材完備

## 2026-06-12 — **Fable 5** — W2: 孤立33ポケットの分類台帳 — 過半はノイズ/越境/離島（61）

- **機械分類**(docs/reports/west_isolated_pockets_2026-06-12.json):
  ノイズ断片(無名junction≤3節点)**10** / 上位接続欠落疑い(上位ヤード5km内)**10** /
  遠隔(離島・山間)**7** / 中距離**6**
- **新発見=越境スライス断片**: 関西の最大孤立2件は**徳島市(20節点)・淡路島(14節点)** —
  四国電力エリアが関西bboxに写り込んだもの(モデル欠陥ではない)。九州にも中国電力
  彦島/下関の写り込み。地域スライスの境界事象として分類に追加すべき知見
- **本命のキュレーション対象**: 「上位接続欠落疑い」10件(例: chubu石和町松本系12節点
  d_upper=2.1km・kyushu犬飼2.6km) — 変圧器/上位線のOSM未収載でW5のOSM編集ターゲット
- kansaiの連結率91%の残りは越境断片が相当を占める見込み → W3で越境を除外した
  「真の連結率」を再計測してゲート判定するのが正しい物差し
- 計測のみ・モデル不変・981 passed

## 2026-06-12 — **Fable 5** — F1: TSO需給実績の所在調査 — 東電検証済み・共通様式確定（60）

- **東電を実地検証**: `eria_jukyu_YYYYMM_03.csv`(UTF-8-sig・30分値)に**燃料別供給実績**
  (原子力/LNG/石炭/石油/水力/地熱/バイオ/太陽光実績+抑制/風力/揚水/蓄電池/連系線)を確認 —
  reconcileの燃料別dispatch検証(F4)に必要な列が全て揃う
- **様式はOCCTO共通**と確定(各TSOが同フォーマットで公開) → F2プロトタイプは東電で実装し、
  F3は各社URLの発見作業に純化。関西は最初の推測パスが外れ(需要のみのjuyo1はヒット)、
  正確なパスをF3課題として正直記録
- docs/VALIDATION_SOURCES.mdに台帳追加。コード変更なし(調査のみ)・981 passed

## 2026-06-12 — **Fable 5** — P1: 論文戦略確定 — 既存IEEJ原稿の増強+方法論第2論文の二段構え（59）

- **現状確認**: papers/ieej.tex(パイプライン+646機UC+動特性、6/3版PDF済)に
  **外部実測検証の章が無い** — 査読の最大の弱点が今回成果でそのまま埋まる構図
- **戦略(docs/PAPER_OUTLINE.md)**: ①既存原稿に新節「外部実測による検証」(recall56.3%・
  3層ρ・OCCTO完全一致・限界3因の明示、図3点) ②第2論文=検証方法論
  (計器設計・**訂正事例集㊼/58/㊱が独自性**・負の結果カタログ・閉ループ実証56)
- 図版5点のTODOと P2〜P5 の割当を確定。台帳がそのまま素材になる構造
  (=毎反復の記録規律が論文の生産手段だったことの回収)

## 2026-06-12 — **Fable 5** — W1: 「西日本重度断片」はKPIの錯視 — 91〜98%は上位網連結済み（58）

- **分類計測**: 西3地域の66kV帯断片の主成分距離 — **8〜9割が8km超**(chubu 60/61等)。
  接続可能なギャップではなく**地方都市ごとの66kVポケット**(東の連続メッシュと運用構造が違う)
- **決定打**: ポケットの上位網(154/275kV)経由連結を計測 — **chubu 95% / kansai 91% /
  kyushu 98%のノードがフル主成分に連結済み**。真の孤立は13+12+8=**33ポケットのみ**
- **テーゼ転覆(㊶の訂正)**: 「66帯最大成分カバー11-19%=重度断片」は**東日本型KPIの誤適用**。
  西の66kVはポケット構造が物理的に正しく、モデルは既におおむね健全だった。
  ㊼(別ヤード訂正)に続き、強い否定形の主張は物差しの妥当性から疑うべきの再教訓
- **Wトラックのゲート差し替え**: カバー≥50%(誤った物差し)→ **上位網連結率≥95%**
  (chubu✓/kyushu✓・kansai 91%が残課題) + **真の孤立33ポケットの個別解消/説明**(レビュー可能規模)
- 道路スコア(53)の「採択9件」もこの文脈で再解釈: ポケット間を66kVで繋ぐのは
  そもそも物理に反する可能性 — レビュー時は上位網経由の妥当性を優先

## 2026-06-12 — **Fable 5** — OCCTO fetch拡張: 種別探査とメタ管理（57・M10完了）

- **種別探査(正直な結果)**: jhSybt=01/03(日粒度)・05/06(時間内)は既存02/04の**予想・計画変種**で
  追加の実績データなし — 「再エネ実績」はこのAPI系列に存在せず**各TSOの需給実績CSV**
  (別ソース系統)。将来のフェッチャ対象として記録、本項の対象外と判定
- **メタ管理**: 取得ごとに`meta_<types>_<window>.json`(出典・URL雛形・窓・取得日時・
  保持~14ヶ月注記)をCSV隣に書き出し — **窓がAPIから消えた後もスナップショットが引用可能**に
- 動作確認: 2026-05窓でフェッチ+メタ生成✓。981 passed(コード変更はフェッチャのみ)
- **M10完了**: fetch(メタ付き)→calibrate(--occto)→DB→reconcile(+UC入口)→LINE の
  突合プラットフォーム一式が運用状態。残=M9地形DEM(発展・保留可)のみ

## 2026-06-12 — **Fable 5** — reconcile所見の実装: 北海道・四国ピークをOCCTO根拠で修正（56）

- **修正**(計器→モデルの初の閉ループ): `regional_demand.yaml` —
  **hokkaido 3,600→5,200MW**(旧値は夏値で冬ピーク欠落。OCCTO p95 4,441/LF=5,225、
  既知の冬ピーク~520万kWとも整合) / **shikoku 5,500→4,700MW**(旧値過大1.16×p95。
  OCCTO p95 4,013/LF=4,721)。出典・台帳番号をyamlコメントに記録
- **検証**: reconcile帯=両地域とも**1.0×p95でq50..p95帯内**に正常化。
  solve健全性: hokkaido AC収束・n_unsolved 0・vm_min 0.858(需要+44%で電圧は沈むが許容)、
  shikoku vm 0.958。テスト1件の旧値ハードコード(5500)を更新して981 passed
- tokyo計器への影響なし(地域独立・境界util不変=ρ再計測不要)。zonal/national成果物は
  次回regen時に新需要で更新される
- 意義: M10計器が**初めて具体的なモデル修正を駆動** — fetch→calibrate→reconcile→config修正
  →帯内確認、の機械的サイクルが一周した

## 2026-06-11 — **Fable 5** — `ajgrid reconcile`: 需要スケーリングの地域別初検証＋UC入口（55・M10-3）

- **実装**: `scripts/reconcile.py` + `ajgrid reconcile` — measured_area_stats(OCCTO)に対し
  (a)各地域の設定断面(ピーク×LF) vs 実測帯q50..p95 (b)境界util(DB導出)
  (c)**外部UC時系列CSV入口**(area,metric,value_mw→同じ帯判定、UC_HANDOFF契約)。
  判定は合否でなく**帯**(<q50 / q50..p95 / >p95)=断面が年間分布のどこかに居るのは正当
- **初検証(所見)**: 10地域中6地域が帯内(東京0.97/中部0.98/九州0.98×p95等=設定の妥当性を
  初めて地域別に確認)。**北海道<q50=設定ピーク過小の疑い**(OCCTO窓に冬を含む・要確認)・
  **四国1.16×p95=過大の疑い** — 需要設定の具体的な修正候補2件が初めて特定された
- レポートをLINE配信(運用開始)。`reconcile_occto_2026-06-11.json`。981 passed
- M10残: fetch拡張(再エネ実績等・軽)。北海道/四国ピークの修正は計測根拠つきで次回判断

## 2026-06-11 — **Fable 5** — OCCTO実測のDB化: 連系線ハードコードを機械更新に移行（54・M10-2）

- **DB化**: `measured_area_stats`(area,metric,source PK / q50,p95,signed_q50,window) —
  calibrate.py `--occto` がkohyo_02(エリア需要10地域)+kohyo_04(連系線14本)を集計・upsert。
  1コマンドで line_stats/bus_loads と同時更新
- **boundary.py移行**: `measured_utilisation_from_db()` — OCCTO符号付き中央値÷yaml容量
  (clamp±1)。ic_id↔OCCTO開示名の対応表`_OCCTO_IC`(**ic_004のみ符号反転**=OCCTO順方向が
  関西→中部)。ハードコードMEASURED_UTILISATIONは凍結スナップショットfallbackに降格
- **検証**: **全9連系線でDB導出値がハードコードと完全一致**(0.15/0.74/−0.33/0.79/−0.15/
  −1.00/−0.05/−0.94/−0.49) — 出自データから機械再現できることを実証。モデル不変
  (値一致のためρ再計測不要と明記)
- 意義: 連系線実測の更新が fetch_occto_kohyo→calibrate の2手に。単体テストで
  符号反転・複数名合算・クランプ・フェイルソフトをpin。980 passed
- M10残: (1)fetch拡張(再エネ実績等) (3)`ajgrid reconcile`レポート+UC時系列入口+LINE

## 2026-06-11 — **Fable 5** — 道路経路スコア再接続: 計器完成・自動接続は見送り判定（53・M9-2）

- **計器**: `scripts/score_road_reconnection.py` — 66kV帯の分断成分ペア(直線≤crow_max)に
  「道路徒歩+道路最短路/直線距離」比でもっともらしさをスコア(prior=51の3倍差が根拠)。
  九州道路網8万kways/805k節点(Overpass、本家レート制限→kumi.systemsミラー)
- **計測(九州)**: 保守パラメータ(≤3km/ratio1.8)=46ペア中**採択3・カバー利得ゼロ** —
  小ギャップはsnap/tapで処理済みで、**西の断片は回廊まるごと欠落**(52の傍証を再確認)。
  緩和(≤8km/ratio2.0)=84ペア中**採択9・カバー18.9→26.0%(+7.1pp)** — 大成分同士の
  結合(101+28等)を含む実質的な潜在量
- **判定**: 4.5〜7.6kmの合成66kV線は「海峡橋を架けない」原則と同種の捏造リスク →
  **自動既定にはしない**。採択9件は(a)人手レビュー付きキュレーション候補
  (b)OSM編集ターゲット(線名・経路つき)として資産化。opt-in統合は将来判断
- モデル不変(計測のみ)・979 passed。M9残=地形DEM版(発展)とbearing継続スナップ

## 2026-06-11 — **Fable 5** — 中間タップスナップ: 「ただの線で接点が見えない」を実装（52・M9）

- **ユーザー実地観察の実装**: OSMは裸のポリライン — T分岐の端点が本線の**径間中央**に
  落ちると共有ノードが無く非接続に見える。計数: 行き止まり端点が他線径間120m以内なのに
  未接続 = **東京201・中部196・関西89件**(実在規模を確認)
- **実装**: ビルダーPass B後に径間グリッド(セグメントbbox全セル登録)→次数1junctionを
  最寄り同クラス径間の端ノードへ接続。`tap=True`が縮約・並列マージを通して伝搬し
  prov `tap=snap` で出荷(捏造の可視化)。**ガード=両側クラス既知かつ同一** —
  不明クラス互換を許すと154/66交差が融合する事故を多電圧回帰テストが検出→締めた
- **デバッグ2件**(正直記録): (a)径間を中点1セルにのみ分箱→長径間が探索から消失(bbox全セルへ)
  (b)タップ挿入で次数2になった端点が連鎖縮約され**フラグだけ消失**(94本接続/6本標識)→フラグ伝搬
- **計測**: 東京タップ54本・成分61→58 / 九州カバー16.3→18.9% / 沖縄はスタブ2本接続
  (pin更新: junctions 16→14・branches 87→85・buses 91→89、コメント付き)。
  ρは誤差帯(全体0.456・154 +0.005) — **連結の実改善+クラス安全を保ち採用**。
  westの断片は中間タップでなく属性欠落が主因という追加証拠も得た
- 979 passed。正準計器=jスコアカード

## 2026-06-11 — **Fable 5** — 「66kVは道路沿い」priorを定量化: クラス単調・66は187+の3倍（51・M9-1）

- **実験**(ユーザー着想の検証): 埼玉中心bbox(35.8-36.3N, 139-140E)の主要道路
  (motorway/trunk/primary/secondary)1.5万waysをOverpass取得→60m間隔に稠密化した
  22万点のKDTreeで、送電線経路点の道路150m以内割合をクラス別計測
- **結果**(架空線): **66-77kV: 平均36%・中央値28%・過半道路沿いの線26%**(n=484) /
  110-154kV: 22%・9% / **187kV+: 11%・6%**(n=217) — **電圧クラスに単調**。
  ユーザーの「66kVは道路に沿う・高圧は地形横断」がそのまま数字に
- **正直な強度評価**: 主要道のみの計測(細道を足せば全クラス上昇)なので絶対値でなく
  **クラス間差分(3倍)が本質**。66kVでも過半沿いは26% → 再接続の**ハード規則ではなく
  スコア特徴**として使うのが適正(道路経路が存在する候補の妥当性を加点)
- 帰結: M9-2(道路経路スコアの断片再接続)に進む根拠が立った。データ: data/external/osm_roads/
  (gitignore準拠・再取得コマンドは本台帳)。モデル不変・979 passed

## 2026-06-11 — **Fable 5** — Ybus出荷品質ゲート: 全10地域PASS・閾値を経験較正（㊿・M8完了）

- **実装**: `src/powerflow/ybus_gate.py` — 島別に基準バス縮約Ybusを構築し
  **1ノルム条件数を推定**(onenormest×LU作用素、密逆行列なし)。FAIL島は名指し報告。
  CLI終了コード(0/1/2)でCI/スクリプト組込可
- **閾値の経験較正**: 全10地域フルモデル(全てAC収束=既知良品)を計測 —
  cond₁ = **5.6e5(okinawa)〜2.0e8(tokyo)** → 閾値1e9(最悪良品の1桁上)。
  既知不良(west統合島)の実測はwest構築時の残TODOとして正直記録
- **単体テスト**: 健全2バス網PASS + 病的低インピーダンス変圧器連鎖(west型)で
  条件数>1000倍悪化→FAILをpin
- **引き渡し文書**: `docs/UC_HANDOFF.md` — 別開発UCへの契約(解く前にgate必須・
  FAIL島の最適化は無意味・ゾーン集約の指針・モデルの正直な限界)
- 979 passed。**M8完了** — westの教訓が恒久計装になった

## 2026-06-11 — **Fable 5** — PTDF需要状態推定v2/v3: 交差検証で「転移なし」を確定（㊾・M7完了）

- **v2(個別負荷PTDF最小二乗)**: 自前B行列→計測回廊のPTDF行を抽出、全train回廊を同時フィット
  (lsq_linear・P≥0・事前分布正則化λ=0.1・総量ソフト保存)。単体検定=放射1回廊で残差20→0の完全較正。
  実機: train(fitted)ρ **0.427**・RMS残差大幅減 — **機構は健全**
- **交差検証(両半分入替)が決定打**: v2 test = **0.191(A) / 0.083(B)** → 平均≈基線0.14。
  Aの0.191は分割運(偶数半は常に難・奇数半は常に易の固有非対称)
- **v3(空間クラスタ再パラメータ化)**: 自由度1,500→~130セル(0.15°格子・決定論)で
  「地域スケール」への転移を狙う → test **0.174(A) / 0.080(B)** — 同じく平均≈基線
- **構造的結論**: 樹状下位網では計測回廊流量=**局所制約**。自身の部分木は完全に較正できる
  (in-sample 0.43)が、他回廊への情報は事前分布を超えない — 「巧い逆推定」ではρ66の天井は
  破れず、**回廊ごとの実測 or 接続改善が必要**という天井の本質を3手法・6計測で確定
- **採否**: 既定不採用(in-sample較正での見かけρ向上は不誠実として明示的に拒否)。
  機構はopt-in計器(`--corridor-calib`/`--calib-swap`)として保存 — 将来、開示回廊が増えた時の道具
- 978 passed。スコアカード: i(v2-A)・/tmp v3系は台帳数値のみ(分割実験のため正本はこのエントリ)

## 2026-06-11 — **Fable 5** — 流量保存則の需要推定v1: trainは効くがtestへ汎化せず（㊽・M7開始）

- **ユーザー指示**「技術的に天井を破るのが仕事・名前はそこまで重要でない」→ 名前非依存の
  **需要状態推定**に着手: 計測回廊で系統を切ると負荷側部分木の需要合計=回廊流量(保存則)。
  名前は回廊の特定にだけ使い、その下流の**無名ヤード全部**へ需要が流量から決まる
- **実装**: `src/powerflow/flow_calibration.py` — 注入ノード(≥140kV変換点/電源)判定、
  入れ子は内側優先で凍結、実測ピン(`measured_*`)保護、過大スケール25倍でスキップ。
  ホールドアウト計器 `--corridor-calib`(決定論的交互分割、train=fitted/test=公正)
- **バグ修正**: 直列N区間の回廊を全部切ると中間junctionが孤立し「2側に分かれない」誤判定
  → 「注入を含む成分 vs 含まない成分の和集合=負荷側」に一般化。帯判定も高い側端点に変更
  (kv不明バスが連結を切らない)。較正到達 7→**40回廊/2.6GW**
- **計測(正直)**: train(153中40較正)ρ 0.145→**0.227** — 機構は効く。だが**test(154)ρ 0.087**
  =無較正0.14より悪い**負の転移**。原因: (a)部分木「合計」のみ正しく内部分布は未制約
  (b)p95を断面にピン=局所過大→全体バランスが歪み未較正回廊へ波及 (c)名前なし85回廊に
  届かず・ループ上71回廊は部分木が定義不能 → **既定不採用**(opt-in計器として保持)
- **v2を設計して運転票に追加**: PTDF最小二乗(全回廊同時フィット・ループ可・正則化で
  事前分布に接地・総量保存)が原理解。次反復で実装し、test ρで採否判定。978 passed

## 2026-06-11 — **Fable 5** — ユーザー指摘で「別ヤード」主張を訂正: eponym連結44%・配置タイア追加（㊼）

- **ユーザー挑戦**「別ヤードなの？適切に接続できる気がする」→ 検証したら**正しかった**
- **再計測**: 線名は行先変電所を名乗る慣習(塚田線→塚田変電所) — この**eponymルール**で
  純66帯回廊475本の**44%(211本)が母線計測変電所と連結可能**。㊲の「計測点ベースで
  カバレッジ中央値0%・ほぼ別集団」は**過小連結の誤り**として訂正(README修正済み)
- **ただし天井の本質は不変**: 回廊流量は行先需要の**中央値2.6倍**(=複数下流ヤードの合算)で
  真値側相関ρ=0.25 — 行先1件の需要では回廊流量を順序づけできない構造は変わらず
- **実装(eponym配置タイア)**: 名前不一致の実測変電所554件のうち、同名回廊がモデル66帯に
  在る**40件/0.56GW**を回廊端点へ配置(`_place_measured_loads`第2タイア・他の実測ヤードの
  端点は奪わないガード)。A/B: 全層誤差帯(0.455不変) — 0.56GWでは解像不能と予測どおり、
  物理的忠実性で採用。基準計器=g。976 passed
- 教訓: 「別集団」のような強い否定主張は**連結ルールを尽くしてから** — ユーザーの
  ドメイン直感が計器の盲点(命名慣習)を突いた好例

## 2026-06-11 — **Fable 5** — ゲート判定と終了記録: 未達=データ律速の天井を確定（㊻・M6=プログラム完了）

- **ゲート判定**(基準計器f): 154 0.106/0.40・66 0.136/0.30・全体0.455/0.50 — **3ゲートとも未達**
- **READMEに正直記載**: 到達点(フルAC 10/10・実測需要1,222件/19GWのDB化・3層計器・recall56.3%)と
  **データ律速の天井**3点(OSM都心地中未収載㉝・開示の線路/母線計測点分離㊲・常開点非公開㊷)を
  台帳参照つきで公開。古いρ0.66表記を現行計器(0.46/419回廊・幹線のみ0.60)に更新
- **他地域展開メモ**: 東日本=構造準備済み(タグ95-98%)・流れρは東電開示のみ・西=断片解消が先
- **プログラム総括**(㉛–㊻・15項目・1日): ρ全体0.418→0.455(計器拡大込み)・66kVρ初の有意・
  接続recall 50.3→56.3%・**負の結果4件**(末端オフテイク偽陽性/需要ピンのρ無効果/放射化無効果/
  人口配分のトレードオフ)を全て記録。「未達の理由を計測可能な形で特定した」ことが最大の成果
- **再開条件を運転票に記録**: OSMケーブル収載進展/他社線別開示/常開点情報 — 自律ループは
  チェックリスト完了により**正常終了**

## 2026-06-11 — **Fable 5** — 154/66トランス妥当性: 分布は健全・変更不要（㊺・M5完了）

- **診断**(東京フル・AC収束): 全772台の負荷率分布をクラス対別に計測 —
  154/66(414台・200MVA): 中央値15%/p90 28%/最大78%・過負荷0。275/66(125台): 中央値22%・
  122%が1台のみ。500/275(51台): 中央値12%/最大98%。**系統的な過負荷・容量不足なし**
- **判定**: 容量(sn_mva)・インピーダンス(vk 10-12%=標準値)は流れを歪めていない。
  タップ最適化も不要(クラス別電圧スケジュール+Q制限で vm_min 0.897 健全) → **変更なしで閉じる**
- 副所見: (500,66)直結バンク53台=OSMで中間クラスが欠けるヤードの近似(既知の縮約)。
  kv=0線の66kVフォールバック警告20件(既知)
- モデル不変(診断のみ)・計器はf(0.455)のまま。**M5完了** — 残りはM6(ゲート判定・展開メモ)

## 2026-06-11 — **Fable 5** — 地中ケーブルのXLPEパラメータ: 物理的忠実性で採用（㊹・M5-3）

- **発見**: OSMは`power=cable`/`location=underground`で地中線を明示 — 東京486 features
  (66kV 313本)。**従来は全線が架空ACSR値**(X=0.29-0.40Ω/km)で解かれていた
- **実装**: line_types.yamlに各クラスの`cable:`変種(66kV XLPE: X=0.11Ω/km≈架空の1/3・
  R=0.05・B=1.1e-4)。`get_line_parameters(kind="cable")`→builderがline.is_cableで選択。
  トポロジ側は cable長を区間→連鎖縮約まで加算し**過半長ルール**でis_cable判定
  (provに`med=cable`)。東京で**151枝/57km**がケーブル化
- **A/B計測**: 全層誤差帯内 — 全体0.463→0.455 / trunk −0.015 / 154 +0.009 / 66 −0.008・
  倍率1.09→**1.07**。OSM収載ケーブルが57kmのみ(都心網の大半は未収載=㉝)のため
  計器では解像不能と正直記録
- **採用判断**: XLPEのX≈架空1/3は教科書的事実=物理的忠実性で**採用**(㉙㊲と同基準)。
  OSMに都心ケーブル網が描かれた時に自動で効く土台。新計器基準=fスコアカード。975 passed

## 2026-06-11 — **Fable 5** — 国勢調査メッシュ需要配分: 154は+0.05動くがtrunkとトレード（㊸・M5-2）

- **データ**: e-Stat 2020国勢調査1kmメッシュ人口 — `scripts/fetch_estat_mesh.py`で関東12メッシュ
  =**34,823セル・49.2M人**取得(downloadType=2エンドポイント。出典明記・data/external/gitignore)
- **実装**: `population_factors()` — 各セルの人口を**最寄り配電バスへVoronoi配分**(KDTree)し
  残余需要の重みに。`estimate_loads(spatial="population")`・CLI `--spatial population`。フェイルソフト
- **A/B計測**(東京フル・実測ピン込み、c基準0.463):
  - 全置換: 全体0.466 / **154 0.097→0.148(+0.051)** / trunk **0.617→0.567(−0.050)** / 倍率1.09→1.31
  - 有界傾斜(0.5+0.5×pop、degree_factors流): 全体0.467 / 154 0.131 / trunk 0.588 / 倍率1.24
- **判定**: 154の改善(ユーザー注力点)は方向性ありだが**p=0.39-0.45で未有意**、最も信頼できる
  trunk計器が悪化し総量倍率も劣化(都心過集中→広域輸送が過大) → **既定にせずopt-in採用**
  (有界版を実装として保持)。AC収束も顕著に重くなる副作用を観測
- 残る改良案: クラス限定傾斜(66kV帯のみ人口傾斜)・昼間人口/事業所統計の併用。
  REPRODUCIBILITY §4にfetch手順追記。974 passed

## 2026-06-11 — **Fable 5** — 放射化プロキシ実験は無効果: 仮説試験済み・不採用（㊷・M5-1）

- **実装**: `radialize_band(net, 60-140kV)` — 回廊グラフの成分毎に**インピーダンスMST**を残し
  非木回廊を開放(並列回線は同一回廊として一括開閉・孤立を作らない構造)。完全opt-in
  (`build_and_solve(radialize_band_kv=)` / CLI `--radialize-66`)、既定挙動は不変
- **A/B計測**(東京フル・実測需要ピンあり): ρ66 **0.144→0.138** / 全体0.463→0.463 /
  trunk −0.002 / 154 +0.004 — **誤差帯内の無効果(やや悪化)** → **不採用**
- **読み**: ㊵の予測(66kV層は既にほぼ樹状・開けるループは114個のみ)どおり上振れ無し。
  MSTプロキシが実際の常開点と一致しない可能性も残るが、現データでは検証不能 —
  実験フラグはコードに保持(将来、常開点情報が得られた時の道具)
- **残るレバー**: M5-2 国勢調査メッシュによる未計測~30GWの地理配分(仲裁実験㊵の
  未計測側ρ0.110→0.19が狙い)・M5-3 R/X現実化。973 passed

## 2026-06-11 — **Fable 5** — 66kV品質の地域別台帳: 東は良好・中部/関西/九州は断片(㊶・M4完了)

- **計器**: `scripts/report_kv66_quality.py` — 各地域の60–140kV帯を構造プロファイル
  (枝数・成分・最大成分カバー・cycle rank・放射端率・電圧タグ由来率)
- **計測**(10地域): 東日本は良好 — hokkaido/tohoku/tokyo のタグ率95.2–97.9%、
  tokyoカバー68.5%。**chubu 11.6%/kansai 17.2%/kyushu 16.3%のカバー=重度断片**
  (chubuはタグ率も69.6%と最低)。cycle rankは全国16–114=**66kV層は全国的にほぼ樹状**
- **含意**: (a) 66kV流れ検証は現状tokyo限定(東電開示)だが、tokyoは**最良の66kV層** —
  他地域展開時はρ天井がさらに低い前提で読む(M6展開メモの根拠) (b) 放射化プロキシの
  上振れは全国で限定的(㊵と整合) (c) 西日本の66kV潮流には断片解消(接続キュレーション)が先決
- レポート: `kv66_quality_by_region_2026-06-11.json`。モデル不変・972 passed。**M4完了**

## 2026-06-11 — **Fable 5** — 放射構造の検証: 66kV層は既にほぼ樹状・ρ66の天井を仲裁実験で分解（㊵・M4-3）

- **モデル66kV層の構造計測**(東京): 1,363実変電所/2,002辺/68成分 — **cycle rank=114**
  (独立ループ数)・放射端24%・次数中央値2 → **モデルは既にほぼ樹状**。「実網の放射運用 vs
  モデルのメッシュ解」仮説の上振れ余地は**最大114ループ分に限定**(死んではいないが主犯級ではない)
- **開示末端集合は真値として弱い**: 26件中モデル名一致13・モデルでも放射端は2件のみ —
  だが不一致の主因は片端計測の罠(新木更津=4次数が混入)とOSM未収載(墨東=孤立ノード)で、
  構造検証の物差しにならないと判定(計器の限界を正直記録)
- **帯内同名異線**: 計測66キー309中、互いに遠い同名別線グループは**8件(3%)** — 容疑棄却
- **仲裁実験(決定打)**: ρ66=0.145を実測需要端点の有無で分割 —
  **実測端点あり129回廊: ρ=0.189(p=0.03) / なし178回廊: ρ=0.110(p=0.15)**
  → (a)需要配置は機能している(計測のある所では+0.08) (b)**実測ありでも0.19が天井** =
  残差は構造・運用・電気定数。ゲート0.30へは「未計測需要の地理代理(国勢調査メッシュ)」と
  「放射化114ループ+R/X」の両輪が必要
- モデル不変(計測のみ)。972 passed

## 2026-06-11 — **Fable 5** — 残存20件の実地検分: 孤立重複ノードとホモニム誤マッチ（㊴・M4-2）

- **実地検分**(分断9+遠距離12+α=20件): 2系統に分解
  - **同名異線の誤マッチ**: 南武-中原線(88km先)・邑楽-小泉線(94km)・高井戸-北烏山線(117km)・
    東川崎-塩浜線(=千葉の市川塩浜線、23km) — loose包含マッチの暴発。**ホモニムガード実装**
    (loose一致かつ最寄端点>20km→「この変電所では欠落」として分類) → 43件を正直に再分類
    (unattached 190→**154**・衝突41→**34**・recall 56.3%は不変=分類学の浄化のみ)
  - **本物の事例**: (a) **西厚木変電所=完全孤立ノード**(接続0本) — 実ヤードはOSMで
    「岡田変電所」(1.78km先)として正しく配線済み。TEPCO名と地区名の二重登録(西北線/稲城型)。
    栄町-寺尾線(1.9km)も同型疑い → キュレーション対象として記録 (b) 都心・山間の
    **地中/山岳ケーブル断片**(東新宿水道橋線・箱根線・新豊洲線) = OSM部分収載(計器上限)
- **モデル不変** → ρはc計器(0.463)のまま。OSM編集ターゲットリストの信頼性が向上
  (偽の「88km先にある」報告が消えた)
- 972 passed。スコアカード: `external_match_tokyo_tepco_banded_2026-06-11c.json`

## 2026-06-11 — **Fable 5** — 「未接続」の正体は線名分節: 隣接タイアで66帯recall 53%・配線は健全（㊳・M4-1）

- **解剖**(㊲の「律速=接続」を検証): 距離つき未接続184件の端点をグラフ到達性で実測 —
  **108件(59%)は公式変電所の1ホップ隣**・3ホップ以内82%・真の分断はわずか9件(+遠距離12)。
  「未接続」の大半は**OSMの線名分節**(ヤードへの最終区間が別名/無名)による計測アーティファクトで、
  **モデルの電気的配線はほぼ正しい**
- **計器改良**: match_tepcoに**グラフ隣接タイア**(公式変電所が線名グループ端点の1セグメント隣
  =電気的接続を確認して接続扱い。crow-fly位置タイアより強い基準) → recall
  50.3%→**56.3%**(+adjacent 63)・帯別 trunk 60.8% / 154 **61.3%** / 66 **46.9→53.1%**・
  unattached 242→190・衝突52→41(隣接が先に判定される分。クラス誤型の可能性は kv_provenance KPI側で追跡)
- **モデル不変**(matcherのみ) → ρは㊲のc計器(0.463)のまま、再計測省略を明記
- **帰結(仮説の再改訂)**: 配線も需要も「ほぼ正しい」のにρ66≈0.14 — 残る最有力仮説は
  **66kVのループ常開(放射)運用**: 実網はメッシュ構造を常開点で放射運用するが、モデルは
  メッシュのまま解くため流量配分が構造的に異なる。常開点は非公開 → プロキシ実験
  (インピーダンス/需要重みでループを開く放射化)をM5に追加。真の配線課題(分断9+遠12)はM4残
- 971 passed。スコアカード: `external_match_tokyo_tepco_banded_2026-06-11b.json`

## 2026-06-11 — **Fable 5** — 実測需要ピン留めはρを動かさず: 律速は接続正確性と判明（㊲・M3完了）

- **実装**: `estimate_loads(measured_bus_loads=, measured_stat="p95")` — 名前一致した
  実測変電所に**絶対MWをピン**(多電圧ヤードは最低≥50kVバス=配電引出し点、目標超過時は
  比例縮小、残差のみ従来の電圧クラス則で未配置バスへ)。pipelineはDBから自動読み
  (`measured_loads="auto"`、行なし地域は従来どおり)。A/B用 `--no-measured-loads`
- **計測(正直な負の結果)**: 647バス/~14GWをピンして **ρ 0.473→0.463(誤差帯)** —
  trunk 0.615→0.617 / 154 0.089→0.097 / 66 0.145→0.144。倍率1.12→**1.09**(総量は正直化)
- **なぜ効かないかの診断(決定打)**: スコア対象の66帯回廊476本に対し、端点が実測需要
  マップに**1つでも**載るのは37%・**端点カバレッジ中央値0%** — 開示は1ヤードにつき
  線路計測か母線計測の**どちらか**が主で、「流れを採点される回廊」と「需要が測れた変電所」は
  ほぼ**別集団**。加えて接続recall 47%(㉜)=半分の回廊は配線自体が違う
- **帰結(M3テーゼの改訂)**: 需要配置は現状の律速ではない。**ρ66の律速=M4接続正確性**
  (unattached 242+衝突52の解消)。接続が直ってはじめて㊲のピン留めが効く構造
- **採用判断**: ρ誤差帯+物理的忠実性(実測絶対量・総量正直化)を根拠に**採用**(㉙と同基準)。
  970 passed。スコアカード: `external_flows_tokyo_full_2026-06-11c.json`

## 2026-06-11 — **Fable 5** — 実測需要地図: 母線列1,201変電所/19GWをDB化（㊱・M3-1）

- **当初案の正直な棄却**: 「ヘッダ1線のみ=末端」案は26件/2.1GWで、上位に**偽陽性**
  (新信濃=周波数変換所、新木更津=500kV変換点 — 開示は線の**片端のみ掲載**があり
  「ヘッダに1線」≠「物理的に1線」)。クロスファイル和集合ガード+変電所種別ガードを実装の上、
  補助計器(terminal_line)に降格
- **本命の発見**: 県別66kV開示の列分類を実測 — **母線(B)列3,372本 ≫ 線路列782本**。
  配電用変電所に下位網は無く母線通過=その変電所の需要 → `tepco_busbar_demands`
- **抽出**(東京): **busbar 1,201変電所 + terminal 21 = 1,222件・q50計19.1GW**
  (庚申塚46MW・角筈38MW等、配電用の典型量。面需要中央値~35GWの過半をカバー)
- **DB**: `measured_bus_loads`(region,sub_key,source PK / method,q50,p95,n_cols,window)
  + フェイルソフトloader。calibrate.py 1コマンドで line_stats と同時更新
- **配置可能性**(M3-2の事前計測): モデル変電所への名前一致 **647/1,201=54%・9.5GW分**
  — 残りは位置タイア・名寄せで回収余地。モデル本体は不変(ρ=0.473のまま、計測スキップ)
- 既知の限界を記録: 中間66kV変電所は下流transitを二重計上しうる(計19GW<35GWより軽微)。
  968 passed

## 2026-06-11 — **Fable 5** — 較正のDB化: measured_line_stats・--from-dbが計器を完全再現（㉟）

- **スキーマ**: `measured_line_stats`(region,line_key,kv_floor,source PK / q50,p95,window) —
  開示CSVは再配布不可のまま、**保持してよい導出集計だけ**をDBの資産に(出典・窓つき)
- **書き込み**: `scripts/db/calibrate.py` — 帯割当はmatcherと同一のtrunk-first。
  実行: 東京**705回廊**(trunk171/154帯59/66帯475)・窓=2024-04-01..2025-03-31通年
- **読み出し2系統**: (a) pipelineが境界回廊重み(q50)をDBから自動読み
  (calibrate済DBがあるときだけ。無ければ等分=従来どおり、地域非対応も従来どおり)
  (b) validator `--flows --from-db` — **CSV直読みと全8ヘッドライン指標が完全一致**
  (ρ4種+n4種SAME)を実測確認。フェイルソフト(DB/行欠如→None→CSVfallback)をテストでpin
- 意義: 「DBで機械的に更新できる仕組み」(ユーザー目標)の較正版 — 開示更新は
  fetch→calibrate→同じ物差し、の3手で完結。965 passed
- 運転票整理: M2の地域別品質KPI台帳化はM4(忠実度報告)へ移動 — **次はM3末端オフテイク(本丸)**

## 2026-06-11 — **Fable 5** — sweepに3層ρ統合: ρ退行が標準レポートで見える化（㉞・M1完了）

- **統合**: `topology_metrics`に`external_flow_metrics()`+`--flows`フラグ — 開示CSVがローカルに
  在る地域(現状tokyo)だけフルモデル(backbone 0)の3層ρをsweep行に追加。レポート末尾に
  `tokyo flows vs disclosure: interior rho=0.473 | trunk 0.615(74) 154 0.089(36) 66 0.145(307)`
- **退行ゲート化**: `--baseline`比較の_DIFF_KEYSにρ3種を追加 — 以後のループでρ悪化が
  `ajgrid validate --topology --flows --baseline`で自動検出される(運転規則2の機械化)
- CSV不在時(CI・fresh clone)は黙ってスキップ=既存sweepと完全互換。960 passed
- **M1(計器)完了**: 3層ρ・帯別接続recall・sweep統合の3点が揃い、以後の改善は全て同じ物差しで測れる
- レポート: `topology_tokyo_flows_2026-06-11.json`(committed 0.473を再現)

## 2026-06-11 — **Fable 5** — 154標本の解剖と変種マッチ: 全体ρ0.473・66kVが初の統計的有意（㉝）

- **ユーザー指示**「154がかなり大量なので肝」→ 154計器の解剖を最優先で実施
- **解剖**: 154kV開示6fileの184回廊中、**119本は幹線(275/500kV)の重複掲載**(幹線帯で計測済)
  → 純154母集団は**65本**。内訳: モデル在band 29 / 帯違い2(小北線・東埼玉線=モデル275kV) /
  部分一致のみ14 / **OSM不在20 — 都心の154kV地中ケーブル網**(北渋谷・和田堀・戸越・常盤橋・墨東等)
- **計器改良**: `_model_name_keys` — OSM名の変種展開(回線接尾辞「3・4L/3,4号線」・複合名「A/B」「A、B」・
  区間名「小山町~北駿線」・括弧別名「坂戸川越線(只見幹線)」) + 計測側: 計測区間限定子(中)(山)(里)の
  折畳・NT=ニュータウン正規化
- **再計測**(同一モデル、物差しのみ刷新): マッチ384→**419**・全体内部ρ 0.418→**0.473**
  - trunk 0.684(57)→**0.615(74)**: 低下は隠れていた都心難回廊(西町線8 vs 3,489等)が真値に
    入ったため — カバレッジ拡大の正直な代償。モデル劣化ではない
  - 154: 0.069(31)→0.089(36, **p=0.61のまま統計的に無意味**) — 名寄せ回収は頭打ち、
    残りはOSM収載(地中ケーブル)が必要 → OSM課題の新例題(東京・地中)
  - 66: 0.112(294)→**0.145(307, p=0.011)** — **66kV層のρが初めて統計的に有意**
- **帰結**: ρ154/66を動かす本命は計器でなく**M3需要配置**と確定(接続recall一様~50%の㉜と整合)。
  attachment計器は不変(57.2/54.9/46.9%)。958 passed
- スコアカード: `external_flows_tokyo_full_2026-06-11b.json`(以後の基準計器)

## 2026-06-11 — **Fable 5** — 接続recallの3層化: 66kV接続真値634ペアで初計測（㉜）

- **計器**: `match_tepco`をクラス帯対応に — 154kV(6file)+県別66kV(27file)のCSVヘッダを
  (変電所,線)接続真値へ統合(`parse_tepco_headers_banded`。帯=trunk≥200/154:140–200/66:60–140、
  同名異帯はsetdefault先勝ちで幹線優先)。`find_line`は**自帯のモデル線のみ**照合
- **初計測**(東京フルモデル): 真値1,482変電所/720線/**1,057接続ペア**(幹線のみ286から×3.7)
  - 接続recall帯別: **trunk 54.9%(286) / 154kV 56.9%(137) / 66kV 46.9%(634)** — 全体50.3%
  - 変電所recall 57.1%・線recall 54.9%exact/74.7%loose・鉄道名除外56・クラス衝突52
- **計器の連続性**: trunk帯54.9%(286) = 旧幹線専用計器(06-10スコアカード)と**完全一致** —
  帯域化は既存計器を歪めていない
- **読み**: 接続構造は全クラスほぼ一様に~半分再現(154帯はtrunk帯を上回りさえする)。
  一方流れのρはtrunk 0.68に対し154 0.07/66 0.11 → **下位網の無相関は構造欠落より
  需要配置が主因**という㉛の診断を独立計器で裏付け(M3末端オフテイクが本丸の確証)
- 956 passed。スコアカード: `external_match_tokyo_tepco_banded_2026-06-11.json`

## 2026-06-11 — **Fable 5** — 新目標「66kV級」始動: 3層ρベースライン確定（㉛）

- **ユーザー新目標**: 66kVまでの潮流を意味ある形で+DB整備+自律ループ → **docs/PLAN_66KV.md**
  (KPIゲート: 154≥0.40/66≥0.30/全体≥0.50、運転規則つきチェックリスト)
- **計器拡張**: 東電154kV(6file)+66kV県別(27file)を**クラス帯マッチング**で計測セット化
  (同名異クラスは衝突扱い)。クラス別ρ分離報告
- **公式ベースライン**(東京フルモデル, n=384内部): trunk **0.684** / 154kV **0.069** /
  66kV **0.112** / 全体0.418(p=1.3e-17)・倍率1.12 — **下位網潮流は現状ほぼ無相関**と
  初の定量化(WEST_AC_ANALYSISの定性結論を数値化)。本丸=M3需要の地理配置(末端オフテイク)

## 2026-06-11 — **Fable 5** — 南北偏りの解剖: 経路は健全、需要配置が本丸（㉚診断）

- **西回りリング検証**: 新所沢→港北の275kV+最小X経路は**26区間・合計X=2.4Ω・par=2-4で
  ボトルネック無し**(南狭山→只見幹線→西北線→港北線) — 「西回りが切れている/細い」仮説は棄却
- **帰結**: 東縦貫過剰(東京東/北線~2,600 vs 実測550-600)・横浜過小(港北532 vs 2,420)は
  経路でなく**需要・電源の置き場所**の問題。横浜系需要が湾岸電源の地産地消で賄われ、
  リング経由の流入需要が立たない構図
- **計器の探索(負の結果)**: 東電基幹CSVの連絡Tr列(=変電所別実測オフテイク)は
  **横浜大黒1箇所のみ** — 変電所別需要較正には154kV/66kV別ファイル(tyouryu_154kV.zip等)の
  取得が必要と判明。次の取得ターゲットとして記録
- ρの残差はここから先、(a)154kV CSVによる変電所別需要較正 (b)地域needsの地理分布
  (国勢調査メッシュ等)のどちらかが律速

## 2026-06-11 — **Fable 5** — 回廊別実測重み付け注入（㉙・誤差帯で採用）

- **変更**: 位置フォールバックの等分注入→**各クラスタの接続回廊の実測中央値で重み付け**
  (validator経由でTEPCO中央値を注入。statsなしは等分のまま、methodに明示)。
  複合線名「A / B」分割もmatcherに追加
- **正直な計測**: 内部ρ 0.718→**0.696(n≈53の誤差帯)**・倍率0.78→0.80・新栃木線2,106→2,272。
  ρ非改善を隠さず記録の上、**物理的忠実性(回廊別実測>恣意的等分)を根拠に採用**
  (junction負荷除去と同じ判断基準)
- 残ミスマッチの構図: 都心東(東京東/北線~2,600 vs 実測550-600の過剰)と
  横浜/湾岸(港北532・新京葉3,088の過小) = **都内の南北ルーティング偏り**が次の本丸

## 2026-06-11 — **Fable 5** — P03単位修正と容量の正規再投入（㉘）

- **修正**: `parse_p03` — `ksj:generatingPower`(KSJ仕様=**kW**)を÷1000でMW化、
  ≦0は欠測扱い、[0.01, 9000]MWの妥当性クランプ。合成GMLで回帰pin(test_p03_units)
- **再enrich**: P03-13 GMLをローカル取得(CP932 zip対応)→12,646施設・容量健全
  (max 2,820MW・幻ゼロ)→**p03_db容量128行を正規再投入**(OSM不明分のみ補完)
- **検証**: 内部ρ 0.718(誤差範囲で不変)・956 passed。REPRODUCIBILITYにP03取得手順追加
- 教訓の実装完了: 「権威データ取込は単位検証+妥当性境界つき」が恒久化

## 2026-06-11 — **Fable 5** — 朝巡回の連鎖デバッグ: スラックv2+P03単位事故隔離（㉗）

- **スラック修正v1の副作用を自分の物差しが検出**: 「現成分内限定」はhokkaidoを直したが
  tokyoの主スラックを断片に幽閉し**ρ 0.72→0.34に崩壊**（正直記録）→ v2=「**最大成分内で
  最良選択+他成分はcomp_slack補修**」で両立（hokkaido 799/799・tokyo 1119/1119有効）
- **ρ未復旧→データ二分で第二の真犯人**: D層世代交代(0835455)が**P03容量のkW→MW単位事故**を
  公開していた — みどり市の36,200kW(36.2MW)ソーラーが「36,200MW」×重複5=**181GWの幻**
  → must-runが東京の需要を食い尽くしLNG全機p=0。**p03_db容量147行を全隔離**
  （P03の名前/事業者/燃料は維持）。enricher修正(kW÷1000+妥当性クランプ)を次タスク化
- **計測**: 内部ρ **0.72復旧**(p=1.3e-09)・倍率0.78・北海道vm[0.947,1.032](正直値)。955 passed
- 教訓: (a)最適化は「成分を迷子にしない」不変条件つきで (b)権威データ取込は**単位検証と
  妥当性境界が必須** (c)ρ崩壊→データ世代の二分が最速だった

## 2026-06-11 — **Fable 5** — 41/799根本修正: スラック移設の成分迷子（㉖）

- **真因**: `select_slack_bus` のスコア(vn×10支配)が**主スラックを小成分の高電圧バスへ移設**
  →北海道の66kV主メッシュ(758バス・発電138機)が**ext_grid 0本**で全NaN。
  「converged, vm 1.000」は41バス統計だった(㉕)
- **修正**(`このcommit`): スラック選択を**現在のext_grid[0]が属する成分内に限定** — 最適化が
  成分を迷子にできない構造に。北海道 **799/799有効・vm[0.947,1.032]・loading 97%**
  （昨日の vm 1.000/17% は撤回・再表明）
- **再発防止**: `solved_metrics` に **n_unsolved_buses**(非有限res数)を計装し、
  okinawa+hokkaidoで**ゼロを回帰pin** — NaNスキップ系のバグは二度と隠れられない
- 配信: hokkaido zonal再生成(799バス・NaN 0)・FAIL明示を解除。955 passed

## 2026-06-11 — **Fable 5** — マップ検証が暴いたsilent-NaNバグ: 北海道41/799問題（㉕・要追跡）

- **発見経路**: nationalタブのPlaywrightスモーク→hokkaidoスライスが不正JSON(vm_pu:NaN)→
  掘ると**pandasのvm統計がNaNをスキップ**しており、本日の北海道のvm/AC数値は
  **実は41/799バスの統計**だったと判明(残758バスはスラック到達不能でNaN。
  build_and_solve('hokkaido')でも再現=モデルレベルのバグ。容疑: multi_slack×変圧器prune干渉)
- **誠実な封じ込め**(`5a9952f`): exporterのNaNガード+allow_nan=False(不正JSONの再発防止) /
  単一地域島はregionalパイプラインへバイパス / 配信は有効JSON化した上で
  **summaryでhokkaido zonal=FAIL明示**(注記つき。黙って欠けるより誠実)。
  地域別(非ゾーナル)の北海道ビューはこの経路を使っておらず無関係
- **影響範囲の正直な訂正**: 本日報告した「北海道 vm 1.000 / loading 17%」は41バス統計であり
  撤回。次セッション最優先=供給到達性の根本原因(再現1行は台帳/引き継ぎに記載)
- 教訓: **統計のNaNスキップは欠測を隠す**。スモークテストが配信前に捕捉した(検証文化の勝利)

## 2026-06-11 — **Fable 5** — #8実行: P03公開反映=D層世代交代（㉔）

- **#8完了**(`0835455`): 全`data/*.geojson`をDBからマーカー付き再生成 —
  **P03権威値が来歴つきで公開ファイルに**(`"_src:capacity_mw": "p03_db"`、自己記述・機械監査可能)。
  再ingestでsource保全(pin済)=機械更新ループ無傷。READMEに「data/*.geojson=DB派生物」宣言
- **C層是正(開示)**: P03エンリッチャが**capacity_mw=-1番兵2,752行**を値として保存していた
  → SQL検証で「正のOSM値マスク=0件」を確認の上削除(欠測は値ではない)。真正147件のみ公開。
  enrichments.jsonl再dump(243,112行)
- **堅牢化**: ingestをupsert化(マーカー由来行と保全済み非legacy行の衝突解消=マーカー付派生の
  再ingestが冪等) / verify_roundtripを実効ビュー比較化(_src:はtransport)
- README同期: 内部ρ0.721。954 passed

## 2026-06-11 — **Fable 5** — 設計+高度化+高性能化+資産化の一括前進（㉓）

- **資産化①: `_src:`per-fieldマーカー=#10核心機構**(`48e5196`, 設計=DB_ARCHITECTURE§6):
  `export --markers`で全enrichment勝者フィールドに来歴を併記→**焼込→再ingestでsource=p03_db保全**
  を回帰pin(test_provenance_roundtrip)。公開GeoJSONが自己記述化し、**#8(P03公開反映)のブロッカー解除**。
  物理分離(a案)は不採用と設計確定(b案=DB正本+マーカー派生)
- **資産化②**: CITATION.cff(引用可能データセット化)
- **高度化**: `demand_config_from_occto(quantile)` — 地域需要をOCCTO実測(median/p95/max)へ
  差し替え可能に(load_factor=1.0、由来をconfigに記録)
- **高性能化**: `--jobs N`並列sweep — 全地域solved backbone **~170s→24.5s(7倍)**、AC 10/10不変
- 953 passed

## 2026-06-11 — **Fable 5** — DB直読み=VISION step5達成+再現性レシピ（㉒）

- **ユーザー方針**「再現できるように。DBとなっているといい」→ **潮流パイプラインが
  grid.db単独から再現可能に**: `build_network_snapped(db=)`がraw⟕enrichmentsの有効ビューを
  メモリ内合成（`ajgrid solve <region> --source db`）。**ファイル構築との完全同一性を
  回帰pin**（tests/test_db_source_build.py: 変電所/枝(parallel込)/発電機の署名一致）
- **docs/REPRODUCIBILITY.md**: fresh cloneから全ヘッドライン数値（AC10/10・内部ρ0.72・
  合成線率・CIM検証）を再現する完全レシピ。外部データの取得コマンド・決定論の注意・
  「committed スコアカード=当時値の正本」の規約まで明文化
- これで「fetch→ingest→(DB直読み)solve→validate」が**ファイル非経由で閉曲線**。
  残るDB化対象は#10のraw/derived物理分離（要ユーザー裁定: data/raw分離 vs 現状のDB追記型）

## 2026-06-11 — **Fable 5** — スタック充填ディスパッチ: 内部ρ 0.659→0.721（㉑）

- **実装**(`0a5b7df`,`68bde14`): `balance_power(mode="stack")` を新デフォルトに —
  再エネ(solar/wind/hydro)はCFでmust-run、火力等は**コスト順に名板100%まで充填**
  (nuclear→geo→bio→coal→gas→oil、限界ユニットのみ部分出力、不足はslackに正直に残す)。
  ゾーン別(balance_power_by_zone)も同規則。proportionalはA/B用に温存
- **計測**: 内部ρ **0.659→0.721** (p=1.2e-09)・倍率中央値 **0.65→0.79** — ⑳診断の予測どおり
  (千葉LNGの一律59%頭打ちが解消)。backbone AC 10/10維持。
  開示: 東京/中部の基幹loadingが104→156/178%に上昇=集中ディスパッチの現実的帰結
- **west島AC**: スタック充填でも**FAIL(DC OK)** — 縫合・ゾーン別・スタックの3手段を尽くし、
  残差は**併合規模(~9千バス)のYbus条件**と確定的。打ち手はDC-OPF移行 or 権威R/X(Pillar 3)

## 2026-06-11 — **Fable 5** — 新京葉線過小の機序確定（⑳診断・実装は次回）

- **解剖結果**: 新京葉線(500kV)はモデルで~2,000-2,070MW vs 実測p95 4,910MW。トポロジは健全
  (並行2回線・新京葉/根戸/新野田/坂東の500kV端点正しい)。**真因=比例CFディスパッチ**:
  千葉LNG群が富津2,950/5,040・千葉2,564/4,380・袖ヶ浦/姉崎2,107/3,600と**一律59%**に頭打ち。
  実p95時間帯はLNGがほぼ全開＝房総→京葉回廊は倍流れる
- **需要レベル自体は整合**: モデル44.2GW(0.85×ピーク) ≈ OCCTO実測東京p95帯。
  つまり「p95需要なのに年平均CFで按分」という**運転点とディスパッチ規則の不整合**が残差
- **次の一手(実装待ち)**: merit-orderを比例配分→**スタック充填**(燃料コスト順に各機100%まで
  積んで需要到達で打切り)に変更。新京葉/新袖ヶ浦/新所沢の上位ミスマッチが同機序で、
  内部ρと倍率0.65の同時改善が見込める本命レバー
- OCCTOエリア需要統計(東京median 30.1GW/現行モデル44.2GW)は「中負荷断面」オプションの根拠
  としてoccto_calibration JSONに保存済み

## 2026-06-11 — **Fable 5** — OCCTO公表APIの発見と実測連系線フロー導入（⑲自己ループ）

- **発見**: OCCTO web-kohyo CSV APIが登録不要で到達可能(30分値・保持窓~14ヶ月)。
  jhSybt=02=エリア需要実測 / 04=連系線計画潮流。FY2025+Q1FY2026を取得し集計を
  `docs/reports/occto_calibration_2026-06-11.json` にcommit(生データは非追跡)
- **boundary.py**: 手置きTYPICAL_UTILISATION → **MEASURED_UTILISATION**(実測中央値/容量)。
  独立クロスチェック: FC −0.33 vs 旧−0.3 / 関門 −0.49 vs −0.5 / 相馬双葉 +0.74 vs +0.6。
  ic_006は実測中央値~5.0GW>容量4,090でクランプ(-1.0)・開示
- **全国ゾーナル配信**(`8e5b37d`): east/hokkaido/okinawa AC を公開ページへ(westはDC継続)
- 年度ずれ注記(検証=FY2024 vs 較正=FY2025+)。backbone AC 10/10維持・内部ρ0.659不変・947 passed

## 2026-06-11 — **Fable 5** — 全国ゾーナルwest島AC再試行: 依然FAIL（⑱・正直記録）

- **実行**: 縫合(2,171バス融合)+累積改善後の初再試行。結果: hokkaido/east/okinawa **AC=OK**
  (east vm 0.886-1.05)、**west(6地域併合 ~9千バス)はAC=FAIL・DC=OKのまま**
- **追加試行**: 旧分析の共犯因子(島一括バランスでkansai/kyushu局所欠乏)に対し
  `balance_power_by_zone`(ゾーン別CFディスパッチ)を実装して再実行 → **それでもFAIL**
- **解釈(正直に)**: 地域単体フルモデルは10/10収束するため、残差は (a)併合規模のYbus条件
  (b)kansaiのCF可用量<自地域需要→名板クリップ→数GWが縫合/合成回廊経由の域間転送になる構造
  (c)ゾーン間転送の明示制御が無い(DC-OPF領域)。**west AC化は引き続き未解決**として
  WEST_AC_ANALYSISの「ゾーナル未再試行」を「再試行したが未解決」に更新
- ゾーン別バランス自体は物理的に正当な改善としてcommit(east副作用チェック済みの上で)

## 2026-06-11 — **Fable 5** — ドキュメント整合+他周波数オーバーレイ（⑰）

- **ドキュメント補正**(`204f028`): README図キャプション(旧kansai×0.4文→14,647バス無スケール)・
  CIM L2節(v1.4.0資産=native6+×0.8×4とリポジトリ内モデルnative10/10の区別)・
  **Limitations#7を書き換え**(「物理的に無意味」→「整合性検証の道具。内部ρ≈0.66で実測と
  順位相関するが、権威パラメータ到来までは運用値ではない」)。
  WEST_AC_ANALYSISに解決追記(歴史的分析は一次資料として保存、全国ゾーナルwest ACは未再試行と明記)
- **他周波数オーバーレイ**(`3e33ba4`): マップに参考表示トグル実装(灰破線・popup=名称/運用者/
  電圧/周波数/理由、デフォルトOFF・地域別遅延ロード)。Playwrightスモーク済
  (コンソールエラー無し・chubu 1,205本fetch確認)。ユーザーの「リアリティ」懸念への完結回答

## 2026-06-11 — **Fable 5** — 地域別backbone floor: 北海道=66kV（⑯・ユーザー指摘）

- **指摘**「北海道は除外しすぎ。66kVまで繋げば」→ 実測で確認: 北海道の154kVは**11本のみ**、
  66kVが**591本**=地域連結の本体（275/187が上位）。本州の≥154kV断面は移植不可能だった
- **修正**(`ac181fc`): `REGION_BACKBONE_FLOOR={"hokkaido": 66.0}` — デフォルト断面要求時のみ
  地域floorで解決（明示値は尊重）。北海道backbone 154→**804バス**(=66kV網ごと保持、
  `reduced:False`=「北海道の基幹は66kV網そのもの」という正しい帰結)、AC収束・vm 1.000
- 教訓: **電圧階級の意味は地域組成依存**（沖縄=132が基幹、北海道=66が連結層）。
  固定閾値でなく組成を見る — auto-degradeに続く2例目

## 2026-06-11 — **Fable 5** — 精度総仕上げ: フルモデルAC 10/10・需要スケール完全撤廃（⑮）

- **回線数仮説の検証(負の結果)**: 公式回線数(東電開示ヘッダ)>モデルparallelは55基幹中3線のみ
  (上野/水道橋ケーブル系)→ 系統的過小潮流の原因ではないと確定
- **実測境界条件**: match_flows 2パス化 — pass1で境界回廊を自動特定し実測中央値で
  連系線注入をキャリブ(ic_002→util 0.573、planning 0.6と独立に整合=相互裏付け)。
  境界回廊はρから除外し **内部ρ=0.659 (p=8e-08)** を正式指標に(誠実化)
- **最終sweep結果**: **フルモデル(下位網込み)で AC 10/10 — 関西も native 収束(vm 0.931)**。
  国家PF図 `fig_cim_national_pf.png` が**14,647バス・demand scaling無し**で初めて全色付き
  (従来は関西x0.4)。backbone も 10/10 (vm≥0.87)
- **開示**: chubu backbone合成線率1.8→8.3%(周波数フィルタが他社50Hz「接着剤」を除去した
  正直な断片化)・関西fullの局所過負荷535%・東京144%
- 朝の評価起点「west AC非収束」は、②〜⑭の累積(多電圧変電所/Q制限/電圧伝播/分岐塔負荷除去/
  周波数帰属/境界注入)により**フルモデルでも解消**

## 2026-06-10 — **Fable 5** — frequency-first化と公式系統図PDFでの検証（⑭）

- **ユーザー指摘が両方向の誤りを発見**: 地図監査(`output/diagnostics/freq_filter_audit_chubu.png`)で
  (a)東電運用×`frequency=60`タグ7本(長野混在地帯)の**誤除外**、(b)非TSO×`frequency=50`の
  **除外漏れ75本**(J-POWER佐久間東幹線・佐久間FC連絡線・JR饋線=60Hz網への偽融合)、
  (c)`frequency=0`(飛騨信濃DC等)のAC線扱い、を特定
- **修正**(`a401886`): `_freq_excluded` — **OSM frequencyタグを第一証拠**に
  (地域一致→保持、`50;60`=FC連絡は両側帰属、`0`=DC→AC網から除外、不一致→除外)、
  operator推定はタグ無しのみ。chubu vm **0.912→0.970**
- **公式系統図PDFで裏付け**(ユーザー指示「PDFでできるのであれば」): 東電・実績系統図
  (2024-07-29 15時断面、転載禁止につきPDF/切抜はdata/external=非追跡)を400dpiレンダ+
  日本語OCR(tesseract)で照合。**佐久間東幹線(↓340MW)・佐久間西幹線(↓350MW)が東電50Hz基幹として
  実在、佐久間FCは新豊根佐久間線経由(当該断面1MW)** — chubuからの除外+tokyoモデル帰属+
  FC=注入点というAGJの構造が公式図と一致
- 残課題: 長野混在地帯7本の最終確定は中部PG系統図側との突合(東電図は275kV+のため対象外電圧)

## 2026-06-10 — **Fable 5** — 周波数不一致TSO設備の除外: chubu vm 0.76→0.91（⑬）

- **診断**: ⑪後にchubuの公開vm_minを支配していた0.76の電圧降下は、**伊豆半島の東電(50Hz)設備が
  chubu(60Hz)スライスに混入**して形成された幻の66kV放射線（湊/中/谷津/峰変電所）だった
- **変更**: operatorタグ→TSO本拠周波数のマップ（北海道/東北/東京=50Hz、中部以西=60Hz）で、
  スライス周波数と矛盾する設備を除外。**同周波数の他社設備は保持**（連系線近傍の境界回廊は
  隣接TSO運用が普通）、非TSO（鉄道/J-POWER/IPP）も保持
- **計測**: chubu vm 0.763→**0.912**・DC角度[-41,38]→[-13,36]。東京vm/ρ不変・沖縄pin無傷。
  **開示**: chubu成分数22→131に増加 — 他社設備が偽の接着剤になっていた断片が正直に現れた
  （multi_slackで全成分解かれる）。北陸も11→22（東北電力境界設備の除去）
- 公開マップ再promote: **全地域 vm_min ≥ 0.89** に到達。944 passed

## 2026-06-10 — **Fable 5** — スライス縫合 + 検証CI化（⑫）

- **スライス縫合** `national.stitch_slice_boundaries`: 地域スライスは重複しており、
  境界回廊が**両地域に切断された並列コピー**として存在（=二重インピーダンス経路の電気的誤り
  +境界で不連続）。島マージ時に異地域×同電圧クラス×~110m以内のバスを融合
  （実変電所を生存側に、線端点・発電機接続を付け替え。同一地域内の重複は意図的シグナルなので不変更）
- **計測**: west島で**2,171バスの重複融合**（成分561→428・カバー87→90%）、east 131（283→271）。
  okinawa/hokkaidoは単一地域なので変化なし=正しい挙動
- **CI化**: `.github/workflows/ci.yml` — push/PRで943本の回帰スイート、週次でslow sweep
  （AJGRID_SLOW_TESTS=1）。回帰pinがローカル習慣でなくマージゲートに

## 2026-06-10 — **Fable 5** — v1.4.0リリース: CIM再エクスポート+マップ再promote（⑪後半）

- **CIM L2 全10地域再エクスポート**（新モデル反映）: cim2pp往復検証 **10/10 OK**
  (vmin 0.86〜0.98)・CGMES厳格検証 **ALL VALID (0 dangling)**。
  **関西のCIMケースが×0.3→×0.8需要に改善**。native 6地域+×0.8が4地域
  — 東京/中部はv1.3でnativeだったが、ネットワークが大幅に濃くなった
  （東京2,954→3,409バス）結果×0.8に。隠さず記載
- **ライブマップ再promote**（⑪反映）: okinawa 0.65→**0.92**・東京0.80→**0.90**・
  関西0.90→0.93・中国0.93→0.98。chubuのみ0.86→0.76に低下（負荷の実変電所集中の影響、
  backbone側は1.008で健全）— 開示
- VERSION 1.3.0→**1.4.0**、GitHub Release v1.4.0（新規。旧リリース資産は不変更）

## 2026-06-10 — **Fable 5** — ジャンクション負荷の除去: backbone vm全地域≥0.98（⑪）

- **変更**: ビルダーがジャンクション（vertex-snapの分岐塔）をpandapower標準の bus type `'n'`
  （補助ノード）として型付けし、負荷配分（regional/national両経路）を `'b'`（実変電所）に限定。
  分岐塔=線の途中点であり受電点ではない、という電気的常識の実装
- **計測**:
  - okinawa full vm **0.647→0.923** — ⑩Cで顕在化した66kVスパーの電圧降下の主因は
    回廊型付けではなく**中間スパンに置かれた合成需要**だったと判明（仮説の再修正）
  - backbone vm_min **全地域≥0.979**（関西0.920→0.984・東京0.919→0.979）、AC 10/10維持
  - **トレードオフを正直に**: 東京ρ 0.707→**0.684**（n=55では誤差範囲）。物理的正しさ
    （受電点モデル+電圧プロファイル）を優先して採用。ρの真の回復は地内ルーティング修正で
- pin変更なし（938 passed + 新テスト1件）

## 2026-06-10 — **Fable 5** — 公開反映: ライブマップに②〜⑩を一括デプロイ（⑩A）

- `regen_powerflow_snapped.sh` で全10地域を再生成→A/B確認→promote。READMEにv1.4.0節
- **公開ページ上の改善**（A/B実測、deployed→staged）:
  - **関西AC: 非収束(vm=0)→0.901で収束** — 公開マップ最大の修正
  - 東京DC角度 [-158°,63°]→[-58°,15°]（物理化）/ vm改善: 東北0.88→0.96・四国0.83→0.92・
    北海道0.81→0.91・中国0.91→0.93 / アクティブバス全地域増（多電圧+端点回復の反映）
  - 正直化の開示: 沖縄vm 0.96→0.65（66kVスパーの正しい型付けで隠れていた降下が表示される）
- 注: ライブマップはfullモデル（地域詳細）。AC製品=backboneモデルはCLI/レポート側
  （`ajgrid solve <region> --backbone`）

## 2026-06-10 — **Fable 5** — 回廊電圧伝播: 電圧不明枝を全国で半減〜1/3（⑩C）

- **変更**: `build_network_snapped(propagate_voltage=True)` — 無タグ線は、その頂点群が出会う
  既知クラスが**一意のとき限り**そのクラスを採用（反復で無タグ鎖を伝播）。曖昧（2クラス以上）は
  棄権=推測しない。ブランチ来歴に `kv=tag|prop|unk` を追加、KPIに `kv_provenance`
- **計測**: 電圧不明枝 中部25.8→**8.2%**・関西25.0→**8.2%**・北陸23.2→**10.8%**・
  四国27.7→13.0%・九州19.9→9.6%。AC 10/10・ρ0.707維持
- **例題仮説の修正（正直に）**: 北陸backbone合成線率は11.1→**10.2%の部分改善のみ**
  → 「属性欠落が主因」は一部のみ正しく、残差=曖昧頂点+真の幾何ギャップ。例題に追補済み
- **正直化の副作用**: 沖縄北部66kVスパーが正しく型付けされ、暗黙の高クラス扱いで隠れていた
  電圧降下(full model vm 0.65)が顕在化 → 製品=backboneモデル(vm 1.006)の回帰チェックを新設し、
  fullモデルのpinは実測値に更新

## 2026-06-10 — **Fable 5** — 県外流入の境界注入: ρ 0.691→0.707（⑩B）

- **変更**: `src/powerflow/boundary.py` — OCCTO連系線(interconnections.yaml)の典型潮流を
  地域モデルの境界変電所へ注入（import=sgen / export=load、`balance_power`は load−imports を
  ローカル給電）。`build_and_solve(boundary_imports=True)` デフォルト
  - 配置は3層: **名前一致**（西日本はほぼ全部: 関ケ原/紀北/加賀/越前/讃岐… ヶ/ケ正規化追加）
    → **FC変換所座標**（新信濃/東清水を実座標で容量加重） → **位置フォールバック**
    （相手地域セントロイドに近い基幹バスを10kmクラスタ化し回廊単位で等分= 東京は
    いわき/栃木/柏崎方面など6回廊に3,330MWを分配）
  - 典型流通方向はOCCTO運用容量×符号付き利用率（東北→東京+0.6 / 中部→東京FC −0.3 /
    九州→中国 −0.5 等、**planning近似と明記**。ロードマップ5のOCCTO実績で置換予定）
- **計測**: ρ **0.691→0.707** (p=1.6e-09)。新いわき線(実測1,970 vs 70MW)が上位ミスマッチから
  **消えた**。backbone AC 10/10維持（輸出側の九州/北海道も収束、東京vm 0.927→0.937）
- 残ミスマッチ: 港北線(2,420 vs 143)・東京西線・南狭山線=**横浜/多摩の地内ルーティング**
  （境界ではなく並行回線・経路の問題）が次の純化された課題

## 2026-06-10 — **Fable 5** — merit-orderディスパッチ: ρ 0.676→0.691・実測で規則選定（⑨）

- **診断**: LNG群（富津5,040MW等）は位置・容量とも正しくモデルに存在。真因は
  `balance_power` の**全機一律スケール**（東京: 名板計132GW→×0.35）で、ほぼフル稼働の
  基幹LNGが35%出力に圧縮され回廊潮流が平坦化していたこと+容量不明太陽光への一律10MW
  デフォルト（幻の分散容量）
- **変更**: 燃料種別CF（gas 0.55 / coal 0.7 / solar 0.15 / oil 0.1 等）による
  **merit-orderディスパッチ**。fuel_typeをビルダー→pandapower `type`列に連携。
  type列が無いnetは従来の一律スケール（後方互換）
- **規則を実測で選定**: multi-fuel「最良燃料」規則はρ 0.657（鹿島 oil;gas 名板5.7GW=
  大半廃止が過大稼働し香取線氾濫）→ **第一トークン規則でρ 0.691**(p=5.2e-09) を採用。
  uniform 0.676 → **0.691**。新袖ヶ浦線・香取線が上位ミスマッチから消えた
- **残るミスマッチの純化**: 上位は県外流入線（新いわき線 実測1,970 vs 70・新栃木線）=
  **地域モデルに県外importが無い構造的限界**が次のレバーとして特定された
  （national zonalモデル or 境界注入で扱う領分）。名板の陳腐化（P03=2013、鹿島廃止等）は
  Pillar 3（権威データ）課題として明記
- backbone AC 10/10維持（vm全≥0.92、東京loading 119→104%）。933 passed

## 2026-06-10 — **Fable 5** — 照合ガード3種: 接続recall 45.8→54.9% / 潮流ρ 0.51→0.68（⑧）

- **故障モード分類が照合側の欠陥を特定** → 3つのガードを実装:
  1. **鉄道専業オペレータ名の除外**（57名）— JRき電線がOSMで同じ命名規則を持つ偽陽性源
  2. **クラス整合** — 東電開示は275kV+基幹。低圧の同名線とのマッチは「クラス衝突」(34件)として分離
  3. **位置ベース接続判定**（±1.5km）— 東電呼称とOSM名の施設同一性ズレ
     （西北線の終端=OSM稲城変電所=東電北多摩、1.1km）を救済
- **接続ペアrecall 45.8%→54.9%**（名前144+位置13/286、真の未接続41件に絞り込み）
- **潮流ρ 0.508→0.676**（p=1.5e-08、正味55線）— 初版の相関を下げていたのは偽マッチとの比較。
  残るミスマッチ上位=発電配置・並行経路の本物の課題（新袖ヶ浦線・港北線等）
- 教訓: **照合器そのものも検証対象**。故障モード分類→ガード→再計測のループが効いた

## 2026-06-10 — **Fable 5** — 潮流値レベルの初検証: Spearman ρ=0.51（ロードマップ4）

- `external_tepco.py --flows`: 東電の通年1時間値潮流（回路群を端点ごとに合算→p95）と
  モデルDC潮流（backbone、名前一致97線）を順位比較
- **結果: Spearman ρ=0.508 (p=1.1e-07)・中央値倍率0.77** — モデルの回廊利用順位は実測と
  有意に相関（「潮流計算が物理的に正しいか」に初めて数字がついた）。
  単一合成断面 vs 通年実測のため順位相関を正式指標とする（誇張防止）
- ミスマッチ上位 = 誤回廊ルーティングの固有名詞リスト（京北線: 実測78MW vs モデル3,496MW 等）
- **負の結果を記録**: ⑤のdegree空間負荷配分はρ 0.506（flat 0.508）で**改善なし**
  → デフォルトflat維持。回廊潮流はトポロジ+発電配置が支配的、クラス内負荷按分はほぼ効かない

## 2026-06-10 — **Fable 5** — 外部照合第2弾: 東電接続正解 + OSM課題例題の記録（⑦）

- **東電実潮流CSV照合** `src/validation/external_tepco.py`: 列名「京浜(変) - 東京南線1･2L」=
  公式の(変電所,線路)接続ペア**286組**を正解として built model を照合
  - **変電所recall 86.4% / 線路recall 82.1%(loose) / 接続ペアrecall 45.8%**
  - 「線は在るが公式の変電所に未接続」**103件** = 固有名詞つき接続改善ワークリスト
  - 前提工事: ビルダーがOSM線路名をブランチへ保持（チェーン縮約は長い側の名前、
    潮流値レベルの照合=ロードマップ4の土台）
- **OSM課題の例題記録**（ユーザー指示）: `docs/reports/2026-06-10_fable5_osm_case_studies.md`
  - 関西=「見かけ」と「電気的使用可能性」の乖離 / 北陸=**属性欠落が連結性を壊す**
    （主幹154kVの23%無タグ→backbone合成線率11.1%の唯一の外れ値）/ 東京=接続正確性が残課題
  - 用途: 論文motivation・講義例題・OSM貢献ターゲット
- 計算リソース方針: 重い計算は各サーバーのsgnbコンテナ利用可（ユーザー許可、メモリ記録済み）

## 2026-06-10 — **Fable 5** — 構造統一: national昇格・import直結・legacy隔離（⑥）

- **変更**:
  - 全国ゾーナルビルダー `examples/build_national_snapped.py` → **`src/powerflow/national.py`** 昇格
    （旧パスは再エクスポートshim）。**`ajgrid solve national [--islands ...]`** をCLIに追加
  - `examples.run_powerflow_all` shim経由だった5ファイル（export_powerflow_pages /
    run_national_powerflow / run_cpf / compare_topology_ab / 診断1本）のimportを **src直結化**
  - `export_cim_level2` の build_and_solve も `src.powerflow.pipeline` 直結
    （監査時の「CIM-L2にインライン再実装」は現存せず=Phase Cで解消済みを確認）
  - `build_and_solve` のデフォルトを `topology="snapped"` に変更（**legacyは比較専用に隔離**、docstring明記）
  - nationalソルバーにも⑤のAVR設定値を配線（okinawa島 vm 0.814→0.843）
- **意図的に未実施**: トポロジビルダーのDB直読み化 — 残タスク#10（raw/derived split）の
  設計判断（ユーザー裁定要: data/raw分離 vs snapshotsテーブル直読）とセットで行うべきで、
  単独先行はprovenance破壊リスク（#8の実証済み教訓）
- テスト925 passed

## 2026-06-10 — **Fable 5** — 潮流物理の底上げ: Q制限・AVR設定値・空間負荷（⑤）

- **変更**:
  - **発電機の無効電力能力**: max_q=0.5Pmax / min_q=-0.3Pmax（同期機の定格力率近傍の典型値）を
    全発電機に付与し、ACソルバー第1・2試行で `enforce_q_lims=True`（限界到達でPV→PQ切替）
    → 「無限フラットVAr源」モデルの卒業
  - **AVR型電圧スケジュール**: フラット1.00 → クラス別設定値（≥400kV:1.03 / ≥200:1.02 / ≥100:1.01）
  - **空間負荷配分（opt-in）**: `estimate_loads(spatial="degree")` 枝次数で電圧クラス重みを傾斜。
    東電の地点別潮流実績CSVで検証できるまでデフォルトにしない（正直方針）
  - 解の来歴: `q_lims_enforced` を結果に記録
- **計測**（backboneモデル、④→⑤）: **AC 10/10維持・全てQ制限有効の物理解**
  （関西: 第1ソルバーで収束、1,073機中326機がQ限界に張り付き=拘束が実効）。
  vm_min 全地域≥0.92、過半が1.00前後の健全プロファイル（関西0.908→0.920）
- フルモデル: AC 9/10（関西のみ非収束=下位網規模が真因のまま、変化なし=想定通り）

## 2026-06-10 — **Fable 5** — 証拠ベース接続: circuitsタグ・端点スナップ・provenance（④）

- **変更**:
  - **`circuits`/`cables` タグの消費**: 並行回線数を幾何推測から OSM 直接証拠へ
    （関西で証拠ベース59%、way単位 `circuits=4` 等を回線数に反映）
  - **端点専用スナップ半径 2.5km**（中間頂点は1.5km維持）: 実測「端点の6〜8%が
    1.5〜2.5kmギャップ（用地フェンス手前で作図が止まる）」に基づく。関西+506・東京+1,340端点回復
  - **接続provenance**: 全ブランチに `conn=S-J;circuits=tag` 形式の来歴を記録、
    KPIに `evidenced_circuit_share`・`conn_kinds` 追加
  - **潜在バグ修正**: `_SubIndex.nearest` が3×3セル(~3km)までしか探索せず、
    大型発電所の20km探索が黙って失敗していた → リング幅を半径連動に（沖縄で発電機16→22）
- **KPI変化**（③→④、フルモデル）: 合成線率 中部7.6→5.5%・関西10.5→**8.9%**・四国6.2→4.3%、
  成分 中部175→137・四国60→45、vm 北海道0.72→**0.91**・四国0.79→**0.92**・東北0.85→0.96
- **backboneモデル**: AC 10/10維持、関西vm 0.838→**0.908**（紀伊半島放射線が端点回復で改善）、
  四国合成線率2.1→0.7%
- ベースライン(改善前)比の合成線率: **関西14.4→8.9%・全地域で低下** — ④の目標(<8%)にほぼ到達

## 2026-06-10 — **Fable 5** — 変電所の多電圧バス化（③）

- **変更**: `build_network_snapped(multi_voltage=True)` をデフォルト化
  - 変電所を**電圧クラスごとのバス**(`sub_5@132`/`@66`/`@u`)に分割し、クラス間を50mスタブで接続
    → `insert_transformers` がスタブを標準系列の**変電所内変圧器**に変換
  - **「線がtrafoに食われる」バグの構造的解消**: 従来は異電圧の線が丸ごと変圧器化され
    線インピーダンスが消失（関西で実線+759本が復活: 1,573→2,332本）
  - ジャンクションも電圧クラス別にキー化 → 異電圧線の交差による**偽接続(~1%の座標)を解消**。
    電圧不明線はその座標の既知最大クラスに合流（2パス決定的）
  - 発電機は容量で接続クラスを選択（≥200MW→最上位クラス、未満→最下位クラス）
- **KPI変化**（ベースライン→多電圧、フルモデル）:
  - 合成線率: 関西14.4→**10.5%**・九州12.8→9.8・中国12.1→10.1・東京7.8→6.6（沖縄のみ12.3→14.4）
  - 東京vm 0.779→**0.875**・過負荷583→257%。北海道/四国はvm悪化（食われていた線の復活で
    実際の電気的距離が現れた=正直な物理）
  - backboneモデル: **AC 10/10維持**・合成線率が激減（関西9.1→**2.4%**・北海道5.4→0.6%・大半≤2.8%）
  - 関西backbone vm 0.946→0.838（最低点は紀伊半島東部154kV放射線の末端=物理的に妥当、⑤の無効電力/タップ対象）
- pin更新: okinawa 81→100バス等（multi_voltage=False でA/B比較可能を維持）。テスト920 passed

## 2026-06-10 — **Fable 5** — backboneモデルでAC 10/10（②）+ 外部照合の初計測（①完結）

- **② AC-solvable backbone** (`decbad0`): `reduce_to_backbone`（≥154kV保持、下位網発電を
  境界バスへBFS集約、需要は縮約後に配分、閾値は地域別auto-degrade）
  - **AC 10/10 native収束**（従来9/10）。**関西が全量需要22,833MWで収束**（従来x0.3〜0.4スケール必須）
  - vm_min 全地域≥0.91（フルモデル: 東京0.78/北海道0.81）、東京過負荷583%→127%
  - 需要スケールladderの撤去がこのモデルでは可能に。`ajgrid solve <region> --backbone`
  - 副産物: reconnector の dense-Ybus クラッシュ修正（小網で顕在化した潜在バグ）
- **① 外部照合** : Web実調査で正解ソース確定（`docs/VALIDATION_SOURCES.md`）。
  **旧メモのC02=電力施設は誤り（C02=港湾、KSJに送電線データは存在しない）**
  - 関西送配電CSV（線路名・回線数・容量、毎日更新）との照合実装 `src/validation/external_match.py`
  - **初計測（関西）**: 公式235線の名前一致40%（厳密17.9%）・**500kV 34線中20線が名前で発見不可**・
    circuits タグ一致56% — 入力(OSM)自体の欠落が初めて定量化された
  - 発見: 東電PGが**変電所×線路名つき1時間値潮流CSV**(2024通年)を公開 = 東京エリアの接続+潮流の正解

## 2026-06-10 — **Fable 5** — プロジェクト評価と検証フレームワーク（①）

- **判断レポート**: [2026-06-10_fable5_evaluation.md](2026-06-10_fable5_evaluation.md)
- **背景**: ユーザー評価「潮流計算と系統の点・線の接続が弱い」→ 全面監査の結果、
  診断は正確で、**接続の弱さが潮流の弱さの根本原因**という構造を確認
- **変更**:
  - `src/validation/`（トポロジ・潮流KPI: 断片化 / 合成線率 / 収束 / 電圧 / OSMタグ証拠）
  - `ajgrid validate --topology`（`--solve` / `--json` / `--baseline` diff）
  - 回帰pinテスト `tests/test_topology_metrics.py`（okinawa exact + 品質フロア + slow全域sweep）
  - KPIベースライン `docs/reports/topology_baseline_2026-06-10.json`
  - 改善計画①〜⑥（評価レポート参照）の起点
- **計測で確定した新事実**:
  - 公開データの合成線率: 関西14.6%・九州9.4%・東京5.8%（n_components=1は橋渡しの結果）
  - `circuits` タグ（並行回線数の直接証拠）が46〜60%充足なのに未活用
  - 関西は電圧タグ31%欠落 / 四国はビルダー段階で56成分・カバー57%
  - okinawa solved n_components=4 は離島の実分離（>5km海峡は捏造しない設計）= 正直な挙動

## 2026-06-08〜10 — モデル記録なし — DB統一(R/C/D)・M1実証・CIM修正・ツール化

- DB機械更新ループ（fetch→ingest→enrich→export）完成、pws-160coreでM1実証
- CIM/CGMES L2のP0バグ9件修正（parallel無視・長さ1000倍など、REVIEW_FINDINGS）
- P03権威データ3,109発電所、`pip install -e .` → `ajgrid` CLI化
- 全体レビュー（7アングル・36候補→CONFIRMED10件）= `REVIEW_FINDINGS.md`

## 2026-05-29〜06-06 — 一部 **Opus 4.7**（記録あり）— トポロジ再設計・west究明

- **Opus 4.7**: PR #13（Sonnet 4.6作業）でAC NR発散→kV²重み復帰+北海道隔離で収束回復
- 頂点グラフ+スナップ法ビルダー（東京481→134成分）、再接続「星形」バグ修正、
  keep_stubsデフォルト化で地域AC 10/10収束（当時計測）
- west島AC非収束の真因確定（154kV未満下位網、`docs/WEST_AC_ANALYSIS.md`）
- 関西AC非収束=電圧安定限界（PVノーズ）と確定、demand-scaled可視化で開示

## 〜2026-05-26 — モデル記録なし — 初期構築

- OSM取得・10地域GeoJSON・MATPOWER全国2189バスケース・GitHub Pages可視化
- 最近傍50kmマッチ法（後に大半の線をdropすると判明→snapped法で置換）
