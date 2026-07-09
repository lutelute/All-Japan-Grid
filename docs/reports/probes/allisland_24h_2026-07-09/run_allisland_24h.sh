#!/bin/bash
# 全島24h検証: --pref-demand --reactive-comp
# 島ごとにプロセス隔離(ハマり⑨ BLAS abort対策)。各島 --all-hours を独立プロセスで。
set -u
cd /Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid
OUT=/private/tmp/claude-501/-Users-shigenoburyuto-Documents-GitHub-project-Hayashi-All-Japan-Grid/78bb2546-5e61-4e06-97de-a53fe1953ee0/scratchpad/allisland24h
mkdir -p "$OUT"

for isl in okinawa hokkaido east west; do
  echo "===BEGIN $isl $(date +%H:%M:%S)==="
  PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py \
    --islands "$isl" --all-hours --pref-demand --reactive-comp \
    --out "$OUT/${isl}.json" > "$OUT/${isl}.log" 2>&1
  echo "===END $isl EXIT=$? $(date +%H:%M:%S)==="
done
echo "===ALL DONE $(date +%H:%M:%S)==="
