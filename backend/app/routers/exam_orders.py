"""檢查醫囑路由 —— 醫師「快速開單」頁用。

刻意獨立成一支 router 而不是塞進 sessions.py：這條是 2026-09-09 新加的並行流程，
現有的 SOAP 報告頁與審閱流程一行都不動（使用者要求），分檔之後兩邊的改動不會互相
牽連。掛在 `/sessions/{session_id}/exam-orders` 之下是因為醫囑的生命週期就綁著場次，
沒有跨場次列出所有醫囑的需求。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_role
from app.schemas.exam_order import ExamOrderCreate, ExamOrderResponse
from app.services.exam_order_service import ExamOrderService

router = APIRouter(prefix="/api/v1/sessions", tags=["檢查醫囑"])


@router.post(
    "/{session_id}/exam-orders",
    response_model=ExamOrderResponse,
    # ⚠️ 必須關掉。FastAPI 預設 by_alias=True，會把 ExamOrderItem 的 `test_name`
    # 用輸入用的 alias 吐成 `testName`，而同一份回應的頂層（session_id / created_at）
    # 沒有 alias 仍是 snake_case —— 一份 JSON 兩種命名。全站約定是「後端一律
    # snake_case，前端 Dio interceptor 負責轉 camelCase」；破了這條，前端就得對
    # 這一支寫特例。alias 只保留給輸入用（容忍沒經過 interceptor 的呼叫端）。
    response_model_by_alias=False,
    status_code=status.HTTP_201_CREATED,
    summary="開立檢查醫囑",
)
async def create_exam_order(
    session_id: UUID,
    payload: ExamOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
) -> ExamOrderResponse:
    """醫師從 AI 建議檢查勾選後送出。

    append-only：可以重新勾選再送，以最新一張為準，舊的留著可回查。
    `items` 允許空陣列＝「看過了，這次不開任何檢查」。
    """
    order = await ExamOrderService.create_order(
        db, session_id=session_id, payload=payload, current_user=current_user
    )
    return ExamOrderResponse.model_validate(order)


@router.get(
    "/{session_id}/exam-orders/latest",
    response_model=ExamOrderResponse | None,
    response_model_by_alias=False,  # 同上：回應一律 snake_case
    status_code=status.HTTP_200_OK,
    summary="取得最新一張檢查醫囑",
)
async def get_latest_exam_order(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
) -> ExamOrderResponse | None:
    """回最新一張；這場次還沒開過則回 `null`（200，不是 404）。"""
    order = await ExamOrderService.get_latest(
        db, session_id=session_id, current_user=current_user
    )
    return ExamOrderResponse.model_validate(order) if order is not None else None
