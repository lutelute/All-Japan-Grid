# All-Japan-Grid 形式的審査報告（2026-06-26, HEAD 3483160）

実施: 多agent審査ワークフロー（36エージェント, 各所見を独立した懐疑委員が実コマンドで反証検証）。モデル: claude-opus-4-8（ultracode / dynamic workflow）。読み取り専用・共有ツリー保護下で実施。

## 総合判定: 6.5 / 10 — major revision 相当（データ成果物単体は minor 寄り）

データ成果物としての出典・ライセンス・CGMES健全性・配信実動は高水準（8〜9）。本セッションの誠実性改修は全て実コマンドで裏取りでき、回帰・捏造は検出されず。一方で査読ブロッキングが複数生存。

## 1. 反証で覆った所見（審査の信頼性担保）

反証義務に基づきネガティブ主張を数え直し、以下を棄却した:
- 「編集サーバに RCE/コマンドインジェクション」→ ❌ `subprocess.run([...])` argv list（`shell=True`無し）。危険は無認証 issue 発行であり任意コード実行ではない（high-RCE→high-unauth-issue へ性質変更）。
- 「パストラバーサル」→ ❌ FastAPI str コンバータが slash 遮断（high→low）。
- 「all.json 11M をブラウザに丸投げ」→ ❌ all.json への fetch 参照ゼロ。Ybus は per-region（最大 tokyo 2.17MB）。
- 「既定地図 17MB」→ ❌ 電圧階級プリパーティションで既定 ~2.5MB（gzip 0.7MB）。17MB は worst-case 明示選択時のみ。
- 「src/dynamics が 17,333 ノードを密展開」→ ❌ nb≤200 の密ガード・全国は疎 pandapower。
- 「容量 retrieved_at が全件一律 06-20」→ ❌ 45@06-20 + 115@06-26 の2バッチ。
- 旧監査の誤判定（動特性コード不在・custom_solvers低品質・matpower三重・.git肥大=履歴・連系線829=捏造・index.html帰属欠落）は全て再反証。

## 2. 本セッション改修 — 検証で「妥当」と確認（回帰なし）

- ρ正直化: README全6箇所で 0.721=容量/トポロジ代理と明記＋実測AC ρ≈0.46/0.60併記＋"to our knowledge"化（git show 74fbe92〜HEADで生存）。
- 容量出典160件: `capacity_provenance verify = 160 ok/0 bad` 実走再現。OSM誤り訂正（柏崎刈羽→8212/蘇我→1.99）、廃止/建設中27件 value=0。source_type内訳がNOTICEと一致。
- CI順序修正: apply→build_static_site後段、pop→set で冪等。plant層出典消失バグを live で end-to-end 実証（utility132/ipp17/all170/generators341）。
- CGMES 10/10 VALID・0 dangling を validate_cgmes --all で独立再現。pytest collect 1137件エラーなし。
- 制限データ統制が模範: k_line.csv は全git履歴で一度も追跡なし（漏洩痕跡ゼロ）。関西TDは集計scorecardのみ。
- NOTICE/CITATION 帰属（WRI CC-BY是正）。

## 3. 生存した査読ブロッキング（HIGH）

- **H1 論文の変電所数 自己矛盾**: `papers/ieee-openaccess.tex` 散文4箇所(L37/59/198/251)=8,164 vs 自Table(L219)/実データ=6,962。UC機数 757 vs ieej 646。L251 "the first openly available" 未ヘッジ。→ 別agentがpapers作業中、協調必須。
- **H2 訂正容量が潮流に未伝播**: `run_full_powerflow_from_db.py` は `capacity_mw` を読むが apply は `capacity_mw_sourced` のみ書く。蘇我=1440MW幻発電所・大間=138.3MW(着工中・実0)が潮流dispatchに残り検証ρに誤注入。意図的設計だが論文/READMEで未明示。
- **H3 編集サーバ:8088 が無認証**: 状態変更7ルート(POST/DELETE)に認証/CORS/rate-limit皆無。`POST /api/issue` が運営者名義で公開issue発行可、`/api/adopt`・`/api/edits` が無認証で data/*.geojson 永続書込=モデル汚染。既定localhostだが外部公開時に高。信頼境界がREADMEで未保証。
- **H4 作業ツリーが自分の回帰pinをFAIL**: builder が `data/okinawa_*_supplement.geojson` を暗黙焼込→`test_okinawa_builder_pins` 実FAIL(89==78)。gitignore未保護で `git add .` 一発でCIも破壊。
- **H5 国際定量ベンチ不在**: PyPSA-Eur/SciGRID/Birchfield/Xiong2025 と同一軸の対照表ゼロ（Xiong被引用0）。データ論文の新規性根拠が欠落。

## 4. MEDIUM / LOW

- M: git tmp_pack garbage 973MiB が継続累積(.git=1.3G、欠落blobがrepack阻害)／OSMスナップショット時刻が完全未記録(再現不能)／CIに lint/型/coverage/regen-diff 無し／パッケージング破綻(`ajgrid`→`from scripts.*` wheel非同梱・`src`名漏れ)。
- L: 0.721 の再生成scorecard未整備／性能エンベロープ未計測(DAE密ヤコビアン上限・47kフィーチャ一括配信)／dual-use開示文書不在／DOI-Zenodo未整備・CHANGELOG v1.3停止。

## 5. 領域スコアカード

deployment 9 / provenance-license 8 / data_quality 7.5 / documentation 7.5 / integrity 7 / governance 7 / reproducibility 6.5 / testing 6.5 / performance 6.5 / architecture 6 / data_freshness 5 / ethics-dual_use 5 / security(:8088) 4 / international_benchmark 3.5。

## 6. 最優先是正

1. 論文の変電所数を6,962へ統一＋UC機数を単一正典値に＋"first"をヘッジ（papers作業中の別agentと協調）。
2. 容量訂正を潮流へ伝播 or「表示専用・潮流は元値」を論文/READMEに明示し幻発電所をモデルから除く。
3. 編集サーバ:8088 を localhost保証＋token/CSRF、`/api/issue` の dry_run既定をTrue、READMEに「外部公開禁止」保証文。
4. okinawa supplement を data/ 配下まで gitignore保護 or 正式統合（pin更新＋builder の data_dir 注入でハーメチック化）。
5. 引用可能アーカイブ化: OSM断面時刻＋WRI版を配布物に記録、Zenodo DOI、CITATION doi、CHANGELOG v1.4追補、容量DBを DATA_DICTIONARY へ。
6. CIに lint/型/coverage＋regen→diff ゲート＋国際比較表、`.git` garbage を協調一掃。

---
本報告は AI 多agent審査の記録。先行監査の過剰なネガティブ（RCE/密展開/捏造）は反証され、課題は文書間整合・訂正の伝播・配布メタデータ・配信安全に収束する。
