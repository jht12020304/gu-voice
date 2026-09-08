"""ExamOrder 檢查醫囑模型。

醫師在「快速開單」頁看完摘要後，從 SOAP `plan.recommended_tests` 勾選要開立的
檢查項目並確認送出，一次送出寫成一列。

**append-only：以最新一列為準。** 醫師可以重新勾選再送（2026-09-09 使用者拍板），
舊列全部留著可回查——與報告審閱、場次軟刪除同一種保守作法：臨床決策的變更軌跡
不覆寫。讀取一律取 `created_at` 最新的那一列（見 ExamOrderService.get_latest）。

`items` 存快照而不是外鍵：AI 建議的檢查項目是 LLM 生成的自由字串，院內沒有代碼表
可綁（2026-09-09 已與使用者確認先不綁）。把當下勾選的項目原文連同緊急度與理由一起
凍結在這裡，日後就算報告被重新生成、`plan` 內容整個換掉，也還原得出醫師當時到底
勾了什麼。
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.session import Session
    from app.models.soap_report import SOAPReport
    from app.models.user import User


class ExamOrder(Base):
    __tablename__ = "exam_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 開單當下依據的那份報告。報告可被重新生成，所以只是佐證用的弱關聯，
    # 報告若被刪除不連坐醫囑（醫師確實開過這張單這件事不會因此消失）。
    report_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soap_reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    ordered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # list[{test_name, urgency, rationale}]，順序即畫面順序。空陣列是合法值：
    # 「看過了，這次不開任何檢查」與「還沒看」在臨床上是兩件事，必須分得出來。
    items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    session: Mapped["Session"] = relationship("Session")
    report: Mapped[Optional["SOAPReport"]] = relationship("SOAPReport")
    orderer: Mapped["User"] = relationship("User", foreign_keys=[ordered_by])

    __table_args__ = (
        # 唯一的讀取樣式就是「這場次最新一張單」。不寫 DESC——Postgres 對 b-tree
        # 反向掃描一樣走索引，省掉在 class body 對 MappedColumn 呼叫 .desc() 的脆弱寫法。
        Index("ix_exam_orders_session_created", "session_id", "created_at"),
    )
