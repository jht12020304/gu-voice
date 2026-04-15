"""
病患管理路由 — 病患 CRUD 與場次歷史
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import AppException
from app.schemas.patient import (
    PatientCreate,
    PatientDetail,
    PatientListResponse,
    PatientUpdate,
)
from app.schemas.session import SessionListResponse
from app.services.patient_service import PatientService

router = APIRouter(prefix="/api/v1/patients", tags=["病患管理"])

patient_service = PatientService()


@router.post(
    "",
    response_model=PatientDetail,
    status_code=status.HTTP_201_CREATED,
    summary="建立病患",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def create_patient(
    payload: PatientCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> PatientDetail:
    """由醫師或管理員手動建立病患資料。"""
    return await patient_service.create_patient(
        db,
        data=payload,
        created_by=current_user.id,
    )


@router.get(
    "",
    response_model=PatientListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得病患列表",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def list_patients(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    search: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    gender: str | None = None,
    age_from: int | None = None,
    age_to: int | None = None,
    has_active_session: bool | None = None,
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
) -> PatientListResponse:
    """取得病患列表，支援以姓名、病歷號碼搜尋，以及多條件篩選。"""
    return await patient_service.list_patients(
        db,
        cursor=cursor,
        limit=limit,
        search=search,
        created_from=created_from,
        created_to=created_to,
        gender=gender,
        age_from=age_from,
        age_to=age_to,
        has_active_session=has_active_session,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/{patient_id}",
    response_model=PatientDetail,
    status_code=status.HTTP_200_OK,
    summary="取得病患詳情",
)
async def get_patient(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> PatientDetail:
    """取得指定病患的完整資料。病患僅可查看自己的資料。"""
    return await patient_service.get_patient(
        db,
        patient_id=patient_id,
        current_user=current_user,
    )


@router.put(
    "/{patient_id}",
    response_model=PatientDetail,
    status_code=status.HTTP_200_OK,
    summary="更新病患資料",
)
async def update_patient(
    patient_id: UUID,
    payload: PatientUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> PatientDetail:
    """更新指定病患的資料。病患僅可更新自己的資料。"""
    return await patient_service.update_patient(
        db,
        patient_id=patient_id,
        data=payload,
        current_user=current_user,
    )


@router.delete(
    "/{patient_id}",
    status_code=status.HTTP_200_OK,
    summary="軟刪除病患",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def delete_patient(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> None:
    """軟刪除指定病患（設定 is_active 為 False）。"""
    await patient_service.soft_delete_patient(
        db,
        patient_id=patient_id,
        deleted_by=current_user.id,
    )


@router.get(
    "/{patient_id}/sessions",
    response_model=SessionListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得病患場次歷史",
)
async def get_patient_sessions(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    date_from: str | None = None,
    date_to: str | None = None,
) -> SessionListResponse:
    """取得指定病患的所有問診場次記錄。病患僅可查看自己的場次。"""
    return await patient_service.get_patient_sessions(
        db,
        patient_id=patient_id,
        current_user=current_user,
        cursor=cursor,
        limit=limit,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
    )
