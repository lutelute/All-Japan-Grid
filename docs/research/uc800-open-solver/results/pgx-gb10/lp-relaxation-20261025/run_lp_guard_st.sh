#!/bin/bash
# GPU LP relaxation with a host-memory guard (GB10 unified memory is not capped by the container limit).
# Usage: run_lp_guard.sh <hours> <min_available_gib> <method...>
h=$1; min_gib=$2; shift 2
for m in "$@"; do
  name=t$h-st-m$m
  start=$(date +%s)
  .venv/bin/cuopt_cli --relaxation --method $m --num-cpu-threads 1 --time-limit 900 \
    --log-file logs/$name.log --solution-file logs/$name.sol mps/n800-t$h-startup_type.mps > logs/$name.out 2>&1 &
  pid=$!; low=999; stop=""
  while kill -0 $pid 2>/dev/null; do
    avail=$(awk "/MemAvailable/{printf \"%d\", \$2/1048576}" /proc/meminfo)
    [ $avail -lt $low ] && low=$avail
    if [ $avail -lt $min_gib ]; then kill -TERM $pid; stop=" stopped_by_memory_guard"; fi
    sleep 1
  done
  wait $pid; rc=$?
  echo "$name exit=$rc wall_s=$(( $(date +%s) - start )) min_available_gib=$low$stop" >> logs/lp_done.txt
done
