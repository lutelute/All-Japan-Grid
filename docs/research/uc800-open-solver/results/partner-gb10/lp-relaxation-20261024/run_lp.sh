#!/bin/bash
# LP relaxation on the GPU, one job at a time, one CPU thread. Usage: run_lp.sh <hours> <method...>
h=$1; shift
for m in "$@"; do
  name=t$h-m$m
  start=$(date +%s.%N)
  .venv/bin/cuopt_cli --relaxation --method $m --num-cpu-threads 1 --time-limit 900 \
    --log-file logs/$name.log --solution-file logs/$name.sol mps/n800-t$h.mps > logs/$name.out 2>&1
  rc=$?
  echo "$name exit=$rc wall_s=$(python3 -c "import time;print(round(time.time()-$start,1))")" >> logs/lp_done.txt
done
