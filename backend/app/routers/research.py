"""
研究分析路由 — 去識別化聚合指標（發表級研究儀表板用）。

僅回傳 aggregate 統計（計數、比例、分佈、描述統計），不含任何
病患層級可識別資料；權限限 doctor / admin。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_role
from app.schemas.research import ResearchAnalyticsResponse
from app.services.research_service import ResearchService

router = APIRouter(
    prefix="/api/v1/research",
    tags=["研究分析"],
    dependencies=[Depends(require_role("doctor", "admin"))],
)

research_service = ResearchService()


@router.get(
    "/analytics",
    response_model=ResearchAnalyticsResponse,
    status_code=status.HTTP_200_OK,
    summary="取得研究分析聚合指標",
)
async def get_research_analytics(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    date_from: date | None = Query(
        None, description="收案起日（依 session created_at，含當日）"
    ),
    date_to: date | None = Query(
        None, description="收案迄日（依 session created_at，含當日）"
    ),
) -> ResearchAnalyticsResponse:
    """
    回傳整個收案期間（或指定日期區間）的研究指標聚合：

    - cohort：收案流（CONSORT-style）與週趨勢
    - efficiency：問診時長 / 病患輪次 / 每輪字數（中位數 + IQR）
    - history_taking：SOAP HPI 10 欄完整度（AMIE 病史採集軸）
    - safety：紅旗率、嚴重度 / 偵測層分佈、偵測與確認延遲（triage 安全）
    - stt_quality：STT 信心分數分佈與低信心率（按語言）
    - documentation：AI 信心、ICD-10 驗證率、醫師審閱同意率（PDQI-9 proxy）
    - by_language：各語言子群摘要（table view）
    """
    return await research_service.get_analytics(
        db, date_from=date_from, date_to=date_to
    )
