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

（snapped系譜の旧介入 — 最近傍drop法・合成橋 — は built 系譜への移行で退役。
経緯は `reports/2026-06-10_fable5_osm_case_studies.md` と topology レポート群）

## 読み方 — 成果物を引用するときの注意

- **「AC収束」は #17 の刈り込み込み**の意味。「全規模AC」と書くときは prune ladder 経由を明示する。
- **slack%（需給整合KPI）は #9-#11 の合成の上の数字**。slackが小さい=現実に近い、ではなく
  「仮定群が内部整合した」まで。外部正解（OCCTO実績・公式潮流）との突合だけが実在性を担保する。
- **tie表は #5 の県近似の上の集計**。嶺南の自社幹線6.8GWが「hokuriku↔kansai」に載る等、
  連系線と域内幹線を区別できない（`reports/zone_reattribution_2026-07-07.md` §3）。
- **バス別・線別の潮流値を個別に引用しない**。#3/#9/#14 の合成であり、個別値に実在の裏付けはない。
  使ってよいのはエリア集計・傾向・相対比較まで（論文の限界節に明記のこと）。

## 保守規約

1. 新しい介入（接続を作る・値を埋める・配分を置く機構）を実装したら、**同一コミットで本台帳に行を追加**する。
2. 「帳簿・開示」欄が「なし」の介入は改善候補。新規実装では帳簿なし介入を認めない。
3. 介入を退役させたら行を削除せず「退役」と記す（幻tie事例の教訓: 過去の介入が過去の公表結果に残る）。
