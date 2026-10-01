#!/bin/bash
# 国土数値情報 (A40 津波浸水想定 / N03 行政区域) を external/ に取得する。3並列・リトライ付き。
# usage: bash fetch_ksj.sh   (既存ファイルはスキップ)
set -u
HERE=$(cd "$(dirname "$0")" && pwd); EXT="$HERE/../external"; mkdir -p "$EXT/ksj_A40" "$EXT/ksj_N03"
dl() { # <subdir> <url>
  local sub=$1 url=$2 f out code rc; f=$(basename "$url"); out="$EXT/$sub/$f"
  if [ -s "$out" ]; then echo "SKIP $f"; return 0; fi
  code=$(curl -sS -L -f --retry 5 --retry-delay 8 --retry-all-errors --max-time 2400 \
        -A "Mozilla/5.0 (AGJ-nankai-hazard fetch)" -o "$out.part" -w "%{http_code}" "$url"); rc=$?
  if [ $rc -eq 0 ] && [ "$code" = "200" ] && [ -s "$out.part" ]; then mv "$out.part" "$out"; echo "OK   $f $(stat -f%z "$out" 2>/dev/null || stat -c%s "$out")B"
  else rm -f "$out.part"; echo "FAIL $f rc=$rc http=$code"; fi
}
export -f dl; export EXT
grep -v '^#' "$HERE/ksj_urls.txt" | xargs -P 3 -L 1 bash -c 'dl "$0" "$1"'
