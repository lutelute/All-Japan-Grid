# 変電所の構内結線: All-AU-Grid / All-EU-Grid の提案の採用と、日本での改良(2026-10-07)

- モデル: Claude Opus 5.5
- オーナー指示(2026-10-07):「all-au-grid で変電所のところの結線提案があったはず、EU もやり始めているけど、いい内容だったら採用しながら自己改善してこのプロジェクト資産に反映して。すこしプロジェクト全体の見通しをよくしたい」
- 方法の正本: [../STATION_NODE_BREAKER.md](../STATION_NODE_BREAKER.md)
- 受けた提案: All-AU-Grid `docs/SUBSTATION_METHOD.md`(v1.1)・`docs/JAPAN_STATION_MIGRATION.md`、
  All-EU-Grid `docs/STATIONS.md`(commit 9b4be87)と、EU がこのリポジトリに置いた比較
  [station_node_breaker_comparison_2026-10-07.md](station_node_breaker_comparison_2026-10-07.md)

## 1. 提案の中身

All-AU-Grid が、変電所の中を「母線・ベイ・開閉器・変圧器の巻線・端子・接続点」の台帳にする方法をまとめた。結線は OSM の node ID の共有だけで決め、
推定した値で穴を埋めない。All-EU-Grid がそれを欧州全体に実装して規則を 5 つ足し、日本の OSM にもかけて SubSLD と比べた。EU の判定は次の 2 点。

- データ層は node ID 方式が上。SubSLD の変圧器(梯子)・開閉器(ベイから推定)・母線の帰属(矩形 +1 km)・端子の過半(引込帯)は観測ではない。
- SubSLD に残る価値は図法と、計算モデルとの照合の発想。

## 2. 独立に確かめたこと

驚く数字は、別の経路で数え直してから使う。

| EU の主張 | こちらの再計算 | 判定 |
|---|---|---|
| 母線 2,530 本の 25%(631)、ベイ 7,929 本の 23%(1,850)が 2 つ以上の別の変電所に入る | 構造 DB をクリーンな main から作り直して数えた: 母線 631/2,530(24.9%)、ベイ 1,848/7,929(23.3%)。原因は `_collect_ways` が外接矩形 +0.01° の母線・ベイを包含の判定なしに全部取ること(コードで確認) | 正しい |
| `_vclasses` は `66000.0` を 660 kV と読む | 数字だけを連結するコードを確認。今の OSM に該当タグは無い | 正しい(潜在) |
| 梯子は OSM の実機と 18% の変電所で食い違う。段を飛ばす実機 47 か所 | 下の §5。地域境界の重複を 1 つに数え、帰属の修正後の構造 DB で比べると、食い違い 98/518(19%)、段飛ばし 32 | 傾向は正しい。件数は数え方で変わる |
| 端子の 55% が引込帯 0.6 km | binding の集計で一致(26,423/47,979) | 正しい |

## 3. 採用したこと

| 採用 | どこに | 効果 |
|---|---|---|
| **SubSLD の母線・ベイの帰属を敷地の多角形で決める**(包含・入れ子は最内側・柵外 25 m) | `scripts/build_substation_structure.py` `internal_way_owners` | 二重計上 25%→0(下表) |
| `_vclasses` で小数を数として読む | `scripts/substation_scope.py` | 潜在不具合の予防 |
| node-breaker のコア(AU の規則 + EU の規則)と派生の読み方 | `src/stations/`(EU commit 9b4be87 から移植し、同日 3d253de の差分を取り込んだ・移植テスト 33 件) | 観測層を新設(§4) |
| 構造 DB の ID は置き換えず、OSM の (type, id) で対応を取る(AU の移行手順の 2) | `scripts/build_station_db.py` `structure_crosswalk` | 構造 DB の OSM キー 6,146 のうち 6,137 が対応 |
| 梯子は仮説として残し、観測と食い違う所を一覧にする(AU の移行手順の 3) | `scripts/compare_station_layers.py` | 確認の一覧(§5) |

**SubSLD の構造 DB の前後**(全国、`scripts/build_structures_batch.py --all`):

| | 前 | 後 |
|---|---:|---:|
| 2 つ以上の別の変電所に入る母線 / ベイ | 631 / 1,848 | 0 / 2 |
| 母線(OSM の way 由来 / 推定) | 2,559 / 2,669 | 1,757 / 2,635 |
| ベイ / ベイから推した開閉点 | 8,753 / 8,386 | 6,283 / 6,008 |
| 端子(頂点共有 / 敷地内 / 引込帯) | 47,979(7,930 / 13,626 / 26,423) | 47,126(5,706 / 13,648 / 27,772) |
| サイト間の接続レコード | 11,586 | 10,334 |
| 梯子の変圧器 | 2,586 | 2,493 |
| 電圧の分かるサイト | 5,649 | 5,630 |
| **Ybus v4 が読む銘板**(`load_nameplates`) | 13 | 13(**中身も同一**) |
| Pages の SubSLD(`docs/data/subsld_pages.json`)で表示が変わる所 | — | 433 / 6,165 |

消えた接続レコード 1,252 件は、隣の変電所の母線・ベイを自分のものにしたことで生まれた架空の接続。
沖縄の例: 津花波変電所が 0.6 km 先の西原変電所のベイ 7 本を取り込み、西原~津花波・渡口~津花波などの接続を 4 件作っていた。
潮流モデルの入力(銘板)は前後で同一なので、Ybus・潮流は変わらない。

## 4. 自分で改良したこと(EU の規則にも無かった穴)

日本の OSM に AU/EU の規則をそのままかけて、課題の内訳から 3 つの穴を見つけた。

1. **柵の外へはみ出して描かれたベイ**(最大の穴)。日本では `line=bay` を柵の外の門型鉄構・鉄塔まで描くことが多い。
   1 つの敷地からはみ出す構内配線 901 本の、柵からの最大距離の中央値は 47 m(25 m 以内は 13 本、100 m 以内が 89%)。
   欧州版の 25 m の緩衝では帰属できず、そこから出る線路が変電所につながらなかった。
   - 観測層: `internal_extension`(100 m まで)を足した。敷地を決められない構内配線 987→177、線路の端が配線に載る 5,762→6,050、
     全閉で母線に届く 2,719→2,840、両側の決まらない開閉器 284→227(EU commit 3d253de の規則で測り直した値)。既定は 0 で、移植元の厳密な読み方を残す。
   - SubSLD: way 単位で同じ穴があった(沖縄の西原変電所のベイ 4 本が柵外 33 m)。頂点がすべて同じ 1 つの敷地に入る way を
     `partly_covered` として帰属させた(ベイ 969 本・母線 27 本)。2 つの敷地にまたがるもの(23 本)は帰属させない。
2. **50 Hz と 60 Hz**。欧州版は 50 Hz 以外を別の階級(`ac_other`)にする。西日本の線は `frequency=60` が付くので、
   タグの有無だけで同じ変電所の 154 kV が 2 階級に割れる。日本は 50/60 Hz を同じ系統 `ac` にし、両方のタグが同じ階級にある所を
   `frequency_mixed_levels` として別に拾った(8 階級。新信濃・佐久間の周波数変換所のほか、中信・松島など境界付近のタグ)。
3. **構造 DB との対応**。EU の比較は重心と名前で照合していた。AGJ の GeoJSON には OSM の (type, id) が残っているので、それで取った。

## 5. 梯子と OSM の実機の突き合わせ

`docs/reports/station_layers_2026-10-07/`(`summary.json`、`transformer_pair_review.csv` 153 行)。OSM が両側の巻線電圧付きで変圧器を描く 518 敷地。

| 判定 | 敷地 |
|---|---:|
| 梯子と同じ | 365(70%) |
| OSM が梯子の一部しか描いていない | 55 |
| 構造 DB に無い階級(6 kV など)への実機 | 66 |
| **梯子が段を飛ばす実機** | **32** |

段飛ばしの組: 275/77(6)、220/66(6)、66/6(5)、500/154(5)、100/6(3)、275/66(2)、500/110・115/66・66/22・154/33・154/6(各 1)。
基幹系の例:
- 275/77 の直結: 西濃・東清水・駿遠・北大阪・淀川・東大阪。梯子は 275/154 と 154/77 を経由する。
- 500/154: 南京都・猪名川・西京都・新岡部・新栃木。
- 500/110: 東岡山。220/66: 西谷・日田・都城・鳥栖・大隅・木佐木。

**同じ梯子の仮定が潮流モデルにもある**(`run_full_powerflow_from_db.py`: 変電所内の電圧階級を高い順に隣どうしで結ぶ)。
段を飛ばす実機は、潮流の経路と変圧器の容量の当て先を変えうる。

**出典付きの銘板と観測が、そろって梯子と食い違う例**:
- 東毛変電所: 出典 DB(`data/transformer_sources.jsonl`)に 275/66 kV・150 MVA がある。しかし梯子(500/275・275/154・154/66)に 275/66 が無いので、
  `apply_transformer_provenance` が「一致する組が無いときは当てない」規則で捨てていた。OSM には 275/66 の変圧器が 5 台描かれている。
  出典と観測の 2 つが同じ組を示している。
- 鹿島変電所の 275/66(出典あり)は、OSM の敷地が 3 つに分かれ、変圧器は 66/6.6 だけ。観測では確かめられない。
- 西島根変電所: 出典は 500/220 kV、OSM の導体は 500/275/110 kV のタグ。中国電力の基幹は 220 kV なので、OSM 側のタグの誤りの候補。

## 6. 採用しなかったこと・保留

| 項目 | 理由 |
|---|---|
| 梯子を観測した組で置き換える(構造 DB・潮流モデル) | モデルの接続の介入。根拠・帳簿・無効化の 3 点をそろえ([MODEL_INTERVENTIONS.md](../MODEL_INTERVENTIONS.md))、オーナーが判断する。一覧は確認の順に並べた |
| SubSLD の引込帯 0.6 km の端子をやめる | 端子の過半(27,772)が引込帯で、Pages の単線結線図と接続レコードが依存している。観測層の端子で根拠を格上げする方が先 |
| kV の切り捨て整数(6.6 kV → `@6`) | 階級 ID `{site}@{kv}` が下流で使われている。観測層は 6.6 のまま持つ |
| built の `sub_props` の付け直し(`build_substation_properties.py --attach`) | 正典 `docs/data/built/all.json` を書き換えるため、このブランチでは見送った。次に Snakefile で正典を作り直すとき自動で反映される |
| ~~EU の作業ツリーにある未コミットの追加~~ | EU が 3d253de でコミットしたので取り込んだ(tee_junction・閉じた開閉器の腕・gaps)|

## 7. オーナーに判断してほしいこと

1. **梯子の置き換えを試すか。** 最初の候補は東毛(出典と観測が一致)。次に上位側が 154 kV 以上の段飛ばし 22 か所。介入として登録し、Ybus・潮流の前後を測る。
2. ~~3 リポジトリの共通ライブラリ化~~ → **共通にはしない(オーナー判断 2026-10-07)**。各リポジトリがコアの写しを持つ。
   規則が黙って分かれないよう、移植元のコミットと差分を [STATION_NODE_BREAKER.md](../STATION_NODE_BREAKER.md) の「移植元との差分」に書き、
   規則の追加は互いにパッチで渡す(§8)。
3. **西島根の OSM の電圧タグ**を OSM 側で直すか(OSM への貢献)。

(番号 2 は判断済み。1 と 3 が残り)

## 8. 姉妹プロジェクトへの還元

- `internal_extension` を EU/AU にも当てられるパッチ:
  [station_layers_2026-10-07/internal_extension_for_sister_projects.patch](station_layers_2026-10-07/internal_extension_for_sister_projects.patch)
  (EU commit 9b4be87 と、EU の今の作業ツリーの両方に `git apply` で当たる。EU のテストは当てた後も全件通る)。既定 0 なので、当てても欧州の結果は変わらない。
- 欧州の 25 m の緩衝の妥当性は、`internal_way_without_unique_site` の柵からの距離の分布で確かめられる(`scripts/build_station_db.py` の `escape_distances`)。
- 50/60 Hz の扱いは日本固有。米国(60 Hz)で同じ規則を使うなら、`ac50` 固定を国の周波数に変える必要がある。

## 9. 再現

```bash
PYTHONPATH=. .venv/bin/python scripts/build_structures_batch.py --all          # 構造 DB(9 秒)
PYTHONPATH=. .venv/bin/python scripts/build_station_db.py --source-md5 <md5>   # 観測層(15 秒、PBF は data/stations/README.md)
PYTHONPATH=. .venv/bin/python scripts/compare_station_layers.py                # 突き合わせ
PYTHONPATH=. .venv/bin/python scripts/build_substation_properties.py && PYTHONPATH=. .venv/bin/python scripts/export_subsld_pages.py
.venv/bin/python -m pytest -q tests/test_stations_core.py tests/test_station_layers.py tests/test_substation_structures.py
```

入力: Geofabrik `japan-latest.osm.pbf`(md5 `99b99e4cda186567e435e37ab37618c6`、2026-10-06T20:21:06Z)。電力だけに絞ったものの SHA-256 は `data/stations/MANIFEST.json`。
