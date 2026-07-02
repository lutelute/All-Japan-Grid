# 変電所内部構造DB (node-breaker) — 接続の第一級データ

オーナー方針(2026-07-02)「線は変電所に入り、変電所で電圧階級・タップ・回線・導体を
接続する(そこから負荷へ分配される)」を第一級データとして実装した構造DB。
OSM(正)から**決定的に再生成可能な D 層生成物**であり、接続は全て根拠付き
(捏造禁止)。

## 生成(ワンコマンド・全国約4秒)

```bash
PYTHONPATH=. .venv/bin/python scripts/build_structures_batch.py --all
# 単一地域: --region kansai / 決定性検証つき: --all --verify-determinism
```

- 品質ゲート: `tests/test_substation_structures.py`(全数生成・参照整合・決定性・
  接続導出・provenance・回帰pin)
- git 方針: 地域ファイルは非追跡(再生成可能)。`summary.json`(全国カタログ)のみ追跡。

## ファイル

| ファイル | 内容 |
|---|---|
| `{region}.json` | 地域の全変電所の構造 + サイト間接続レコード |
| `summary.json` | 全国カタログ(地域別統計・binding分布・品質指標) |

## スキーマ(`src/model/substation_structure.py`, CIM整合)

```
structures[]:
  site:            SubstationSite  (cim:Substation)  物理変電所。地域重複は aliases で相互参照
  voltage_levels[]: VoltageLevel   (cim:VoltageLevel) sid@kv。kv_source= tag|line-tag|unknown
  busbars[]:       BusbarSection  (cim:BusbarSection) 頂点共有成分。無タグは kv_inferred+kv_evidence
  bays[]:          Bay            (cim:Bay)           触れる母線を busbar_ids に記録
  terminals[]:     Terminal       (cim:Terminal)      線端の束縛 = 「なぜ繋がるか」のレコード
  transformers[]:  TransformerSpec(cim:PowerTransformer) 階級ラダー(structural。銘板/タップは出典待ち)
connections[]:     サイト間接続(線の両端が別サイトに束縛) from/to site・vl・binding・par・confidence
```

Terminal の binding 語彙(強い順): `vertex-shared`(OSM頂点共有) > `polygon`(敷地内包)
> `leadin`(0.6km引込帯) > `name-evidence` > `manual`。

## 品質(2026-07-02 生成)

- 全国 6,956 サイト / 端子 48,081 / 接続レコード 10,888 / エラー 0 / 決定性 identical
- VL既知率 77.4%(line-tag 導出 2,058 VL を含む。改善前 59.1%)
- 外部妥当性: 接続レコードの **96.5% が built 正典(all.json)と同一連結成分**。
  built 別成分の 210 件は島削減候補として
  `docs/reports/structure_db_island_lever_candidates_2026-07-02.json` に記録。

## 位置づけ

- **正典はこのディレクトリの地域ファイル**(一括生成のみが書く)。ダッシュボード
  (:8088/tools)の単発抽出は点検用で /tmp に出力する。
- 将来(Phase A 本実装): C 層(手動編集・出典付き銘板/タップ)を重ね、build が
  「幾何再推論」でなく「このDBの適用+差分検出」になるのがゴール。
