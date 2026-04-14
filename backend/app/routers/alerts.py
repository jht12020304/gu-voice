"""
紅旗警示路由 — 警示管理、確認、規則管理
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.red_flag_alert import RedFlagAlert as RedFlagAlertModel

from app.core.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import AppException
from app.schemas.alert import (
    AcknowledgeAlertRequest,
    AcknowledgeAlertResponse,
    AlertDetail,
    AlertListResponse,
    RedFlagRuleCreate,
    RedFlagRuleDetail,
    RedFlagRuleListResponse,
    RedFlagRuleUpdate,
)
from app.services.alert_service import AlertService

router = APIRouter(prefix="/api/v1/alerts", tags=["紅旗警示"])

alert_service = AlertService()


# ── 警示管理 ────────────────────────────────────────────

@router.get(
    "",
    response_model=AlertListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得警示列表",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    severity: str | None = None,
    alert_type: str | None = None,
    is_acknowledged: bool | None = None,
    session_id: UUID | None = None,
    patient_id: UUID | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> AlertListResponse:
    """取得紅旗警示列表，支援依嚴重程度、確認狀態、場次等篩選。"""
    return await alert_service.list_alerts(
        db,
        cursor=cursor,
        limit=limit,
        severity=severity,
        alert_type=alert_type,
        is_acknowledged=is_acknowledged,
        session_id=session_id,
        patient_id=patient_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/rules",
    response_model=RedFlagRuleListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得紅旗規則列表",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def list_rules(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    severity: str | None = None,
    is_active: bool | None = True,
    category: str | None = None,
) -> RedFlagRuleListResponse:
    """取得所有紅旗警示觸發規則。"""
    return await alert_service.list_rules(
        db,
        cursor=cursor,
        limit=limit,
        severity=severity,
        is_active=is_active,
        category=category,
    )


@router.post(
    "/rules",
    response_model=RedFlagRuleDetail,
    status_code=status.HTTP_201_CREATED,
    summary="建立紅旗規則",
    dependencies=[Depends(require_role("admin"))],
)
async def create_rule(
    payload: RedFlagRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> RedFlagRuleDetail:
    """新增紅旗警示觸發規則。僅限管理員。"""
    return await alert_service.create_rule(
        db,
        data=payload,
        created_by=current_user.id,
    )


@router.get(
    "/unacknowledged/count",
    status_code=status.HTTP_200_OK,
    summary="取得未確認警示數量",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def get_unacknowledged_count(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict:
    """取得未確認紅旗警示的數量。"""
    result = await db.execute(
        select(func.count())
        .select_from(RedFlagAlertModel)
        .where(RedFlagAlertModel.acknowledged_by.is_(None))
    )
    return {"count": result.scalar() or 0}


@router.get(
    "/{alert_id}",
    response_model=AlertDetail,
    status_code=status.HTTP_200_OK,
    summary="取得警示詳情",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def get_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> AlertDetail:
    """取得指定紅旗警示的完整詳細資料。"""
    return await alert_service.get_alert(db, alert_id=alert_id)


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AcknowledgeAlertResponse,
    status_code=status.HTTP_200_OK,
    summary="確認警示",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def acknowledge_alert(
    alert_id: UUID,
    payload: AcknowledgeAlertRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> AcknowledgeAlertResponse:
    """醫師確認已查看並處理紅旗警示。"""
    acknowledge_notes = payload.acknowledge_notes if payload else None
    action_taken = payload.action_taken if payload else None
    return await alert_service.acknowledge_alert(
        db,
        alert_id=alert_id,
        acknowledged_by=current_user.id,
        acknowledge_notes=acknowledge_notes,
        action_taken=action_taken,
    )


@router.put(
    "/rules/{rule_id}",
    response_model=RedFlagRuleDetail,
    status_code=status.HTTP_200_OK,
    summary="更新紅旗規則",
    dependencies=[Depends(require_role("admin"))],
)
async def update_rule(
    rule_id: UUID,
    payload: RedFlagRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> RedFlagRuleDetail:
    """更新指定紅旗規則。僅限管理員。"""
    return await alert_service.update_rule(
        db,
        rule_id=rule_id,
        data=payload,
    )


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_200_OK,
    summary="刪除紅旗規則",
    dependencies=[Depends(require_role("admin"))],
)
async def delete_rule(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> None:
    """刪除指定紅旗規則（硬刪除）。僅限管理員。"""
    await alert_service.delete_rule(db, rule_id=rule_id)
