#!/bin/bash
# でんき予報リアルタイムサイクル: 取得 → NOW断面PF → Pages更新(commit+push)
# 手動実行 or launchd/cron から30-60分間隔で呼ぶ。
# 蓄積はローカル data/realtime/(nas03再起動期間のため)。復帰後は
# scripts/sync_realtime_to_nas.sh で退避。
set -e
cd "$(dirname "$0")/.."
LOG=data/realtime/cycle.log
mkdir -p data/realtime
{
  echo "===== $(date '+%F %T') ====="
  python3 scripts/fetch_denkiyoho.py || { echo "fetch失敗(過半未達)"; exit 1; }
  # 燃料別実績(エリア需給実績・手法(a)): 前日+当日を取得(関西は当日配信の蓄積)
  python3 scripts/fetch_area_fuelmix.py || true
  python3 scripts/export_flow_map_data.py --realtime
  # 日付別断面: 前日分が未生成なら生成(1日1回だけ走る)
  YD=$(date -v-1d +%Y%m%d 2>/dev/null || date -d yesterday +%Y%m%d)
  if [ ! -f "docs/data/flow_map/days/${YD}.json" ]; then
    PYTHONPATH=. python3 scripts/export_day_flows.py --date "$YD" || true
  fi
  # 当日断面の増分更新(新しい実績時刻だけPF・既計算分は再利用)
  PYTHONPATH=. python3 scripts/export_day_flows.py --date "$(date +%Y%m%d)" || true
  python3 scripts/slim_flow_map.py || true
  # 並行アクター配慮: pull --rebase してから該当ファイルのみ commit
  git pull --rebase --autostash origin main >/dev/null 2>&1 || true
  git add docs/data/realtime/latest.json docs/data/flow_map/flows_now_*.geojson \
          docs/data/flow_map/gens_now_*.geojson docs/data/flow_map/now_meta.json \
          docs/data/flow_map/days/ 2>/dev/null
  if ! git diff --cached --quiet; then
    git commit -q -m "data(realtime): でんき予報スナップショット+NOW断面 $(date '+%F %H:%M')

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
    git push -q origin main
    echo "push済"
  else
    echo "変更なし"
  fi
} >> "$LOG" 2>&1
tail -3 "$LOG"
