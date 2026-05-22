#!/usr/bin/env bash
# PDF を 5 MB 以下に圧縮するスクリプト
# 使い方: bash compress_pdf.sh [入力PDF] [出力PDF]
# 例:     bash compress_pdf.sh ieej.pdf ieej_compressed.pdf
set -euo pipefail

INPUT="${1:-ieej.pdf}"
OUTPUT="${2:-${INPUT%.pdf}_compressed.pdf}"
TARGET_KB=5000

if [[ ! -f "$INPUT" ]]; then
  echo "ERROR: $INPUT が見つかりません"; exit 1
fi

SIZE_KB=$(du -k "$INPUT" | awk '{print $1}')
echo "元サイズ: ${SIZE_KB} KB  →  目標: ${TARGET_KB} KB 以下"

if (( SIZE_KB <= TARGET_KB )); then
  echo "既に目標サイズ以下のためコピーのみ行います"
  cp "$INPUT" "$OUTPUT"
  exit 0
fi

# ---------- ghostscript で圧縮 ----------
compress_gs() {
  local quality="$1"
  gs -q -dNOPAUSE -dBATCH -dSAFER \
     -sDEVICE=pdfwrite \
     -dCompatibilityLevel=1.5 \
     -dPDFSETTINGS="/${quality}" \
     -dColorImageDownsampleType=/Bicubic \
     -dColorImageResolution=150 \
     -dGrayImageDownsampleType=/Bicubic \
     -dGrayImageResolution=150 \
     -dMonoImageDownsampleType=/Bicubic \
     -dMonoImageResolution=300 \
     -dEmbedAllFonts=true \
     -dSubsetFonts=true \
     -sOutputFile="$OUTPUT" \
     "$INPUT"
}

# まず screen (最小) → ebook → printer の順で試す
for q in ebook printer; do
  compress_gs "$q"
  OUT_KB=$(du -k "$OUTPUT" | awk '{print $1}')
  echo "  [$q] → ${OUT_KB} KB"
  if (( OUT_KB <= TARGET_KB )); then
    echo "成功: $OUTPUT (${OUT_KB} KB)"
    exit 0
  fi
done

# それでも超える場合は解像度をさらに下げる
gs -q -dNOPAUSE -dBATCH -dSAFER \
   -sDEVICE=pdfwrite \
   -dCompatibilityLevel=1.5 \
   -dPDFSETTINGS=/screen \
   -dColorImageResolution=96 \
   -dGrayImageResolution=96 \
   -dEmbedAllFonts=true \
   -dSubsetFonts=true \
   -sOutputFile="$OUTPUT" \
   "$INPUT"

OUT_KB=$(du -k "$OUTPUT" | awk '{print $1}')
echo "最終結果: $OUTPUT (${OUT_KB} KB)"

if (( OUT_KB > TARGET_KB )); then
  echo "WARNING: 目標 ${TARGET_KB} KB を超えています。図の解像度をさらに下げることを検討してください。"
fi
