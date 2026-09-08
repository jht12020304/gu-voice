"""檢查醫囑（快速開單）業務邏輯。

授權完全借用場次那一條：能讀這場問診的臨床帳號，才能對它開檢查單。所以這裡
**不自己重寫一份權限判斷**——`SessionService.get_session()` 已經把軟刪除、
`get_clinician_scope_id()` 的 row-level 隔離、病患只能看自己那幾條規則收在一起，
再抄一份就是給它們製造第二個會走樣的來源。角色閘門（病患不得開單）在 router 用
`require_role("doctor", "admin")` 擋，與其他醫師專用端點一致。
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuditAction
from app.models.exam_order import ExamOrder
from app.schemas.exam_order import ExamOrderCreate
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)


class ExamOrderService:
    """檢查醫囑：建立（append-only）與讀取最新一張。"""

    @staticmethod
    async def create_order(
        db: AsyncSession,
        *,
        session_id: UUID,
        payload: ExamOrderCreate,
        current_user: Any,
    ) -> ExamOrder:
        """開立一張檢查單。

        每次送出都是新的一列，不 update 既有列——醫師可以重新勾選再送，以最新一張
        為準，舊的留著可回查（2026-09-09 使用者拍板）。
        """
        session = await SessionService().get_session(
            db, session_id, current_user=current_user
        )

        order = ExamOrder(
            session_id=session.id,
            report_id=payload.report_id,
            ordered_by=current_user.id,
            items=[item.model_dump(mode="json") for item in payload.items],
            note=payload.note,
        )
        db.add(order)
        await db.flush()

        # 稽核：開檢查單是臨床決策，要留下誰在什麼時候開了哪幾項。
        # 失敗不可擋住開單本身（同 report review / session 狀態轉移的既有作法）。
        try:
            from app.services.audit_log_service import AuditLogService

            await AuditLogService.log(
                db,
                user_id=current_user.id,
                action=AuditAction.CREATE,
                resource_type="exam_order",
                resource_id=str(order.id),
                details={
                    "session_id": str(session.id),
                    "report_id": str(payload.report_id) if payload.report_id else None,
                    "item_count": len(order.items),
                    "test_names": [i.get("test_name") for i in order.items],
                },
                language=session.language,
            )
        except Exception as exc:  # pragma: no cover - 稽核失敗不可擋臨床動作
            logger.warning(
                "檢查醫囑稽核寫入失敗（非致命，醫囑已建立）| order=%s, error=%s",
                order.id,
                exc,
            )

        await db.refresh(order)
        return order

    @staticmethod
    async def get_latest(
        db: AsyncSession,
        *,
        session_id: UUID,
        current_user: Any,
    ) -> Optional[ExamOrder]:
        """取這場次最新一張檢查單；沒開過回 None（不是 404——「還沒開」是正常狀態）。"""
        await SessionService().get_session(db, session_id, current_user=current_user)

        result = await db.execute(
            select(ExamOrder)
            .where(ExamOrder.session_id == session_id)
            .order_by(ExamOrder.created_at.desc(), ExamOrder.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
