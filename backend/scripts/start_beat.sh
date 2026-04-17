#!/usr/bin/env bash
# =============================================================================
# Celery Beat — 定時任務排程（Session 超時檢查、月度分區建立）
# *** 全系統僅能有一個 Beat 實例，否則任務會重複觸發 ***
# =============================================================================

set -euo pipefail

BEAT_PID=""

cleanup() {
    echo "[beat] 收到終止信號，正在關閉..."
    if [ -n "$BEAT_PID" ] && kill -0 "$BEAT_PID" 2>/dev/null; then
        kill -SIGTERM "$BEAT_PID"
        TIMEOUT=30
        while [ $TIMEOUT -gt 0 ] && kill -0 "$BEAT_PID" 2>/dev/null; do
            sleep 1
            TIMEOUT=$((TIMEOUT - 1))
        done
        if kill -0 "$BEAT_PID" 2>/dev/null; then
            kill -SIGKILL "$BEAT_PID"
        fi
    fi
    exit 0
}

trap cleanup SIGTERM SIGINT

LOG_LEVEL="$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
# Beat schedule 檔位置：Railway 磁碟可能唯讀，改寫到 /tmp
SCHEDULE_FILE="${CELERY_BEAT_SCHEDULE:-/tmp/celerybeat-schedule}"

echo "=============================================="
echo " GU Voice — Celery Beat"
echo " Schedule file: ${SCHEDULE_FILE}"
echo " Log level:     ${LOG_LEVEL}"
echo "=============================================="

celery -A app.tasks.celery_app beat \
    --loglevel="${LOG_LEVEL}" \
    --schedule="${SCHEDULE_FILE}" &

BEAT_PID=$!
echo "[beat] Celery Beat 已啟動 (PID: ${BEAT_PID})"

wait "$BEAT_PID"
EXIT_CODE=$?
echo "[beat] Beat 已結束，退出碼: ${EXIT_CODE}"
exit $EXIT_CODE
