"""
醫師儀表板 WebSocket 處理器

提供即時推送功能，讓醫師與管理員能接收：
- 新場次通知
- 場次狀態變更
- 紅旗警示
- 排隊狀態更新
- 統計數據更新
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.websocket.auth import authenticate_websocket
from app.websocket.connection_manager import (
    DASHBOARD_EVENTS_CHANNEL,
    manager,
)

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
            await websocket.close(code=4003, reason="errors.ws.forbidden_role")
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
        # L-20：比照對話端，發生未預期錯誤時送出 canonical error code 給前端，
        # 讓前端能以 `t(code, {ns:'ws'})` 渲染並提示使用者，而非靜默斷線。
        try:
            await websocket.send_json(
                manager._create_envelope(
                    msg_type="error",
                    payload={
                        "code": "errors.ws.internal_error",
                        "params": {},
                        "severity": "critical",
                    },
                )
            )
        except Exception:
            # 連線可能已斷開，無法再送 error，忽略
            pass

    finally:
        await manager.disconnect_dashboard(websocket)
        logger.info(
            "儀表板 WebSocket 清理完成 | user=%s, dashboard_count=%d",
            user_id,
            manager.dashboard_connection_count,
        )


# ── 跨行程儀表板事件 subscriber（H-8） ───────────────────

async def dashboard_event_subscriber() -> None:
    """訂閱 Redis 儀表板事件頻道，收到後對本行程的 dashboard WS 連線 fan-out。

    由 main.py lifespan 以背景 task 啟動（僅在有 Redis 設定時）。任何行程
    （含 Celery worker）publish 到 ``DASHBOARD_EVENTS_CHANNEL`` 的事件，都會在
    這裡被各 API 行程收到並本地廣播，解決跨行程 in-memory 廣播觸及不到的問題。

    韌性：本協程不可讓 app 啟動 / 關閉失敗。Redis 不可用時記 warning 後直接
    返回；被 ``cancel()`` 時乾淨退出。連線中斷會嘗試重連，並做退避避免忙迴圈。
    """
    import redis.asyncio as aioredis

    from app.core.config import settings

    backoff = 1.0
    while True:
        client = None
        pubsub = None
        try:
            client = aioredis.from_url(
                settings.REDIS_URL_CACHE,
                decode_responses=True,
            )
            pubsub = client.pubsub()
            await pubsub.subscribe(DASHBOARD_EVENTS_CHANNEL)
            logger.info(
                "儀表板事件 subscriber 已訂閱 | channel=%s",
                DASHBOARD_EVENTS_CHANNEL,
            )
            backoff = 1.0  # 連上即重置退避
            async for raw in pubsub.listen():
                if raw is None or raw.get("type") != "message":
                    continue
                await _dispatch_dashboard_event(raw.get("data"))
        except asyncio.CancelledError:
            # app 關閉：乾淨退出，不再重連
            logger.info("儀表板事件 subscriber 已取消，停止訂閱")
            raise
        except Exception as exc:  # noqa: BLE001 — 訂閱迴圈不可讓 app 崩潰
            logger.warning(
                "儀表板事件 subscriber 連線中斷，將重試 | error=%s", str(exc)
            )
        finally:
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass
        # 走到這裡代表 listen 迴圈結束或拋例外（非 cancel）；退避後重連
        try:
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            raise
        backoff = min(backoff * 2, 30.0)


async def _dispatch_dashboard_event(data: Any) -> None:
    """解析頻道訊息並對本行程連線本地 fan-out（單筆訊息失敗不可中斷迴圈）。"""
    if not data:
        return
    try:
        envelope = json.loads(data)
    except (ValueError, TypeError) as exc:
        logger.warning("儀表板事件 payload 非合法 JSON，略過 | error=%s", str(exc))
        return
    event_type = envelope.get("type")
    if not event_type:
        return
    payload = envelope.get("payload") or {}
    try:
        await manager.local_broadcast_dashboard_event(event_type, payload)
    except Exception as exc:  # noqa: BLE001 — 本地送出失敗不可中斷 subscriber
        logger.warning(
            "本地 fan-out 儀表板事件失敗（非致命） | event=%s, error=%s",
            event_type,
            str(exc),
        )


# ── 結構化事件推播 helper（H-8） ─────────────────────────

async def broadcast_queue_and_stats(
    db: AsyncSession,
    redis: Redis,
) -> None:
    """重新計算並向所有儀表板連線推播 queue_updated + stats_updated 事件。

    可被外部（如 conversation_handler 在場次狀態變更時）import 呼叫。

    注意：`broadcast_dashboard` 為「廣播給所有連線」，無法逐醫師分流；
    因此這裡計算的是全域（admin 視角，doctor_id=None）的排隊與統計，
    與既有 `new_red_flag` / `session_status_changed` 的廣播語意一致。
    本函式不可拋例外，避免阻塞呼叫端的主流程。
    """
    if manager.dashboard_connection_count == 0:
        return
    try:
        queue_data = await _get_queue_status(db, redis, doctor_id=None)
        await manager.broadcast_queue_updated(
            total_waiting=queue_data.get("total_waiting", 0),
            total_in_progress=queue_data.get("total_in_progress", 0),
            queue=_to_camel_queue_items(queue_data.get("queue", [])),
        )
    except Exception as exc:
        logger.warning("推播 queue_updated 失敗（非致命） | error=%s", str(exc))

    try:
        stats = await _get_dashboard_stats(db, redis, doctor_id=None)
        await manager.broadcast_stats_updated(
            sessions_today=stats.get("sessions_today", 0),
            completed=stats.get("completed", 0),
            red_flags=stats.get("red_flags", 0),
            pending_reviews=stats.get("pending_reviews", 0),
        )
    except Exception as exc:
        logger.warning("推播 stats_updated 失敗（非致命） | error=%s", str(exc))


def _to_camel_queue_items(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把 `_get_queue_status` 的 snake_case 排隊明細轉為前端 camelCase。

    對齊 `QueueUpdatedPayload.queue`（sessionId / patientName /
    chiefComplaint / status / waitingSeconds）。`_get_queue_status` 不含
    patientName / waitingSeconds，缺值以保守預設（""/0）填入。
    """
    camel_items: list[dict[str, Any]] = []
    for item in items:
        camel_items.append(
            {
                "sessionId": item.get("session_id", ""),
                "patientName": item.get("patient_name", ""),
                "chiefComplaint": item.get("chief_complaint", ""),
                "status": item.get("status", ""),
                "waitingSeconds": item.get("waiting_seconds", 0),
            }
        )
    return camel_items


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
    queue_data = await _get_queue_status(db, redis, doctor_id)
    active_alerts = await _get_active_alerts(db, redis, doctor_id)
    stats = await _get_dashboard_stats(db, redis, doctor_id)

    return {
        "queue": queue_data,
        "active_alerts": active_alerts,
        "stats": stats,
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }


async def _get_queue_status(
    db: AsyncSession, redis: Redis, doctor_id: str | None = None
) -> dict[str, Any]:
    """
    取得目前病患排隊狀態

    Args:
        db: 資料庫 session
        redis: Redis 客戶端
        doctor_id: 醫師 ID；非 None 時僅統計該醫師負責的場次（admin 傳 None 看全部）

    Returns:
        排隊狀態字典
    """
    try:
        from app.models.session import Session
        from sqlalchemy import func, select

        # 統計等待中與進行中的場次（醫師範圍：僅自己負責的場次）
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
        if doctor_id:
            waiting_stmt = waiting_stmt.where(Session.doctor_id == doctor_id)
            in_progress_stmt = in_progress_stmt.where(Session.doctor_id == doctor_id)

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
        if doctor_id:
            queue_stmt = queue_stmt.where(Session.doctor_id == doctor_id)
        queue_result = await db.execute(queue_stmt)
        queue_sessions = queue_result.scalars().all()

        queue_items = []
        for sess in queue_sessions:
            queue_items.append(
                {
                    "session_id": str(sess.id),
                    "status": sess.status,
                    # chief_complaint 是未 eager-load 的 relationship，在 async session
                    # 直接存取會觸發 lazy-load → greenlet 例外被吞掉使整個排隊數歸 0。
                    # 改用已載入的純文字欄位 chief_complaint_text。
                    "chief_complaint": getattr(sess, "chief_complaint_text", "") or "",
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
        from app.models.session import Session
        from sqlalchemy import select

        stmt = (
            select(RedFlagAlert)
            .where(RedFlagAlert.acknowledged_at.is_(None))
            .order_by(RedFlagAlert.created_at.desc())
            .limit(50)
        )
        # 醫師範圍：僅顯示自己負責場次的警示（admin 傳 None 看全部）
        if doctor_id:
            stmt = stmt.where(
                RedFlagAlert.session_id.in_(
                    select(Session.id).where(Session.doctor_id == doctor_id)
                )
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

        # 醫師範圍：以 session.doctor_id 過濾自己負責的場次 / 警示（admin 看全部）
        doctor_session_subq = None
        if doctor_id:
            doctor_session_subq = select(Session.id).where(
                Session.doctor_id == doctor_id
            )

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

        if doctor_id:
            sessions_today_stmt = sessions_today_stmt.where(
                Session.doctor_id == doctor_id
            )
            completed_stmt = completed_stmt.where(Session.doctor_id == doctor_id)
            red_flags_stmt = red_flags_stmt.where(
                RedFlagAlert.session_id.in_(doctor_session_subq)
            )
            pending_stmt = pending_stmt.where(
                RedFlagAlert.session_id.in_(doctor_session_subq)
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
