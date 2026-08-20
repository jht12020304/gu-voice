#!/bin/zsh
# 一鍵跑單一 E2E 情境（假設 docker postgres/redis 與 uvicorn 已啟動）
# 用法： ./run_scenario.sh dontknow_zh
#        ./run_scenario.sh hematuria_coop_en
#        E2E_BACKEND_DIR=/path/to/worktree/backend ./run_scenario.sh torsion_critical_zh
# （E2E_BACKEND_DIR 影響 driver 讀哪份 .env 拿 OPENAI_API_KEY、記錄哪個 git HEAD；
#   實際受測的是「已啟動的那個 uvicorn」——請確保 start_backend.sh 用同一個目錄。）
set -e
E2E_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="${E2E_BACKEND_DIR:-$(cd "$E2E_DIR/../../backend" && pwd)}"
VENV="${E2E_VENV:-$BACKEND/venv}"

set -a
source "$E2E_DIR/local.env"
set +a

# driver 的 backend/API 位置：預設跟著本 repo 與 E2E_PORT（預設 8000）
export E2E_BACKEND_DIR="$BACKEND"
PORT="${E2E_PORT:-8000}"
export E2E_API_BASE="${E2E_API_BASE:-http://127.0.0.1:$PORT/api/v1}"
export E2E_WS_BASE="${E2E_WS_BASE:-ws://127.0.0.1:$PORT/api/v1/ws}"

exec "$VENV/bin/python" "$E2E_DIR/driver.py" "$@"
