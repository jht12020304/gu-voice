"""
對話紀錄服務
- 建立對話輪次
- 查詢場次對話歷史
"""

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.conversation import Conversation
from app.models.session import Session
from app.utils.datetime_utils import utc_now


class ConversationService:
    """對話紀錄業務邏輯"""

    @staticmethod
    async def create(
        db: AsyncSession,
        session_id: UUID,
        role: str,
        content_text: str,
        audio_url: Optional[str] = None,
        audio_duration: Optional[float] = None,
        stt_confidence: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Conversation:
        """
        建立新的對話紀錄

        Args:
            db: 資料庫 session
            session_id: 場次 ID
            role: 對話角色（patient / assistant / system）
            content_text: 文字內容
            audio_url: 語音檔案 URL
            audio_duration: 語音時長（秒）
            stt_confidence: STT 信心分數（0~1）
            metadata: 擴充欄位（引擎資訊等）

        Returns:
            新建的 Conversation 物件
        """
        # 計算下一個序號前先拿 transaction-scoped advisory lock 序列化同 session 的寫入。
        # 沒這個 lock：兩個併發 WS 訊息會各自讀到同樣 MAX(seq)，然後都寫 seq+1，
        # 觸發 BEFORE INSERT trigger `conversations_check_seq_unique_trg` 回 IntegrityError。
        # Lock key：hashtext(session_id)，精度雖有微量碰撞風險但對「序列化同一 session」
        # 已足夠；pg_advisory_xact_lock 會在 commit/rollback 時自動釋放。
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:sid))"),
            {"sid": str(session_id)},
        )

        # 計算下一個序號
        max_seq_result = await db.execute(
            select(func.coalesce(func.max(Conversation.sequence_number), 0))
            .where(Conversation.session_id == session_id)
        )
        next_sequence = (max_seq_result.scalar() or 0) + 1

        conversation = Conversation(
            session_id=session_id,
            sequence_number=next_sequence,
            role=role,
            content_text=content_text,
            audio_url=audio_url,
            audio_duration_seconds=audio_duration,
            stt_confidence=stt_confidence,
            red_flag_detected=False,
            metadata=metadata,
            created_at=utc_now(),
        )
        db.add(conversation)
        await db.flush()
        return conversation

    @staticmethod
    async def get_by_session(
        db: AsyncSession,
        session_id: UUID,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        取得場次的對話紀錄列表（Cursor-based 分頁）

        Args:
            session_id: 場次 ID
            cursor: 分頁游標（上一頁最後一筆的 ID）
            limit: 每頁筆數

        Returns:
            包含 data、pagination 的字典
        """
        limit = min(limit, 100)

        query = (
            select(Conversation)
            .where(Conversation.session_id == session_id)
            .order_by(Conversation.sequence_number.asc())
        )

        if cursor:
            result = await db.execute(
                select(Conversation).where(Conversation.id == cursor)
            )
            cursor_record = result.scalar_one_or_none()
            if cursor_record:
                query = query.where(
                    Conversation.sequence_number > cursor_record.sequence_number
                )

        result = await db.execute(query.limit(limit + 1))
        conversations = result.scalars().all()

        has_more = len(conversations) > limit
        if has_more:
            conversations = conversations[:limit]

        count_result = await db.execute(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.session_id == session_id)
        )
        total_count = count_result.scalar() or 0

        return {
            "data": conversations,
            "pagination": {
                "next_cursor": str(conversations[-1].id) if has_more and conversations else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
        }

    @staticmethod
    async def get_by_id(db: AsyncSession, conversation_id: UUID) -> Conversation:
        """
        根據 ID 取得對話紀錄

        Raises:
            NotFoundException: 對話紀錄不存在
        """
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise NotFoundException("對話紀錄不存在")
        return conversation
