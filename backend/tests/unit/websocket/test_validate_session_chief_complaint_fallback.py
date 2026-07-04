"""E8-2 回歸測試：`_validate_session` 的 chief_complaint fallback 不可洩漏 ORM 物件。

根因：建場次不帶 `chief_complaint_text`（只有 `chief_complaint_id`）時，舊版
fallback 成 `getattr(session_obj, "chief_complaint", "")`——那其實是
`selectinload` 載入的整個 ChiefComplaint ORM 關聯物件，不是字串。之後
`shared.py` 的 `get_red_flags_for_complaint` 對它做 `cc in chief_complaint`
substring 比對會直接 TypeError，導致整個問診 WS 開場直接 internal_error 掛掉
（e2e_realopenai_findings 2026-06-28）。

修法：fallback 改沿用 #6 的場次語言解析（`name_by_lang` → `name`），最終保證
`session_context["chief_complaint"]` 一定是字串（含空字串）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.websocket.conversation_handler as ch

HEMATURIA_ID = "00000000-0000-4000-8000-0000000000c1"


class _FakeExecResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeDB:
    """最小 AsyncSession 替身：`execute()` 直接回傳預先塞好的 ORM 物件。"""

    def __init__(self, obj):
        self._obj = obj

    async def execute(self, stmt):
        return _FakeExecResult(self._obj)


def _session_obj(chief_complaint_text=None, cc=None, language="zh-TW"):
    return SimpleNamespace(
        id=uuid4(),
        status="waiting",
        chief_complaint_text=chief_complaint_text,
        chief_complaint=cc,
        patient=None,
        intake_data=None,
        language=language,
    )


def _hematuria_cc():
    return SimpleNamespace(
        id=HEMATURIA_ID,
        name="血尿",
        name_by_lang={"zh-TW": "血尿", "en-US": "Hematuria"},
    )


def test_missing_text_falls_back_to_localized_name_string_not_orm_object():
    """建場次不帶 chief_complaint_text（只有 chief_complaint_id）→ chief_complaint
    欄位必須解析成字串（依場次語言的 name_by_lang），絕不能是 ORM 物件本身。"""
    session_obj = _session_obj(chief_complaint_text=None, cc=_hematuria_cc(), language="en-US")
    result = asyncio.run(
        ch._validate_session(str(session_obj.id), _FakeDB(session_obj))
    )
    assert result is not None
    assert isinstance(result["chief_complaint"], str)
    assert result["chief_complaint"] == "Hematuria"
    assert result["chief_complaint_display"] == "Hematuria"


def test_missing_text_and_no_relation_falls_back_to_empty_string():
    """chief_complaint_text 與 chief_complaint 關聯都缺（極端防禦情境）
    → 空字串，絕不是 None 或 ORM 物件。"""
    session_obj = _session_obj(chief_complaint_text=None, cc=None)
    result = asyncio.run(
        ch._validate_session(str(session_obj.id), _FakeDB(session_obj))
    )
    assert result is not None
    assert result["chief_complaint"] == ""
    assert result["chief_complaint_display"] is None


def test_present_text_still_wins_over_localized_name():
    """chief_complaint_text 有值時仍優先採用（病患實際輸入 / 既有行為不變）。"""
    session_obj = _session_obj(chief_complaint_text="血尿（三天了）", cc=_hematuria_cc())
    result = asyncio.run(
        ch._validate_session(str(session_obj.id), _FakeDB(session_obj))
    )
    assert result is not None
    assert result["chief_complaint"] == "血尿（三天了）"
    # display 仍走場次語言解析（給開場問診語用），與 #6 既有行為一致
    assert result["chief_complaint_display"] == "血尿"


def test_resolved_chief_complaint_is_usable_by_shared_red_flag_lookup():
    """端到端銜接：_validate_session 產出的 chief_complaint 丟進
    get_red_flags_for_complaint 不得 TypeError（回歸鎖：曾經是 ORM 物件時會炸）。"""
    from app.pipelines.prompts.shared import get_red_flags_for_complaint

    session_obj = _session_obj(chief_complaint_text=None, cc=_hematuria_cc())
    result = asyncio.run(
        ch._validate_session(str(session_obj.id), _FakeDB(session_obj))
    )
    flags = get_red_flags_for_complaint(result["chief_complaint"])
    titles = {f["title"] for f in flags}
    assert "大量血尿" in titles
