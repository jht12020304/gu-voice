"""
GU Voice API — FastAPI 入口
泌尿科 AI 語音問診助手後端服務
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import engine
from app.core.dependencies import close_redis, init_redis
from app.core.exceptions import register_exception_handlers
from app.core.middleware import AuditLoggingMiddleware, RequestIdMiddleware
from app.schemas.common import HealthResponse


# ── Lifespan（啟動 / 關閉） ─────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """應用程式生命週期管理：連線資料庫與 Redis"""
    # 啟動
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
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 例外處理器 ─────────────────────────────────────────
register_exception_handlers(app)


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
from fastapi import Depends, WebSocket  # noqa: E402

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
