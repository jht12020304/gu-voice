"""Cursor 分頁共用小工具。"""

from typing import Optional
from uuid import UUID


def parse_cursor(cursor: Optional[str]) -> Optional[UUID]:
    """
    將 cursor 解析為 UUID。

    cursor 為「上一頁最後一筆的 id」（UUID 字串）。無法解析為合法 UUID 時
    保守視為「無 cursor」（回傳 None），避免把無效字串直接餵進 UUID 欄位比對
    （Postgres 會對垃圾字串回 500），同時維持既有「cursor 查不到對應 record
    即從頭分頁」的向後相容行為。
    """
    if not cursor:
        return None
    if isinstance(cursor, UUID):
        return cursor
    try:
        return UUID(str(cursor))
    except (ValueError, AttributeError, TypeError):
        return None
