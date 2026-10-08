# 変電所の構内結線 DB(node-breaker 観測層)

OSM の **node ID** だけで母線・ベイ・開閉器・変圧器の巻線・線路の端を結んだ、変電所の中の台帳。
方法と規則は [docs/STATION_NODE_BREAKER.md](../../docs/STATION_NODE_BREAKER.md)。
SubSLD の構造 DB([data/structures](../structures/README.md))とは別の層で、ID は置き換えない。

## 作り方(約 15 秒)

```bash
# 1. 入力: Geofabrik の日本全体(2.5 GB)を電力だけに絞る(9 MB)。md5 を .md5 と照合する
curl -O https://download.geofabrik.de/asia/japan-latest.osm.pbf
curl -O https://download.geofabrik.de/asia/japan-latest.osm.pbf.md5 && md5 -r japan-latest.osm.pbf
osmium tags-filter japan-latest.osm.pbf nwr/power r/route=power -o data/osm_pbf/japan-power.osm.pbf

# 2. 行と summary(pyosmium が要る: uv pip install osmium、または pip install -e '.[stations]')
PYTHONPATH=. .venv/bin/python scripts/build_station_db.py --source-md5 <md5>

# 3. SubSLD の構造 DB と突き合わせる(先に scripts/build_structures_batch.py --all)
PYTHONPATH=. .venv/bin/python scripts/compare_station_layers.py
```

## ファイル

| ファイル | git | 内容 |
|---|---|---|
| `MANIFEST.json` | 追跡 | 入力 PBF の時点・SHA-256・元の md5・絞り込みの式・ライセンス・規則の版とパラメータ |
| `summary.json` | 追跡 | 件数・状態・課題・端子の根拠・ベイの機能・周波数の混在 |
| `japan_rows.json.gz` | 非追跡 | 行(levels / equipment / nodes / terminals / ends / circuits / members / issues)、派生の読み方(bays / binding / levels / pairs)、構造 DB との対応(crosswalk) |
| `read_cache.pkl` | 非追跡 | PBF の読み取りキャッシュ(PBF の md5 と敷地数が一致するときだけ使う) |

PBF は `data/osm_pbf/`(非追跡)。行は PBF から決定的に作り直せる D 層の生成物。

## 状態の読み方

`coverage` の状態は **記録の充実度** であって、実設備の網羅・開閉状態・定格の確認ではない。

| 状態 | 意味 |
|---|---|
| `lines_only` | 線路の端だけ。構内の配線も機器も描かれていない |
| `conductors_only` | 母線・ベイ・構内配線はあるが、開閉器・変圧器が無い |
| `layout_only` | 機器はあるが配線に載っていない |
| `partial` | 機器と配線はあるが、配線に載らない端子・未解決の機器がある |
| `mapped` | 記録された機器の端子がすべて接続点に載っている |
