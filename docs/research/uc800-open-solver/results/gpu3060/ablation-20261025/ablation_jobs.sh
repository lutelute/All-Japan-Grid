#!/bin/bash
# Technique ablation: same instance, one technique changed, HiGHS/SCIP 1 thread 300 s, 8 at a time.
# Usage: ablation_jobs.sh <python> <frontier cells dir with *.solution.json.gz>
PY=$1; BEST=$2
mkdir -p runs logs
{
for inst in "100 48" "200 48" "800 24"; do
  set -- $inst; n=$1; h=$2; base="n$n-t$h"
  echo "$base default HiGHS"
  echo "$base seed1 HiGHS --highs-option random_seed=1"
  echo "$base seed2 HiGHS --highs-option random_seed=2"
  echo "$base presolve-off HiGHS --highs-option presolve=off"
  echo "$base heuristic-0.3 HiGHS --highs-option mip_heuristic_effort=0.3"
  echo "$base no-symmetry HiGHS --highs-option mip_detect_symmetry=false"
  echo "$base no-restart HiGHS --highs-option mip_allow_restart=false"
  echo "$base lp-ipm HiGHS --highs-option mip_lp_solver=ipm"
  echo "$base start-rolling HiGHS --warm-start rolling --rolling-time-limit 120 --rolling-gap 0.02"
  echo "$base start-best HiGHS --warm-start file --warm-start-file $BEST/$base-strong.solution.json.gz"
done
echo "n100-t48 scip-default SCIP"
echo "n100-t48 scip-presolve-off SCIP --scip-param presolving/maxrounds=0"
echo "n100-t48 scip-start-rolling SCIP --warm-start rolling --rolling-time-limit 120 --rolling-gap 0.02"
} | xargs -P 8 -L 1 bash -c '
  inst=$0; tech=$1; solver=$2; shift 2
  n=${inst#n}; n=${n%%-*}; h=${inst##*-t}; name=$inst-$tech
  start=$(date +%s)
  taskset -c 0-15 timeout 1500 '"$PY"' -W ignore -m scripts.uc_open_solver_benchmark --units $n --hours $h --solver $solver \
    --time-limit 300 --gap 0.001 --threads 1 --strengthen startup_type "$@" --out runs/$name.json > logs/$name.out 2>&1
  echo "$name exit=$? wall=$(( $(date +%s) - start ))" >> runs/done.txt
'
echo all-done >> runs/done.txt
