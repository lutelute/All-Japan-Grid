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
  # 外部の公表データを最新に保つ(2026-10-21)。この毎時の処理の中で、日に 1 回・週に 1 回だけ走らせる。
  # 置き場は本体のチェックアウト(data/realtime は本体の data/realtime へのリンクなので、その親)
  STORE="$(cd -P data/realtime/.. && pwd -P)"   # -P: リンクを先に解決してから .. をたどる
  TODAY=$(date +%Y%m%d)
  # OCCTO 系統情報公表(エリア需要 02・連系線 04 の 30 分値)。API は約 14 か月しか残らないので、
  # 取り損ねた月は二度と取れない(2026-06 で止まっていた)。毎日、当月を取り直す。月初の 3 日は前月も
  if [ ! -f "data/realtime/.occto_kohyo_$TODAY" ]; then
    D0=$(date +%Y-%m-01); D1=$(date +%Y-%m-%d)
    if [ "$(date +%d)" -le 3 ]; then
      D0=$(date -v-1m +%Y-%m-01 2>/dev/null || date -d "$(date +%Y-%m-01) -1 month" +%Y-%m-%d)
    fi
    python3 scripts/fetch_occto_kohyo.py --from "$D0" --to "$D1" --out-dir "$STORE/external/occto" \
      && touch "data/realtime/.occto_kohyo_$TODAY" || echo "OCCTO 系統情報公表の取得に失敗(次の回に再試行)"
  fi
  # 各社の系統情報公表(潮流実績)。年 1 回の公表なので週 1 回確かめ、新しい公表があれば観測の表を作り直す。
  # 新しい観測の表は、この後の export_flow_map_data(観測との向きの照合)にそのまま入る
  WEEK=$(date +%G%V)
  if [ ! -f "data/realtime/.flow_actual_$WEEK" ]; then
    export AGJ_SYSTEM_DISCLOSURE="$STORE/external/system_disclosure"
    # 出所の記録は追跡しているファイルなので、本体の作業ツリーを汚さないよう git の外へ書く
    export AGJ_SD_PROVENANCE="$STORE/realtime/system_disclosure_provenance.jsonl"
    CH="data/realtime/.flow_actual_changed"
    # 終了コード 2 = 通信の失敗あり(取れた分の記録と --changed-file は書かれる)
    if python3 -m scripts.fetch_system_disclosure --kind flow_actual --changed-file "$CH" > data/realtime/flow_actual_fetch.log 2>&1; then
      FA_OK=1
    else
      FA_OK=0
    fi
    if [ -s "$CH" ]; then
      echo "潮流実績: 新しい公表 $(wc -l < "$CH" | tr -d ' ') ファイル → 観測の表を作り直す"
      python3 scripts/build_line_observations.py || echo "観測の表の作り直しに失敗"
      # 観測から作って公開している 2 つ(潮流マップの「観測と比べる」と地方系統の観測)も作り直す
      PYTHONPATH=. python3 scripts/export_obs_compare.py || echo "obs_compare の作り直しに失敗"
      PYTHONPATH=. python3 scripts/export_obs_local.py || echo "obs_local の作り直しに失敗"
      # 地点需要の表(介入#30・潮流のピン留め)も作り直す(2026-10-26)。それまでは 08-17 のままで、
      # その後に取った東北 FY2025 が入っていなかった。潮流の出力は重いのでここでは作り直さない。
      # 正典の版に記録した表と違えば、そのことを出す(作り直すのは regenerate_all)
      python3 scripts/parse_point_demand.py > data/realtime/point_demand_parse.log 2>&1 || echo "地点需要の表の作り直しに失敗"
      PYTHONPATH=. python3 -m scripts.check_point_demand_stamp || true
    fi
    if [ "$FA_OK" = 1 ]; then
      touch "data/realtime/.flow_actual_$WEEK"
    else
      # 取り直しは毎回全部を落とす(約 12 分)ので、同じ週は 3 回まで
      echo x >> "data/realtime/.try_flow_actual_$WEEK"
      if [ "$(wc -l < "data/realtime/.try_flow_actual_$WEEK")" -ge 3 ]; then
        touch "data/realtime/.flow_actual_$WEEK"
        echo "潮流実績: 通信の失敗が 3 回 → この週は見送る(data/realtime/flow_actual_fetch.log)"
      else
        echo "潮流実績: 通信の失敗あり(次の回に再試行・data/realtime/flow_actual_fetch.log)"
      fi
    fi
  fi
  # 変電所の構造 DB(data/structures・git の外)を基底の OSM から作る(約 5 秒・決定的)。潮流は変圧器の銘板の
  # 容量をここから読む。この worktree には無く、NOW 断面は銘板なし(推定の容量)で組まれていた(2026-10-25)
  PYTHONPATH=. python3 scripts/build_structures_batch.py --all > data/realtime/structures_build.log 2>&1 \
    || echo "構造 DB の作成に失敗(data/realtime/structures_build.log)"
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
