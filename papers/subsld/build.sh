#!/usr/bin/env bash
# SubSLD論文ビルド (IEEEtran / pdflatex)
set -euo pipefail
cd "$(dirname "$0")"
TEX=subsld
for i in 1 2 3; do
  pdflatex -interaction=nonstopmode ${TEX}.tex > /dev/null 2>&1 || {
    echo "ERROR pass $i"; pdflatex -interaction=nonstopmode ${TEX}.tex 2>&1 | tail -25; exit 1; }
done
PAGES=$(grep -oE 'Output written.*\(([0-9]+) page' ${TEX}.log | grep -oE '[0-9]+ page' | grep -oE '[0-9]+' || echo "?")
echo "Done: ${PAGES} pages -> ${TEX}.pdf ($(du -k ${TEX}.pdf | awk '{print $1}') KB)"
