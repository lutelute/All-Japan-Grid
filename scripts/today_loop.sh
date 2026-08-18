#!/bin/bash
# 今日だけの1時間毎更新ループ(プレゼン用・2026-08-18限定)
# 停止: pkill -f today_loop.sh / 日付が変わったら自動終了
cd "$(dirname "$0")/.."
TODAY=$(date +%Y%m%d)
while [ "$(date +%Y%m%d)" = "$TODAY" ]; do
  bash scripts/realtime_cycle.sh || true
  sleep 3600
done
echo "$(date): 日付が変わったためループ終了" >> data/realtime/cycle.log
