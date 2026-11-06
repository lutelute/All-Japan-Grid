# 公表データの保管庫（nas03）運用メモ

OCCTO と一般送配電 10 社の公表データを、研究室の NAS（pws-nas03 の `PWS_DB`）へ定期的に取って置く仕組み。
公開期間が短いもの（OCCTO の潮流実績は 2025-04-01 以降しか出ていない）を取りこぼさないことと、
Mac の毎時の処理（`scripts/realtime_cycle.sh`、スリープ中は止まる）に頼らないことが目的（2026-11-05 から）。

## 何をどこへ

| 置き場（`/mnt/nas03/` = `//10.0.70.189/PWS_DB`） | 中身 | 取り方 |
|---|---|---|
| `occto_raw/chinai_flow/` ほか 9 種類 | OCCTO 系統情報サービスの情報ダウンロード（地内基幹送電線・連系線の潮流実績、運用容量の実績、需要実績、作業停止、故障、周波数、再エネ出力抑制、連系線空容量） | `scripts/fetch_occtonet_bulk.py` |
| `occto_raw/kohyo/` | 広域予備率Web公表システムのエリア需給（02）・連系線（04） | `scripts/fetch_occto_kohyo.py` |
| `system_disclosure_raw/{社}/{種別}/` | 10 社の系統情報公表（潮流実績・インピーダンス・空容量・系統図） | `scripts/fetch_system_disclosure.py`（`AGJ_SD_KEEP_VERSIONS=1` で前の版を `_versions/` に残す） |
| `db/parquet/occto_*`（統合 DB `pws.duckdb` の表） | 地内基幹の潮流 `occto_line_flow_30min`・連系線 `occto_interconnector_5min`・運用容量の実績 `occto_line_capacity_daily`、線路の一覧のビュー `occto_lines` | DB整理 `etl/db_sources.py`（nas03-agent の日次ビルド、JST 08:00） |

各フォルダの README.md と NAS の目録（`_catalog/datasets.toml` → `README.md`・`index.html`）に同じ説明がある。

統合 DB は研究室の中で使う（公開はまだ考えていない。生値の再配布はしない）。読み方:

```python
import duckdb
con = duckdb.connect("/mnt/nas03/db/pws.duckdb", read_only=True)
con.sql("SELECT dt, line, direction, flow_MW FROM occto_line_flow_30min WHERE line = '狩勝幹線' ORDER BY dt")
```

## いつ・どこで回るか

pws-160core の cron（UTC 表記）。コードは `~/agj-archive`（このリポジトリの疎なクローン: scripts・config・src）。

| cron の印 | JST | 内容 |
|---|---|---|
| `agj_archive_daily` | 毎日 06:10 | `nas_archive_cycle.sh daily`: OCCTO の当月（月初 5 日は前月も）を取り直す。周波数は直近 3 日。最後に保管庫の確認 |
| `agj_archive_backfill` | 毎日 01:00 | `nas_archive_cycle.sh backfill`（`MAX_UNITS=300`）: 無い単位と覆い終えていない単位を古い順に。周波数（2016-04〜、1 日 1 単位）はこれで約 2 週間かけてそろう |
| `agj_archive_weekly` | 日曜 05:30 | `nas_archive_cycle.sh weekly`: 10 社の公表を確かめ、新しい・替わったファイルを取る。OCCTO は締まった直近 3 か月を取り直す |

ログは `~/data_pipeline/logs/agj_archive_{daily,backfill,weekly}.log`。crontab の控えは `~/data_pipeline/crontab.bak-20261105-agj-archive`。

コードを新しくするとき: `cd ~/agj-archive && git fetch -q origin main && git checkout -q --detach origin/main`
（cron は今あるチェックアウトをそのまま使い、自動では更新しない）。

## OCCTO の情報ダウンロードの手順（ブラウザなし）

画面「公表 > ダウンロード情報 > CSVダウンロード > 情報ダウンロード」（CF01S010C）。

1. `GET LOGIN_login` → `POST` 画面（公開利用者のセッション。入口を飛ばすと以後「タイムアウトが発生しました」で弾かれる）
2. `POST actionSubType=initDisplay` → 公開範囲（`…Kkn` の欄。例 `(2025/04/01〜2026/11/05)`）と年の選択肢
3. `POST actionSubType=ok`（種類・期間・全エリアを入れる）→ `downloadKey` と `requestToken`
4. `POST actionSubType=download` → CSV（cp932）

期間を指定できる種類は 1 か月を 1 回で取れる（地内基幹の潮流実績で 1 か月 3.4 MB、連系線で 8.4 MB）。
OCCTO は 2026-10-23 に「過度なアクセスはアクセス制限することがある」と告知しているので、1 リクエストごとに 5 秒空ける。
**利用条件（定期取得の可否）は未確認**（2026-11-05、オーナー判断で先に取得を始めた）。

## 公開範囲（2026-11-05 に画面で確認）

| 種類 | 公開範囲 |
|---|---|
| 地内基幹送電線潮流実績・運用容量の実績・連系線潮流実績 | 2025-04-01〜 |
| 需要実績 日別 | 2024-04-01〜 |
| 連系線空容量（翌日） | 2016-06-02〜 |
| 作業停止計画・実績 | 2016-03-19〜 |
| 故障情報 | 2016-07-29〜2026-08-07 |
| 周波数（50Hz・60Hz） | 2016-04-07〜 |
| 再エネ出力抑制実績 | 2015-05〜 |

`python3 scripts/fetch_occtonet_bulk.py --list` でいまの公開範囲が出る。

## 取り溜めを続けるための決まり（2026-11-06）

OCCTO の公開範囲は動く（潮流実績は 2025-04-01 以降。年度が替わると古い年度から消えるとみている）。
保管庫は一度取った行を減らさないことを第一にする。

- **上書きの決まり**（`fetch_occtonet_bulk.py` の `save()`、公表 API は `fetch_occto_kohyo.py` の `fetch()`）
  - 中身が同じなら書かない。更新時刻も変えないので、統合 DB の作り直しも起きない
  - 今あるファイルより行が減る応答では上書きしない。応答は `{種類}/_versions/{名前}.shorter.csv` に置き、ログに残す
  - 行の数が同じで中身が違う（過去の値の改訂）ときは、前の版を `{種類}/_versions/{名前}.{日付}.csv` に残す
- **覆い終えたかの台帳** `occto_raw/{種類}/_manifest.json`: 単位（月・日）ごとに、どの日まで覆ったか（`to`）。
  当日分は途中までしか出ていないので、`to` は「取った日の前日」までにする。
  160core が月末に止まって前月が途中のまま残ったときや、公開範囲が後から延びたとき（故障情報は公開の終わりが今日より前）は、
  夜の backfill が `to` の届いていない単位を取り直す。台帳ができる前に取ったファイルは「取った日の前日まで」とみなした（2026-11-06）
- **改訂の拾い直し**: 週次で締まった直近 3 か月を取り直す（`--revisit-months 3`）。変わっていなければ書かない
- **見張り** `scripts/nas_archive_check.py`（日次の最後）: 各種類がどの日まで覆ったか・CSV の見出しが替わっていないか・
  最新の月が統合 DB に入ったか・公表 API と 10 社の最新・NAS の空きを見て、`occto_raw/_status.txt` と `_status.json` に書く。
  NG があれば日次の終了コードが 1 になる（ログの `rc=1`）。研究室のサーバーに通知の仕組みが無いので、外へは知らせない
- **統合 DB**: Parquet は月ごとに作り、原本の CSV が無くなっても消さない（`db_build.py` は無い月を消さない）。
  列は固定してあるので、OCCTO が列を足しても月ごとの Parquet の列はそろう（増えた列は入らない。見張りの「書式」が NG になったら直す）
- **バックアップ**: nas03 → nas04 の写し（`PWSlab-server-env/servers/pws-nas04/spec.md`）は 2026-11-06 時点で**未配備**。
  それまでは nas03 の RAID10 だけで、誤削除や NAS の故障からは守れない

