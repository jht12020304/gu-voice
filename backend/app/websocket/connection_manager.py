"""
WebSocket 連線管理器 — 集中管理所有 WebSocket 連線

負責追蹤語音問診場次連線與醫師儀表板連線，
提供統一的訊息發送與廣播介面。
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


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

    async def connect_session(self, websocket: WebSocket, session_id: str) -> None:
        """
        接受並註冊問診場次 WebSocket 連線

        Args:
            websocket: WebSocket 實例
            session_id: 問診場次 ID
        """
        await websocket.accept()
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

    async def connect_dashboard(self, websocket: WebSocket) -> None:
        """
        接受並註冊儀表板 WebSocket 連線

        Args:
            websocket: WebSocket 實例
        """
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
            # 移除已斷開的連線
            self.active_connections.pop(session_id, None)
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
