"""
WebSocket 連線管理器 — 集中管理所有 WebSocket 連線

負責追蹤語音問診場次連線與醫師儀表板連線，
提供統一的訊息發送與廣播介面。
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# ── 跨行程儀表板事件 Redis 頻道（H-8） ─────────────────────
# report 完成點在 Celery worker 行程，與持有 dashboard WS 連線的 API 行程不同；
# in-memory broadcast 跨不了行程。改以 Redis pub/sub 橋接：任何行程 publish 到此
# 頻道，API 行程的 subscriber task（main.py lifespan 啟動）收到後再對本行程的
# dashboard WS 連線做本地 fan-out。沿用 gu: key 前綴慣例。
DASHBOARD_EVENTS_CHANNEL = "gu:dashboard:events"


class ConnectionManager:
    """
    WebSocket 連線管理器（Singleton）

    管理兩種類型的 WebSocket 連線：
    1. 語音問診場次連線：session_id → WebSocket 的一對一映射
    2. 醫師儀表板連線：多個醫師可同時連線
    """

    def __init__(self) -> None:
        # 問診場次連線：session_id → WebSocket
        self.active_connections: dict[str, WebSocket] = {}
        # 儀表板連線列表
        self.dashboard_connections: list[WebSocket] = []

        logger.info("ConnectionManager 初始化完成")

    # ── 問診場次連線管理 ─────────────────────────────────

    async def connect_session(
        self,
        websocket: WebSocket,
        session_id: str,
        already_accepted: bool = False,
    ) -> None:
        """
        接受並註冊問診場次 WebSocket 連線

        Args:
            websocket: WebSocket 實例
            session_id: 問診場次 ID
            already_accepted: 呼叫端若已 `accept()`（例如認證 handshake 時）設 True，
                避免重複 accept 引發 `RuntimeError`
        """
        if not already_accepted:
            await websocket.accept()
        # L-18：同一 session_id 已有舊連線時（重連 / 多分頁），主動 close 舊連線，
        # 避免靜默覆蓋造成舊連線變成不會被清理的殭屍連線。新連線接手該 session。
        existing_ws = self.active_connections.get(session_id)
        if existing_ws is not None and existing_ws is not websocket:
            logger.warning(
                "偵測到場次重複連線，將關閉舊連線 | session=%s",
                session_id,
            )
            try:
                await existing_ws.close(
                    code=4008, reason="errors.ws.session_superseded"
                )
            except Exception:
                # 舊連線可能已斷開，close 失敗可忽略
                pass
        self.active_connections[session_id] = websocket
        logger.info(
            "問診場次 WebSocket 已連線 | session=%s, active_count=%d",
            session_id,
            len(self.active_connections),
        )

    async def disconnect_session(self, session_id: str) -> None:
        """
        移除並清理問診場次 WebSocket 連線

        Args:
            session_id: 問診場次 ID
        """
        ws = self.active_connections.pop(session_id, None)
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                # 連線可能已經關閉，忽略錯誤
                pass
        logger.info(
            "問診場次 WebSocket 已斷線 | session=%s, active_count=%d",
            session_id,
            len(self.active_connections),
        )

    # ── 儀表板連線管理 ───────────────────────────────────

    async def connect_dashboard(
        self,
        websocket: WebSocket,
        already_accepted: bool = False,
    ) -> None:
        """
        接受並註冊儀表板 WebSocket 連線

        Args:
            websocket: WebSocket 實例
            already_accepted: 呼叫端若已 `accept()` 設 True
        """
        if not already_accepted:
            await websocket.accept()
        self.dashboard_connections.append(websocket)
        logger.info(
            "儀表板 WebSocket 已連線 | dashboard_count=%d",
            len(self.dashboard_connections),
        )

    async def disconnect_dashboard(self, websocket: WebSocket) -> None:
        """
        移除並清理儀表板 WebSocket 連線

        Args:
            websocket: WebSocket 實例
        """
        if websocket in self.dashboard_connections:
            self.dashboard_connections.remove(websocket)
            try:
                await websocket.close()
            except Exception:
                pass
        logger.info(
            "儀表板 WebSocket 已斷線 | dashboard_count=%d",
            len(self.dashboard_connections),
        )

    # ── 訊息發送 ─────────────────────────────────────────

    async def send_to_session(
        self, session_id: str, message: dict[str, Any]
    ) -> bool:
        """
        向指定問診場次發送 WSMessage 信封格式訊息

        Args:
            session_id: 目標場次 ID
            message: 包含 type 和 payload 的訊息字典

        Returns:
            是否成功發送
        """
        ws = self.active_connections.get(session_id)
        if ws is None:
            logger.warning("無法發送訊息：場次 %s 無活躍連線", session_id)
            return False

        envelope = self._create_envelope(
            msg_type=message.get("type", "unknown"),
            payload=message.get("payload", {}),
        )

        try:
            await ws.send_json(envelope)
            return True
        except Exception as exc:
            logger.error(
                "發送訊息至場次失敗 | session=%s, type=%s, error=%s",
                session_id,
                message.get("type"),
                str(exc),
            )
            # M-18：發送失敗代表連線已半開（half-open）。除了從註冊表 pop 之外，
            # 還必須主動 close WebSocket，否則 receive 主迴圈會卡在
            # `await websocket.receive_json()` 形成殭屍連線。close 後下一次
            # receive 會丟 WebSocketDisconnect，主迴圈得以乾淨退出。
            self.active_connections.pop(session_id, None)
            try:
                await ws.close()
            except Exception:
                # 連線可能已完全斷開，close 失敗可忽略
                pass
            return False

    async def broadcast_dashboard(self, message: dict[str, Any]) -> None:
        """
        向所有儀表板連線廣播訊息

        Args:
            message: 包含 type 和 payload 的訊息字典
        """
        if not self.dashboard_connections:
            return

        envelope = self._create_envelope(
            msg_type=message.get("type", "unknown"),
            payload=message.get("payload", {}),
        )

        # 記錄需要移除的斷線連線
        disconnected: list[WebSocket] = []

        for ws in self.dashboard_connections:
            try:
                await ws.send_json(envelope)
            except Exception as exc:
                logger.warning(
                    "廣播至儀表板連線失敗，將移除 | error=%s", str(exc)
                )
                disconnected.append(ws)

        # 清理斷線連線
        for ws in disconnected:
            if ws in self.dashboard_connections:
                self.dashboard_connections.remove(ws)

        if disconnected:
            logger.info(
                "已清理 %d 個斷線的儀表板連線，剩餘 %d 個",
                len(disconnected),
                len(self.dashboard_connections),
            )

    # ── Canonical code-based 本地化訊息（TODO-E2） ───────
    # 以下 helper 統一把 `{code, params, severity}` 的 canonical body
    # 包進既有 envelope 外殼，確保前端 i18n 能以 `t(code, params)` 渲染，
    # 切語言時自然重新渲染（不存 rendered string）。

    async def send_localized_to_session(
        self,
        session_id: str,
        msg_type: str,
        code: str,
        params: dict[str, Any] | None = None,
        severity: str = "info",
        extra: dict[str, Any] | None = None,
    ) -> bool:
        """向 session 推播 canonical localizable 訊息。

        extra：合併進 payload 的額外欄位（如終態 `status`，讓前端據以導頁/停止重連）。
        """
        payload: dict[str, Any] = {
            "code": code,
            "params": params or {},
            "severity": severity,
        }
        if extra:
            payload.update(extra)
        return await self.send_to_session(
            session_id,
            {"type": msg_type, "payload": payload},
        )

    async def broadcast_localized_dashboard(
        self,
        msg_type: str,
        code: str,
        params: dict[str, Any] | None = None,
        severity: str = "info",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """向全部 dashboard 廣播 canonical localizable 訊息。

        `extra` 可附加非本地化的結構資料（例：alertId、sessionId），
        會併入 payload root；與 `code/params/severity` 並列但不衝突。
        """
        payload: dict[str, Any] = {
            "code": code,
            "params": params or {},
            "severity": severity,
        }
        if extra:
            for k, v in extra.items():
                if k in ("code", "params", "severity"):
                    continue  # 保留 canonical 欄位不被覆寫
                payload[k] = v
        await self.broadcast_dashboard({"type": msg_type, "payload": payload})

    # ── 儀表板結構化事件推播（H-8） ───────────────────────
    # docstring 宣稱會推播 queue_updated / stats_updated / session_created /
    # report_generated / red_flag_acknowledged 等事件，但先前只實作了
    # new_red_flag / session_status_changed / initial_state。以下提供可被
    # 外部 import 呼叫的具名 helper，payload 一律使用 camelCase 以對齊前端
    # `types/websocket.ts`（本專案無自動 camel 轉換機制，沿用既有手動 camelCase
    # 慣例）。這些 helper 僅負責「推播」；資料來源由呼叫端組好後傳入。

    async def publish_dashboard_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """把儀表板事件 publish 到 Redis 頻道（跨行程，worker 也能用）。

        與 ``broadcast_dashboard`` 不同：本方法不依賴本地連線數，也不直接送出
        到任何 WS；它只把 ``{type, payload}`` 的 JSON publish 到
        ``DASHBOARD_EVENTS_CHANNEL``，由 API 行程的 subscriber task 收到後再對
        本行程的 dashboard WS 連線做本地 fan-out（見 ``local_broadcast_dashboard_event``）。

        韌性：Redis 不可用（測試環境 / 暫時性故障）時絕不可拋例外，僅記 log；
        每次建立短命 client 並於送出後關閉，避免在 worker 行程持有長連線。

        Args:
            event_type: 事件類型字串，需與前端 `DashboardEventType` 對齊。
            payload: 事件內容（鍵名須為 camelCase 以對齊前端型別）。
        """
        message = json.dumps({"type": event_type, "payload": payload or {}})
        client = None
        try:
            import redis.asyncio as aioredis

            from app.core.config import settings

            client = aioredis.from_url(
                settings.REDIS_URL_CACHE,
                decode_responses=True,
            )
            await client.publish(DASHBOARD_EVENTS_CHANNEL, message)
        except Exception as exc:  # noqa: BLE001 — publish 失敗只 log，不可影響主流程
            logger.warning(
                "publish 儀表板事件失敗（非致命） | event=%s, error=%s",
                event_type,
                str(exc),
            )
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    # 連線關閉失敗可忽略
                    pass

    async def local_broadcast_dashboard_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """對「本行程」的 dashboard WS 連線送出結構化事件（不經 Redis）。

        供 main.py lifespan 的 Redis subscriber task 收到頻道訊息後呼叫，
        把跨行程傳來的事件 fan-out 給本行程實際持有的連線。
        """
        await self.broadcast_dashboard(
            {"type": event_type, "payload": payload or {}}
        )

    async def broadcast_dashboard_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """向所有儀表板連線推播一個結構化事件（type + camelCase payload）。

        H-8：為使單／多行程一致，本方法改走 ``publish→subscriber→本地``——
        publish 到 Redis 頻道後，由各 API 行程的 subscriber task 統一做本地
        fan-out（含送出此事件的同一行程）。如此 worker 行程觸發的事件也能
        被持有 WS 連線的 API 行程收到。呼叫端（含 session_service /
        alert_service 的具名 helper）簽名不變。

        Args:
            event_type: 事件類型字串，需與前端 `DashboardEventType` 對齊，
                例：``queue_updated`` / ``stats_updated`` / ``session_created`` /
                ``report_generated`` / ``red_flag_acknowledged``。
            payload: 事件內容（鍵名須為 camelCase 以對齊前端型別）。
        """
        await self.publish_dashboard_event(event_type, payload)

    async def broadcast_queue_updated(
        self,
        total_waiting: int,
        total_in_progress: int,
        queue: list[dict[str, Any]] | None = None,
    ) -> None:
        """推播 ``queue_updated`` 事件（對齊前端 ``QueueUpdatedPayload``）。"""
        await self.broadcast_dashboard_event(
            "queue_updated",
            {
                "totalWaiting": total_waiting,
                "totalInProgress": total_in_progress,
                "queue": queue or [],
            },
        )

    async def broadcast_stats_updated(
        self,
        sessions_today: int,
        completed: int,
        red_flags: int,
        pending_reviews: int,
    ) -> None:
        """推播 ``stats_updated`` 事件（對齊前端 ``StatsUpdatedPayload``）。"""
        await self.broadcast_dashboard_event(
            "stats_updated",
            {
                "sessionsToday": sessions_today,
                "completed": completed,
                "redFlags": red_flags,
                "pendingReviews": pending_reviews,
            },
        )

    async def broadcast_session_created(
        self,
        session_id: str,
        patient_name: str,
        chief_complaint: str,
        status: str,
    ) -> None:
        """推播 ``session_created`` 事件（對齊前端 ``SessionCreatedPayload``）。"""
        await self.broadcast_dashboard_event(
            "session_created",
            {
                "sessionId": session_id,
                # 後端不送本地化「未知」字樣，缺值以空字串交由前端依 locale 顯示
                "patientName": patient_name or "",
                "chiefComplaint": chief_complaint or "",
                "status": status,
            },
        )

    async def broadcast_report_generated(
        self,
        report_id: str,
        session_id: str,
        patient_name: str,
        status: str,
    ) -> None:
        """推播 ``report_generated`` 事件（對齊前端 ``ReportGeneratedPayload``）。"""
        await self.broadcast_dashboard_event(
            "report_generated",
            {
                "reportId": report_id,
                "sessionId": session_id,
                "patientName": patient_name or "",
                "status": status,
            },
        )

    async def broadcast_red_flag_acknowledged(
        self,
        alert_id: str,
        acknowledged_by: str,
    ) -> None:
        """推播 ``red_flag_acknowledged`` 事件（對齊前端 ``RedFlagAcknowledgedPayload``）。"""
        await self.broadcast_dashboard_event(
            "red_flag_acknowledged",
            {
                "alertId": alert_id,
                "acknowledgedBy": acknowledged_by,
            },
        )

    # ── 工具方法 ─────────────────────────────────────────

    @staticmethod
    def _create_envelope(msg_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        建立 WSMessage 標準信封格式

        格式：
        {
            "type": str,          # 訊息類型
            "id": str,            # UUID
            "timestamp": str,     # ISO 8601
            "payload": dict,      # 訊息內容
        }

        Args:
            msg_type: 訊息類型（如 "stt_partial", "ai_response_chunk" 等）
            payload: 訊息內容

        Returns:
            標準信封格式字典
        """
        return {
            "type": msg_type,
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }

    def get_session_connection(self, session_id: str) -> WebSocket | None:
        """取得指定場次的 WebSocket 連線"""
        return self.active_connections.get(session_id)

    def is_session_connected(self, session_id: str) -> bool:
        """檢查指定場次是否有活躍的 WebSocket 連線"""
        return session_id in self.active_connections

    @property
    def active_session_count(self) -> int:
        """目前活躍的問診場次數"""
        return len(self.active_connections)

    @property
    def dashboard_connection_count(self) -> int:
        """目前活躍的儀表板連線數"""
        return len(self.dashboard_connections)


# ── Singleton 實例 ───────────────────────────────────────
manager = ConnectionManager()


# ── 模組層 broadcast helper（H-8） ───────────────────────
# 提供可直接 `from app.websocket.connection_manager import broadcast_dashboard_event`
# 的具名函式，讓跨服務觸發點（後續『跨服務推播』步驟接線）無需先取得 manager 實例。
async def broadcast_dashboard_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """向所有儀表板連線推播結構化事件（委派給 singleton ``manager``）。

    H-8：經由 Redis publish→subscriber→本地，跨行程一致。
    payload 鍵名須為 camelCase 以對齊前端 ``types/websocket.ts``。
    """
    await manager.broadcast_dashboard_event(event_type, payload)


async def publish_dashboard_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """把儀表板事件 publish 到 Redis 頻道（委派給 singleton ``manager``）。

    供 Celery worker 等「不持有 WS 連線」的行程使用（如 report_generated）；
    payload 鍵名須為 camelCase 以對齊前端 ``types/websocket.ts``。
    """
    await manager.publish_dashboard_event(event_type, payload)
