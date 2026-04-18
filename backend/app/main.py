"""
GU Voice API — FastAPI 入口
泌尿科 AI 語音問診助手後端服務
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import engine
from app.core.dependencies import close_redis, init_redis
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
    yield
    # 關閉
    await close_redis()
    await engine.dispose()


# ── 建立 FastAPI App ───────────────────────────────────
app = FastAPI(
    title="GU Voice API",
    version="1.0.0",
    description="泌尿科 AI 語音問診助手 API",
    lifespan=lifespan,
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
    ],
    expose_headers=["X-Request-ID"],
    max_age=600,  # 10 分鐘 preflight cache，減少 OPTIONS 來回
)


# ── 例外處理器 ─────────────────────────────────────────
register_exception_handlers(app)


# ── Prometheus metrics（TODO P1-#10 / TODO-O2） ────────
# /metrics 回 text format；若設 PROMETHEUS_METRICS_ENABLED=false 可關閉
# import app.core.metrics 會觸發 Counter/Histogram 在 default REGISTRY 註冊，
# Instrumentator 共用同一個 default REGISTRY，兩者的指標會一起暴露。
from app.core import metrics as _app_metrics  # noqa: F401, E402

if getattr(settings, "PROMETHEUS_METRICS_ENABLED", True):
    Instrumentator().instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
        tags=["系統"],
    )


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
    sessions,
)

app.include_router(auth.router)
app.include_router(patients.router)
app.include_router(sessions.router)
app.include_router(complaints.router)
app.include_router(reports.router)
app.include_router(alerts.router)
app.include_router(dashboard.router)
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
