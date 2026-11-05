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

各フォルダの README.md と NAS の目録（`_catalog/datasets.toml` → `README.md`・`index.html`）に同じ説明がある。

## いつ・どこで回るか

pws-160core の cron（UTC 表記）。コードは `~/agj-archive`（このリポジトリの疎なクローン: scripts・config・src）。

| cron の印 | JST | 内容 |
|---|---|---|
| `agj_archive_daily` | 毎日 06:10 | `nas_archive_cycle.sh daily`: OCCTO の当月（月初 5 日は前月も）を取り直す。周波数は直近 3 日 |
| `agj_archive_backfill` | 毎日 01:00 | `nas_archive_cycle.sh backfill`（`MAX_UNITS=300`）: 欠けている単位を古い順に。周波数（2016-04〜、1 日 1 単位）はこれで約 2 週間かけてそろう |
| `agj_archive_weekly` | 日曜 05:30 | `nas_archive_cycle.sh weekly`: 10 社の公表を確かめ、新しい・替わったファイルを取る |

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
