"""
Unit tests for llm_conversation.format_messages 的 Supervisor 指導注入（#2）。

守護:
- 指導注入時必附「別重問」硬性護欄,且護欄涵蓋「已表示不知道」
- 護欄優先級高於指導(標題不再無條件「請優先執行」/「top priority」)
- fallback 佔位指導不得注入
- 兩個 guidance i18n key 在 5 語系皆有非空在地化字串
"""

from app.core.config import Settings
from app.pipelines.llm_conversation import LLMConversationEngine
from app.utils.i18n_messages import MESSAGES

_LOCALES = ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN")


def _system_prompt(guidance, language=None) -> str:
    engine = LLMConversationEngine(Settings())
    msgs = engine.format_messages(
        history=[{"role": "patient", "content": "我真的不知道"}],
        system_prompt="BASE",
        supervisor_guidance=guidance,
        language=language,
    )
    return msgs[0]["content"]


def test_guidance_injects_hard_guardrail_zh():
    sp = _system_prompt({"next_focus": "請詢問症狀持續時間"}, "zh-TW")
    assert "請詢問症狀持續時間" in sp
    assert "硬性護欄" in sp
    assert "不知道" in sp
    assert "請優先執行" not in sp


def test_guidance_injects_hard_guardrail_en():
    sp = _system_prompt({"next_focus": "Ask about duration"}, "en-US")
    assert "Hard guardrail" in sp
    assert "do not know" in sp
    assert "top priority" not in sp


def test_fallback_guidance_not_injected():
    assert _system_prompt({"next_focus": "x", "fallback": True}, "zh-TW") == "BASE"


def test_empty_next_focus_not_injected():
    assert _system_prompt({"next_focus": ""}, "zh-TW") == "BASE"


def test_guidance_i18n_keys_localized_for_all_locales():
    for key in ("llm.supervisor_guidance_section", "llm.supervisor_guidance_no_repeat"):
        entry = MESSAGES[key]
        for locale in _LOCALES:
            assert entry.get(locale), f"{key} 缺 {locale}"
