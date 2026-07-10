#!/bin/bash
# 介入#19/#20/#21 既定ON化の判断パッケージ用プローブ (2026-07-10)
# 4島 × {old=従来既定(全OFF), new=新既定(#19/#20/#21 ON)} を各々独立プロセスで実行。
# 判定はシェルが OK/FAIL を出す(ハマり対策: 「収束」≠「正しく解けた」→ summary.json の
# served_frac / converged を後段の compare.py が機械照合する)。
set -u
cd "$(dirname "$0")/../../../.."   # → リポジトリルート
PROBE=docs/reports/probes/default_on_2026-07-10

for island in hokkaido east west okinawa; do
  for mode in old new; do
    out="$PROBE/$mode/$island"
    mkdir -p "$out"
    if [ "$mode" = "old" ]; then
      flags="--no-pref-demand --no-reactive-comp --no-dedup-nodes"
    else
      flags=""   # 新既定 = フラグ無し
    fi
    echo "=== [$island/$mode] flags='$flags' $(date +%H:%M:%S) ==="
    PYTHONPATH=. .venv/bin/python scripts/run_full_powerflow_from_db.py \
      --islands "$island" --output-dir "$out" $flags \
      > "$out/stdout.log" 2>&1
    rc=$?
    if [ $rc -eq 0 ] && [ -f "$out/summary.json" ]; then
      echo "OK [$island/$mode]"
    else
      echo "FAIL [$island/$mode] rc=$rc (log: $out/stdout.log)"
    fi
  done
done
echo "=== probe done $(date +%H:%M:%S) ==="
