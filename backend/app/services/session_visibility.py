"""已軟刪除場次的可見性 —— 所有讀 Session 的 query 共用這一支。

2026-08-23：admin 可軟刪除問診場次（`sessions.is_deleted`）。軟刪除的價值完全
取決於「有沒有漏掉一條讀取路徑」——漏一條，已刪場次就從那裡漏回畫面（而且是
使用者以為已經刪掉的病歷內容）。所以條件只寫在這裡一份，各 service 一律 import，
不要在各自檔案裡手寫 `Session.is_deleted.is_(False)`。

兩種用法：
    stmt = stmt.where(session_not_deleted())          # 已經 select(Session) 的 query
    stmt = stmt.where(SOAPReport.session_id.in_(visible_session_ids()))  # 子查詢限縮

⚠️ 唯一該繞過它的地方是軟刪除本身（要能對已刪場次冪等）與 DB 層救援腳本。
"""

from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.sql.elements import ColumnElement

from app.models.session import Session


def session_not_deleted() -> ColumnElement[bool]:
    """`WHERE sessions.is_deleted = false`。每次呼叫回新的運算式。"""
    return Session.is_deleted.is_(False)


def visible_session_ids() -> Select:
    """未刪除場次的 id 子查詢（給 `IN (...)` 限縮用）。"""
    return select(Session.id).where(session_not_deleted())
