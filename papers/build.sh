#!/usr/bin/env bash
# IEEJ論文ビルドスクリプト
# 使い方: bash build.sh [--compress]
# --compress: 投稿用 5MB 圧縮版 ieej_submit.pdf も生成
set -euo pipefail
cd "$(dirname "$0")"

TEX=ieej
PASSES=${PASSES:-3}   # 参照解決のため3パス

echo "=== Build: ${TEX}.tex (${PASSES} passes) ==="
for i in $(seq 1 $PASSES); do
  echo "  Pass $i..."
  uplatex -interaction=nonstopmode ${TEX}.tex > /dev/null 2>&1 || {
    echo "ERROR: uplatex failed on pass $i"
    uplatex -interaction=nonstopmode ${TEX}.tex 2>&1 | tail -20
    exit 1
  }
done

echo "  dvipdfmx..."
dvipdfmx ${TEX}.dvi > /dev/null 2>&1

PAGES=$(grep "Output written" ${TEX}.log 2>/dev/null | grep -oE '[0-9]+ page' | grep -oE '[0-9]+' || echo "?")
SIZE_KB=$(du -k ${TEX}.pdf | awk '{print $1}')
echo "  Done: ${PAGES} pages, ${SIZE_KB} KB → ${TEX}.pdf"

# 圧縮オプション
if [[ "${1:-}" == "--compress" ]]; then
  echo "  Compressing → ${TEX}_submit.pdf ..."
  bash compress_pdf.sh ${TEX}.pdf ${TEX}_submit.pdf
fi
