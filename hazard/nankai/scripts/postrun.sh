#!/usr/bin/env bash
# 本計算(run_pipeline.py)の後処理を一括で行う: 内閣府比較・原因分解・公開地図HTML・1手ずつビューア・動画・図の docs/reports へのコピー
#   bash hazard/nankai/scripts/postrun.sh <run_dir> <docs_fig_dir> [gmpe_run_dir]
set -euo pipefail
RUN=$1; DOCS=$2; GMPE=${3:-}
ROOT=$(cd "$(dirname "$0")/../../.." && pwd); cd "$ROOT"
export PYTHONPATH=hazard/nankai/src
python3 hazard/nankai/scripts/compare_naikakufu.py "$RUN" | tail -4
python3 hazard/nankai/scripts/decompose_causes.py --samples 30 --out "$RUN" | tail -3
[ -n "$GMPE" ] && python3 hazard/nankai/scripts/compare_naikakufu.py "$GMPE" | tail -1
mkdir -p "$DOCS"
python3 hazard/nankai/scripts/build_artifact.py "$RUN" "$DOCS/hazard_map_artifact.html"
python3 hazard/nankai/scripts/build_steps_viewer.py "$DOCS/steps_viewer.html" --island west --seed 7
python3 hazard/nankai/scripts/make_video.py "$RUN" "$DOCS/nankai_hazard_walkthrough.mp4" --island west --seed 7 | tail -1
for isl in west east; do
  for f in hazard pout_t0 pout_t1 pout_t7 pout_t30 expected_days potential potential_immediate curve restoration.gif timeline_summary.csv municipalities.csv; do
    src="$RUN/$isl/$f"; [ -f "$src" ] || src="$RUN/$isl/$f.png"; [ -f "$src" ] || continue
    ext="${src##*.}"; base="${f%.*}"; cp "$src" "$DOCS/${base}_${isl}.${ext}"
  done
done
cp "$RUN/naikakufu_compare.png" "$DOCS/naikakufu_compare_jshis.png"; cp "$RUN/naikakufu_compare.md" "$DOCS/naikakufu_compare_jshis.md"; cp "$RUN/naikakufu_compare.json" "$DOCS/naikakufu_compare_jshis.json"
cp "$RUN/cause_decomposition.png" "$DOCS/cause_decomposition_jshis.png"; cp "$RUN/cause_decomposition.csv" "$DOCS/cause_decomposition_jshis.csv"; cp "$RUN/summary.json" "$DOCS/summary_jshis.json"
[ -n "$GMPE" ] && { cp "$GMPE/naikakufu_compare.png" "$DOCS/naikakufu_compare_gmpe.png"; cp "$GMPE/naikakufu_compare.json" "$DOCS/naikakufu_compare_gmpe.json"; cp "$GMPE/summary.json" "$DOCS/summary_gmpe.json"; cp "$GMPE/west/hazard.png" "$DOCS/hazard_west_gmpe.png"; }
echo "postrun done -> $DOCS"
