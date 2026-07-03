#!/bin/zsh
# 啟動受測 backend（前景執行；要背景跑請自行 nohup ... &）
#
# 用法：
#   ./start_backend.sh                       # 原 repo backend
#   E2E_BACKEND_DIR=/path/to/worktree/backend ./start_backend.sh   # §E 修復 worktree
#
# - venv 一律共用主 repo 的 /Users/chun/Desktop/GU_0410/backend/venv
# - cwd 切到受測 backend 目錄：pydantic-settings 由該處讀 .env（含 OPENAI_API_KEY）
# - local.env 覆寫本機 DB/Redis/REDIS_KEY_PREFIX（見 README）
set -e
E2E_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="${E2E_BACKEND_DIR:-/Users/chun/Desktop/GU_0410/backend}"
VENV=/Users/chun/Desktop/GU_0410/backend/venv

if [[ ! -f "$BACKEND/.env" ]]; then
  echo "FATAL: $BACKEND/.env 不存在（worktree 需先複製 .env）" >&2
  exit 1
fi

set -a
source "$E2E_DIR/local.env"
set +a

cd "$BACKEND"
exec "$VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000 --log-level info
