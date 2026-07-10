#!/bin/bash
# 全島24h検証(新既定=#19/#20/#21 ON・フラグ無し)。v1.6.0出荷前の96断面確認。
# 島ごとにプロセス隔離(BLAS abort対策)。07-09の検証は#21エッジdedup前だったため再検証する。
set -u
cd /Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid
OUT=docs/reports/probes/default_on_2026-07-10/allisland24h
mkdir -p "$OUT"

for isl in okinawa hokkaido east west; do
  echo "===BEGIN $isl $(date +%H:%M:%S)==="
  PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py \
    --islands "$isl" --all-hours \
    --out "$OUT/${isl}.json" > "$OUT/${isl}.log" 2>&1
  echo "===END $isl EXIT=$? $(date +%H:%M:%S)==="
done
echo "===ALL DONE $(date +%H:%M:%S)==="
