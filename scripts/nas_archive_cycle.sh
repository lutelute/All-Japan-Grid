#!/bin/bash
# 公表データを nas03 の保管庫(PWS_DB)へ定期的に取って置く。pws-160core の cron から呼ぶ。
#
#   daily     OCCTO 系統情報サービスの一括ダウンロード(地内基幹・連系線の潮流実績など 10 種類)の当月分と、
#             OCCTO 公表 API(エリア需給 02・連系線 04)の当月分を取り直す
#             最後に保管庫の確認(scripts/nas_archive_check.py)を回し、occto_raw/_status.txt に書く
#   weekly    一般送配電 10 社の系統情報公表(潮流実績・インピーダンス・空容量・系統図など)を確かめ、
#             新しい公表を取る。中身が替わったファイルは前の版を _versions/ に残す。
#             OCCTO の一括ダウンロードは締まった直近 3 か月を取り直す(過去の値の改訂を拾う)
#   backfill  OCCTO の一括ダウンロードで、公開範囲のうち無い単位と覆い終えていない単位を古い順に取る
#             (MAX_UNITS で 1 種類あたりの上限。周波数は 1 日 1 単位なので夜ごとに少しずつ)
#   check     保管庫の確認だけ
#
# 取り溜めを減らさない決まり(2026-11-06): 同じ中身は書かない・行が減る応答では上書きしない・
# 過去の値が替わったら前の版を _versions/ に残す。どこまで覆ったかは occto_raw/{種類}/_manifest.json
#
# 置き場(既定 /mnt/nas03 = //10.0.70.189/PWS_DB):
#   occto_raw/{chinai_flow,interconnector_flow,...}/{YYYY}/  一括ダウンロードの CSV(cp932 のまま)
#   occto_raw/kohyo/                                         公表 API の月ごとの CSV
#   system_disclosure_raw/{社}/{種別}/                       各社の公表ファイル
#
# OCCTO は 2026-10-23 に「過度なアクセスはアクセス制限することがある」と告知している。
# 一括ダウンロードは 1 リクエストごとに 5 秒空ける(scripts/fetch_occtonet_bulk.py の --sleep)。
#
# 使い方: bash scripts/nas_archive_cycle.sh daily|weekly|backfill|check
set -u
cd "$(dirname "$0")/.."
NAS=${AGJ_NAS_ROOT:-/mnt/nas03}
OCCTO=$NAS/occto_raw
SD=$NAS/system_disclosure_raw
MODE=${1:-daily}

if [ ! -d "$OCCTO" ]; then
  echo "NAS が見えない: $OCCTO(nas03 のマウントを確かめる)" >&2
  exit 1
fi
echo "===== $(date '+%F %T %Z') $MODE ($(git rev-parse --short HEAD 2>/dev/null)) ====="

rc=0
case "$MODE" in
  daily)
    python3 scripts/fetch_occtonet_bulk.py --out "$OCCTO" --daily || rc=$?
    # 公表 API は約 17 か月で消える。毎日、当月を取り直す(月初の 3 日は前月も)
    D0=$(date +%Y-%m-01)
    if [ "$(date +%-d)" -le 3 ]; then D0=$(date -d "$D0 -1 month" +%F); fi
    python3 scripts/fetch_occto_kohyo.py --types 02 04 --from "$D0" --to "$(date +%F)" \
      --out-dir "$OCCTO/kohyo" || rc=$?
    python3 scripts/nas_archive_check.py --nas "$NAS" || rc=$?
    ;;
  weekly)
    AGJ_SYSTEM_DISCLOSURE="$SD" AGJ_SD_PROVENANCE="$SD/provenance.jsonl" AGJ_SD_KEEP_VERSIONS=1 \
      python3 -m scripts.fetch_system_disclosure || rc=$?
    python3 scripts/fetch_occtonet_bulk.py --out "$OCCTO" --revisit-months 3 || rc=$?
    ;;
  backfill)
    python3 scripts/fetch_occtonet_bulk.py --out "$OCCTO" --backfill --max-units "${MAX_UNITS:-150}" || rc=$?
    ;;
  check)
    python3 scripts/nas_archive_check.py --nas "$NAS" || rc=$?
    ;;
  *)
    echo "使い方: $0 daily|weekly|backfill|check" >&2
    exit 2
    ;;
esac
echo "===== 終了 $(date '+%F %T') rc=$rc ====="
exit $rc
