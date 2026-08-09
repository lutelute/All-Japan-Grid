# data/dataspace — 源泉から畳んで持ってきた派生データ

`docs/DATA_SPACE.md` の zero-copy 原則にもとづき、**源泉（研究室 NAS 等）に留めた生データを
源泉側で集約し、その結果だけ**を置く場所。契約は `config/dataspace.yaml`、
取得の出所記録は `data/cache/dataspace/provenance.jsonl`。

生データは複製しない（`redistribute_raw: false`）。ここにあるのは
`redistribute_derived: true` の契約で許された派生物だけ。

## solar_by_area_{year}.csv — エリア別の時別日射

| | |
|---|---|
| 出典 | ERA5 再解析（Copernicus, CC-BY-4.0 相当）／ Open-Meteo 経由 |
| 源泉 | 研究室 pws-nas03 `/volume1/PWS_DB/openmeteo_raw`（152地点 × 3年 = 178MB） |
| 集約 | `scripts/dataspace/aggregate_solar_from_nas.py` を NAS マウント側で実行 |
| 粒度 | 10 エリア × 8,760 時間（1.2MB） |
| 契約 | `config/dataspace.yaml` の `nas03_era5_solar` |

列は `time` と、エリアごとの `{area}_ghi_wm2`（全天日射 W/m²）・`{area}_cf`。
`_cf` は `ghi / 1000`（STC 基準）の素朴な変換で、**PV の温度損失・傾斜・システム損失は
含まない**。実際の設備利用率はこれより低くなるので、使う側で係数を掛けること。
生の日射も残してあるのはそのため。

`solar_stations_{year}.csv` は地点 → エリアの割当監査表（緯度経度つき）。
割当は `docs/data/built/regions_bbox.json` による地理判定で、bbox が重なる場合は
領域中心が近い方を採る。

### 再生成

```bash
# NAS をマウントしたサーバー（pws-160core 等）へ送って実行
scp scripts/dataspace/aggregate_solar_from_nas.py docs/data/built/regions_bbox.json \
    pws-ubuntu-server@100.104.225.55:/tmp/
ssh pws-ubuntu-server@100.104.225.55 \
  'cd /tmp && python3 aggregate_solar_from_nas.py --bbox regions_bbox.json \
     --year 2025 --out solar_by_area_2025.csv --stations-out solar_stations_2025.csv'
scp pws-ubuntu-server@100.104.225.55:/tmp/solar_by_area_2025.csv data/dataspace/
```

### 検証済みの性質（2026-08-09）

- 日変化: 正午 581 W/m² をピークに夜間ゼロ（JST 整合）
- 季節: 全エリアで 7 月 > 1 月
- 緯度勾配: 北海道 152 → 沖縄 193 W/m²（年平均）
- 地点分布: 151 地点が 10 エリアすべてに配分（最少 hokuriku 7・最多 kyushu 24）

### 用途

潮流モデルの**発電機出力配分**の検証に使う。容量較正の結果、モデルの過負荷は
需要配分ではなく発電側か網の欠けに起因すると絞り込まれている
（`docs/reports/demand_validation_*.md`）。太陽光の時空間パターンを実況ベースで
与えられれば、そのうち発電側の寄与を切り分けられる。
