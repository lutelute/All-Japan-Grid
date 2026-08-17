#!/bin/bash
# ローカル蓄積(data/realtime/)を pws-nas03 のAGJ領域へ退避する。
# nas03再起動期間(2026-08-19〜20頃)後に実行。マウント方式はFinderのSMB
# (smb://pws-nas03.local)を想定し、マウントポイントを引数で指定可能。
# 使い方: scripts/sync_realtime_to_nas.sh [/Volumes/<share>/AGJ/realtime]
set -e
cd "$(dirname "$0")/.."
DEST="${1:-/Volumes/LaboData/AGJ/realtime}"
if [ ! -d "$(dirname "$DEST")" ]; then
  echo "NG: $(dirname "$DEST") が見えません。nas03をマウントしてから再実行してください"
  echo "    (Finder → 移動 → サーバへ接続 → smb://pws-nas03.local)"
  exit 1
fi
mkdir -p "$DEST"
rsync -av --ignore-existing data/realtime/ "$DEST/"
echo "同期完了: data/realtime/ → $DEST (ローカルは残置=一次コピー)"
