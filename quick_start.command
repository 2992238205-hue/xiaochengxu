#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== 英语小说阅读：一键启动 ==="
echo "1) 请输入管理员密钥（你自己定一个密码，用来上传书）"
echo -n "管理员密钥（例如 my123456 ）: "
read -r ADMIN_KEY_INPUT
if [[ -z "${ADMIN_KEY_INPUT}" ]]; then
  ADMIN_KEY_INPUT="my123456"
  echo "未输入，自动使用默认密钥: ${ADMIN_KEY_INPUT}"
fi

echo -n "2) 端口（直接回车自动用 5090，并自动避开冲突）: "
read -r PORT_INPUT
if [[ -z "${PORT_INPUT}" ]]; then
  PORT_INPUT="5090"
fi

while lsof -nP -iTCP:${PORT_INPUT} -sTCP:LISTEN >/dev/null 2>&1; do
  echo "端口 ${PORT_INPUT} 已被占用，自动切换..."
  PORT_INPUT="$((PORT_INPUT + 1))"
done

echo
echo "即将启动服务..."
echo "管理员密钥: ${ADMIN_KEY_INPUT}"
echo "端口: ${PORT_INPUT}"
echo

IP="$(ipconfig getifaddr en0 || true)"
if [[ -z "$IP" ]]; then
  IP="$(ipconfig getifaddr en1 || true)"
fi
if [[ -z "$IP" ]]; then
  IP="127.0.0.1"
fi

echo "将自动打开后台页面（如果没自动打开，就手动复制下面地址）:"
echo "http://${IP}:${PORT_INPUT}/admin"
echo

AUTO_KEY="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "${ADMIN_KEY_INPUT}")"
open "http://127.0.0.1:${PORT_INPUT}/admin?k=${AUTO_KEY}" >/dev/null 2>&1 || true

ADMIN_KEY="${ADMIN_KEY_INPUT}" ./start_backend.sh "${PORT_INPUT}"
