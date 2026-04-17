#!/usr/bin/env bash
# =============================================================================
# Celery Worker — 背景任務處理（推播重試、SOAP 報告產生、場次逾時、分區管理）
# 與主 API service 分離部署，共用 Redis broker
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# 優雅關閉（Railway / K8s 停機時送 SIGTERM）
# ---------------------------------------------------------------------------
WORKER_PID=""

cleanup() {
    echo "[worker] 收到終止信號，等待 in-flight task 完成..."
    if [ -n "$WORKER_PID" ] && kill -0 "$WORKER_PID" 2>/dev/null; then
        # Celery 收到 SIGTERM 後會停止接新任務，但會完成目前執行中的
        kill -SIGTERM "$WORKER_PID"
        # 等到 soft_time_limit (600s) 加一點 buffer
        TIMEOUT=660
        while [ $TIMEOUT -gt 0 ] && kill -0 "$WORKER_PID" 2>/dev/null; do
            sleep 1
            TIMEOUT=$((TIMEOUT - 1))
        done
        if kill -0 "$WORKER_PID" 2>/dev/null; then
            echo "[worker] 超過 660s 仍未結束，強制終止"
            kill -SIGKILL "$WORKER_PID"
        fi
    fi
    exit 0
}

trap cleanup SIGTERM SIGINT

# ---------------------------------------------------------------------------
# 環境變數
# ---------------------------------------------------------------------------
CONCURRENCY="${CELERY_CONCURRENCY:-2}"
LOG_LEVEL="$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"

echo "=============================================="
echo " GU Voice — Celery Worker"
echo " Concurrency: ${CONCURRENCY}"
echo " Log level:   ${LOG_LEVEL}"
echo "=============================================="

# ---------------------------------------------------------------------------
# 啟動 Worker
#   -A app.tasks.celery_app     : Celery app 位置
#   --concurrency               : 並行 worker 數（CPU-bound 任務建議 = vCPU）
#   --without-gossip / mingle   : 節省網路開銷（單節點部署時）
#   --prefetch-multiplier 1     : 配合 acks_late 降低任務遺失風險
# ---------------------------------------------------------------------------
celery -A app.tasks.celery_app worker \
    --loglevel="${LOG_LEVEL}" \
    --concurrency="${CONCURRENCY}" \
    --prefetch-multiplier=1 \
    --without-gossip \
    --without-mingle &

WORKER_PID=$!
echo "[worker] Celery Worker 已啟動 (PID: ${WORKER_PID})"

wait "$WORKER_PID"
EXIT_CODE=$?
echo "[worker] Worker 已結束，退出碼: ${EXIT_CODE}"
exit $EXIT_CODE
