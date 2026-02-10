#!/bin/zsh
set -euo pipefail

PORT="${1:-8080}"
IP="$(ipconfig getifaddr en0 || true)"
if [[ -z "$IP" ]]; then
  IP="$(ipconfig getifaddr en1 || true)"
fi
if [[ -z "$IP" ]]; then
  IP="127.0.0.1"
fi

echo "Desktop: http://localhost:${PORT}"
echo "Mobile : http://${IP}:${PORT}"
echo "(Keep this terminal running)"

python3 -m http.server "$PORT"
