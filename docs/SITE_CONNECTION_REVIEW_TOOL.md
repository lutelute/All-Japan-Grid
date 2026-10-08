# 敷地・端子・母線を分けて調べる接続監査ツール

同名設備の断片を、元のOSM設備、航空写真、保存線形、電圧別の計算母線から調べる。実在する敷地と枝の記録を保持し、接続仮説を別に比較する。名称や座標を一つにまとめるだけでは失われる根拠を残すためのツール。

**状態：レビュー用の試作。正典モデルへの適用は未実施。** 今回の13組は実験用の同定候補で、承認済み接続リストではない。写真確認後に5組を再追跡へ戻している。

## Claude・Codex共通の入口

リポジトリ直下から実行する。入口のCLIはPython 3.10以上の標準ライブラリだけで動き、ファイルの変更・ダウンロード・潮流の再計算を行わない。結果はJSON、成功は終了コード0、不整合・欠損は1、引数誤りは2。

```bash
python3 scripts/site_connection_review.py summary
python3 scripts/site_connection_review.py case SS04
python3 scripts/site_connection_review.py verify
python3 scripts/site_connection_review.py verify --check-current-input
```

| コマンド | 読み取るもの |
|---|---|
| `summary` | 候補数、写真による再追跡対象、敷地・端子数、保存済みの回路比較結果、HTML・PPTのパス |
| `case SS04` | 1組の元属性、観察・解釈・未確定事項、所属敷地、保存された枝の端点 |
| `verify` | HTML、再現入力ZIPと全メンバー、航空写真と撮影期間データ、目視したコンタクトシートのSHA、主要結果間の入力同一性 |
| `verify --check-current-input` | 上記に加え、現在の `docs/data/built/all.json` が記録時と同一か |

別の同じ形式の保存結果は `--report-dir <directory>` で指定する。`verify` の成功は保存資料の整合性を意味する。全成果物のハッシュ検証、写真の再判読、ブラウザQA、潮流の再計算、実回路の正しさの証明は含まない。コードと設定の来歴は各JSONの `source_files` / `assembly_manifest` と下記固定コミットで追える。

クリーンなチェックアウトには正典の生成JSONがないことがある。その場合も `verify` で保存資料を確認できる。`--check-current-input` は欠損や更新をエラーとして知らせる。

登録時の確認（2026-09-14）：27組すべての `case` 読み出しと、現在入力を含む1,778件のSHA照合が成功。使い捨ての資料コピーでHTMLの変更・写真の欠損・異なる入力を検出し、復元後に再び成功すること、存在しないIDと引数誤りを拒否することを確認した。

## 最初に見るもの

- [全27組のBefore / After / 第三案を比較するHTML](reports/codex_same_site_trial_2026-09-13/index.html)：背景写真、元属性、保存線端、重複候補、コード差分、スライドを収録。ローカルではフォルダ全体を置いて `index.html` を開く。
- [6枚のPowerPoint](reports/codex_same_site_trial_2026-09-13/AllJapanGrid_site_terminal_review_2026-09-14.pptx)：発想、試行錯誤、回路を変えない表示分離を説明。
- [詳細な実験記録](reports/codex_same_site_trial_2026-09-13/REVIEW.md)：手順、数値、失敗、副作用、再現条件。
- [元のstoryスライドを含む全体比較HTML](reports/codex_before_after_2026-09-12/index.html)。
- [Claudeレビュー用 Issue #53](https://github.com/lutelute/All-Japan-Grid/issues/53)。

実験の固定コミットは [`4998689`](https://github.com/lutelute/All-Japan-Grid/commit/4998689af42a35c98038e9d3bdfc3b703535ca02)、共有ブランチは `codex/story-and-circuit-review-2026-09-12`。このツール登録はその後の別コミットに置き、実験記録を上書きしない。

## 判断の手順と、なぜ分けるのか

| 順序 | どう調べるか | 理由・うまくいかない条件 |
|---|---|---|
| 1. 入力を固定 | built、元GeoJSON、設定、コードのSHAを記録し、同期島ごとに連結成分を再計算する | 保存済みの `main` / `deg` や地域内連番は更新で古くなる。同じ行番号を別入力へ引き継がない |
| 2. 設備を同定 | 同名・500m以内を候補抽出に使い、OSM type/id、敷地形状、元タグとモデル電圧を照合する | 同名・近接だけでは別設備や別電圧の母線を区別できない。未知電圧を一致扱いしない |
| 3. 背景を実際に見る | 写真のみ／線を重ねた表示を切り替え、敷地、道路、鉄道、引込経路を拡大確認する。撮影年月と目視画像のSHAも残す | 線の重ね描きは見たい形へ判断を誘導する。古い写真やモザイクの時期差、地下線、開閉状態は写真だけで解決しない |
| 4. 敷地・端子・母線を分ける | 敷地は面、端子は保存枝の端点、計算母線は電圧別IDで保持する。所属・導通・表示位置を別フィールドにする | 代表点へ線を寄せると実在位置が失われる。一方、敷地を通過する線を境界で切ると架空の接続点を作る |
| 5. 線の来歴を見る | 共有区間を候補抽出し、元way、復元chain、回線数、継ぎ目距離を照合する | 幾何の重なりは二重計上にも実際の並行回線にもなる。保存builtの線形には過去の復元も含まれる |
| 6. 同じ運転点で比較 | P/Q、機器条件を固定して接続仮説を比較し、線路・変圧器の端点とR/X/C等も照合する | 負荷の再配分や線長推定の変化が混ざると、接続変更の効果を識別できない |
| 7. 判断と未確定を保存 | 各組に「見えたこと」「解釈」「未確定」「次の調査」を記録し、採用・保留・再追跡を明示する | 断片数の減少やDC収束だけでは物理的に正しい接続を選べない |

## 今回の試行錯誤を引き継ぐ

初回の27組から同一OSM・同一モデル電圧の13組を試し、東日本の地理的な断片は221→210となった。このうち元の電圧タグでも一致するのは5組。その後、全27組の写真と8枚の拡大図を目視し、**SS04・SS07・SS11・SS12・SS13** は経路を再追跡する扱いに戻した。電圧タグが一致する5組と、写真で再追跡に戻した5組は別の集合。

代表点を移すだけの試行では、保存線形のない枝10781の推定長が1.0344→0.9931kmへ変わった。元端点を `identity_length_reference` に保持し、接続仮説以外の電気定数が変わらないよう修正した。初回の不一致は `powerflow_attempt1.json` に残している。

第三案では元の17,738ノード・19,944枝の記録を残し、24敷地と70のモデル枝端を別に記述した。東日本の実回路では同じ13組の接続仮説に対して34母線の表示位置を敷地側へ移し、電気属性表は一致、DC線路潮流差は0 MW。これは表示と回路を分離できる検証であり、13組の実導通を確認した結果ではない。

秩父の宮地線では約1.351kmの保存経路が共有され、回線数は2と1で食い違った。こうした共有経路を42組検出したが、自動削除はしていない。ACは元モデル・5組・13組の全試行で非収束。第三案は電気属性が同一なのでACを再実行していない。

## 実装の分担

| ファイル | 役割 |
|---|---|
| [site_identity.py](../src/powerflow/site_identity.py) | 入力ダイジェスト・電圧・同期島・端点の曖昧さを検査した、コピー上の同定試行 |
| [site_terminals.py](../src/powerflow/site_terminals.py) | 敷地・保存枝端の証拠を構築し、計算回路の表示座標へ投影 |
| [trial_same_site_connections.py](../scripts/trial_same_site_connections.py) | 候補抽出、元OSMへの照合、トポロジ比較 |
| [solve_same_site_trial.py](../scripts/solve_same_site_trial.py) | 同じP/Qでの東日本実回路比較と独立再構築の照合 |
| [trial_site_terminal_projection.py](../scripts/trial_site_terminal_projection.py) | 第三案の電気属性一致とDC差を実回路で確認 |
| [audit_site_path_overlaps.py](../scripts/audit_site_path_overlaps.py) | 保存経路の共有区間を、回線数・復元履歴付きで抽出 |
| [fetch_same_site_basemaps.py](../scripts/fetch_same_site_basemaps.py) | 写真タイル・撮影期間の取得とSHA記録 |
| [build_same_site_review.py](../scripts/build_same_site_review.py) / [check_same_site_review.py](../scripts/check_same_site_review.py) | 比較HTML生成／ブラウザ表示の検証 |
| [visual_review.json](reports/codex_same_site_trial_2026-09-13/visual_review.json) | 実際に画像を見た際の所見。生成スクリプトの自動判定ではない |

## 再現と、次の入力で使う場合

今回の実験を再現する場合は、固定コミットの使い捨てチェックアウトと、[SHA付き再現入力](reports/codex_same_site_trial_2026-09-13/reproduction_inputs.json)を使う。[REVIEW.mdの実行順](reports/codex_same_site_trial_2026-09-13/REVIEW.md#検証再現)に沿って実行する。再現入力ZIPはその使い捨てチェックアウトに展開する。電気解析にはプロジェクトの依存環境（記録時pandapower 3.4.0）、写真再取得にはネットワーク、表示検証にはPlaywrightが必要。既存の写真キャッシュと目視記録は保持する。

次の入力への適用は、現在の低水準スクリプトに残る固定の入力・出力パスを新しい実験用へ設定してから行う。新しいSHA、元OSM対応、候補、写真と撮影期間を採り直し、目視所見を新規に記録する。13組の `alias_plan.json` や `visual_review.json` を流用しない。このCLIは保存結果の閲覧・検証入口であり、任意データを一括修正するパイプラインではない。

Claudeへの依頼は、まず **SS04の保存線端と敷地、SS01の共有経路、SS12の電圧一致と写真判断の食い違い** を同じ画面で確認し、次にソースと試験を読む順序がよい。候補を採用する変更では、元の枝・敷地・異電圧母線を保持すること、線長と回線数の副作用、未確定な端子の扱いをレビュー対象に含める。
