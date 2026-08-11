# モデル介入台帳 — 「繋がって/解けて見える」を作っている仮定の全リスト

- 制定: 2026-07-07 / オーナー指示:
  「専門知識がないと、つながったと信じ込んでしまう。盲信につながる修正をたくさん
  したので、これも技術的記録として残すべき」
- 発端: 幻tie事例（`reports/case_study_phantom_tie_2026-07-07.md`）—
  内部的に無矛盾なモデルは実在しない設備を平然と含み得ると実証された。
- **原則**: モデルを「解ける/繋がる/完全」に見せる介入はすべて、
  **①根拠 ②帳簿（どこに開示されるか） ③無効化手段** の3点セットでここに登録する。
  登録なき介入の追加は認めない（出典必須DBの「捏造REJECT」と同格の規約）。

## なぜこの台帳が必要か（盲信の構造）

本モデルの成果物（全国潮流の収束・整った系統図・tie表）は、以下の介入の**合成**である。
介入はそれぞれ正当化を持つが、合成結果は「実在の系統の観測」ではなく
「仮定を重ねた推定」である。専門知識のない読者は完成品の滑らかさから前者だと信じ込む
— 幻tieでは**作った我々自身すら**、突合で外部正解に当たるまで信じていた。
介入が増えるほど成果物は良く見え、盲信リスクは上がる。だから介入の全量を1枚で見えるようにする。

## 介入一覧（built/計算系譜・2026-07-07時点）

凡例 — 種別: 【構造】接続・トポロジを作る / 【値】パラメータを埋める / 【配分】需給を置く。
リスク: ★★★=実在しないものを実在すると誤認させ得る / ★★=量を歪める / ★=局所的。

| # | 介入 | 種別 | リスク | 実装 | 根拠 | 帳簿・開示 | 無効化 |
|---|---|---|---|---|---|---|---|
| 1 | **越境stitch**（同一座標~110m・同電圧階級の県境スライス連結） | 構造 | ★★ | `src/powerflow/connectivity.py` STITCH_CELL | 同一座標=同一物理点（証拠=座標一致） | conn meta `n_stitch` | 抽出単位で見る |
| 2 | **OCCTO ACタイの明示追加**（島内地域対の連系を枝として付与） | 構造 | ★ | `connectivity.py` tie_edges | OCCTO公表の実在連系 | `n_tie`・tie名 | — |
| 3 | **発電所の最近傍接続**（プラント→最寄り変電所バス ≤20km） | 構造 | ★★★ | `run_full_powerflow_from_db.attach_generators` | 「発電所はどこかに繋がっている」仮定。**実際の接続先の証拠なし** | なし（**要改善**: 距離分布の帳簿化候補） | — |
| 4 | **backbone断片復帰**（断片上のgen/loadを地理最寄りbackboneバスへ、最大57.7km） | 構造 | ★★★ | `uc_to_pf_built.build_backbone_net` | 実在電源は現実に繋がっている（=現実の回復）。ただし**接続先バスは推定** | ledger全件（moved/from_fragment/距離max/越境数） | `--model full` |
| 5 | **zone領土再属性**（座標→県ポリゴン→エリア・県近似） | 構造 | ★★ | `src/powerflow/region_attribution.py` | 県→供給区域の対応（公知）。**飛騨神岡・熊野等の県内乖離は未処理**・周波数跨ぎは禁止 | `region_reattribution`(changes/skipped_freq)・`region_src`退避 | `territory=False` |
| 6 | **周波数ガード**（50/60Hz跨ぎの再属性拒否=抽出元ラベル温存） | 構造 | ★★ | 同上 AREA_FREQ | 県近似がFC設備を壊す実害（新信濃） | `skipped_freq`（522件） | — |
| 7 | **発電所osm_id dedup**（重複コピーを領土地域優先で1回採用） | 構造 | ★★ | `attach_generators(territory=True)` | bbox重なり由来の重複（幻tie事例⑤） | 統合件数をstdout（**要改善**: JSON化） | `territory=False` |
| 8 | **島境界注入**（UC連系フローを境界設備バスへsgen注入） | 配分 | ★★ | `uc_to_pf_built` BOUNDARY_POINTS | 設備バスはOSM実在を名前解決。**分割比は定格固定・実運用配分ではない**。受け皿なき点は再配分（佐久間→新信濃0.83等） | `boundary_injection`/`boundary_mw`（時刻別） | フラグ省略（既定OFF） |
| 9 | **需要の合成配賦**（エリアピーク×電圧階級重みで変電所バスへ按分） | 配分 | ★★★ | `allocate_loads` | エリア計はOCCTO実績。**バス別の内訳は全くの合成** | なし（設定はdemand config） | — |
| 10 | **UC注入の容量比例配分**（燃料別合計MWを同燃料機へ容量比例で） | 配分 | ★★ | `src/uc/pf_injection.inject_dispatch` | 機別1:1対応が存在しない | clipped/unmatched（時刻別JSON・07-07から） | — |
| 11 | **成分別合成slack**（全連結成分にslack付与=断片も静かに給電される） | 配分 | ★★★ | `add_per_component_slacks` | 解けない成分を解くための数値的必須 | slack合計はKPIとして常時報告。**成分別内訳はdiagnose_slackで** | — |
| 12 | **容量欠損のデフォルト値**（fuel別: nuclear1000/coal600/gas400/…/fallback30MW） | 値 | ★★★ | `_DEFAULT_CAP`/`_CAP_FALLBACK` | 燃料別の典型値。**銘板の証拠なし**。okinawa事例で実害実証（47.3%の主因の片翼） | なし（**要改善**: 適用件数の帳簿化候補） | capacity_bridge適用で上書き |
| 13 | **capacity_bridge**（出典付き容量パッチ・大型機dedup・稼働炉リスト・zone_override） | 値 | ★★ | `src/uc/capacity_bridge.py` | data/reference YAML（出典note付き）・nuclear_status | 適用レポート（patched/dedup/retired/unmatched_patches） | `--bridge`省略（既定OFF） |

⚠ **介入の合成リスクの実例（2026-07-07）**: #13(bridge)+#8(境界注入)を**full全規模**へ合成すると
east のACが発散し、#17 の prune が網の9割を切断した見せかけ解に到達した（backbone では
同じ合成が健全: slack 3.06%）。単体で正当な介入も**合成先の構成で破綻し得る** —
新しい構成の初回実行では必ず給電率(served_frac)と損失の物理妥当性を確認すること。
| 14 | **線路の階級典型パラメータ**（R/X/C/max_i を電圧階級で一律） | 値 | ★★ | `get_line_parameters_safe`/line_types.yaml | 教科書典型値。導体・地中の個体差は無視 | なし（yamlが定義） | — |
| 15 | **変圧器の階級典型値+v4銘板**（既定=典型sn_mva、出典ありサイトのみ実銘板） | 値 | ★★ | `_TRAFO_PARAMS`+`load_nameplates` | 銘板=出典必須DB（existing 266）。**残り~1,500器は典型値** | `@nameplate`刻印・`n_trafo_nameplate` | `nameplates=None` |
| 16 | **不明電圧の66kVフォールバック**（kv≤0のノード） | 値 | ★★ | `build_island_net` | 送電網最下級として可解性維持 | なし | — |
| 17 | **AC prune ladder**（DC不可行枝を刈ってからAC・段階的閾値） | 構造 | ★★★ | `solve_island`/`uc_to_pf_built.solve_hour` | 発散する全規模ACを解くための数値手段。**刈られた枝の潮流は存在しない扱い**。⚠実害実証(2026-07-07): pruneが網の9割を切断した残片の収束を「AC成功」と報告する**見せかけAC解**(east full+bridge構成で served 6.2/57.4GW)→solve_hourに**給電率ガード**(served≥95%必須・未満は却下し次段へ)を追加 | prune段数・solved_mode・**served_load_mw/served_frac**(07-07から) | maxバス数設定 |
| 18 | **有界ACチェーン**（backbone系: 厳tol×100反復×3構成のみ・粘らない） | 値 | ★ | `uc_to_pf_built._BOUNDED_AC` | BLAS abort回避+緩tol解の物理的無意味さ | solver名がJSONに | — |
| 19 | **県別実需要シェア配分**（#9のzone内一様を、県別実需要シェア→県内電圧重みの2段に細分化） | 配分 | ★★ | `allocate_loads(pref_gwh=…)`+`src/powerflow/pref_demand.py` | 出典=電力調査統計3-(2)都道府県別電力需要実績FY2024年度計（資源エネ庁・URL/引用/checksum付きJSON=`data/reference/pref_demand_fy2024.json`）。**年間電力量シェア→ピークシェアの近似（県別負荷率差は無視）**・県がzoneを跨ぐ分（静岡富士川split・周波数ガード飛び地=長野の東電50Hz帯15.4%等）はsubノード数按分(share帳簿化)。動機=A案回帰の真因が#9の粗さと確定（`reports/a_plan_east_ac_regression_2026-07-08.md`）。⚠適用しても**east fullのACは回復しない**（誠実にdc_fallback。回復に見えた初版は飛び地バグのバラスト効果と判明し出荷前に棄却=同レポート§7） | `net._pref_demand_ledger`→uc_to_pf JSONの`pref_demand_ledger`（zone×県のn_bus/gwh/target_mw全件）・split_prefs | **既定ON**（2026-07-10既定化・`reports/default_on_decision_2026-07-10.md`）。`--no-pref-demand`=従来zone一様（回帰比較用） |
| 20 | **無効電力の局所補償**［2026-08-11 factor 0.6→**0.8** に再較正］（負荷バスへ容量性シャント=コンデンサバンクを付与し無効需要を局所供給） | 値 | ★★ | `--reactive-comp`→`src/powerflow/pipeline.add_reactive_compensation`（`allocate_loads`直後・slack付与前） | 実配電用変電所のコンデンサバンク/SVC（OSM欠落）のモデル化。動機=east full AC非収束の真因が**角度でなく無効電力/電圧崩壊**と診断確定（DC角度健全でprune0本・負荷無効19GVarが局所補償なしで高X66kV網を流れ電圧崩壊。`reports/east_network_reactive_2026-07-09.md`）。補償で誠実AC回復（給電98.2%・vm 98.4%が0.9-1.1pu帯）。**補償率0.6は一次資料アンカーの保守側**（`reports/reactive_comp_provenance_2026-07-10.md`: 四国EGC 2024実測換算で直近≈0.8・1990年代≈0.05のレンジ内。0.6=送電端力率0.991相当=2000年代中盤水準。単一公表値は存在せず換算には仮定4点・グラフ目視±10-15%）・0.8への引き上げは要再スイープの将来課題・vm外れ値41バス(0.66%)残存。**精緻化(07-10)**: 24h経路はシャントをbase断面で固定張りのため軽負荷時刻に過補償過電圧（t=3 vm2.99）→`--hourly-shunts`で時刻別地域負荷スケールに追従（コンデンサバンク投入/開放運用のモデル化・factor×Q_load(t)の本来意図）。効果: t=3 vm_max 2.99→1.77・vm_min 0.748→0.859・損失2623→2123MW（`reports/east_voltage_refinement_2026-07-10.md`）。既定OFF | JSONの`reactive_comp`（factor/n_shunt/q_comp_mvar）・meta`hourly_shunts` 。**2026-08-11 再較正 0.6→0.8**: 0.6 は太陽光既定 10MW（太陽光180GW）の頃の値で、介入#25 で 0.10MW に正した時点で合わなくなった。発電機は `max_q_mvar=0.5×容量` の無効電力源でもあるため、**水増し太陽光を消すと捏造された無効電力サポートも消える**（hokkaido vm<0.80 が 8→45バス）。0.8 は4島すべてで電圧・最大負荷率とも悪化させない（hokkaido 38→1 / okinawa 2→0 / east 0→0 / west 11→10）。⚠**捏造の付け替え**でもある（4島計 +9,000MVar 弱のコンデンサバンク増）— ただし後者は数えられ・開示され・切れる。経緯=`reports/reactive_factor_recalibration_2026-08-11.md`| **既定ON**（2026-07-10既定化・factor=config 0.6・`reports/default_on_decision_2026-07-10.md`）。`--no-reactive-comp`=補償なし（回帰比較用）。`--hourly-shunts`は別opt-in |
| 21 | **bbox二重抽出のdedup**（①重複ノード=同一座標6桁+kv を1バス ②重複エッジ=同一バス対+同一経路 を1本・parはmax保存） | 構造 | ★ | `build_island_net(dedup_nodes=True)`→`--dedup-nodes` | **除去であって接続追加でない**（座標/経路はOSM幾何由来ゆえ完全一致=同一物理点。bbox重なりで同一OSMオブジェクトが別regionに二重抽出された分）。検証（`reports/west_fragmentation_rootcause_2026-07-09.md`§5-7）: **飛騨変換所は同一osm_id=975217734が2抽出に存在**・ノード重複633の98.6%同名一致・エッジ重複1837の**99.6%が経路完全一致**・本物の複線(par>1単一エッジ8898)は不変・自己ループ0。効果=west断片化 2,531→544成分(east 532→312)・west線9793→8353(二重計上是正で損失+5.7%=より現実的)。⚠**断片化を直すがwest full ACの特効薬ではない**(dedup後もfactor≤0.6/CLI順序でdc_fallback)。周波数跨ぎ併合は起きない(同一島=同一周波数のみ処理) | bstatsの`n_dedup_merged`/`n_edge_dup_removed`→JSON`dedup_nodes`・Ybus meta.jsonの`dedup_nodes` | **既定ON**（2026-07-10既定化=オーナー承認・Ybus v5.0.0として正典再生成・`reports/default_on_decision_2026-07-10.md`）。`--no-dedup-nodes`=v4相当（回帰比較用・従来と完全一致の不変量維持） |

| 22 | **サイト内変圧器リンク**（同名変電所=電圧/_N複製サフィックス除去後の正規化名一致+空間クラスタ0.6km以内の異電圧階級バスを2巻線変圧器で連結） | 構造 | ★★ | `build_island_net(site_trafos=True)`→`--site-trafos` | 従来の変圧器は同一座標(_k5≈1m)のみ生成のため、同一サイトでも電圧階級ヤードが数十m離れると未連結（west T-gap 57%・東京城南チェーン低電圧の背景機構）。根拠=複数電圧階級を持つ同名変電所は変圧器で階級間を結ぶ実在構造そのもの。sub=1ノード限定・既存連結スキップ・銘板(@nameplate)適用は座標式と同一規則。**保守的R=0.6kmの実効は小**（east+6器/west+20器・west成分544→543・east外れ値不変=`reports/east_voltage_refinement_2026-07-10.md`）。**0.6-2.0kmのグレーゾーン54件**（加賀500/275・上ノ原500/275等の大物含む）は`probes/east_outliers_2026-07-10/sitetrafo_candidates.json`に候補化=**人間レビュー待ち・自動採用禁止** | bstats `n_site_trafo`・枝名`site_trafo_*` | `--site-trafos`省略（既定OFF） |
| 23 | **未供用線の正直化**（建設済み・供用開始前の送電線を出典必須リストで in_service=False 建て） | 構造 | ★ | `build_island_net(deenergize_unbuilt=True)`→`--deenergize-unbuilt`・正本=`data/reference/not_in_service_lines.json`（URL+逐語引用必須） | idle原子炉の正直化と同型=「物理資産は存在するが系統潮流を担っていない」の反映。初例=**大間幹線**（500kV・61km・大間原発は**運転開始 未定**=J-POWER一次）。モデル上通電すると無負荷EHV線61km(充電125MVar)のフェランチ効果で大間ポケットに vm1.33-1.75の過電圧を生んでいた。**効果: east過電圧バス12→0**（500kV 2+66kV 10全消滅・`reports/east_voltage_refinement_2026-07-10.md`）。供用開始確認で行を削除し再生成 | bstats `n_deenergized`・リストのquote/retrieved_at | `--deenergize-unbuilt`省略（既定OFF） |

| 24 | **発電機の接続電圧規則**（繋ぎ先を最寄りでなく受電容量／電圧階級で選ぶ）**［2026-08-09 既定ON＝`cap`］** | 構造 | ★★★ | `attach_generators(attach_mode=…)`→`--gen-attach {nearest,site,cap,kvfit}`・モデル既定は定数 `GEN_ATTACH_DEFAULT="cap"`（`uc_to_pf_built`・`sensitivity/*`・`diagnose_pf_frontier` も同定数を明示的に渡す）。**関数の引数既定は `nearest` のまま**＝what-if 群（`whatif_solar_default`/`whatif_stepdown`/`overload_vs_topology`/`repair_search` の base）は引数なし呼び出しで「旧既定＝最寄り」を比較基準として保つため。ここを動かすと公表済み診断の base が黙って cap に化ける | **#3 の精緻化であり、#3 の欠陥の是正**。最寄り規則は 66kV 変電所が桁違いに多いため接続先がほぼ 66kV になり、east は発電容量の **53.2%(99GW) が 66kV バス**、姉崎火力3,600MW・川崎火力3,420MW・横浜火力2,800MW まで 66kV 接続になっていた（実系統では 500/275kV）。判定基準は**モデル自身の導体定数**から測った階級の梯子（66kV 137MVA / 154kV 533 / 275kV 1,905 / 500kV 6,928MVA）だけで作り、**外部の接続電圧表は持ち込まない**（持ち込むと捏造）。効果=`reports/repair_search_2026-08-09.md`: east cap で過負荷 603→551、太陽光是正(#25)と併せて **603→303・最大 1,668%→823%**。**繋ぎ替えは外科的**（8,235機中167機・45,464MW、接続電圧が変わったのは72機のみ＝`reports/gen_attach_diff_2026-08-09.md` に名指しで開示）。⚠**接続先バスは依然として推定**であり実接続の証拠ではない（#3 と同じ★★★）。⚠**副作用（2026-08-10 発見）**: 受電容量で繋ぎ先を選ぶため**エリア境界を越えて繋ぎ替えうる**。west 8,775機中ゾーンが変わったのは2機だが、うち**舞鶴火力1,800MWが kansai→hokuriku** へ移り、`balance_by_zone` が座標zoneで容量を数えるため出力が1/3になる（大飯・高浜の計7,886MWは nearest 時点からの既存問題） | 実行ログ `介入#24 gen-attach=…: 繋ぎ替え N機/M MW`・`gen_attach_diff_*.md`（大型機の before/after を名指し）・**副作用**=`zone_attribution_dispatch_2026-08-10.md` | `--gen-attach nearest` |
| 25 | **燃料別既定容量による容量合成**（`capacity_mw` 欠落を燃料別の既定値で埋める）**［2026-08-10 太陽光を 10→0.10MW に是正］** | 値 | ★★★ | `_DEFAULT_CAP`／`attach_generators`→`--default-cap FUEL=MW` | **従来から存在したが未登録だった介入**（本表の規約違反を 2026-08-09 に是正）。モデル総容量 477GW の **48.3% が既定値による合成**（`reports/generation_fleet_audit_2026-08-09.md`）。とくに太陽光の既定 10MW は OSM 実容量の**中央値 0.10MW の 100倍**で、太陽光を 180GW＝実績ピーク 56.7GW の 318% に膨らませている。`balance_by_zone` はゾーン内を容量比例で配分するので、**既定値がそのまま発電の空間配分になる**（tokyo はゾーン発電の 52.6% が太陽光ノード）。⚠単独で 0.10MW に正すと east 最大負荷率は 1,668%→**3,371% と悪化**する — 膨らんだ太陽光が過負荷を隠していたため。**#24 と併せて初めて改善する**（cap+0.10MW で 823%）。交互作用の測定=`reports/repair_search_2026-08-09.md`。**2026-08-10 に 0.10MW へ是正（既定ON）** — 合成率 48.3%→20.1%。⚠**是正で新しい限界が現れた**: 太陽光は実績ピーク 56,684MW の **318%→20%** となり、今度は**下回る**（kyushu 2.6%・okinawa 0.6%）。OSM は小規模設備が大半で大規模事業所の`capacity_mw` が入っていないため、件数×中央値では実績に届かない。**既定値では解けない** — 出典付き容量充填（GEM 充填と同型）が要る。**その第一歩を 2026-08-10 に実施** — 出典付き容量 350 件（227GW）は 1-C GEM 充填で D層 `docs/data/plants_all.geojson` に入っていたが、潮流も CIM も R層 `data/*_plants.geojson` を読むため**誰も使っていなかった**（08-09 監査「`capacity_mw_sourced` を持つのは 0 件」）。**R層は書き換えず読む側がD層を引く**形で塞いだ（座標キーで 350/350 一致・重複0・出典値0は0のまま尊重＝大間原発）。合成率 **20.1%→14.0%**、kyushu **100%→33.3%**・okinawa **100%→3.9%** で「実容量ゼロ」の地域が消えた。無効化 `--no-sourced-capacity`。夕方ピーク断面の潮流への影響は小さいが、**昼間断面・RE 接続可能量の研究にはそのまま効く**（`generation_fleet_audit_2026-08-10.md`） | 実行ログ `介入#25 default-cap: FUEL 旧→新`・`出典付き容量: N件/M MW を出典値で置換`・合成割合は `generation_fleet_audit_*.json` の `synth_share`（**48.3%→20.1%→14.0%**・総容量 477,173→308,655→339,182MW） | `--default-cap solar=10.0` / `--no-sourced-capacity` |

| 27 | **187kV線路抵抗の実測較正**（`r_ohm_per_km` 0.038→0.060）**［既定OFF］** | 値 | ★ | `config/line_types.yaml` の `187.calibrated` + `get_line_parameters(..., calibrated=True)`（`kind="cable"` と同じ上書き機構）。**既定 False** なので明示的に要求した経路だけが使う | **推定ではなく外部実測との照合**。事業者公表の様式5インピーダンス（[[docs/reports/system_disclosure_survey_2026-08-11.md]]）の187kV **107本**で実測 X/R = **5.83**。標準表は 0.350/0.038 = **9.21** で実測の1.58倍。187kVは定義上そのまま**北海道・四国のみ**なのでこの107本は実質全数であり、**両社が独立に一致**（北海道65本 5.63 / 四国42本 6.15）＝標本の偏りではない。原因は `conductor: ACSR 330mm2 **x 2**`（2導体）の仮定が抵抗を半分に見積もっていたことと考えられ、逆算値 0.060 は単導体 ACSR 330mm2（154kV=0.050・132kV=0.045）と整合する。**x は据え置き**（迂回係数からの示唆は n=22 と弱く端点照合の誤差が混じるため、根拠の強い X/R のみ動かす） | `docs/reports/system_disclosure_survey_2026-08-11.md` §4.5。observed の原本は `data/external/system_disclosure/`（gitignore・再配布不可） | **既定OFF**。使うとき `calibrated=True` を明示。恒久的に消すなら yaml の `187.calibrated` ブロックを削除 |
| 26 | **発電機の計上エリアを operator で決める**（座標zoneでなく OSM の operator タグ→管内）**［2026-08-10 既定ON］** | 配分 | ★ | `attach_generators` が `zone_src` 列を付与 → `balance_by_zone(use_zone_src=True)`→`--gen-zone-by-operator`（**既定ON**・定数 `GEN_ZONE_BY_OPERATOR`） | **捏造ではなく、既にある出典を使う是正**。表は `src/uc/scenario.OPERATOR_REGION`（既存の単一出典）で、`capacity_bridge` が UC 経路向けに**同じ上書きを既に実装しており**その docstring に嶺南の事情が明記されている（「高浜/大飯/美浜は立地=福井県(hokuriku領土)だが関西電力の電源としてkansaiにディスパッチされる」）。銘板経路(`balance_by_zone`)だけがそれを消費していなかった非対称の解消。効果=`reports/zone_attribution_dispatch_2026-08-10.md`: 大飯 899→**2,668MW**・高浜 679→**2,013MW**・舞鶴 360→**1,068MW**（×3）。**集計の過負荷への影響は小さく方向も混在**（east 551→544・超過−5.5% / west 291→293・超過+6% / hokkaido・okinawa 不変）。⚠つまりこれは**個別発電所の出力の正しさ**のための修正であって、過負荷を減らす梃子ではない | 実行ログ `介入#26 gen-zone-by-operator: 計上エリアを変えた N機/M MW`（west 73機/17,541MW・east 18機/5,556MW） | `--no-gen-zone-by-operator` |

（snapped系譜の旧介入 — 最近傍drop法・合成橋 — は built 系譜への移行で退役。
経緯は `reports/2026-06-10_fable5_osm_case_studies.md` と topology レポート群）

## 読み方 — 成果物を引用するときの注意

- **「AC収束」は #17 の刈り込み込み**の意味。「全規模AC」と書くときは prune ladder 経由を明示する。
- **slack%（需給整合KPI）は #9-#11 の合成の上の数字**。slackが小さい=現実に近い、ではなく
  「仮定群が内部整合した」まで。外部正解（OCCTO実績・公式潮流）との突合だけが実在性を担保する。
- **tie表は #5 の県近似の上の集計**。嶺南の自社幹線6.8GWが「hokuriku↔kansai」に載る等、
  連系線と域内幹線を区別できない（`reports/zone_reattribution_2026-07-07.md` §3）。
- **発電機の個別出力を引用しない**。#26 を OFF にしていると計上エリアが座標由来になり、嶺南原発群のような越境電源は**出力が 1/3 に出る**（大飯 4,494MW の機が 899MW）。
- **バス別・線別の潮流値を個別に引用しない**。#3/#9/#14 の合成であり、個別値に実在の裏付けはない。
  使ってよいのはエリア集計・傾向・相対比較まで（論文の限界節に明記のこと）。

## 保守規約

1. 新しい介入（接続を作る・値を埋める・配分を置く機構）を実装したら、**同一コミットで本台帳に行を追加**する。
2. 「帳簿・開示」欄が「なし」の介入は改善候補。新規実装では帳簿なし介入を認めない。
3. 介入を退役させたら行を削除せず「退役」と記す（幻tie事例の教訓: 過去の介入が過去の公表結果に残る）。
