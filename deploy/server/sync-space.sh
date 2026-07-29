#!/usr/bin/env bash
# 把一个空间从 Mac 传到服务器（在【Mac】上跑）
#
# 为什么需要这一步：空间数据（全景图、深度图、space.json）是在 Mac 上做出来的，
# 服务器上的 worker 要读它才知道该往哪儿放照片。
#
# 用法：
#   bash deploy/server/sync-space.sh s4 47.98.1.2
#
# 什么时候跑：婚礼开始【之前】，摄影师的全景图都传完、空间建好之后。
# 传完再启动服务器上的 worker，当天就不用管了。

set -euo pipefail

SID="${1:-}"
HOST="${2:-}"
USER_AT="${SSH_USER:-root}"
APP_DIR="${APP_DIR:-/opt/unseen}"

if [ -z "$SID" ] || [ -z "$HOST" ]; then
  echo "用法: bash $0 <空间ID> <服务器IP>"
  echo "例如: bash $0 s4 47.98.1.2"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${REPO_ROOT}/server/spaces/${SID}"

[ -d "$SRC" ] || { echo "✗ 本地找不到空间 ${SID}（看了 ${SRC}）"; exit 1; }

SIZE=$(du -sh "$SRC" | cut -f1)
echo "==> 准备传空间 ${SID}（${SIZE}）到 ${USER_AT}@${HOST}"

ssh "${USER_AT}@${HOST}" "mkdir -p ${APP_DIR}/server/spaces"

# 用 rsync 而不是 scp：只传变化的部分，改一点点不用重传整个空间。
# --delete 让服务器那份和 Mac 完全一致，避免残留旧节点造成诡异现象。
if command -v rsync >/dev/null 2>&1; then
  rsync -az --delete --info=progress2 "${SRC}/" "${USER_AT}@${HOST}:${APP_DIR}/server/spaces/${SID}/"
else
  echo "（没装 rsync，退回 scp，会整包重传）"
  scp -rq "$SRC" "${USER_AT}@${HOST}:${APP_DIR}/server/spaces/"
fi

echo "==> 校验两边文件数是否一致"
LOCAL_N=$(find "$SRC" -type f | wc -l | tr -d ' ')
REMOTE_N=$(ssh "${USER_AT}@${HOST}" "find ${APP_DIR}/server/spaces/${SID} -type f | wc -l" | tr -d ' ')
echo "    Mac ${LOCAL_N} 个文件 / 服务器 ${REMOTE_N} 个文件"
[ "$LOCAL_N" = "$REMOTE_N" ] || { echo "✗ 文件数对不上，别启动，先查为什么"; exit 1; }

cat <<EOF

✅ 传完了，两边文件数一致。

服务器上启动它：
    systemctl enable --now unseen-worker@${SID}

看它在干什么：
    journalctl -u unseen-worker@${SID} -f

EOF
