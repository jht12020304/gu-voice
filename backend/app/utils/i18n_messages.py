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
    # ── Errors（router / service 層 exception 使用者可見訊息） ─
    # 命名規則：errors.<domain>.<reason>；format kwargs 使用 named placeholders。
    # 所有 `AppException.message_key` 皆在此查表 → i18n_error_handler 負責解譯。
    "errors.unauthorized": {
        "zh-TW": "未認證或 Token 已過期",
        "en-US": "Not authenticated or token expired",
    },
    "errors.invalid_auth_header": {
        "zh-TW": "Authorization header 格式錯誤",
        "en-US": "Invalid authorization header format",
    },
    "errors.token_invalid_or_expired": {
        "zh-TW": "Token 無效或已過期",
        "en-US": "Token is invalid or expired",
    },
    "errors.token_payload_missing_sub": {
        "zh-TW": "Token payload 缺少 sub",
        "en-US": "Token payload missing subject",
    },
    "errors.token_revoked": {
        "zh-TW": "Token 已失效",
        "en-US": "Token has been revoked",
    },
    "errors.token_payload_incomplete": {
        "zh-TW": "Token payload 不完整",
        "en-US": "Token payload is incomplete",
    },
    "errors.refresh_token_invalid": {
        "zh-TW": "Refresh token 無效或已過期",
        "en-US": "Refresh token is invalid or expired",
    },
    "errors.refresh_token_reused": {
        "zh-TW": "Refresh token 重複使用，請重新登入",
        "en-US": "Refresh token reuse detected; please sign in again",
    },
    "errors.password_reset_link_invalid": {
        "zh-TW": "重設密碼連結已過期或無效",
        "en-US": "Password reset link is expired or invalid",
    },
    "errors.forbidden": {
        "zh-TW": "權限不足",
        "en-US": "Permission denied",
    },
    "errors.account_disabled": {
        "zh-TW": "帳號已停用",
        "en-US": "Account has been disabled",
    },
    "errors.role_required": {
        "zh-TW": "需要角色: {roles}",
        "en-US": "Required role: {roles}",
    },
    "errors.session_access_no_principal": {
        "zh-TW": "缺少認證主體，無法判定場次存取權限",
        "en-US": "Missing authenticated principal; cannot authorize session access",
    },
    "errors.session_list_no_principal": {
        "zh-TW": "缺少認證主體，無法列出場次",
        "en-US": "Missing authenticated principal; cannot list sessions",
    },
    "errors.session_unknown_role": {
        "zh-TW": "未知角色，無法列出場次",
        "en-US": "Unknown role; cannot list sessions",
    },
    "errors.session_forbidden_other_doctor": {
        "zh-TW": "此場次已由其他醫師負責",
        "en-US": "This session is already assigned to another doctor",
    },
    "errors.session_forbidden_patient": {
        "zh-TW": "您沒有權限存取此場次",
        "en-US": "You do not have permission to access this session",
    },
    "errors.session_unknown_role_access": {
        "zh-TW": "未知角色，拒絕存取",
        "en-US": "Unknown role; access denied",
    },
    "errors.assign_doctor_conflict": {
        "zh-TW": "此場次已由其他醫師負責，無法重新指派",
        "en-US": "This session is already assigned to another doctor; cannot reassign",
    },
    "errors.assign_doctor_role_required": {
        "zh-TW": "僅 doctor / admin 可指派醫師",
        "en-US": "Only doctor or admin can assign a doctor",
    },
    "errors.session_patient_unresolved": {
        "zh-TW": "無法決定場次對應的病患",
        "en-US": "Cannot determine the patient associated with this session",
    },
    "errors.session_not_found": {
        "zh-TW": "場次不存在",
        "en-US": "Session not found",
    },
    "errors.session_not_active": {
        "zh-TW": "場次非活躍狀態",
        "en-US": "Session is not active",
    },
    "errors.invalid_status_transition": {
        "zh-TW": "不合法的狀態轉移",
        "en-US": "Invalid status transition",
    },
    "errors.status_transition_not_allowed": {
        "zh-TW": "無法從 {current} 轉移至 {target}",
        "en-US": "Cannot transition from {current} to {target}",
    },
    "errors.report_not_found": {
        "zh-TW": "報告不存在",
        "en-US": "Report not found",
    },
    "errors.report_not_ready": {
        "zh-TW": "報告尚未產生完成",
        "en-US": "Report is not ready yet",
    },
    "errors.report_already_exists": {
        "zh-TW": "報告已存在",
        "en-US": "Report already exists",
    },
    "errors.alert_not_found": {
        "zh-TW": "警示不存在",
        "en-US": "Alert not found",
    },
    "errors.alert_already_acknowledged": {
        "zh-TW": "警示已確認",
        "en-US": "Alert has already been acknowledged",
    },
    "errors.red_flag_rule_not_found": {
        "zh-TW": "紅旗規則不存在",
        "en-US": "Red flag rule not found",
    },
    "errors.complaint_not_found": {
        "zh-TW": "主訴不存在",
        "en-US": "Chief complaint not found",
    },
    "errors.notification_not_found": {
        "zh-TW": "通知不存在",
        "en-US": "Notification not found",
    },
    "errors.patient_not_found": {
        "zh-TW": "病患不存在",
        "en-US": "Patient not found",
    },
    "errors.conversation_not_found": {
        "zh-TW": "對話紀錄不存在",
        "en-US": "Conversation record not found",
    },
    "errors.audit_log_not_found": {
        "zh-TW": "稽核日誌不存在",
        "en-US": "Audit log not found",
    },
    "errors.user_not_found": {
        "zh-TW": "使用者不存在",
        "en-US": "User not found",
    },
    "errors.not_found": {
        "zh-TW": "資源不存在",
        "en-US": "Resource not found",
    },
    "errors.validation_failed": {
        "zh-TW": "請求參數驗證失敗",
        "en-US": "Request validation failed",
    },
    "errors.conflict": {
        "zh-TW": "資源衝突",
        "en-US": "Resource conflict",
    },
    "errors.invalid_credentials": {
        "zh-TW": "帳號或密碼錯誤",
        "en-US": "Invalid credentials",
    },
    "errors.current_password_incorrect": {
        "zh-TW": "目前密碼不正確",
        "en-US": "Current password is incorrect",
    },
    "errors.email_already_exists": {
        "zh-TW": "Email 已註冊",
        "en-US": "Email is already registered",
    },
    "errors.ai_service_unavailable": {
        "zh-TW": "AI 服務不可用",
        "en-US": "AI service is unavailable",
    },
    "errors.ai_chat_unavailable": {
        "zh-TW": "AI 對話服務暫時不可用，請稍後重試",
        "en-US": "AI chat service is temporarily unavailable; please retry later",
    },
    "errors.soap_generation_bad_format": {
        "zh-TW": "SOAP 報告生成失敗：回應格式異常",
        "en-US": "SOAP report generation failed: unexpected response format",
    },
    "errors.soap_generation_unavailable": {
        "zh-TW": "SOAP 報告生成服務暫時不可用，請稍後重試",
        "en-US": "SOAP report generation is temporarily unavailable; please retry later",
    },
    "errors.rate_limit_exceeded": {
        "zh-TW": "超過速率限制",
        "en-US": "Rate limit exceeded",
    },
    "errors.login_ip_rate_limited": {
        "zh-TW": "登入嘗試過於頻繁，請於 {retry_after} 秒後再試",
        "en-US": "Too many login attempts; please retry in {retry_after} seconds",
    },
    "errors.account_locked": {
        "zh-TW": "帳號因連續登入失敗已暫時鎖定，請於 {retry_after} 秒後再試",
        "en-US": "Account is temporarily locked due to repeated failures; please retry in {retry_after} seconds",
    },
    "errors.llm_rate_limited": {
        "zh-TW": "AI 呼叫過於頻繁，請於 {retry_after} 秒後再試",
        "en-US": "AI calls are too frequent; please retry in {retry_after} seconds",
    },
    "errors.internal_error": {
        "zh-TW": "內部伺服器錯誤",
        "en-US": "Internal server error",
    },
    "errors.dashboard_date_format": {
        "zh-TW": "date 必須為 YYYY-MM-DD",
        "en-US": "date must be in YYYY-MM-DD format",
    },
    "errors.dashboard_month_format": {
        "zh-TW": "month 必須為 YYYY-MM",
        "en-US": "month must be in YYYY-MM format",
    },

    # ── Auth 成功訊息（MessageResponse body） ─────────
    "messages.logout_success": {
        "zh-TW": "登出成功",
        "en-US": "Logged out successfully",
    },
    "messages.password_changed": {
        "zh-TW": "密碼變更成功",
        "en-US": "Password changed successfully",
    },
    "messages.password_reset_link_sent": {
        "zh-TW": "若此電子郵件已註冊，密碼重設連結已寄出",
        "en-US": "If this email is registered, a password reset link has been sent",
    },
    "messages.password_reset_success": {
        "zh-TW": "密碼重設成功，請使用新密碼登入",
        "en-US": "Password reset successful; please sign in with your new password",
    },

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


def is_message_key(candidate: str | None) -> bool:
    """判斷字串是否為登錄在 MESSAGES 的 key（供 exception handler 辨識 i18n 標記）。"""
    if not candidate or not isinstance(candidate, str):
        return False
    return candidate in MESSAGES


__all__ = ["MESSAGES", "get_message", "is_message_key"]
