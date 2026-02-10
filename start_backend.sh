#!/bin/zsh
set -euo pipefail

REQUESTED_PORT="${1:-5090}"
PORT="${REQUESTED_PORT}"
ADMIN_KEY="${ADMIN_KEY:-change-this-admin-key}"
ALLOW_ADMIN_BOOTSTRAP="${ALLOW_ADMIN_BOOTSTRAP:-1}"
export ADMIN_KEY
export ALLOW_ADMIN_BOOTSTRAP
VENV_DIR="/Users/yuanxi/Documents/New project/.venv"

while lsof -nP -iTCP:${PORT} -sTCP:LISTEN >/dev/null 2>&1; do
  if [[ "${PORT}" == "${REQUESTED_PORT}" ]]; then
    echo "端口 ${PORT} 已被占用，自动切换..."
  fi
  PORT=$((PORT + 1))
done

export PORT

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install -q -r "/Users/yuanxi/Documents/New project/backend/requirements.txt"

IP="$(ipconfig getifaddr en0 || true)"
if [[ -z "$IP" ]]; then
  IP="$(ipconfig getifaddr en1 || true)"
fi
if [[ -z "$IP" ]]; then
  IP="127.0.0.1"
fi

echo "Reader URL : http://${IP}:${PORT}/"
echo "Admin URL  : http://${IP}:${PORT}/admin"
echo "Admin key  : ${ADMIN_KEY}"
echo "注意：必须带端口号（:${PORT}），否则可能出现 403。"
echo "(Keep this terminal running)"

"${VENV_DIR}/bin/python" backend/server.py
