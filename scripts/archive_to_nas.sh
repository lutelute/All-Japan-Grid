#!/usr/bin/env bash
# 電力系データの NAS(nas03) 退避 — リリース版のスナップショットを残す。
#
# 目的: git に載せない(重い/再生成可能な)成果物を、**どの版から作ったか**が
# 分かる形で保全する。再生成には時間がかかる(CIM全国で数分、SubSLDギャラリーで
# 1時間)ため、リリースごとの実物を残しておくと過去版との比較・再配布が効く。
#
# 実行はサーバ側(160core)から。Mac からは NAS が自動マウントされないため、
#   ssh pws-ubuntu-server@10.0.70.42 'bash ~/subsld/scripts/archive_to_nas.sh ...'
# のように呼ぶか、Mac 側で NAS をマウントしてから直接実行する。
#
# 使い方:
#   bash scripts/archive_to_nas.sh              # 既定のセットを現在のHEADで退避
#   bash scripts/archive_to_nas.sh v1.8.0       # タグ名を明示して退避
#   DRY=1 bash scripts/archive_to_nas.sh        # 何を送るか表示するだけ
set -euo pipefail
cd "$(dirname "$0")/.."

NAS=${NAS:-/mnt/nas03-share/claude-agent/alljapangrid}
VER=${1:-$(git describe --tags --always 2>/dev/null || echo unknown)}
# git 情報は環境変数で渡せる(サーバ側は git 管理外のため、Mac 側から
#   GIT_HEAD=$(git rev-parse HEAD) ssh ... bash scripts/archive_to_nas.sh v1.8.0
# のように渡す)。省略時はローカルの git から取る。
GIT_HEAD=${GIT_HEAD:-$(git rev-parse HEAD 2>/dev/null || echo "")}
GIT_DIRTY=${GIT_DIRTY:-$( [ -n "$(git status --porcelain 2>/dev/null)" ] && echo true || echo false )}
DEST="$NAS/$VER"

# 退避対象: 「再生成できるが高価」なもの。基底データ(data/*.geojson)は
# git 管理下なので含めない。
TARGETS=(
  "dist/cim"                  # CGMES EQ/GL 全国(node-breaker層込み)
  "dist/cim_level2"           # CGMES Level-2(EQ/TP/SSH/SV・解ける潮流ケース)
  "dist/matpower_canonical"   # MATPOWER 正典エクスポート
  "data/structures"           # 変電所構造DB(node-breaker)
  "data/osm_raw_towers"       # OSM 鉄塔(Overpass生)
  "docs/data/powerflow_full"  # 全国潮流の結果
  "docs/data/flow_map"        # 潮流方向マップ(NOW断面+日別断面)
)

if [ ! -d "$(dirname "$NAS")" ]; then
  echo "NAS が見えない: $(dirname "$NAS")" >&2
  echo "  → サーバ側で実行するか、Mac に nas03 をマウントしてください" >&2
  exit 1
fi

echo "退避先: $DEST"
total=0
for t in "${TARGETS[@]}"; do
  [ -e "$t" ] || { echo "  skip(無し): $t"; continue; }
  sz=$(du -sm "$t" | cut -f1)
  total=$((total + sz))
  echo "  $t  ${sz}MB"
done
echo "  合計 ${total}MB"
[ "${DRY:-}" = "1" ] && { echo "(DRY=1 のため送信しない)"; exit 0; }

mkdir -p "$DEST"
for t in "${TARGETS[@]}"; do
  [ -e "$t" ] || continue
  mkdir -p "$DEST/$(dirname "$t")"
  rsync -a --delete "$t/" "$DEST/$t/"
done

# どの版・いつ・何から作ったかを残す(これが無いと後で使えない)
{
  echo "{"
  echo "  \"version\": \"$VER\","
  echo "  \"git_head\": \"$GIT_HEAD\","
  echo "  \"git_dirty\": $GIT_DIRTY,"
  echo "  \"archived_at\": \"$(date -Is)\","
  echo "  \"host\": \"$(hostname)\","
  echo "  \"size_mb\": $total,"
  echo "  \"targets\": [$(printf '"%s",' "${TARGETS[@]}" | sed 's/,$//')]"
  echo "}"
} > "$DEST/MANIFEST.json"

echo "完了: $DEST (${total}MB)"
ls -la "$DEST"
