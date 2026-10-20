#!/bin/bash
# リアルタイム断面を、作業ツリーのブランチに関係なく origin/main へ公開する。
#
# なぜ要るか(2026-09-21): realtime_cycle.sh は「いまチェックアウト中のブランチ」に commit して
# `git push origin main` していた。作業ツリーが feature ブランチにある間、commit はそのブランチに
# 積もり、push されるのは動いていないローカル main なので、Pages の NOW 断面が 9/12 から 9 日間
# 止まっていた(誰も気づかなかった)。さらに `git pull --rebase origin main` が feature ブランチを
# main へ rebase しようとする副作用もあった。
#
# ここでは main 専用の疎な worktree(公開対象のパスだけ展開・数十MB)を data/realtime/.publish に
# 持ち、生成物をそこへコピーして commit → origin main へ push する。作業ツリーの HEAD は触らない。
#
#   scripts/realtime_publish.sh            # 公開する
#   AGJ_REALTIME_NO_PUSH=1 scripts/realtime_publish.sh   # commit まで(push しない・動作確認用)
#   AGJ_REALTIME_SRC=/path/to/tree scripts/realtime_publish.sh   # 生成物を別の作業ツリーから拾う
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUB="$ROOT/data/realtime/.publish"           # data/realtime/ は .gitignore 済み
SRC="${AGJ_REALTIME_SRC:-$ROOT}"             # 生成物のある作業ツリー(既定は自分自身)
PATHS=(docs/data/realtime docs/data/flow_map)

cd "$ROOT"
git fetch -q origin main

if [ ! -e "$PUB/.git" ]; then
  git worktree prune
  mkdir -p "$(dirname "$PUB")"
  git worktree add -q --no-checkout --detach "$PUB" origin/main
  git -C "$PUB" sparse-checkout set --no-cone "${PATHS[@]/%//}"
fi
# 毎回 origin/main の先端から作り直す(前回 push に失敗した commit を引きずらない)
git -C "$PUB" checkout -q -f --detach origin/main

cp "$SRC/docs/data/realtime/latest.json" "$PUB/docs/data/realtime/latest.json"
for f in "$SRC"/docs/data/flow_map/flows_now_*.geojson "$SRC"/docs/data/flow_map/gens_now_*.geojson \
         "$SRC/docs/data/flow_map/now_meta.json" \
         "$SRC/docs/data/flow_map/pulse.json" "$SRC/docs/data/flow_map/pulse.png"; do
  [ -f "$f" ] && cp "$f" "$PUB/docs/data/flow_map/$(basename "$f")"
done
mkdir -p "$PUB/docs/data/flow_map/days"
cp "$SRC"/docs/data/flow_map/days/*.json "$PUB/docs/data/flow_map/days/"

git -C "$PUB" add docs/data/realtime/latest.json docs/data/flow_map/flows_now_*.geojson \
    docs/data/flow_map/gens_now_*.geojson docs/data/flow_map/now_meta.json docs/data/flow_map/days/
# pulse は export_pulse.py が失敗した回には無いことがある(無ければ足さない)
for f in pulse.json pulse.png; do
  if [ -f "$PUB/docs/data/flow_map/$f" ]; then git -C "$PUB" add "docs/data/flow_map/$f"; fi
done
if git -C "$PUB" diff --cached --quiet; then
  echo "変更なし"
  exit 0
fi
git -C "$PUB" commit -q -m "data(realtime): でんき予報スナップショット+NOW断面 $(date '+%F %H:%M')

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
if [ -n "${AGJ_REALTIME_NO_PUSH:-}" ]; then
  echo "commit のみ(push 省略): $(git -C "$PUB" log -1 --format=%h)"
  git -C "$PUB" --no-pager show --stat --format= HEAD | tail -3
  exit 0
fi
# main が fetch 後に進んでいたら拒否される。次のサイクルが新しい先端から作り直すので失敗扱いにしない
if git -C "$PUB" push -q origin HEAD:main; then
  echo "push済 ($(git rev-parse --abbrev-ref HEAD) から main へ公開)"
else
  echo "push 拒否(main が先に進んだ)→ 次回再試行"
fi
