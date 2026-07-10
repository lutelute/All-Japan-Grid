# Phase 1-B 次段 — 出典が正典グラフ(all.json)と CGMES まで届いた 2026-07-11

- 指示: オーナー「やろう」(1-B次段=built透過の推奨に対する承認)
- モデル: Claude Fable 5
- 前提: 第一弾(`117a2fe`)は「器」まで — Enrichment出典4列(v5)・統合バリデータ・CIM発電所(add_plant)への貫通。
  スコープ調査の結論は「出典は3系統に分裂し、**builtには出典欄が無い**」だった。

## 1. 何を繋いだか(3本の配線+バックアップの穴)

```
Enrichment(C層・出典4列)
  └─ compose(markers=True) → GeoJSON _src:<field> / **_srcurl:<field>** (新設)   [配線①]
       └─ snapped builder(sub_info.prov) → Substation.provenance
            └─ built_view node["src"] → docs/data/built/{region,all}.json        [配線②]
data/transformer_sources.jsonl(銘板・URL+quote必須)
  └─ 構造DB TransformerSpec(source=nameplate, note="url | quote")
       └─ CIM Level-1 **PowerTransformer**(新設) description=出典URL             [配線③]
```

- **配線① `_srcurl:` マーカー**(`src/db/geojson_sync.py`): D層エクスポートが出典URLを
  `_srcurl:<field>` として随伴、ingestが回収して `Enrichment.source_url` に復元
  (roundtripで出典が落ちない)。upsertは COALESCE=無マーカー再ingestで既存URLを消さない。
- **配線② built透過**(`snapped_topology → Substation.provenance → built_view → build_editor_data`):
  GeoJSONの `_src:`/`_srcurl:` を `{field: {src, url}}` に畳んでノードの `src` へ。
  **正典 docs/data/built で 3,813/17,336 ノード(22%)が出典ラベル付き**になった
  (現時点の中身は name の enrichment 由来。1-D電圧タグ充填が始まればURLごと自動で乗る)。
- **配線③ CGMES PowerTransformer**(`src/cim/exporter.py`): 構造DBの変圧器を Level-1 EQ に
  写像(全国2,385器・うち銘板13器は description=出典URL)。tokyo_EQ.xml に
  池上変電所の東芝レビューURL・東電PG整備計画URLが実際に乗ることを確認。
- **バックアップの穴**: `dump/load_enrichments_jsonl`(追跡バックアップ)と `apply_enrichments` が
  出典4列を運んでいなかった=「DBにだけ出典がある」状態に逆戻りする欠陥。4列を配管した。

## 2. 誠実性の規約(変圧器のCGMES写像)

- `ratedS` は**銘板(existing出典)を持つ spec のみ**。structural spec に定格を書かない(捏造しない)。
- バンク台数は名前の `×N` で開示(CGMES 2.4 に台数属性が無い)。
- `description` は source="nameplate" の出典URLのみ。
- 電圧階級が読めない spec は写像しない。

## 3. 検証

- golden test 3本追加(`tests/test_provenance_propagation.py`):
  ①_srcurl roundtrip(apply→export→ingest→dump全経路) ②built透過(マーカー→node.src)
  ③PowerTransformer(URL貫通・ratedSは銘板のみ・境界込み0 dangling)。**計202 passed**
  (正規ゲート52+geojson_sync/enrich/CIM/snapped系一括)。
- CGMES構造検証: okinawa(追跡分) **2,659 objects / 0 dangling**・tokyo(サニティ)
  **149,165 objects / 0 dangling**。dist/cim_level2(L2)は無変更。
- built再生成: **9地域はノードid集合・全フィールドがHEADと完全一致(src追加のみ)**。

## 4. hokuriku の追随(正直な開示)

正典 built(2026-06-18生成)はビルダー改良(信州154kV網の型付け)を未反映だった。再生成で:

- 新信濃・竜島・松本市_3 が電圧階級別バスへ分割(784→787ノード)
- 松本エリアのjunction 4点が kv 0→154 に型付け(id改番)・松本市_5 が孤立(deg0)→154kVで結線(deg2)

データ(GeoJSON)は6/18から不変=**純粋にビルダー進化の追随**。all.json は 17,333→17,336。

## 5. 併せて直したもの

- **editor.html のドリフト解消**: 07-10のモバイル対応を生成物(docs/editor.html)に直接当てて
  いた(誤り)。テンプレ(`src/server/templates/editor.html`)へ移設し、Pagesビルダーに
  :8088専用 `/tools` リンクの剥がしを追加。**再生成結果は出荷済みHEADとバイト一致**
  (=公開物は不変のまま、テンプレ=単一の正が復旧)。drift検査 4 passed。

## 6. 残り(1-Bの完了条件)

1. `_srcurl:` マーカー付き公開GeoJSONの実出荷(現状の公開ファイルはURLマーカー0件 —
   URL付きenrichmentが入るのは1-D電圧タグ充填/1-C容量充填から)
2. CIM Level-2(解ける潮流ケース)側の変圧器銘板(=snappedパイプラインへの nameplate 配線は未・
   run_full系のCGMES出力経路も未整備)
3. dist/cim は okinawa のみ追跡。全国XMLの配布方針(bundleに入れるか)はデータセット改版時に判断

## 7. 再現

```bash
PYTHONPATH=. .venv/bin/python scripts/build_structures_batch.py --all   # 構造DB(銘板伝播)
PYTHONPATH=. .venv/bin/python scripts/build_editor_data.py              # built正典(src付き)
PYTHONPATH=. .venv/bin/python scripts/export_cim.py                     # L1 CGMES(変圧器+URL)
PYTHONPATH=. .venv/bin/python -m pytest tests/test_provenance_propagation.py -q
```

注意: built再生成時は 1-F未裁定の okinawa supplement/cuts(untracked)を混入させないこと
(本作業では一時退避して生成し、正典は従来どおり supplement なし基準を維持した)。
