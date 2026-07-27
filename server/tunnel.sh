#!/usr/bin/env bash
#
# server/tunnel.sh —— 把本机的空间记忆服务(:8777)开成一个公网临时地址。
#
# ⚠️⚠️ 先看清楚这一段再决定要不要跑 ⚠️⚠️
#
#   1. 这个脚本会把你这台电脑上的 :8777 服务**暴露到公网**。
#      跑起来之后会拿到一个 https://xxxx.trycloudflare.com 地址,
#      **地球上任何人拿到这个地址都能打开登录页**；主办动作仍由服务端 PIN
#      和 HttpOnly 会话保护。地址本身仍只应交给现场主办方。
#   2. 之所以需要它:婚礼现场宾客用的是手机流量,连不上你的 Wi-Fi 局域网,
#      所以必须有个公网地址他们才扫得到。
#   3. 地址是随机的、临时的,不会被搜索引擎收录,短时间演示风险可控。
#      但是——**演示一结束,立刻回到这个窗口按 Ctrl-C 关掉。**
#      别让它整宿开着,别把地址发到公开群里。
#   4. Ctrl-C 之后地址立刻失效,同时脚本会删掉 public_url.txt,
#      后端就自动退回"只发局域网链接"的状态。
#
# 用法(在仓库根目录):
#     bash server/tunnel.sh
# 可选:换端口
#     PORT=8777 bash server/tunnel.sh
#
# 跑起来后会做三件事:
#   - 解析出公网地址
#   - 写进 server/public_url.txt(后端读它来生成宾客链接和二维码)
#   - 前台挂着不退出,窗口别关
#
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8777}"
URL_FILE="$REPO_ROOT/server/public_url.txt"
CLOUDFLARED="${CLOUDFLARED:-/opt/homebrew/bin/cloudflared}"

# ── 0. 先检查工具在不在 ────────────────────────────────────────────────
if [ ! -x "$CLOUDFLARED" ]; then
  if command -v cloudflared >/dev/null 2>&1; then
    CLOUDFLARED="$(command -v cloudflared)"
  else
    echo "❌ 找不到 cloudflared。"
    echo "   装一下:  brew install cloudflared"
    exit 1
  fi
fi

# ── 1. 确认后端已经起来了,不然隧道开出来也是 502 ───────────────────────
if ! curl -s -o /dev/null -m 3 "http://localhost:$PORT/"; then
  echo "⚠️  本机 :$PORT 好像没在跑。"
  echo "   请先开另一个终端窗口跑:  bash server/run.sh"
  echo "   起好之后再回来跑这个脚本。"
  echo ""
  printf "   还是要继续吗?(y/N) "
  read -r ans
  case "$ans" in [yY]*) ;; *) echo "已取消。"; exit 1 ;; esac
fi

LOG="$(mktemp -t psm-tunnel)"
TUNNEL_PID=""
TAIL_PID=""

# ── 2. 退出时的清扫:删掉地址文件 + 关掉隧道 ─────────────────────────────
cleanup() {
  echo ""
  echo "🧹 收摊中…"
  [ -n "$TAIL_PID" ] && kill "$TAIL_PID" 2>/dev/null
  [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null
  rm -f "$URL_FILE"
  rm -f "$LOG"
  echo "   公网地址已关闭,server/public_url.txt 已删除。"
  echo "   后端还在跑(局域网仍然可用),要停后端去那个窗口按 Ctrl-C。"
}
trap cleanup EXIT INT TERM

# ── 3. 起隧道 ─────────────────────────────────────────────────────────
echo "🚇 正在开公网隧道(本机 :$PORT)…"
"$CLOUDFLARED" tunnel --no-autoupdate --url "http://localhost:$PORT" > "$LOG" 2>&1 &
TUNNEL_PID=$!

# ── 4. 从日志里把 https://xxxx.trycloudflare.com 抠出来 ─────────────────
PUBLIC_URL=""
ROADSHOW_SID="${PSM_ROADSHOW_SPACE_ID:-s900003}"
CLOUD_JOIN_BASE="${PSM_CLOUD_JOIN_BASE:-https://unseen-d3gtp0sxh53bbef61-1316841054.tcloudbaseapp.com/web/join.html}"
for _ in $(seq 1 60); do
  PUBLIC_URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -n 1)"
  [ -n "$PUBLIC_URL" ] && break
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "❌ cloudflared 自己退出了,下面是它的输出:"
    echo "────────────────────────────────────────"
    cat "$LOG"
    echo "────────────────────────────────────────"
    exit 1
  fi
  sleep 1
done

if [ -z "$PUBLIC_URL" ]; then
  echo "❌ 等了 60 秒也没拿到公网地址。cloudflared 的输出:"
  echo "────────────────────────────────────────"
  cat "$LOG"
  echo "────────────────────────────────────────"
  echo "   常见原因:网络不通、被墙、或者 cloudflared 版本太老。"
  exit 1
fi

# ── 5. 写进 public_url.txt,后端读它生成宾客链接和二维码 ─────────────────
printf '%s\n' "$PUBLIC_URL" > "$URL_FILE"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ 公网地址已就绪"
echo ""
echo "  新人(你自己)开这个:"
echo "      $PUBLIC_URL/server/roadshow-admin.html"
echo ""
echo "  宾客扫的码指向这个:"
echo "      ${CLOUD_JOIN_BASE}?s=${ROADSHOW_SID}&roadshow=1"
echo ""
echo "  地址已写入:server/public_url.txt"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  ⚠️  这个地址现在全世界都能打开。演示一完就回来按 Ctrl-C。"
echo "  ⚠️  这个窗口别关、电脑别睡,关了地址就没了。"
echo ""
echo "  ──── 下面是 cloudflared 的实时日志 ────"

tail -n +1 -f "$LOG" &
TAIL_PID=$!
wait "$TUNNEL_PID"
