# 接続編集プラットフォーム 設計 (Connection Editor Platform)

作成: 2026-06-14 (Opus 4.8) / オーナー要件「全OSM点を選択可能に＋点追加(緯度経度自動＋属性)＋誤接続の切断＋編集ログ→潮流計算/DB検証→判定＋多ユーザー」「完璧な設計まで実行」。

## 1. 目的と原則

I6-5 で判明した本質: **島(非連結成分)の最大要因は OSM の接続情報の欠如**(東京262島中、孤立変電所105・うち85島はOSMに送電線が無い／繋ぐ候補は僅か, 台帳111-112)。自動接続は軽微な効果しかなく、距離一律拡張は偽接続になる(台帳109)。

→ **人間が OSM 地図で実在を確認しながら、点を結ぶ／誤接続を切る／点を追加し、その編集を潮流計算と DB で検証して判定する**プラットフォームを作る。

**不可侵原則**:
- **物理接続=真・計算は検証器**(オーナー方針 2026-06-13)。人間が実在確認した編集のみ採用=捏造でない。
- **全編集は append 専用ログに記録**(誰が・いつ・何を・根拠・状態)。履歴改変しない。
- **採用は検証(潮流計算/DB)を経て判定**。pending のまま本番モデルは変えない。
- 既存資産(committedスコアカード13b・基底extract・再現性)は不可触。

## 2. アーキテクチャ

```
┌─ Leaflet エディタ (ブラウザ) ──────────────┐
│ ・全OSM点(変電所+線頂点/鉄塔)を表示&選択   │  HTTP
│ ・接続(2点)/切断(線)/点追加/属性編集        │ ───────► FastAPI (src/server/app.py)
└──────────────────────────────────────────┘          ├─ GET  /api/geojson/{region}/{layer}   (既存・全点/線)
                                                        ├─ GET  /editor                         (エディタpage・新規)
                                                        ├─ POST /api/edits                      (編集を記録・新規)
                                                        ├─ GET  /api/edits/{region}             (編集一覧・新規)
                                                        └─ POST /api/verify/{region}            (検証→判定材料・新規)
                                                              │
                          編集ログ  data/db/connection_edits.jsonl  (append専用・git追跡)
                                                              │ 適用層(機械処理・src/edit_apply.py)
        connect → {region}_lines_supplement.geojson(LineString,source=manual)
        add_point → {region}_substations_supplement.geojson(Point)
        disconnect → {region}_cuts.json (cut list)  ──► build_network_snapped が該当edgeを張らない
        set_attr → data/db/enrichments.jsonl (source=manual・最優先)
                                                              │
                          build_network_snapped → 島数 / 潮流(ρ 13b比・AC収束) → 判定(status更新)
```

既存の `ajgrid map`(docs/静的配信)と併存。本格編集はFastAPI(`uvicorn src.server.app:app --port 8080`)で配信。

## 3. データモデル — `data/db/connection_edits.jsonl`

append専用・1行1編集・JSONL(git追跡・diff可能・冪等)。`enrichments.jsonl` と同じ運用思想。

```json
{"id":"e_0001","action":"connect","region":"tokyo","a":{"node":"tokyo_sub_1354","lat":35.93636,"lon":139.61077},"b":{"node":"tokyo_jct_...","lat":35.939,"lon":139.611},"kv":66000,"user":"shigenobu","ts":"2026-06-14T03:00:00Z","status":"pending","evidence":"osm_visible","note":"OSMで明らかに同じ鉄塔列"}
{"id":"e_0002","action":"disconnect","region":"tokyo","a":{...},"b":{...},"user":"...","ts":"...","status":"pending","note":"別系統が誤接続"}
{"id":"e_0003","action":"add_point","region":"tokyo","pt":{"lat":..,"lon":..},"attrs":{"power":"substation","name":"○○変電所","voltage":66000},"user":"...","ts":"...","status":"pending"}
{"id":"e_0004","action":"set_attr","region":"tokyo","feature_key":"g:...","field":"voltage","value":154000,"user":"...","ts":"...","status":"pending"}
```

**status ライフサイクル**: `pending`(記録) → `verified`(検証実行・数値付き) → `adopted`(採用=supplement/cut/enrichmentに反映) / `rejected`(却下)。

**action と適用先**:
| action | 意味 | 適用先(adopted時) |
|---|---|---|
| connect | 2点を結ぶ(欠落線) | `{region}_lines_supplement.geojson` に LineString追記 |
| disconnect | 誤接続を切る | `{region}_cuts.json` に追記 → builder が該当edge非生成 |
| add_point | 点(変電所/鉄塔)追加 | `{region}_substations_supplement.geojson` に Point追記 |
| set_attr | 属性訂正(電圧/名称等) | `enrichments.jsonl`(source=manual・最優先) |

## 4. API (FastAPI拡張)

- `POST /api/edits` — body=編集1件。座標/重複/同電圧の軽い検証→`connection_edits.jsonl`にappend→`{id,status}`返す
- `GET /api/edits/{region}?status=` — 編集一覧(地図に色分け表示用)
- `POST /api/verify/{region}` — `pending`編集を一時data_dirに適用→build+島数(+solveでρ/AC)→各編集に before/after Δ を付け `verified` に。判定材料を返す
- (将来) `POST /api/edits/{id}/judge` body={adopt|reject} — 採用は適用先へ反映

## 5. フロントエンド (エディタ `/editor`)

- **全OSM点をもれなく表示&選択**: 変電所(`/api/geojson/{region}/substations`)+線頂点(linesの座標)。大量点は `L.markerClusterGroup` でクラスタリング、ズームで個別選択可
- **ツール(モード切替)**:
  1. **接続**: 点A→点B クリックで `connect`(同電圧か警告・OSM下地で実在確認)
  2. **切断**: 線をクリックで `disconnect`
  3. **点追加**: 地図クリック→**緯度経度を自動取得**→属性フォーム(power/name/voltage)→`add_point`
  4. **属性編集**: 点クリック→フォーム→`set_attr`
- 各操作→`POST /api/edits`。pending=橙点線/adopted=緑実線で色分け
- **検証ボタン**→`/api/verify`→島削減・ρ・AC を表示(判定材料)
- OSMタイル下地で常に実在を確認(物理接続=真)

## 6. builder 取込 — 切断(cut)の機構

- connect/add_point は既存の supplement 取込(`_layer()` snapped_topology.py:391-421)で自動
- **disconnect(新規)**: `build_network_snapped(..., cuts=...)` を追加。`{region}_cuts.json`(node対 or line_key)を読み、Pass B でその edge を張らない。opt-in→検証後にデフォルト。誤接続の除去=偽接続(3,365の教訓)の人手解決

## 7. 検証→判定 (E8)

`apply_connections.py` を拡張 or `/api/verify`:
- `pending` 編集を一時 data_dir に適用(connect→supp / disconnect→cut / add_point→supp)
- `build_network_snapped` → 島数 before/after、(任意で)`build_and_solve`→ρ(13b比)/AC収束
- 各編集に Δ(島・ρ・AC)を付け `verified`。悪化(偽接続/AC破綻)は `rejected` 候補、改善は `adopted` 候補
- モデル変更時は before/after 系統図を自動送付(feedback_before_after_figures)

## 8. 多ユーザー対応 (E9・将来)

- 簡易認証(トークン)→`user`記録
- 同時編集: 楽観ロック(編集IDで競合検出)
- レビュー承認フロー: `adopt` は別レビュアの承認を要する
- **OSM ODbL 還元**: `adopted` 接続を OSM changeset 化しコミュニティへ(本プロジェクトの一次根拠主義に合致)

## 9. 段階 (E5→E9)

- **E5** 本設計doc ✅
- **E6** 編集ログ基盤(`connection_edits.jsonl`+`src/server/edit_log.py`)+API(`POST/GET /api/edits`)
- **E7** 本格エディタ(`/editor`・全点選択+接続/切断/点追加/属性編集)
- **E8** 検証→判定(`/api/verify`・潮流+DB→status)
- **E9** 多ユーザー(認証/同時編集/レビュー/OSM還元)
