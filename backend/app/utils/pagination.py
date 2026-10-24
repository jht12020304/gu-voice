"""Cursor 分頁共用小工具（所有清單 service 共用，別再各自複製）。"""

from typing import Any, Optional, Sequence
from uuid import UUID


def coerce_uuid(value: Any) -> Optional[UUID]:
    """寬鬆轉 UUID：UUID 原樣回傳、合法字串轉換、其餘（含 None／垃圾字串）回 None。"""
    if not value:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def parse_cursor(cursor: Optional[str]) -> Optional[UUID]:
    """
    將 cursor 解析為 UUID。

    cursor 為「上一頁最後一筆的 id」（UUID 字串）。無法解析為合法 UUID 時
    保守視為「無 cursor」（回傳 None），避免把無效字串直接餵進 UUID 欄位比對
    （Postgres 會對垃圾字串回 500），同時維持既有「cursor 查不到對應 record
    即從頭分頁」的向後相容行為。
    """
    return coerce_uuid(cursor)


def keyset_after(query: Any, cursor_record: Any, column: Any, id_column: Any, descending: bool = True) -> Any:
    """依排序方向套用 keyset 分頁條件（排序欄 + id tie-break），使 cursor 與 sort 一致。

    descending → 取「排在 cursor 之後」= column < cursor_value，tie 時 id < cursor_id。
    ascending  → column > cursor_value，tie 時 id > cursor_id。
    """
    cursor_value = getattr(cursor_record, column.key)
    cursor_id = getattr(cursor_record, id_column.key)
    if descending:
        return query.where(
            (column < cursor_value) | ((column == cursor_value) & (id_column < cursor_id))
        )
    return query.where(
        (column > cursor_value) | ((column == cursor_value) & (id_column > cursor_id))
    )


def page_slice(rows: Sequence[Any], limit: int) -> tuple[list[Any], bool, Optional[str]]:
    """「多取一筆判斷下一頁」的收尾：回 (本頁列, has_more, next_cursor)。"""
    rows = list(rows)
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    next_cursor = str(rows[-1].id) if has_more and rows else None
    return rows, has_more, next_cursor
