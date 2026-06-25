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


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    """將 ISO-8601 字串轉成 datetime；無效或 None 時回 None（不拋例外）。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


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
        resource_id: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        ip_address: Optional[str] = None,
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
        if resource_id:
            query = query.where(AuditLog.resource_id == resource_id)
        if ip_address:
            query = query.where(AuditLog.ip_address == ip_address)
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

        # 精確總筆數（套用與 list 相同的篩選條件，含日期範圍）
        count_query = select(func.count()).select_from(AuditLog)
        if user_id:
            count_query = count_query.where(AuditLog.user_id == user_id)
        if action:
            count_query = count_query.where(AuditLog.action == action)
        if resource_type:
            count_query = count_query.where(AuditLog.resource_type == resource_type)
        if resource_id:
            count_query = count_query.where(AuditLog.resource_id == resource_id)
        if ip_address:
            count_query = count_query.where(AuditLog.ip_address == ip_address)
        if date_from:
            count_query = count_query.where(AuditLog.created_at >= date_from)
        if date_to:
            count_query = count_query.where(AuditLog.created_at <= date_to)
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
            raise NotFoundException("errors.audit_log_not_found")
        return log

    # ── Router 對應方法 ─────────────────────────────────
    # audit_logs router 以這兩個名稱呼叫；統一 caller/callee 命名（ADMIN-1）。
    async def list_audit_logs(
        self,
        db: AsyncSession,
        cursor: Optional[str] = None,
        limit: int = 20,
        user_id: Optional[UUID] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        取得稽核日誌列表 — router 入口。

        將 router 傳入的字串 `action` / `date_from` / `date_to` 轉成
        對應型別後委派給 `get_list`。無效值靜默忽略，不讓查詢 500。
        """
        action_enum: Optional[AuditAction] = None
        if action:
            try:
                action_enum = AuditAction(action)
            except ValueError:
                action_enum = None

        return await self.get_list(
            db,
            cursor=cursor,
            limit=limit,
            user_id=user_id,
            action=action_enum,
            resource_type=resource_type,
            resource_id=resource_id,
            date_from=_parse_iso_datetime(date_from),
            date_to=_parse_iso_datetime(date_to),
            ip_address=ip_address,
        )

    async def get_audit_log(self, db: AsyncSession, log_id: int) -> AuditLog:
        """取得單筆稽核日誌 — router 入口，委派給 `get_by_id`。"""
        return await self.get_by_id(db, log_id)
