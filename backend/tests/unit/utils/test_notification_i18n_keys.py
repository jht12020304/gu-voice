"""
守護站內通知 i18n keys（session_data_inventory §11-7 修復）：

doctor-facing 通知以醫師 preferred_language 解析，5 個支援語系都必須有翻譯
（缺譯會 fallback 到 DEFAULT_LANGUAGE，醫師會看到非母語通知）。
"""

from __future__ import annotations

import pytest

from app.utils.i18n_messages import MESSAGES, get_message

_NOTIFICATION_KEYS = [
    "notifications.session_complete.title",
    "notifications.session_complete.body",
    "notifications.report_ready.title",
    "notifications.report_ready.body",
]

_ALL_LOCALES = ["zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN"]


@pytest.mark.parametrize("key", _NOTIFICATION_KEYS)
def test_notification_keys_cover_all_locales(key: str):
    entry = MESSAGES.get(key)
    assert entry is not None, f"缺 key：{key}"
    for locale in _ALL_LOCALES:
        assert entry.get(locale), f"{key} 缺 {locale} 翻譯"


@pytest.mark.parametrize("locale", _ALL_LOCALES)
def test_body_templates_render_patient_name(locale: str):
    msg = get_message(
        "notifications.report_ready.body", locale, patient_name="王小明"
    )
    assert "王小明" in msg
    assert "{patient_name}" not in msg
