"""
raw_transcript 格式化的單一來源。

WS 結束路徑（conversation_handler._generate_soap_report_async）與 Celery
重生路徑（report_queue._async_generate）都必須產出**完全相同格式**的逐字稿
（`[patient] ...` / `[assistant] ...` 中性英文標籤，不隨場次語言變動）。
歷史教訓：兩處各自 inline 格式化曾漂移成「病患：/AI 助手：」vs `[patient]`，
下游（PDF 匯出、報告比對）無法穩定解析。任何格式調整只能改這裡。
"""

from __future__ import annotations

from typing import Any, Iterable


def format_raw_transcript(entries: Iterable[dict[str, Any]]) -> str:
    """把對話 entries（含 role / content 鍵）串成單一逐字稿文字。

    Args:
        entries: 對話列表；每筆至少含 `role`（patient / assistant / system）
            與 `content`。缺鍵時分別以 "unknown" / "" 補。

    Returns:
        `[role] content` 逐行串接的字串。
    """
    return "\n".join(
        f"[{entry.get('role', 'unknown')}] {entry.get('content', '')}"
        for entry in entries
    )
