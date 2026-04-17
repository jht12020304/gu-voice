"""
後端使用者可見字串的集中化 i18n 表（Phase 3-1）。

目前兩個主要 callsites：
    1. RedFlagAlert 固定模板（rule-based fallback 規則觸發時寫入的 reason / description）
    2. SOAP / Red Flag LLM prompt 的輸出語言指示段（system prompt 尾段附加）

設計原則
--------
- 只集中「模板」；具體值（關鍵字、病患原文片段等）由 caller 以 format kwargs 傳入。
- 支援語言以 `settings.SUPPORTED_LANGUAGES` 為準；若 caller 傳入未支援語言，
  自動 fallback 至 `settings.DEFAULT_LANGUAGE`，不 raise。
- 若某 key 僅在某些語言有翻譯，以 DEFAULT_LANGUAGE 為權威版本進行補洞。
- 新增 key 時務必兩個 locale 都填；缺譯將在 unit test 中被 catch。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── 訊息表 ──────────────────────────────────────────────
# key 規則：`<domain>.<identifier>`，domain 建議為 alert / soap / llm / ws。
# 值為 `str`，可含 Python str.format 佔位符（使用 named placeholders 較易讀）。
MESSAGES: dict[str, dict[str, str]] = {
    # ── Alert / Red Flag 固定模板 ────────────────────
    "alert.rule_match_reason": {
        "zh-TW": "關鍵字比對：「{keyword}」",
        "en-US": "Keyword match: \"{keyword}\"",
    },
    "alert.regex_match_reason": {
        "zh-TW": "模式比對：「{match}」",
        "en-US": "Pattern match: \"{match}\"",
    },
    "alert.combined_trigger_reason": {
        "zh-TW": "[規則] {rule_reason} | [語意] {semantic_reason}",
        "en-US": "[Rule] {rule_reason} | [Semantic] {semantic_reason}",
    },
    "alert.unknown_title": {
        "zh-TW": "未知紅旗",
        "en-US": "Unknown red flag",
    },
    "alert.semantic_default_title": {
        "zh-TW": "語意偵測紅旗",
        "en-US": "Semantic-detected red flag",
    },
    "alert.push_notification_title": {
        "zh-TW": "紅旗警示: {title}",
        "en-US": "Red flag alert: {title}",
    },

    # ── LLM prompt 語言指示（附加在 system prompt 尾段） ───
    # 會被 wrap 在 prompt 末端，用來強制 LLM 以該語言輸出。
    "llm.soap_language_instruction": {
        "zh-TW": (
            "\n\n## 輸出語言（硬性規定）\n"
            "- 除 ICD-10 代碼外，所有文字欄位（chief_complaint、hpi 各欄、"
            "differential_diagnoses、clinical_impression、recommended_tests、"
            "treatments、medications、patient_education、referrals、"
            "follow_up、diagnostic_reasoning、summary 等）必須以 **繁體中文** 撰寫。\n"
            "- 不要在繁體中文欄位中混入英文原文（ICD-10 代碼除外）。"
        ),
        "en-US": (
            "\n\n## Output Language (Strict)\n"
            "- Except for ICD-10 codes, every text field "
            "(chief_complaint, hpi sub-fields, differential_diagnoses, "
            "clinical_impression, recommended_tests, treatments, medications, "
            "patient_education, referrals, follow_up, diagnostic_reasoning, "
            "summary, etc.) must be written in **US English**.\n"
            "- Do not mix Traditional Chinese into English fields "
            "(ICD-10 codes are exempt)."
        ),
    },
    "llm.red_flag_language_instruction": {
        "zh-TW": (
            "\n\n## 輸出語言（硬性規定）\n"
            "- title / description / suggested_actions 等欄位必須以 **繁體中文** 撰寫。\n"
            "- trigger_reason 請保持原文（病患原始陳述的語言），不要翻譯。"
        ),
        "en-US": (
            "\n\n## Output Language (Strict)\n"
            "- title / description / suggested_actions must be written in **US English**.\n"
            "- trigger_reason should preserve the original language "
            "(the patient's actual utterance), do not translate."
        ),
    },

    # ── Greeting（初始問診語） ───────────────────────
    "ws.initial_greeting": {
        "zh-TW": (
            "您好！我是泌尿科 AI 問診助手，今天將協助您進行初步問診。"
            "請問您的「{chief_complaint}」症狀是什麼時候開始的？"
        ),
        "en-US": (
            "Hello! I'm your urology AI intake assistant and I'll help with "
            "your initial assessment today. When did your \"{chief_complaint}\" "
            "symptom first start?"
        ),
    },
}


def _resolve_lang(lang: str | None) -> str:
    """將 caller 傳入的語言正規化到 SUPPORTED_LANGUAGES；不支援時 fallback default。"""
    if not lang:
        return settings.DEFAULT_LANGUAGE
    if lang in settings.SUPPORTED_LANGUAGES:
        return lang
    logger.debug(
        "i18n_messages: language %r not in SUPPORTED_LANGUAGES, fallback to %s",
        lang,
        settings.DEFAULT_LANGUAGE,
    )
    return settings.DEFAULT_LANGUAGE


def get_message(key: str, lang: str | None = None, **fmt_kwargs: Any) -> str:
    """
    取得本地化訊息。

    Args:
        key: MESSAGES 表中的 key（如 "alert.rule_match_reason"）。
        lang: BCP-47 語言碼，如 "zh-TW" / "en-US"；未傳或未支援時用預設。
        **fmt_kwargs: 套到模板的 named placeholders。

    Returns:
        已套上 kwargs 的訊息字串。

    Notes:
        - 找不到 key → log warning 並回 `f"[missing:{key}]"`，不 raise，
          避免一個未翻譯字串 crash 掉整個 pipeline。
        - 找得到 key 但該語言缺譯 → 退到 DEFAULT_LANGUAGE；若 default 也缺則同上。
    """
    entry = MESSAGES.get(key)
    if entry is None:
        logger.warning("i18n_messages: unknown key %r", key)
        return f"[missing:{key}]"

    resolved = _resolve_lang(lang)
    template = entry.get(resolved) or entry.get(settings.DEFAULT_LANGUAGE)
    if template is None:
        # 兩個 locale 都缺：取第一個有值的
        template = next(iter(entry.values()), None)
    if template is None:
        logger.warning("i18n_messages: key %r has no localized value", key)
        return f"[missing:{key}]"

    if not fmt_kwargs:
        return template

    try:
        return template.format(**fmt_kwargs)
    except (KeyError, IndexError) as exc:
        logger.warning(
            "i18n_messages: format failed for key=%r, lang=%s, kwargs=%s, error=%s",
            key,
            resolved,
            list(fmt_kwargs.keys()),
            exc,
        )
        return template  # 保留未格式化版本，至少不 crash


__all__ = ["MESSAGES", "get_message"]
