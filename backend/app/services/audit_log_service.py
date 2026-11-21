"""
稽核日誌服務
- 記錄使用者操作
- 查詢稽核紀錄
- 不可修改或刪除（僅 INSERT）
"""

from ipaddress import ip_address as parse_address
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.pagination import page_slice
from app.core.authz import clinical_reader_id
from app.models.user import User
from app.core.exceptions import NotFoundException, ValidationException
from app.models.audit_log import AuditLog
from app.models.enums import AuditAction
from app.utils.datetime_utils import parse_iso


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
        language: Optional[str] = None,
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
            language: 事件發生時 session / 請求所用語言（BCP-47），可為 None

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
            language=language,
            created_at=utc_now(),
        )
        db.add(audit_log)
        await db.flush()
        return audit_log

    @staticmethod
    def _scoped_query(actor: User):
        query = select(AuditLog)
        user_id = clinical_reader_id(actor)
        if user_id is not None:
            query = query.where(AuditLog.user_id == user_id)
        return query

    async def list_audit_logs(
        self,
        db: AsyncSession,
        *,
        actor: User,
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
        query = self._scoped_query(actor)
        if user_id:
            query = query.where(AuditLog.user_id == user_id)
        if action:
            try:
                action_enum = AuditAction(action)
            except ValueError:
                pass  # 相容舊客戶端：忽略未知 action。
            else:
                query = query.where(AuditLog.action == action_enum)
        if resource_type:
            query = query.where(AuditLog.resource_type == resource_type)
        if resource_id:
            query = query.where(AuditLog.resource_id == resource_id)
        if ip_address:
            try:
                address = parse_address(ip_address)
            except ValueError as exc:
                raise ValidationException(details={"field": "ip_address"}) from exc
            query = query.where(AuditLog.ip_address == address)
        if date_from is not None:
            query = query.where(AuditLog.created_at >= parse_iso(date_from))
        if date_to is not None:
            query = query.where(AuditLog.created_at <= parse_iso(date_to))

        total = await db.scalar(query.with_only_columns(func.count(), maintain_column_froms=True))
        if cursor:
            try:
                query = query.where(AuditLog.id < int(cursor))
            except ValueError:
                pass
        limit = min(limit, 100)
        query = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        rows = await db.scalars(query.limit(limit + 1))
        logs, has_more, next_cursor = page_slice(rows.all(), limit)
        return {
            "data": logs,
            "pagination": {
                "next_cursor": next_cursor,
                "has_more": has_more,
                "limit": limit,
                "total_count": total,
            },
        }

    async def get_audit_log(self, db: AsyncSession, log_id: int, *, actor: User) -> AuditLog:
        log = await db.scalar(self._scoped_query(actor).where(AuditLog.id == log_id))
        if log is None:
            raise NotFoundException("errors.audit_log_not_found")
        return log
