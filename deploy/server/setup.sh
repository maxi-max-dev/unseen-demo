#!/usr/bin/env bash
# UNSEEN worker 服务器一键安装（在【服务器】上跑，不是在 Mac 上跑）
#
# 装完之后，处理宾客照片的程序就常驻在服务器上了，Mac 关机也不影响。
#
# 用法（登上服务器后）：
#   bash setup.sh
#
# 干了什么：装 Python 和依赖 → 建虚拟环境 → 预下载 CLIP 模型 → 装成开机自启的服务。
# 全程幂等：重复跑不会搞坏，只会补上缺的部分。

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/unseen}"
REPO_URL="${REPO_URL:-https://github.com/maxi-max-dev/unseen-demo.git}"
PY="${APP_DIR}/.venv/bin/python"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请用 root 跑（或者在命令前加 sudo）"

say "1/6 装系统依赖"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip git curl
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y -q python3 python3-pip git curl
elif command -v yum >/dev/null 2>&1; then
  yum install -y -q python3 python3-pip git curl
else
  die "认不出这个系统的包管理器（试过 apt/dnf/yum）"
fi

say "2/6 拉代码到 ${APP_DIR}"
if [ -d "${APP_DIR}/.git" ]; then
  git -C "${APP_DIR}" pull --ff-only
else
  mkdir -p "$(dirname "${APP_DIR}")"
  git clone --depth 1 "${REPO_URL}" "${APP_DIR}"
fi

say "3/6 建虚拟环境"
[ -x "${PY}" ] || python3 -m venv "${APP_DIR}/.venv"
"${PY}" -m pip install -q --upgrade pip

say "4/6 装 Python 依赖（torch 走 CPU 版，比 GPU 版小很多）"
# ⚠️ 不加 --index-url 的话 pip 会拉 CUDA 版 torch（好几个 G），这台机器没显卡，纯浪费。
"${PY}" -m pip install -q --index-url https://download.pytorch.org/whl/cpu torch torchvision
# 其余依赖：把 torch 那两行去掉，避免覆盖上面装的 CPU 版
grep -viE '^(torch|torchvision|torchaudio)==' "${APP_DIR}/requirements.txt" > /tmp/req-noturch.txt
"${PY}" -m pip install -q -r /tmp/req-noturch.txt

say "5/6 预下载 CLIP 模型（约 580MB，现在下好，免得婚礼当天现下）"
"${PY}" - <<'PYEOF'
from sentence_transformers import SentenceTransformer
import time
t0 = time.time()
SentenceTransformer("clip-ViT-B-32")
print(f"CLIP 就绪，耗时 {time.time()-t0:.1f}s")
PYEOF

say "6/6 装成开机自启的服务"
install -m 644 "${APP_DIR}/deploy/server/unseen-worker@.service" /etc/systemd/system/
systemctl daemon-reload

cat <<EOF

✅ 装完了。

还差两件事，都要你手动做一次：

  ① 放 OSS 凭证（Mac 上跑这条，把 <服务器IP> 换成真的）：
       scp ~/.config/psm/aliyun.json root@<服务器IP>:/root/.config/psm/aliyun.json
     （服务器上先建目录：mkdir -p /root/.config/psm && chmod 700 /root/.config/psm）

  ② 把空间数据传过来，然后启动（<空间ID> 例如 s4）：
       Mac 上：  bash deploy/server/sync-space.sh <空间ID> <服务器IP>
       服务器上：systemctl enable --now unseen-worker@<空间ID>

  看它跑得怎么样：  journalctl -u unseen-worker@<空间ID> -f
  停掉：            systemctl disable --now unseen-worker@<空间ID>

EOF
