#!/usr/bin/env bash
# =============================================================================
# 泌尿科 AI 語音問診助手 — 服務啟動腳本
# 功能：執行資料庫遷移 → 啟動 Uvicorn → 優雅關閉
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# 信號處理 — 接收 SIGTERM/SIGINT 時優雅關閉
# ---------------------------------------------------------------------------
UVICORN_PID=""
CELERY_WORKER_PID=""
CELERY_BEAT_PID=""

cleanup() {
    echo "[啟動腳本] 收到終止信號，正在優雅關閉服務..."
    for pid in "$CELERY_BEAT_PID" "$CELERY_WORKER_PID"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill -SIGTERM "$pid" 2>/dev/null || true
        fi
    done
    if [ -n "$UVICORN_PID" ] && kill -0 "$UVICORN_PID" 2>/dev/null; then
        # 送出 SIGTERM 讓 Uvicorn 優雅關閉
        kill -SIGTERM "$UVICORN_PID"
        # 等待最多 30 秒讓請求處理完畢
        TIMEOUT=30
        while [ $TIMEOUT -gt 0 ] && kill -0 "$UVICORN_PID" 2>/dev/null; do
            sleep 1
            TIMEOUT=$((TIMEOUT - 1))
        done
        # 若仍未結束，強制終止
        if kill -0 "$UVICORN_PID" 2>/dev/null; then
            echo "[啟動腳本] 服務未在時限內關閉，強制終止"
            kill -SIGKILL "$UVICORN_PID"
        fi
    fi
    echo "[啟動腳本] 服務已關閉"
    exit 0
}

trap cleanup SIGTERM SIGINT

# ---------------------------------------------------------------------------
# 環境變數預設值
# ---------------------------------------------------------------------------
APP_ENV="${APP_ENV:-production}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-4}"
LOG_LEVEL="$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"

echo "=============================================="
echo " 泌尿科 AI 語音問診助手 — 後端服務"
echo " 環境: ${APP_ENV}"
echo " 埠號: ${PORT}"
echo " Workers: ${WORKERS}"
echo "=============================================="

# ---------------------------------------------------------------------------
# 步驟一：執行資料庫遷移（Alembic）
# ---------------------------------------------------------------------------
echo "[啟動腳本] 正在執行資料庫遷移..."

if [ -f "alembic.ini" ]; then
    # 重試機制 — 資料庫可能尚未就緒（最多重試 5 次）
    MAX_RETRIES=5
    RETRY_COUNT=0

    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        if alembic upgrade head; then
            echo "[啟動腳本] 資料庫遷移完成"
            break
        else
            RETRY_COUNT=$((RETRY_COUNT + 1))
            if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
                WAIT_TIME=$((RETRY_COUNT * 5))
                echo "[啟動腳本] 資料庫遷移失敗，${WAIT_TIME} 秒後重試（第 ${RETRY_COUNT}/${MAX_RETRIES} 次）..."
                sleep "$WAIT_TIME"
            else
                echo "[啟動腳本] 資料庫遷移在 ${MAX_RETRIES} 次嘗試後仍然失敗，終止啟動"
                exit 1
            fi
        fi
    done
else
    echo "[啟動腳本] 未找到 alembic.ini，跳過資料庫遷移"
fi

# ---------------------------------------------------------------------------
# 步驟二：啟動 Celery worker + beat（同容器）
#
# SOAP 生成是 Celery 單一路徑（conversation_handler 只建 GENERATING row 然後
# .delay()），worker 沒在跑 → 報告永遠停在 GENERATING。Railway 上沒有獨立的
# worker/beat service，所以跑在這個容器裡。
#
# ponytail: 單容器共存，理由是（a）不必跨 service 複製 20+ 個環境變數、
# （b）每多一個常駐 service 就多一組 Supabase session-pooler 連線，那正是
# 2026-07-04 pooler idle 佔滿事故的成因。要獨立擴縮時再依
# docs/railway_celery_runbook.md 拆成獨立 service，並把 RUN_CELERY_IN_API 設 false。
#
# ⚠️ beat 全系統只能有一個副本。railway.toml 是 numReplicas=1，成立；
#    要調大 replicas 前必須先把 beat 拆出去，否則排程會重複觸發。
# ---------------------------------------------------------------------------
RUN_CELERY_IN_API="${RUN_CELERY_IN_API:-true}"
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-2}"

if [ "$RUN_CELERY_IN_API" = "true" ]; then
    echo "[啟動腳本] 正在啟動 Celery worker（concurrency=${CELERY_CONCURRENCY}）..."
    celery -A app.tasks.celery_app worker \
        --loglevel="${LOG_LEVEL}" \
        --concurrency="${CELERY_CONCURRENCY}" \
        --prefetch-multiplier=1 \
        --without-gossip \
        --without-mingle &
    CELERY_WORKER_PID=$!
    echo "[啟動腳本] Celery worker 已啟動 (PID: ${CELERY_WORKER_PID})"

    echo "[啟動腳本] 正在啟動 Celery beat..."
    celery -A app.tasks.celery_app beat \
        --loglevel="${LOG_LEVEL}" \
        --schedule="${CELERY_BEAT_SCHEDULE:-/tmp/celerybeat-schedule}" &
    CELERY_BEAT_PID=$!
    echo "[啟動腳本] Celery beat 已啟動 (PID: ${CELERY_BEAT_PID})"
else
    echo "[啟動腳本] RUN_CELERY_IN_API=false，跳過 Celery（應有獨立 worker/beat service）"
fi

# ---------------------------------------------------------------------------
# 步驟三：啟動 Uvicorn ASGI 伺服器
# ---------------------------------------------------------------------------
echo "[啟動腳本] 正在啟動 Uvicorn 伺服器..."

# Railway 會透過 PORT 環境變數指定埠號
# --workers：Worker 程序數量，根據容器 CPU 核心數調整
# --timeout-keep-alive：WebSocket 長連線需要較長的 keep-alive
# --timeout-graceful-shutdown：優雅關閉的等待時間
# --access-log：啟用存取日誌
# --proxy-headers：Railway 使用反向代理，需啟用此選項以正確取得客戶端 IP
# --forwarded-allow-ips：信任 Railway 代理的轉發標頭

uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers "${WORKERS}" \
    --log-level "${LOG_LEVEL}" \
    --timeout-keep-alive 120 \
    --timeout-graceful-shutdown 30 \
    --access-log \
    --proxy-headers \
    --forwarded-allow-ips="*" \
    --no-server-header &

UVICORN_PID=$!
echo "[啟動腳本] Uvicorn 已啟動 (PID: ${UVICORN_PID})"

# 任一子程序結束就讓容器退出，交給 Railway 的 ON_FAILURE 重啟。
# 若只 wait uvicorn，celery worker 死掉會變成「容器健康但 SOAP 永遠卡 GENERATING」的靜默故障。
set +e
wait -n
EXIT_CODE=$?
set -e

for name_pid in "Uvicorn:${UVICORN_PID}" "Celery worker:${CELERY_WORKER_PID}" "Celery beat:${CELERY_BEAT_PID}"; do
    name="${name_pid%%:*}"; pid="${name_pid##*:}"
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
        echo "[啟動腳本] ${name} 已結束（PID ${pid}）"
    fi
done

echo "[啟動腳本] 子程序結束，退出碼: ${EXIT_CODE}；容器將退出並由 Railway 重啟"
exit $EXIT_CODE
