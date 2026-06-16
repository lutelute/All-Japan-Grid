# 全面改修計画 — 正(source of truth)を1つに

作成: 2026-06-16 / **Claude Opus 4.8** / オーナー指示「全面改修(エディタ以外も含め全体見直し)」。
3並列調査(データ/モデル/DB・2エディタ・end-to-end一貫性)の実コード根拠にもとづく。

## 0. 根因 — なぜ「OSMで接続したのにビューが無茶苦茶」が起きるか

単一の症状でなく**「正の分岐」という構造問題**。実コードで確認した分岐:

| # | 分岐 | 根拠(file:line) | 影響 |
|---|---|---|---|
| 1 | 出力が別パイプライン・別タイミング | `build_static_site.py:57`(raw OSM・4/23) vs `build_editor_data.py`(built・6/16) vs `export_cim.py:4`(raw) | 同一系統が公開レイヤ内で複数表現・**7週間の鮮度差** |
| 2 | DB(正候補)が本番buildに未接続 | `snapped_topology.py:338` 既定`db=None`・実DB注入は`cli.py:64`のopt-inのみ | `MODEL_SOURCE_UNIFICATION` R1未実装・`data/grid.db`(134MB)が死蔵 |
| 3 | 破壊的enrich経路が残存・到達可能 | `scripts/enrich_*.py`(6本 in-place)+`enrich_all.py:74` | 実行で基底extract(D層)を無印で上書き→DBと乖離 |
| 4 | 連結性計算が2系統 | `national.py:105`(融合+ties) vs `built_view.py:40`(表示stitch0.15km) | Pages島色 ≠ 潮流の島 ≠ census(`island_substations.py`) |
| 5 | エディタ2本+派生バグ | `templates/editor.html`(本物) vs `docs/editor.html`(lossy) / `app.py:61,83`(/api/regions二重) / chord描画 | 見た目・データ・挙動の不統一(今回の全不具合の源) |

## 1. 不変条件(改修が守る)

物理接続=真・計算は検証器・**捏造禁止**・**基底extract不変**・committedスコアカード不可触・
偽接続(3,365の教訓)を作らない・モデル変更はbefore/after系統図。supplement/cutsは加算のみ(可逆)。

## 2. 到達点(単一の正)

```
R層 raw_features(grid.db) ─┐
C層 enrichments(.jsonl正本)─┼─→ build_network_snapped(db) ─→【唯一のモデル】─→ 全出力(一括再生成・MODEL_VERSION刻印)
+ supplement/cuts(加算PRIMARY)┘                              ├ built_view/all(編集ビュー=Pages)
                                                              ├ national(潮流・連結性の唯一の権威)
                                                              ├ matpower / CIM
                                                              └ Pages公開geojson(rawでなくbuild由来)
エディタ=1本(起動時backend検出: /api有→ライブ編集 / 無→静的JSON+下書きexport)
```

## 3. フェーズ(各フェーズ: pytest緑・A/B計測・before/after図・悪化revert・明示パスcommit)

### Phase 0 — 即効バグ修正(低リスク・独立・ユーザー可視)
- **全国chord描画**: `build_editor_data.build_national`/`built_view_all`で**path無し辺を表示から除外 or 短path合成**(stitch/stub辺が直線弦で交差するのを止める)。※長距離弦は path 付与済(済)、残るは短い無path辺。
- **/api/regions二重定義**(`app.py:61`死/`:83`勝ち): 分離(`/api/regions/bbox`)し全国編集の地域振分け(`regionAt`)を復活。
- **kVスケール要検証**: `templates/editor.html`が`node.kv`を`/1000`(W前提)、`built_view`はkV。実害有無を確認し正規化。
- **edit_log status遷移**: verified/adopted/rejected の書込みが未実装(全件pending)。adopt/verify時にstatus更新を実装。

### Phase 1 — 破壊経路の封鎖(基底extract不変を構造保証)
- `scripts/enrich_*.py`(in-place 6本)・`enrich_all.py`・`fix_plant_capacity.py`・`restore_missing_plants.py`・`slim_geojson.py` を**削除 or git-guard**(`data/*.geojson`書込みをassert拒否)。enrichは`src/db/enrich.py`(DB-native)へ一本化。
- supplement書込みの一本化: `scripts/apply_connections.py`等の非editor経路を`edit_apply.adopt()`のedit_id管理・可逆方式へ統合。

### Phase 2 — 単一の正: builderをDB直読みに(R1 / DB_ARCHITECTURE Step5)
- `build_network_snapped`の既定を`db`(grid.db)経由へ。round-trip等価テスト(`tests/test_db_source_build.py`既存)で担保。`--source files`は退避フラグ。
- supplement/cutsは加算入力のまま(DB外PRIMARY)。

**調査結果(2026-06-17・着手して判明)**: **ソースレベルの正は既に統一済みだった**。
- 永続 `data/grid.db` build ≡ files build が **全10地域で完全同値**(subs/lines/gens厳密署名 ALL MATCH)。
- committed `data/*.geojson` は **全10地域で DB の忠実な D層 export**(`verify_roundtrip` クリーン)。
- → committed files = DB(R⟕C)の検証済みコピー。**正はDBに一本化済み**で、files はその reproducible export。
- 不変条件として固定: `tests/test_db_source_unified.py`(CI-safe全地域roundtrip 10 + ローカルgrid.db build同値 3)。
- **重要な含意**: 今回の「全国が無茶苦茶/見た目が違う」不統一の真因は**ソースDBでなく下流(出力生成)**。
  grid.db は gitignore(=CIはfiles=DB-exportでbuild・ローカルはどちらでも同値)なので、**build既定の
  files→DBへの切替は必須でない**(files=DB-exportが reproducible な正)。むしろ切替は local DB drift と
  committed の乖離リスクを生むため**保留**。代わりに「files=DB-export を破壊させない」=Phase 1(破壊封鎖)が
  真の保護。→ **次は下流の不統一(Phase 3 連結性 / Phase 4 出力オーケストレーション)が本丸**。

### Phase 3 — 単一の連結性権威 + 定義の一本化
- `national.build_island_networks`(stitch+ties)を**全国連結性の唯一の計算**に。`built_view_all`/`build_national`はそれを消費(round-5座標グラフの再計算を廃止)→ Pages島色=潮流島=census が構造的に一致。
- 地域→周波数のハードコード4箇所(`national.py:44`/`pandapower_builder.py:51`/`built_view.py:10`/`dynamics builder`)を`src/regions.py`(config/regions.yaml)へ一本化。

### Phase 4 — 全出力を単一オーケストレーションで派生 + 鮮度統一
- `scripts/regenerate_all.py`: `build_editor_data`→`run_national_powerflow`→`export_national_matpower`→`export_cim`→`build_static_site` を順に実行し、**MODEL_VERSION**(git HEAD+timestamp)を全出力metadataに刻印。7週間skewを解消。
- OSM mapレイヤ+CIMを**supplement/cuts反映**(真の統一) or 「raw extract(pre-model)」と明示ラベル。
- CI(`deploy-pages.yml`)のtriggerに`snapped_topology.py`/`built_view.py`を追加し、build jobで`build_editor_data.py`を実行。

### Phase 5 — エディタ1本化(runtime-adaptive)
- **DataSource抽象**: `LiveSource`(/api)・`StaticSource`(静的JSON+localStorage下書き)。起動時backend検出で差替。
- `renderModel`/`SnapIndex`/`COLORS`を共有コアに抽出(2ファイルの重複/乖離を解消)。
- **単一HTML正本**(`templates/editor.html`)→ build時`docs/editor.html`へコピー。:8088もPagesも同一コード・同一の見た目/幾何。
- verify/adoptはliveのみ、staticは下書き+export(捏造しない)。レビュー/候補機能は両モードに露出。

## 4. 推奨実行順
**0(可視バグ即修正)→ 1(破壊封鎖=安全)→ 5(エディタ統一=痛点解消)→ 3(連結性一致)→ 2(DB正化)→ 4(出力統一+CI)**。
0/1/5でユーザー可視の不統一と安全性を先に解決、3/2/4で構造の正を畳む。各フェーズ独立にcommit・検証・revert可能。
