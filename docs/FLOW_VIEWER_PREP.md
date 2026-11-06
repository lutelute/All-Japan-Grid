# 潮流ビューアーの下ごしらえ（2026-11-06）

OCCTO の潮流実績（地内基幹送電線 30 分値・連系線 5 分値）を、AGJ の地図の上で時刻を動かして見るビューアーを作るための準備。
**研究室の中で使う**（公開はまだ考えていない。生値は再配布しない。OCCTO の利用条件も未確認）。

## そろっているもの

| もの | 置き場 | 中身 |
|---|---|---|
| 潮流の値 | 統合 DB `/mnt/nas03/db/pws.duckdb` の `occto_line_flow_30min`・`occto_interconnector_5min` | 2025-04-01〜、毎朝増える（取得は [NAS_ARCHIVE.md](NAS_ARCHIVE.md)） |
| 運用容量 | 同 `occto_line_capacity_daily` | 線路×日の運用容量と決定要因（熱容量・安定度・電圧）。負荷率の分母 |
| 線路 → モデルの線 | 同 `occto_line_model_keys`（`scripts/build_occto_line_crosswalk.py`） | OCCTO の線路ごとに、AGJ のモデルの線の鍵・向き・回線数・照合の確からしさ（A/B/C） |
| 線の形 | `docs/data/flow_map/flows_now_*.geojson`（AGJ の潮流マップ） | モデルの線の鍵 `k` ごとの LineString。照合で使った鍵 507 本はすべてここにある |

1 回の SQL で「時刻 × モデルの線の鍵 × 潮流」が出る:

```sql
SELECT f.dt, k.model_key, f.flow_MW * k.sign AS flow_along_model_MW, k.conf
FROM occto_line_flow_30min f
JOIN occto_line_model_keys k USING (area, line, direction)
WHERE f.dt = TIMESTAMP '2026-11-05 18:00' AND k.model_key IS NOT NULL;
```

`sign` は +1 ならモデルの線の from→to が OCCTO の正方向と同じ。平行線をまとめたモデルの線は `circuits` で按分する。

## 照合の現状

OCCTO の地内基幹送電線 467 本のうち 327 本（70%）をモデルの線につないだ。

| エリア | 本数 | A（名前と両端） | B（両端のみ） | C（片端と線名） | 未照合 |
|---|---|---|---|---|---|
| 北海道 | 40 | 27 | 3 | 6 | 4 |
| 東北 | 35 | 25 | 3 | 0 | 7 |
| 東京 | 88 | 51 | 10 | 8 | 19 |
| 中部 | 81 | 27 | 10 | 8 | 36 |
| 北陸 | 11 | 6 | 0 | 0 | 5 |
| 関西 | 54 | 23 | 17 | 3 | 11 |
| 中国 | 31 | 18 | 2 | 1 | 10 |
| 四国 | 25 | 19 | 5 | 0 | 1 |
| 九州 | 71 | 17 | 26 | 10 | 18 |
| 沖縄 | 31 | 0 | 2 | 0 | 29 |

照合のやり方は各社の潮流実績で使っているもの（`scripts/export_obs_compare.py` の `match_all`）と同じ。
OCCTO の向きの欄の書き方（「北新得SS」「日野（変）」「三重」）を変電所名にそろえてから解決した。

**確からしさの確かめ**（照合とは別の根拠）: 同じモデルの線に OCCTO の線路と各社の潮流実績（2024 年度）の両方がつながった
155 組で、潮流の大きさ（絶対値の 95 パーセンタイル）の比 OCCTO ÷ 各社 は中央値 0.99（A 0.99・B 0.98・C 0.95）、
0.5〜2 倍に入るのは 147/154 組。外れは東京の東毛線（モデルの線を新坂戸線と共有）など、モデル側で別の線とまとまっているもの。
期間が違う（OCCTO は 2025-04〜06 と 2026-01〜、各社は 2024 年度）ので、同時刻の一致ではなく規模の一致。

未照合の主な理由: 沖縄（132 kV の母線がモデルに無い・変電所名が引けない）、中部（同じ電圧の経路が見つからない 22 本・
その電圧の母線が無い 11 本）、分岐点（「571T(西南多摩線)」「山陰幹線」のように端が鉄塔や線になっているもの）。

## 作り直すとき

モデルの正典（`docs/data/built/all.json`）を作り直すと線の鍵が替わる。台帳の `built_sha256` が今の正典と違ったら作り直す:

```bash
PYTHONPATH=. python3 scripts/build_occto_line_crosswalk.py --db /mnt/nas03/db/pws.duckdb \
    --parquet /mnt/nas03/db/parquet/occto_line_model_keys.parquet
```

（`/mnt/nas03` の見えないところでは、`occto_lines` を CSV にして `--lines` で渡し、Parquet を 160core で置く）

## ビューアーで決めること

- どこで動かすか（研究室の中だけ。OptiPlex の nginx の裏か、160core か。DuckDB は CIFS 越しに読める）
- 何を色にするか（潮流の大きさ／運用容量に対する負荷率／向き）。運用容量は線路名と日でつなぐ（`occto_line_capacity_daily`、1 日に 2〜4 行ある線は向きで選ぶ）
- 連系線（`occto_interconnector_5min`）を同じ地図に載せるか。運用容量・マージン・空容量・計画潮流もある
- 各社の潮流実績（ローカル系統まで、1 時間値、`system_disclosure_raw/*/flow_actual`）も重ねるか。これは統合 DB にまだ入っていない
- 期間は 2025-04-01 以降しかない（OCCTO の公開範囲）
