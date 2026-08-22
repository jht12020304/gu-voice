"""
GU Voice API — FastAPI 入口
泌尿科 AI 語音問診助手後端服務
"""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import engine
from app.cache.redis_client import close_redis, init_redis
from app.core.exceptions import register_exception_handlers
from app.core.firebase import initialize_firebase
from app.core.language_middleware import LanguageMiddleware
from app.core.middleware import (
    AuditLoggingMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.sentry import init_sentry
from app.schemas.common import HealthResponse

# 全 app 的 logging 初始化。先前完全沒有任何 basicConfig/dictConfig，root logger
# 因此停在預設的 WARNING → 整個 backend 的 logger.info() 全被靜默丟棄（生產實測：
# forgot_password 的 `[email:log-only]`、紅旗偵測、SOAP 生成的 INFO 訊息全看不到，
# 只有 logger.warning 以上才進得了 Railway log）。
# 注意 LOG_LEVEL 這個環境變數原本只餵給 `uvicorn --log-level`，管不到 app 自己的 logger。
logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger(__name__)

# 已知的開發預設值 — production 啟動時若環境變數等於這些值則拒絕啟動。
# 這些字串來自 backend/.env / config.py 預設值，在 git 裡是公開的。
_DEV_DEFAULT_SECRETS: dict[str, set[str]] = {
    "APP_SECRET_KEY": {
        "change-me-in-production",
        "dev-secret-key-at-least-32-characters-long",
    },
    "JWT_SECRET_KEY": {
        "",
        "dev-jwt-secret-at-least-32-characters-long-for-hs256",
    },
}


def _enforce_production_secrets() -> None:
    """
    Production 啟動時檢查關鍵 secret 不是 git 公開的 dev 預設值。

    以 `APP_ENV` 區分環境，非 production 時只記 warning 不中斷，方便本機開發。
    """
    env = (settings.APP_ENV or "").lower()
    is_production = env == "production"

    offending: list[str] = []
    for key, bad_values in _DEV_DEFAULT_SECRETS.items():
        current = getattr(settings, key, None)
        if current is None:
            continue
        if current in bad_values:
            offending.append(key)

    if not offending:
        return

    msg = (
        f"檢測到關鍵 secret 仍為 git 公開的 dev 預設值: {', '.join(offending)}。"
        " 這些值在倉庫裡是公開的，任何人可以偽造 JWT token → 禁止以此狀態啟動 production。"
    )
    if is_production:
        raise RuntimeError(msg)
    logger.warning("[dev] %s (APP_ENV=%s → 允許啟動，但切 production 前必須輪替)", msg, env)


# ── Lifespan（啟動 / 關閉） ─────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """應用程式生命週期管理：連線資料庫與 Redis"""
    # 啟動
    _enforce_production_secrets()
    init_sentry()  # 早期初始化：讓 lifespan 後續錯誤也能被捕獲
    initialize_firebase()
    await init_redis()

    # 分區兜底：每次部署/啟動補建 conversations / audit_logs 的未來月份分區，
    # 防 Celery beat 失效跨月 → 新月份 INSERT 撞「no partition of relation」。
    # 失敗只 log 不阻擋啟動（ensure_partitions_on_startup 內部已吞例外）。
    try:
        from app.tasks.partition_manager import ensure_partitions_on_startup

        await ensure_partitions_on_startup()
    except Exception as exc:  # noqa: BLE001 — 兜底失敗不可中斷 app 啟動
        logger.error("啟動時分區補建 hook 失敗（非致命） | error=%s", str(exc))

    # H-8：啟動跨行程儀表板事件 subscriber（背景 task）。
    # report 完成點在 Celery worker 行程，無法用 in-memory 廣播觸及本 API 行程持有
    # 的 dashboard WS 連線；改由各行程 publish 到 Redis 頻道，本 task 收到後做本地
    # fan-out。韌性：僅在有 Redis 設定時啟動；建立失敗只 log，絕不讓 app 啟動失敗。
    dashboard_subscriber_task: asyncio.Task[None] | None = None
    if getattr(settings, "REDIS_URL_CACHE", None):
        try:
            from app.websocket.dashboard_handler import dashboard_event_subscriber

            dashboard_subscriber_task = asyncio.create_task(
                dashboard_event_subscriber()
            )
            logger.info("已啟動儀表板事件 subscriber 背景 task")
        except Exception as exc:  # noqa: BLE001 — 啟動失敗不可中斷 app
            logger.warning("啟動儀表板事件 subscriber 失敗（非致命） | error=%s", str(exc))

    yield

    # 關閉：先取消 subscriber task，再關閉 Redis / DB
    if dashboard_subscriber_task is not None:
        dashboard_subscriber_task.cancel()
        try:
            await dashboard_subscriber_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    await close_redis()
    await engine.dispose()


# ── 建立 FastAPI App ───────────────────────────────────
# `/docs`、`/redoc`、`/openapi.json` 在 development 以外一律不掛公開路由
# （2026-08-22；在此之前三個都是公開的）。openapi.json 仍然拿得到，但要帶 token —— 見下方，
# 因為部署驗證靠它判斷新碼有沒有真的上線（docs/deployment_guide.md 一、）。
_docs = settings.docs_exposed

app = FastAPI(
    title="GU Voice API",
    version="1.0.0",
    description="泌尿科 AI 語音問診助手 API",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)


# ── 中介層（順序很重要：先加的最後執行） ──────────────────
# SecurityHeaders 最早加 → 最後執行 → 確保注入到所有其他 middleware 的 response 之上
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(RequestIdMiddleware)
# LanguageMiddleware 早於 CORS 以便 handler 及 exception_handler 都能讀 state.language
app.add_middleware(LanguageMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    # P2 #18：明確列舉，杜絕 "*" + credentials 的瀏覽器拒絕（Access-Control-Allow-Origin 不可為 *
    # 當 credentials 為 true）以及多餘 verb 的誤用
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "Origin",
        "X-Requested-With",
        "X-Request-ID",
        # M-22：double-submit CSRF token header（/auth/refresh、/auth/logout 需帶）
        "X-CSRF-Token",
    ],
    expose_headers=["X-Request-ID"],
    max_age=600,  # 10 分鐘 preflight cache，減少 OPTIONS 來回
)

# 最後加 → 最先執行 → 包在最外層，看得到最終 response body。
#
# 這個 API 回的幾乎都是 JSON，而且是很好壓的那種：`GET /sessions` 每一筆都帶完整的
# intake 快照、`GET /reports` 每一筆都帶 SOAP summary 與 patient-facing JSON，
# 前端多半只讀其中幾個欄位。實測本專案的 payload 壓縮比在 5-10 倍之間，
# 而診間 Wi-Fi 與手機網路上「傳輸位元組數」正是使用者實際等的東西。
#
# minimum_size=1000：小回應壓了反而變大（gzip header），且省不到可感知的時間。
# starlette 只在 client 送 `Accept-Encoding: gzip` 時才壓，而且會跳過已經帶
# `Content-Encoding` 的 response，所以不會重複壓縮。
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ── 例外處理器 ─────────────────────────────────────────
register_exception_handlers(app)


# ── Prometheus metrics（TODO P1-#10 / TODO-O2） ────────
# /metrics 回 text format。開關是 METRICS_ENABLED，存取要 METRICS_TOKEN。
# ⚠️ 這裡原本寫的是 `PROMETHEUS_METRICS_ENABLED`，而 Settings 裡從來沒有那個欄位，
#    加上 `extra="ignore"`，等於一個設了也沒用的假開關（2026-08-22 修）。
# import app.core.metrics 會觸發 Counter/Histogram 在 default REGISTRY 註冊，
# Instrumentator 共用同一個 default REGISTRY，兩者的指標會一起暴露。
from app.core import metrics as _app_metrics  # noqa: F401, E402

def _ops_token_ok(request: Request) -> bool:
    """運維端點的共用閘門：`Authorization: Bearer <METRICS_TOKEN>`。

    與 Prometheus scrape config 的 `bearer_token` 相容。比對走
    `secrets.compare_digest`，避免用回應時間把 token 逐字元試出來。

    **正式環境沒設 token ＝ 關閉**，不是放行。這幾支端點合起來是一份完整的偵查
    資料（API 介面與全部欄位名稱、每支端點的流量與錯誤率、紅旗觸發次數、精確的
    Python 版本、以及什麼時段沒人在用），fail-open 的預設值在醫療系統上不可接受。
    """
    expected = settings.METRICS_TOKEN
    if not expected:
        return settings.metrics_open_without_token
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    return secrets.compare_digest(token, expected)


def _not_found() -> HTTPException:
    """未授權一律回 404 而不是 401/403。

    401 等於告訴掃描的人「這裡有東西，只是你沒鑰匙」，反而把偵查目標標了起來。
    形狀比照 FastAPI 對未知路徑的預設 404。
    """
    return HTTPException(status_code=404, detail="Not Found")


if settings.METRICS_ENABLED:
    # 只裝 middleware（記錄 http_requests_total / http_request_duration_seconds），
    # **不用 `.expose()`** —— 那會掛一條無條件公開的 /metrics。路由自己掛，才擋得住。
    Instrumentator().instrument(app)

    @app.get("/metrics", include_in_schema=False, tags=["系統"])
    async def metrics_endpoint(request: Request) -> Response:
        if not _ops_token_ok(request):
            raise _not_found()
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


if not _docs:
    # 部署驗證要靠它區分新舊容器（`healthz` 恆綠，區分不出來），所以不能直接拿掉，
    # 只能上鎖。用法見 docs/deployment_guide.md 一、。
    @app.get("/openapi.json", include_in_schema=False, tags=["系統"])
    async def openapi_gated(request: Request) -> JSONResponse:
        if not _ops_token_ok(request):
            raise _not_found()
        return JSONResponse(app.openapi())


# ── 路由註冊 ───────────────────────────────────────────
# 各 router 已自帶 /api/v1 前綴，直接 include 即可
from app.routers import (  # noqa: E402
    admin,
    alerts,
    audit_logs,
    auth,
    complaints,
    dashboard,
    notifications,
    patients,
    reports,
    research,
    sessions,
)

app.include_router(auth.router)
app.include_router(patients.router)
app.include_router(sessions.router)
app.include_router(complaints.router)
app.include_router(reports.router)
app.include_router(alerts.router)
app.include_router(dashboard.router)
app.include_router(research.router)
app.include_router(notifications.router)
app.include_router(admin.router)
app.include_router(audit_logs.router)


# ── WebSocket 路由 ────────────────────────────────────────
from fastapi import WebSocket  # noqa: E402

from app.core.dependencies import get_db, get_redis  # noqa: E402
from app.websocket.conversation_handler import conversation_websocket  # noqa: E402
from app.websocket.dashboard_handler import dashboard_websocket  # noqa: E402


@app.websocket("/api/v1/ws/sessions/{session_id}/stream")
async def ws_conversation(
    websocket: WebSocket,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    await conversation_websocket(websocket, session_id, db, redis, settings)


@app.websocket("/api/v1/ws/dashboard")
async def ws_dashboard(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    await dashboard_websocket(websocket, db, redis, settings)


# ── 健康檢查 ───────────────────────────────────────────
@app.get("/api/v1/health", response_model=HealthResponse, tags=["系統"])
async def health_check() -> HealthResponse:
    """健康檢查端點"""
    return HealthResponse(
        status="ok",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc),
    )


# 深度健康檢查所用的單次檢查逾時；DB / Redis 任一超過 2 秒就判定 fail
_DEEP_HEALTH_TIMEOUT_SECONDS = 2.0


async def _deep_check_db(db: AsyncSession) -> str:
    """對 DB 跑 SELECT 1；成功回 "ok"，失敗回 "fail: <err>"。"""
    try:
        async def _probe() -> None:
            await db.execute(text("SELECT 1"))
        await asyncio.wait_for(_probe(), timeout=_DEEP_HEALTH_TIMEOUT_SECONDS)
        return "ok"
    except asyncio.TimeoutError:
        return f"fail: timeout >{_DEEP_HEALTH_TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001 — 要回報給呼叫端
        return f"fail: {exc}"


async def _deep_check_redis(redis: Any) -> str:
    """對 Redis 跑 ping；成功回 "ok"，失敗回 "fail: <err>"。"""
    try:
        await asyncio.wait_for(redis.ping(), timeout=_DEEP_HEALTH_TIMEOUT_SECONDS)
        return "ok"
    except asyncio.TimeoutError:
        return f"fail: timeout >{_DEEP_HEALTH_TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001
        return f"fail: {exc}"


@app.get("/api/v1/healthz/deep", tags=["系統"])
async def deep_health_check(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> JSONResponse:
    """
    深度健康檢查 — 真實連線 DB 與 Redis 各一次。

    - DB 跑 `SELECT 1`、Redis 跑 `PING`，兩者各 2 秒逾時
    - 全過 → 200 `{"status": "ok", "checks": {...}}`
    - 任一失敗 → 503，並在 `checks` 欄位回 `fail: <err>` 方便排錯
    """
    checks = {
        "db": await _deep_check_db(db),
        "redis": await _deep_check_redis(redis),
    }
    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ok" if all_ok else "fail", "checks": checks},
    )
