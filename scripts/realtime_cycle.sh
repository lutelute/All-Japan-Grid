#!/bin/bash
# でんき予報リアルタイムサイクル: 取得 → NOW断面PF → Pages更新(realtime_publish.sh が main へ公開)
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
  # 表紙・埋め込み用の軽い断面(docs/pulse.html・docs/js/pulse.js が読む)。失敗しても公開は続ける
  python3 scripts/export_pulse.py || true
  # 公開は main 専用の疎な worktree 経由(scripts/realtime_publish.sh)。作業ツリーがどのブランチに
  # あっても origin/main へ出る。ここで commit/pull --rebase をすると、feature ブランチに commit が
  # 積もるだけで Pages には出ない(2026-09-12〜21 に実際に9日間止まった)。
  bash scripts/realtime_publish.sh
} >> "$LOG" 2>&1
tail -3 "$LOG"
