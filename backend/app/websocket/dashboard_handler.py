"""
醫師儀表板 WebSocket 處理器

提供即時推送功能，讓醫師與管理員能接收：
- 新場次通知
- 場次狀態變更
- 紅旗警示
- 排隊狀態更新
- 統計數據更新
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.websocket.auth import authenticate_websocket
from app.websocket.connection_manager import manager

logger = logging.getLogger(__name__)

# ── Redis key 常數 ───────────────────────────────────────
_DASHBOARD_STATS_KEY = "gu:dashboard:stats:{doctor_id}"
_ACTIVE_ALERTS_KEY = "gu:alert:active:{doctor_id}"
_QUEUE_KEY = "gu:queue:patients"


async def dashboard_websocket(
    websocket: WebSocket,
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
) -> None:
    """
    醫師儀表板 WebSocket 主處理函式

    流程：
    1. 驗證 Token（僅允許 doctor / admin 角色）
    2. 發送初始狀態（排隊狀態、活躍警示）
    3. 維持連線，接收並回應 ping
    4. 事件推送由 ConnectionManager.broadcast_dashboard() 負責

    Args:
        websocket: FastAPI WebSocket 實例
        db: 非同步資料庫 session
        redis: Redis 非同步客戶端
        settings: 應用程式設定
    """
    user_id: str | None = None
    user_role: str | None = None

    try:
        # ── 步驟 1：認證與授權 ──────────────────────────
        payload = await authenticate_websocket(
            websocket,
            context="dashboard-ws",
        )
        if payload is None:
            return  # authenticate_websocket 已 close
        user_id = payload.get("sub")
        user_role = payload.get("role")

        # 僅允許 doctor 與 admin 角色
        if user_role not in ("doctor", "admin"):
            logger.warning(
                "儀表板 WebSocket 權限不足 | user=%s, role=%s",
                user_id,
                user_role,
            )
            await websocket.close(code=4003, reason="權限不足，僅限醫師與管理員")
            return

        # ── 步驟 2：建立連線（authenticate_websocket 已 accept） ──
        await manager.connect_dashboard(websocket, already_accepted=True)

        logger.info(
            "儀表板 WebSocket 已連線 | user=%s, role=%s",
            user_id,
            user_role,
        )

        # ── 步驟 3：發送初始狀態 ────────────────────────
        initial_state = await _build_initial_state(db, redis, user_id)
        await websocket.send_json(
            manager._create_envelope(
                msg_type="initial_state",
                payload=initial_state,
            )
        )

        # ── 步驟 4：維持連線 / 訊息迴圈 ────────────────
        while True:
            raw_message = await websocket.receive_json()
            msg_type = raw_message.get("type", "")

            # 心跳回應
            if msg_type == "ping":
                await websocket.send_json(
                    manager._create_envelope(
                        msg_type="pong",
                        payload={
                            "server_time": datetime.now(timezone.utc).isoformat()
                        },
                    )
                )
                continue

            # 儀表板目前僅接收 ping，其他事件透過 broadcast 推送
            logger.debug(
                "儀表板收到非預期訊息類型 | user=%s, type=%s",
                user_id,
                msg_type,
            )

    except WebSocketDisconnect:
        logger.info("儀表板 WebSocket 已斷開 | user=%s", user_id)

    except Exception as exc:
        logger.error(
            "儀表板 WebSocket 發生未預期錯誤 | user=%s, error=%s",
            user_id,
            str(exc),
            exc_info=True,
        )

    finally:
        await manager.disconnect_dashboard(websocket)
        logger.info(
            "儀表板 WebSocket 清理完成 | user=%s, dashboard_count=%d",
            user_id,
            manager.dashboard_connection_count,
        )


# ── 輔助函式 ─────────────────────────────────────────────

async def _build_initial_state(
    db: AsyncSession,
    redis: Redis,
    doctor_id: str | None,
) -> dict[str, Any]:
    """
    建構儀表板初始狀態

    包含：
    - 目前排隊狀態
    - 活躍紅旗警示
    - 今日統計數據

    Args:
        db: 資料庫 session
        redis: Redis 客戶端
        doctor_id: 醫師 ID

    Returns:
        初始狀態字典
    """
    import json

    # 嘗試從 Redis 快取載入
    queue_data = await _get_queue_status(db, redis)
    active_alerts = await _get_active_alerts(db, redis, doctor_id)
    stats = await _get_dashboard_stats(db, redis, doctor_id)

    return {
        "queue": queue_data,
        "active_alerts": active_alerts,
        "stats": stats,
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }


async def _get_queue_status(
    db: AsyncSession, redis: Redis
) -> dict[str, Any]:
    """
    取得目前病患排隊狀態

    Args:
        db: 資料庫 session
        redis: Redis 客戶端

    Returns:
        排隊狀態字典
    """
    try:
        from app.models.session import Session
        from sqlalchemy import func, select

        # 統計等待中與進行中的場次
        waiting_stmt = (
            select(func.count())
            .select_from(Session)
            .where(Session.status == "waiting")
        )
        in_progress_stmt = (
            select(func.count())
            .select_from(Session)
            .where(Session.status == "in_progress")
        )

        waiting_result = await db.execute(waiting_stmt)
        in_progress_result = await db.execute(in_progress_stmt)

        total_waiting = waiting_result.scalar() or 0
        total_in_progress = in_progress_result.scalar() or 0

        # 取得排隊中的場次明細
        queue_stmt = (
            select(Session)
            .where(Session.status.in_(["waiting", "in_progress"]))
            .order_by(Session.created_at.asc())
            .limit(50)
        )
        queue_result = await db.execute(queue_stmt)
        queue_sessions = queue_result.scalars().all()

        queue_items = []
        for sess in queue_sessions:
            queue_items.append(
                {
                    "session_id": str(sess.id),
                    "status": sess.status,
                    "chief_complaint": getattr(sess, "chief_complaint", ""),
                    "created_at": (
                        sess.created_at.isoformat()
                        if hasattr(sess, "created_at") and sess.created_at
                        else None
                    ),
                }
            )

        return {
            "total_waiting": total_waiting,
            "total_in_progress": total_in_progress,
            "queue": queue_items,
        }

    except Exception as exc:
        logger.error("取得排隊狀態失敗 | error=%s", str(exc))
        return {
            "total_waiting": 0,
            "total_in_progress": 0,
            "queue": [],
        }


async def _get_active_alerts(
    db: AsyncSession, redis: Redis, doctor_id: str | None
) -> list[dict[str, Any]]:
    """
    取得活躍中的紅旗警示

    Args:
        db: 資料庫 session
        redis: Redis 客戶端
        doctor_id: 醫師 ID

    Returns:
        活躍警示列表
    """
    try:
        from app.models.red_flag_alert import RedFlagAlert
        from sqlalchemy import select

        stmt = (
            select(RedFlagAlert)
            .where(RedFlagAlert.acknowledged_at.is_(None))
            .order_by(RedFlagAlert.created_at.desc())
            .limit(50)
        )
        result = await db.execute(stmt)
        alerts = result.scalars().all()

        return [
            {
                "alert_id": str(alert.id),
                "session_id": str(alert.session_id) if alert.session_id else None,
                "severity": alert.severity,
                "title": alert.title,
                "description": getattr(alert, "description", ""),
                "created_at": (
                    alert.created_at.isoformat()
                    if hasattr(alert, "created_at") and alert.created_at
                    else None
                ),
            }
            for alert in alerts
        ]

    except Exception as exc:
        logger.error("取得活躍警示失敗 | error=%s", str(exc))
        return []


async def _get_dashboard_stats(
    db: AsyncSession, redis: Redis, doctor_id: str | None
) -> dict[str, Any]:
    """
    取得儀表板統計數據

    Args:
        db: 資料庫 session
        redis: Redis 客戶端
        doctor_id: 醫師 ID

    Returns:
        統計數據字典
    """
    import json

    # 先嘗試從 Redis 快取取得
    if doctor_id:
        stats_key = _DASHBOARD_STATS_KEY.format(doctor_id=doctor_id)
        try:
            cached = await redis.get(stats_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    try:
        from datetime import date

        from app.models.red_flag_alert import RedFlagAlert
        from app.models.session import Session
        from sqlalchemy import func, select

        today = date.today()

        # 今日場次數
        sessions_today_stmt = (
            select(func.count())
            .select_from(Session)
            .where(func.date(Session.created_at) == today)
        )
        # 已完成場次數
        completed_stmt = (
            select(func.count())
            .select_from(Session)
            .where(
                func.date(Session.created_at) == today,
                Session.status == "completed",
            )
        )
        # 紅旗數
        red_flags_stmt = (
            select(func.count())
            .select_from(RedFlagAlert)
            .where(func.date(RedFlagAlert.created_at) == today)
        )
        # 待審閱數
        pending_stmt = (
            select(func.count())
            .select_from(RedFlagAlert)
            .where(RedFlagAlert.acknowledged_at.is_(None))
        )

        sessions_today = (await db.execute(sessions_today_stmt)).scalar() or 0
        completed = (await db.execute(completed_stmt)).scalar() or 0
        red_flags = (await db.execute(red_flags_stmt)).scalar() or 0
        pending_reviews = (await db.execute(pending_stmt)).scalar() or 0

        stats = {
            "sessions_today": sessions_today,
            "completed": completed,
            "red_flags": red_flags,
            "pending_reviews": pending_reviews,
        }

        # 快取至 Redis（5 分鐘）
        if doctor_id:
            stats_key = _DASHBOARD_STATS_KEY.format(doctor_id=doctor_id)
            try:
                await redis.set(stats_key, json.dumps(stats), ex=300)
            except Exception:
                pass

        return stats

    except Exception as exc:
        logger.error("取得儀表板統計失敗 | error=%s", str(exc))
        return {
            "sessions_today": 0,
            "completed": 0,
            "red_flags": 0,
            "pending_reviews": 0,
        }
