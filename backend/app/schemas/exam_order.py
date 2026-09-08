"""檢查醫囑 Pydantic Schema（快速開單頁）。"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExamOrderItem(BaseModel):
    """一筆勾選的檢查項目。

    欄位形狀刻意對齊 SOAP `plan.recommended_tests` 的元素（test_name / urgency /
    rationale），前端只要把勾到的那幾筆原樣送回來即可，不必再做一次對映。
    """

    test_name: str = Field(..., min_length=1, max_length=200, alias="testName")
    urgency: Optional[str] = Field(None, max_length=32)
    rationale: Optional[str] = Field(None, max_length=2000)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("test_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("檢查項目名稱不可為空白")
        return v


class ExamOrderCreate(BaseModel):
    """送出一張檢查單。

    `items` 允許空陣列——「醫師看過摘要、決定這次不開任何檢查」是有意義的臨床決策，
    與「還沒看」必須分得出來（見 ExamOrder 的 docstring）。
    """

    items: list[ExamOrderItem] = Field(default_factory=list, max_length=50)
    note: Optional[str] = Field(None, max_length=2000)
    report_id: Optional[UUID] = Field(None, alias="reportId")

    model_config = ConfigDict(populate_by_name=True)


class ExamOrderResponse(BaseModel):
    """一張檢查單。回應維持 snake_case，由前端 Dio interceptor 轉 camelCase。"""

    id: UUID
    session_id: UUID
    report_id: Optional[UUID] = None
    ordered_by: UUID
    items: list[ExamOrderItem] = Field(default_factory=list)
    note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
