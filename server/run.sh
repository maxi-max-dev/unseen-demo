#!/usr/bin/env bash
# 「上传即合成」本地服务一键启动。
# 用法:在仓库根目录跑  bash server/run.sh
# 起好后浏览器开:  http://localhost:8777/server/upload.html
# 全程本地、断网可用(CLIP 放置 + DAP 深度都在本机跑)。Ctrl+C 停。
set -e
cd "$(dirname "$0")/.."
SITE_ORIGIN_FILE="server/public_site_url.txt"
HOST_PIN_FILE="server/.host_pin"
if [[ -z "${UNSEEN_HOST_PIN:-}" && -f "$HOST_PIN_FILE" ]]; then
  IFS= read -r UNSEEN_HOST_PIN < "$HOST_PIN_FILE"
  export UNSEEN_HOST_PIN
fi
if [[ -f "$SITE_ORIGIN_FILE" ]]; then
  IFS= read -r UNSEEN_SITE_ORIGIN < "$SITE_ORIGIN_FILE"
  if [[ "$UNSEEN_SITE_ORIGIN" == https://* ]]; then
    export PSM_CLOUD_JOIN_BASE="${UNSEEN_SITE_ORIGIN%/}/web/join.html"
  fi
fi
echo "启动合成服务(首次加载 CLIP 约 10-15 秒)…"
echo "就绪后开:http://localhost:8777/server/upload.html"
exec .venv/bin/python -m uvicorn server.compose_server:app --host 0.0.0.0 --port 8777
