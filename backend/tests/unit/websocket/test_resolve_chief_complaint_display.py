"""_resolve_chief_complaint_display 單元測試（#6 場次語言解析 + #5「其他」sentinel）。

鎖定行為：
- 「其他」sentinel：名稱只是佔位詞，開場語必須改念病患自述（chief_complaint_text），
  任何語言場次皆然；自述為空（舊 client / 直接打 API）才落回一般解析，
  至少顯示在地化的「其他」。
- 非 sentinel 主訴行為不變：按場次語言解析 name_by_lang（#6 回歸）。
- 無主訴記錄 → None（呼叫端 fallback 回 chief_complaint_text）。
"""

from types import SimpleNamespace
from uuid import UUID

from app.websocket.conversation_handler import (
    OTHER_CHIEF_COMPLAINT_ID,
    _resolve_chief_complaint_display,
)


HEMATURIA_ID = "00000000-0000-4000-8000-0000000000c1"


def _session(cc, text=None, language="zh-TW"):
    return SimpleNamespace(
        chief_complaint=cc,
        chief_complaint_text=text,
        language=language,
    )


def _other_cc(id_value=OTHER_CHIEF_COMPLAINT_ID):
    return SimpleNamespace(
        id=id_value,
        name="其他",
        name_by_lang={"zh-TW": "其他", "en-US": "Other"},
    )


# ── 「其他」sentinel ──────────────────────────────────────────
def test_sentinel_returns_patient_text():
    s = _session(_other_cc(), text="睪丸腫了一顆")
    assert _resolve_chief_complaint_display(s) == "睪丸腫了一顆"


def test_sentinel_returns_patient_text_regardless_of_language():
    # 自述是病患原話，不做語言解析——任何語言場次都原樣回傳
    s = _session(_other_cc(), text="left side hurts", language="en-US")
    assert _resolve_chief_complaint_display(s) == "left side hurts"


def test_sentinel_with_uuid_object_id_still_matches():
    # ORM 的 id 是 UUID 物件而非 str，特判必須以 str() 比對
    s = _session(_other_cc(id_value=UUID(OTHER_CHIEF_COMPLAINT_ID)), text="腰很痠")
    assert _resolve_chief_complaint_display(s) == "腰很痠"


def test_sentinel_empty_text_falls_back_to_localized_name():
    # 前端已擋空自述；防禦舊 client / 直接打 API → 至少顯示在地化「其他」
    s = _session(_other_cc(), text=None, language="en-US")
    assert _resolve_chief_complaint_display(s) == "Other"


def test_sentinel_whitespace_text_treated_as_empty():
    s = _session(_other_cc(), text="   ", language="en-US")
    assert _resolve_chief_complaint_display(s) == "Other"


# ── 非 sentinel（#6 回歸）───────────────────────────────────────
def test_regular_complaint_resolved_by_session_language():
    cc = SimpleNamespace(
        id=HEMATURIA_ID,
        name="血尿",
        name_by_lang={"zh-TW": "血尿", "en-US": "Hematuria"},
    )
    # 就算 chief_complaint_text 有值，非 sentinel 仍走語言解析（開場語要在地化名稱）
    s = _session(cc, text="血尿（三天了）", language="en-US")
    assert _resolve_chief_complaint_display(s) == "Hematuria"


def test_no_complaint_returns_none():
    assert _resolve_chief_complaint_display(_session(None, text="whatever")) is None
