"""
守護 ADMIN-9 self-deactivation guard 的 i18n 化（I18N-keys wave）。

先前 toggle_active 對「管理員切換自己」的守護是硬寫純中文字串
（'無法變更自己的帳號啟用狀態'），英文 / 其他 locale 也會原樣回傳中文。
改為 raise i18n key `errors.cannot_toggle_self`，交由 i18n_error_handler
依 Accept-Language 解譯。

這裡用純 Python stub（無真 DB），只驗：
- self-guard 在進 DB 前就 raise ForbiddenException
- 拋出的 message 是 i18n key（is_message_key 為真），而非純字面字串
- errors.cannot_toggle_self 在 ACTIVE_LANGUAGES 各 locale 都有翻譯且彼此不同
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.core.config import settings
from app.core.exceptions import ForbiddenException
from app.services.admin_service import AdminService
from app.utils.i18n_messages import MESSAGES, get_message, is_message_key


def _run(coro):
    """在 sync test 裡跑 coroutine，避免多裝 pytest-asyncio。"""
    return asyncio.run(coro)


class _FakeDB:
    """最小 AsyncSession 替身；self-guard 應在任何 execute 前就擋下。"""

    def __init__(self) -> None:
        self.execute_calls = 0

    async def execute(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        self.execute_calls += 1
        raise AssertionError("self-guard 應在進 DB 前就 raise，不該呼叫 execute")


def test_toggle_self_raises_i18n_key_not_literal():
    """管理員切換自己 → ForbiddenException，且 message 是 i18n key。"""
    admin_id = uuid.uuid4()
    db = _FakeDB()
    svc = AdminService()

    with pytest.raises(ForbiddenException) as exc_info:
        _run(svc.toggle_active(db, user_id=admin_id, toggled_by=admin_id))

    # 進 DB 前就擋下
    assert db.execute_calls == 0
    # message 必須是登錄在 MESSAGES 的 i18n key，而非硬寫字面字串
    assert exc_info.value.message == "errors.cannot_toggle_self"
    assert is_message_key(exc_info.value.message)


def test_cannot_toggle_self_key_registered_for_all_active_locales():
    """errors.cannot_toggle_self 在 ACTIVE_LANGUAGES 各 locale 都有非空翻譯。"""
    entry = MESSAGES["errors.cannot_toggle_self"]
    for locale in settings.ACTIVE_LANGUAGES:
        assert locale in entry, f"缺 {locale} 翻譯"
        assert entry[locale], f"{locale} 翻譯為空"


def test_cannot_toggle_self_localizes_differently_per_locale():
    """zh-TW / en-US 應解出不同語言字串（確認真的有在地化）。"""
    zh = get_message("errors.cannot_toggle_self", "zh-TW")
    en = get_message("errors.cannot_toggle_self", "en-US")
    assert zh == "無法變更自己的帳號啟用狀態"
    assert "account" in en.lower()
    assert zh != en


@pytest.mark.parametrize(
    "key",
    [
        "errors.patient_access_no_principal",
        "errors.patient_forbidden_other_doctor",
        "errors.patient_forbidden_role",
    ],
)
def test_newly_registered_patient_keys_cover_active_locales(key: str):
    """patient_service 發出的授權錯誤 key 不再 fallback 成原始 key 字串。"""
    assert is_message_key(key)
    entry = MESSAGES[key]
    for locale in settings.ACTIVE_LANGUAGES:
        assert locale in entry and entry[locale], f"{key} 缺 {locale} 翻譯"
