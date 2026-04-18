"""
守護 `app.utils.i18n_messages` 的基本行為：

- 已支援語言（zh-TW / en-US）可拿到對應翻譯
- 不支援 / None language → fallback 到 settings.DEFAULT_LANGUAGE
- 未知 key 不 raise，回退 placeholder 字串
- fmt_kwargs 套用成功，且格式失敗不 crash
- 每個 key 在所有 SUPPORTED_LANGUAGES 都要有翻譯（避免上線後才發現缺譯）
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.utils.i18n_messages import MESSAGES, get_message


def test_zh_tw_rule_match_reason_renders():
    msg = get_message("alert.rule_match_reason", "zh-TW", keyword="發燒")
    assert msg == "關鍵字比對：「發燒」"


def test_en_us_rule_match_reason_renders():
    msg = get_message("alert.rule_match_reason", "en-US", keyword="fever")
    assert msg == 'Keyword match: "fever"'


def test_unsupported_language_falls_back_to_default():
    # fr-FR 不在 SUPPORTED_LANGUAGES → 使用 DEFAULT_LANGUAGE
    msg = get_message("alert.rule_match_reason", "fr-FR", keyword="fever")
    if settings.DEFAULT_LANGUAGE == "zh-TW":
        assert "關鍵字比對" in msg
    else:
        assert "Keyword match" in msg


def test_none_language_falls_back_to_default():
    msg = get_message("alert.unknown_title", None)
    assert msg == MESSAGES["alert.unknown_title"][settings.DEFAULT_LANGUAGE]


def test_unknown_key_returns_placeholder_and_does_not_raise():
    msg = get_message("does.not.exist", "zh-TW")
    assert msg.startswith("[missing:")
    assert "does.not.exist" in msg


def test_missing_fmt_kwarg_does_not_crash():
    """模板需要 {keyword} 但沒傳；應回退到未格式化版本而非 raise。"""
    msg = get_message("alert.rule_match_reason", "zh-TW")
    # 未格式化仍包含 placeholder literal
    assert "{keyword}" in msg


def test_combined_trigger_reason_en_us():
    msg = get_message(
        "alert.combined_trigger_reason",
        "en-US",
        rule_reason='Keyword match: "hematuria"',
        semantic_reason="LLM: possible malignancy",
    )
    assert msg.startswith("[Rule]")
    assert "[Semantic]" in msg


def test_soap_language_instruction_zh_mentions_traditional_chinese():
    msg = get_message("llm.soap_language_instruction", "zh-TW")
    assert "繁體中文" in msg


def test_soap_language_instruction_en_mentions_english():
    msg = get_message("llm.soap_language_instruction", "en-US")
    assert "English" in msg


def test_red_flag_language_instruction_both_locales_exist():
    zh = get_message("llm.red_flag_language_instruction", "zh-TW")
    en = get_message("llm.red_flag_language_instruction", "en-US")
    assert "繁體中文" in zh
    assert "English" in en


def test_initial_greeting_substitutes_chief_complaint():
    zh = get_message("ws.initial_greeting", "zh-TW", chief_complaint="血尿")
    en = get_message("ws.initial_greeting", "en-US", chief_complaint="hematuria")
    assert "血尿" in zh
    assert "hematuria" in en
    # 中英文應該明顯不同（英文模板不會含中文字）
    assert "泌尿科" not in en


@pytest.mark.parametrize("key", sorted(MESSAGES.keys()))
def test_every_key_has_every_active_locale(key: str):
    """每個 key 都必須涵蓋 ACTIVE_LANGUAGES 的所有 locale，避免缺譯。

    Beta locale（ja-JP / ko-KR / vi-VN）為 best-effort — 允許缺譯並 fallback
    至 DEFAULT_LANGUAGE，待 add_new_language.md runbook 跑完補齊。
    """
    entry = MESSAGES[key]
    for locale in settings.ACTIVE_LANGUAGES:
        assert locale in entry, (
            f"i18n key {key!r} 缺 {locale} 翻譯；"
            f"ACTIVE_LANGUAGES={settings.ACTIVE_LANGUAGES}"
        )
        assert entry[locale], f"i18n key {key!r} 的 {locale} 翻譯為空"
