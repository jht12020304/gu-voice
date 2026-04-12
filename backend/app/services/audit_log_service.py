"""
稽核日誌服務
- 記錄使用者操作
- 查詢稽核紀錄
- 不可修改或刪除（僅 INSERT）
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.audit_log import AuditLog
from app.models.enums import AuditAction


class AuditLogService:
    """稽核日誌業務邏輯"""

    @staticmethod
    async def log(
        db: AsyncSession,
        user_id: Optional[UUID],
        action: AuditAction,
        resource_type: str,
        resource_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        """
        寫入稽核日誌

        Args:
            db: 資料庫 session
            user_id: 操作者 ID（系統操作時為 None）
            action: 操作類型
            resource_type: 資源類型（user / patient / session / report ...）
            resource_id: 資源 ID
            details: 操作詳情
            ip_address: 客戶端 IP
            user_agent: 客戶端 User-Agent

        Returns:
            新建的 AuditLog 物件
        """
        from app.utils.datetime_utils import utc_now

        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=utc_now(),
        )
        db.add(audit_log)
        await db.flush()
        return audit_log

    @staticmethod
    async def get_list(
        db: AsyncSession,
        cursor: Optional[str] = None,
        limit: int = 20,
        user_id: Optional[UUID] = None,
        action: Optional[AuditAction] = None,
        resource_type: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """
        取得稽核日誌列表（Cursor-based 分頁 + 多條件篩選）

        Args:
            cursor: 分頁游標（上一頁最後一筆的 ID）
            limit: 每頁筆數
            user_id: 篩選操作者
            action: 篩選操作類型
            resource_type: 篩選資源類型
            date_from: 起始日期
            date_to: 結束日期
        """
        limit = min(limit, 100)

        query = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())

        # 條件篩選
        if user_id:
            query = query.where(AuditLog.user_id == user_id)
        if action:
            query = query.where(AuditLog.action == action)
        if resource_type:
            query = query.where(AuditLog.resource_type == resource_type)
        if date_from:
            query = query.where(AuditLog.created_at >= date_from)
        if date_to:
            query = query.where(AuditLog.created_at <= date_to)

        # Cursor 分頁（使用 BIGINT id）
        if cursor:
            try:
                cursor_id = int(cursor)
                query = query.where(AuditLog.id < cursor_id)
            except ValueError:
                pass  # 無效的 cursor 值，忽略

        result = await db.execute(query.limit(limit + 1))
        logs = result.scalars().all()

        has_more = len(logs) > limit
        if has_more:
            logs = logs[:limit]

        # 近似總筆數
        count_query = select(func.count()).select_from(AuditLog)
        if user_id:
            count_query = count_query.where(AuditLog.user_id == user_id)
        if action:
            count_query = count_query.where(AuditLog.action == action)
        if resource_type:
            count_query = count_query.where(AuditLog.resource_type == resource_type)
        total_result = await db.execute(count_query)
        total_count = total_result.scalar() or 0

        return {
            "data": logs,
            "pagination": {
                "next_cursor": str(logs[-1].id) if has_more and logs else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
        }

    @staticmethod
    async def get_by_id(db: AsyncSession, log_id: int) -> AuditLog:
        """
        根據 ID 取得稽核日誌

        Raises:
            NotFoundException: 日誌不存在
        """
        result = await db.execute(
            select(AuditLog).where(AuditLog.id == log_id)
        )
        log = result.scalar_one_or_none()
        if log is None:
            raise NotFoundException("稽核日誌不存在")
        return log
