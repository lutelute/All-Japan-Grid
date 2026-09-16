#!/bin/zsh
# run_v8: UFLS の段階的な再送電を入れた動的カスケード。シナリオ卓の 12 通り(西 4・東 8)を順に回す。途中で止まっても済んだものは飛ばす。
#   zsh hazard/nankai/scripts/run_v8_batch.sh [workers]
set -u
cd "$(dirname "$0")/.." || exit 1
export OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 PYTHONPATH=src:scripts
W=${1:-8}
TB='tsunami_exclude_boxes.value=[[35.28, 35.80, 139.60, 140.20]]'
NOTR='grid_overrides.tepco_transformer_capacity.enabled=false'
NOOL='relays.overload_enabled=false'
run() { local out=$1; shift; local isl=()
  while [[ $# -gt 0 && $1 != --set ]]; do [[ $1 != --islands ]] && isl+=($1); shift; done
  local todo=()
  for i in $isl; do [[ -f output/$out/$i/dyn_summary.csv ]] || todo+=($i); done
  if [[ ${#todo} -eq 0 ]]; then echo "== $out: done already"; return; fi
  echo "== $out --islands $todo $*"
  python3 scripts/run_dynamic.py --samples 200 --workers $W --islands $todo --out output/$out "$@" >> output/$out.log 2>&1 || echo "FAIL $out"
  grep -h "done" output/$out.log; }
run run_v8            --islands west east
run run_v8_nool       --islands west east --set $NOOL
run grid8_ol1_tr0_tb1 --islands west east --set $NOTR
run grid8_ol0_tr0_tb1 --islands west east --set $NOOL $NOTR
run grid8_ol1_tr1_tb0 --islands east --set "$TB"
run grid8_ol0_tr1_tb0 --islands east --set $NOOL "$TB"
run grid8_ol1_tr0_tb0 --islands east --set $NOTR "$TB"
run grid8_ol0_tr0_tb0 --islands east --set $NOOL $NOTR "$TB"
echo V8DONE
