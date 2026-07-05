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
    "errors.complaint_default_forbidden": {
        "zh-TW": "系統預設主訴僅限管理員修改或刪除",
        "en-US": "Only an administrator may modify or delete a system default chief complaint",
        "ja-JP": "システム既定の主訴は管理者のみが変更・削除できます",
        "ko-KR": "시스템 기본 주 증상은 관리자만 수정하거나 삭제할 수 있습니다",
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
    "errors.patient_access_no_principal": {
        "zh-TW": "缺少認證主體，無法判定病患存取權限",
        "en-US": "Missing authenticated principal; cannot authorize patient access",
    },
    "errors.patient_forbidden_other_doctor": {
        "zh-TW": "此病患已由其他醫師負責",
        "en-US": "This patient is assigned to another doctor",
    },
    "errors.patient_forbidden_role": {
        "zh-TW": "您沒有權限存取此病患",
        "en-US": "You do not have permission to access this patient",
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
    "errors.session_not_switchable": {
        "zh-TW": "目前場次狀態無法切換語言",
        "en-US": "Cannot switch language on a session in the current state",
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
    "errors.cannot_toggle_self": {
        "zh-TW": "無法變更自己的帳號啟用狀態",
        "en-US": "You cannot change the active status of your own account",
    },
    "errors.not_found": {
        "zh-TW": "資源不存在",
        "en-US": "Resource not found",
    },
    "errors.validation_failed": {
        "zh-TW": "請求參數驗證失敗",
        "en-US": "Request validation failed",
    },
    "errors.invalid_date_format": {
        "zh-TW": "日期格式無效，必須為 ISO-8601",
        "en-US": "Invalid date format; must be ISO-8601",
        "ja-JP": "日付の形式が無効です。ISO-8601 形式である必要があります",
        "ko-KR": "날짜 형식이 잘못되었습니다. ISO-8601 형식이어야 합니다",
    },
    "errors.invalid_severity": {
        "zh-TW": "警示嚴重度數值無效",
        "en-US": "Invalid alert severity value",
        "ja-JP": "アラートの重大度の値が無効です",
        "ko-KR": "경보 심각도 값이 잘못되었습니다",
    },
    "errors.invalid_status": {
        "zh-TW": "狀態數值無效",
        "en-US": "Invalid status value",
        "ja-JP": "ステータスの値が無効です",
        "ko-KR": "상태 값이 잘못되었습니다",
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

    # ── 站內通知（doctor-facing；以醫師 preferred_language 解析） ───
    "notifications.session_complete.title": {
        "zh-TW": "問診完成",
        "en-US": "Consultation completed",
        "ja-JP": "問診が完了しました",
        "ko-KR": "문진 완료",
        "vi-VN": "Hoàn tất buổi khám",
    },
    "notifications.session_complete.body": {
        "zh-TW": "病患 {patient_name} 的問診已完成，SOAP 報告生成中。",
        "en-US": "Consultation for {patient_name} is complete; the SOAP report is being generated.",
        "ja-JP": "{patient_name} さんの問診が完了しました。SOAP レポートを生成しています。",
        "ko-KR": "{patient_name} 환자의 문진이 완료되었습니다. SOAP 보고서를 생성 중입니다.",
        "vi-VN": "Buổi khám của bệnh nhân {patient_name} đã hoàn tất; báo cáo SOAP đang được tạo.",
    },
    "notifications.report_ready.title": {
        "zh-TW": "SOAP 報告已生成",
        "en-US": "SOAP report ready",
        "ja-JP": "SOAP レポートが完成しました",
        "ko-KR": "SOAP 보고서 생성 완료",
        "vi-VN": "Báo cáo SOAP đã sẵn sàng",
    },
    "notifications.report_ready.body": {
        "zh-TW": "病患 {patient_name} 的 SOAP 報告已生成，請審閱。",
        "en-US": "The SOAP report for {patient_name} is ready for review.",
        "ja-JP": "{patient_name} さんの SOAP レポートが完成しました。ご確認ください。",
        "ko-KR": "{patient_name} 환자의 SOAP 보고서가 준비되었습니다. 검토해 주세요.",
        "vi-VN": "Báo cáo SOAP của bệnh nhân {patient_name} đã sẵn sàng để xem xét.",
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
        "ja-JP": (
            "\n\n## 出力言語(必須)\n"
            "- ICD-10 コードを除き、すべての文字フィールド(chief_complaint、hpi の各項目、"
            "differential_diagnoses、clinical_impression、recommended_tests、"
            "treatments、medications、patient_education、referrals、"
            "follow_up、diagnostic_reasoning、summary など)は必ず**日本語**で記述してください。\n"
            "- 日本語フィールドに他言語の原文を混在させないでください(ICD-10 コードは例外)。"
        ),
        "ko-KR": (
            "\n\n## 출력 언어(필수)\n"
            "- ICD-10 코드를 제외한 모든 텍스트 필드(chief_complaint, hpi 하위 항목, "
            "differential_diagnoses, clinical_impression, recommended_tests, "
            "treatments, medications, patient_education, referrals, "
            "follow_up, diagnostic_reasoning, summary 등)는 반드시 **한국어**로 작성하세요.\n"
            "- 한국어 필드에 다른 언어 원문을 섞지 마세요(ICD-10 코드는 예외)."
        ),
        "vi-VN": (
            "\n\n## Ngôn ngữ đầu ra (bắt buộc)\n"
            "- Ngoại trừ mã ICD-10, mọi trường văn bản (chief_complaint, các mục hpi, "
            "differential_diagnoses, clinical_impression, recommended_tests, "
            "treatments, medications, patient_education, referrals, "
            "follow_up, diagnostic_reasoning, summary, v.v.) phải được viết bằng **tiếng Việt**.\n"
            "- Không xen nguyên văn ngôn ngữ khác vào các trường tiếng Việt "
            "(mã ICD-10 được miễn trừ)."
        ),
    },
    # 用於 LLMConversationEngine.build_system_prompt「角色定位」段，
    # 硬性規定 AI 問診助手以病患選擇的語言回覆，避免 Whisper 判對語言但 LLM 仍回中文。
    "llm.conversation_language_rule": {
        "zh-TW": "使用繁體中文與病患溝通",
        "en-US": "Communicate with the patient in US English",
        "ja-JP": "丁寧な日本語で患者とコミュニケーションを取ってください",
        "ko-KR": "정중한 한국어로 환자와 소통하세요",
        "vi-VN": "Giao tiếp với bệnh nhân bằng tiếng Việt trang trọng",
    },
    # 問診 prompt 中「偵測到紅旗時要提醒」的規則。情境＝院內候診（平板/Kiosk）：病患已在現場，
    # 故不講含糊的「盡速就醫」（病患會困惑是去門診還是等醫師），改為明確指示「立即告知現場
    # 櫃台/醫護人員」，以便儘快安排醫師處理。指令形式讓 LLM 用當下輸出語言組句。
    "llm.conversation_red_flag_alert_rule": {
        "zh-TW": (
            "若偵測紅旗，請在該次回覆結尾以繁體中文加上一句，提醒病患立即告知現場的櫃台"
            "或醫護人員，以便儘快安排醫師處理（語氣自然、沉穩不驚嚇病患，不要照抄固定範本）。"
        ),
        "en-US": (
            "If a red-flag symptom is detected, append one short sentence in US English "
            "at the end of your reply, telling the patient to notify the front desk or "
            "on-site clinical staff right away so a physician can attend to them quickly "
            "(natural, calm, non-alarming phrasing; do not copy a fixed template)."
        ),
        "ja-JP": (
            "レッドフラッグ症状を検知した場合は、返答の末尾に自然で落ち着いた日本語で、"
            "受付または現場の医療スタッフにすぐ伝えるよう促す一文を添えてください"
            "（患者を驚かせない言い回し、定型文を丸写ししないこと）。"
        ),
        "ko-KR": (
            "레드 플래그 증상이 감지되면, 답변 끝에 자연스럽고 차분한 한국어로 접수처나 "
            "현장 의료진에게 즉시 알리도록 안내하는 문장을 덧붙이세요"
            "(환자를 놀라게 하지 않는 표현, 정형 문장을 그대로 베끼지 마세요)."
        ),
        "vi-VN": (
            "Nếu phát hiện triệu chứng cờ đỏ, hãy thêm ở cuối câu trả lời một câu bằng "
            "tiếng Việt, nhắc bệnh nhân báo ngay cho quầy tiếp nhận hoặc nhân viên y tế "
            "tại chỗ để bác sĩ xử lý sớm (giọng tự nhiên, trấn an, không sao chép mẫu cố định)."
        ),
    },
    # #5：語音辨識只支援「場次語言」。病患問能否改台語/客語/方言/其他語言時，AI 不得宣稱聽得懂
    # （whisper-1 無法可靠辨識台語等），要親切說明並請對方改用場次語言或點文字輸入框打字。
    "llm.conversation_unsupported_speech_rule": {
        "zh-TW": (
            "語音辨識目前僅聽得懂本場次語言。若病患詢問能否改用台語、客語或其他方言／語言，"
            "請親切說明語音目前只能聽懂本場次語言，並請對方改用該語言說、或點畫面上的文字輸入框打字；"
            "切勿宣稱你聽得懂台語或其他方言／語言。"
        ),
        "en-US": (
            "Speech recognition currently understands only this session's language. If the "
            "patient asks to speak a dialect or another language, kindly explain that voice "
            "input only understands this session's language, and ask them to speak in it or "
            "use the on-screen text box; never claim you can understand a dialect or another language."
        ),
        "ja-JP": (
            "音声認識は現在この問診の言語しか聞き取れません。患者が方言や他の言語に切り替えたいと"
            "尋ねた場合は、音声は現在この言語しか理解できないと丁寧に説明し、その言語で話すか画面の"
            "テキスト入力欄に入力するよう促してください。方言や他の言語を聞き取れると主張しないでください。"
        ),
        "ko-KR": (
            "음성 인식은 현재 이 문진의 언어만 이해할 수 있습니다. 환자가 방언이나 다른 언어로 "
            "바꿔도 되는지 물으면, 음성은 현재 이 언어만 알아들을 수 있다고 친절히 설명하고 그 "
            "언어로 말하거나 화면의 텍스트 입력창에 입력하도록 안내하세요. 방언이나 다른 언어를 "
            "알아들을 수 있다고 주장하지 마세요."
        ),
        "vi-VN": (
            "Nhận dạng giọng nói hiện chỉ hiểu ngôn ngữ của buổi hỏi bệnh này. Nếu bệnh nhân "
            "hỏi có thể dùng phương ngữ hoặc ngôn ngữ khác không, hãy nhẹ nhàng giải thích rằng "
            "giọng nói chỉ hiểu ngôn ngữ hiện tại, và mời họ nói bằng ngôn ngữ đó hoặc gõ vào ô "
            "nhập văn bản trên màn hình; tuyệt đối không tuyên bố bạn hiểu được phương ngữ hay ngôn ngữ khác."
        ),
    },
    # Conversation handler format_messages 注入 Supervisor 指導時的區段標題。
    # 放 system prompt 內部不直接給病患看，但避免中文標題被 LLM 誤當輸出語言的訊號。
    "llm.supervisor_guidance_section": {
        "zh-TW": "## 👨‍⚕️ 來自資深醫師的即時指導（受下方護欄約束）",
        "en-US": "## 👨‍⚕️ Realtime guidance from the senior supervising physician (subject to the guardrail below)",
        "ja-JP": "## 👨‍⚕️ 上級指導医からのリアルタイム指導（下記のガードレールに従うこと）",
        "ko-KR": "## 👨‍⚕️ 선임 지도 전문의의 실시간 지도(아래 가드레일이 우선함)",
        "vi-VN": "## 👨‍⚕️ Hướng dẫn thời gian thực từ bác sĩ giám sát cấp cao (tuân theo rào chắn bên dưới)",
    },
    # #2：附在上面 Supervisor 指導之後的「別重問」硬性護欄，優先級高於指導本身。
    # Supervisor 指導為上一輪結果，常仍指向 AI 剛問過的題目；病患「已明確回答」或
    # 「已表示不知道／無法回答」皆視為已處理，LLM 不得換句話重問，直接接下一個面向。
    "llm.supervisor_guidance_no_repeat": {
        "zh-TW": "【硬性護欄，優先於上述指導】若上述指導所問的內容，病患在前面對話已明確回答過、或已表示不知道／記不得／無法回答，請勿以任何形式重問（包括換句話），直接接續尚未釐清的下一個面向。",
        "en-US": "[Hard guardrail — overrides the guidance above] If the patient has already clearly answered what the guidance above asks, or has said they do not know / cannot remember / cannot answer, do NOT ask it again in any form (including rephrasing) — move on to the next unclarified aspect.",
        "ja-JP": "【ハードガードレール：上記の指導より優先】上記の指導が尋ねる内容について、患者がすでに明確に回答している、または「分からない・覚えていない・答えられない」と述べている場合は、言い換えを含むいかなる形でも再質問せず、まだ明らかでない次の面に進んでください。",
        "ko-KR": "[하드 가드레일 — 위 지도보다 우선] 위 지도가 묻는 내용을 환자가 앞선 대화에서 이미 명확히 답했거나 모른다·기억나지 않는다·답할 수 없다고 밝혔다면, 표현을 바꾸는 것을 포함해 어떤 형태로도 다시 묻지 말고 아직 확인되지 않은 다음 측면으로 넘어가세요.",
        "vi-VN": "[Rào chắn cứng — ưu tiên hơn hướng dẫn ở trên] Nếu bệnh nhân đã trả lời rõ nội dung mà hướng dẫn trên hỏi, hoặc đã nói không biết / không nhớ / không thể trả lời, thì KHÔNG hỏi lại dưới bất kỳ hình thức nào (kể cả diễn đạt lại) — hãy chuyển sang khía cạnh tiếp theo chưa được làm rõ.",
    },
    # 問診自動收尾指示（本輪限定，僅在 should_conclude 時由 format_messages 附加到 system prompt）。
    # 目的：HPI 完整度達標或達回合硬上限時，讓 LLM 講一句溫暖的結束語、不再發問，
    # 之後 handler 會自動把場次標為 completed 並觸發 SOAP。仍保留「先前若有緊急徵象要再提醒就醫」。
    # 情境＝院內候診（平板/Kiosk）：問診結束後病患在原處等醫師看診，故結束語請他「稍候、醫師
    # 將很快看診」，而非含糊的「後續跟進」；紅旗時請他「立即告知現場櫃台/醫護」而非「盡速就醫」。
    "llm.conversation_wrap_up_rule": {
        "zh-TW": (
            "\n\n## 結束問診（本輪硬性指示）\n"
            "- 你已收集到足夠病史，本輪請收尾：簡短感謝病患，並請他在原處稍候，"
            "醫師將很快依這些資訊為他看診。\n"
            "- 本輪不要再提出任何新問題。\n"
            "- 若先前對話出現需緊急處理的徵象，請提醒病患立即告知現場櫃台或醫護人員。\n"
            "- 保持 1-2 句、口語化。"
        ),
        "en-US": (
            "\n\n## Wrap up the interview (strict, this turn only)\n"
            "- You have collected enough history. Close the conversation: briefly thank "
            "the patient and ask them to wait where they are; a physician will see them "
            "shortly using this information.\n"
            "- Do NOT ask any new question this turn.\n"
            "- If earlier symptoms warranted urgent attention, tell the patient to notify "
            "the front desk or on-site staff right away.\n"
            "- Keep it to 1-2 conversational sentences."
        ),
        "ja-JP": (
            "\n\n## 問診の締めくくり（本ターンのみ・必須）\n"
            "- 十分な病歴が得られました。本ターンは締めくくり、患者へ簡潔に感謝し、"
            "その場でお待ちいただくよう伝えてください。医師がこの情報をもとに間もなく診察します。\n"
            "- 本ターンでは新しい質問をしないでください。\n"
            "- 緊急の対応が必要な兆候があれば、受付または現場の医療スタッフにすぐ伝えるよう促してください。\n"
            "- 1〜2文の会話調で。"
        ),
        "ko-KR": (
            "\n\n## 문진 마무리(이번 턴 한정·필수)\n"
            "- 충분한 병력을 수집했습니다. 이번 턴은 마무리로, 환자에게 간단히 감사하고 "
            "그 자리에서 잠시 기다려 달라고 안내하세요. 의사가 이 정보를 바탕으로 곧 진료합니다.\n"
            "- 이번 턴에는 새 질문을 하지 마세요.\n"
            "- 긴급 대응이 필요한 징후가 있었다면 접수처나 현장 의료진에게 즉시 알리도록 안내하세요.\n"
            "- 1~2문장 구어체로."
        ),
        "vi-VN": (
            "\n\n## Kết thúc buổi hỏi bệnh (bắt buộc, chỉ lượt này)\n"
            "- Đã thu thập đủ tiền sử. Lượt này hãy kết thúc: cảm ơn ngắn gọn và mời "
            "bệnh nhân chờ tại chỗ; bác sĩ sẽ sớm thăm khám dựa trên thông tin này.\n"
            "- KHÔNG đặt thêm câu hỏi mới ở lượt này.\n"
            "- Nếu trước đó có dấu hiệu cần xử lý khẩn cấp, hãy nhắc bệnh nhân báo ngay "
            "cho quầy tiếp nhận hoặc nhân viên y tế tại chỗ.\n"
            "- Giữ 1-2 câu, giọng trò chuyện."
        ),
    },
    # 問診 system prompt 尾段的強制輸出語言區段，配合 conversation_language_rule 使用。
    "llm.conversation_output_language_rule": {
        "zh-TW": (
            "\n\n## 輸出語言（硬性規定）\n"
            "- 不論病患用何種語言提問,你都必須以 **繁體中文** 回覆。\n"
            "- 不要混入其他語言的原文。"
        ),
        "en-US": (
            "\n\n## Output Language (Strict)\n"
            "- Regardless of the language the patient uses, you must reply in **US English**.\n"
            "- Do not mix in other languages."
        ),
        "ja-JP": (
            "\n\n## 出力言語(必須)\n"
            "- 患者がどの言語で話しても、あなたは必ず**日本語**で返答してください。\n"
            "- 他言語の原文を混ぜないでください。"
        ),
        "ko-KR": (
            "\n\n## 출력 언어(필수)\n"
            "- 환자가 어떤 언어로 말하든, 반드시 **한국어**로 답변하세요.\n"
            "- 다른 언어의 원문을 섞지 마세요."
        ),
        "vi-VN": (
            "\n\n## Ngôn ngữ đầu ra (bắt buộc)\n"
            "- Dù bệnh nhân dùng ngôn ngữ nào, bạn phải trả lời bằng **tiếng Việt**.\n"
            "- Không xen lẫn nguyên văn ngôn ngữ khác."
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

    # ── SOAP Plan urgency（TODO-M13 enum 化 4 級）────
    # UI 渲染 Plan 的 urgency 時依 locale 取此字串，再與 boilerplate 組合。
    # 新增 urgency 必須同時更新 `Urgency` enum 與此表（測試有守護）。
    "soap.red_flag_impression_prefix": {
        "zh-TW": "偵測到紅旗徵象，需優先緊急評估。",
        "en-US": "Red flag detected — requires urgent priority evaluation.",
        "ja-JP": "レッドフラグを検出しました。緊急の優先評価が必要です。",
        "ko-KR": "위험 징후가 감지되었습니다. 긴급 우선 평가가 필요합니다.",
    },
    "soap.urgency.er_now": {
        "zh-TW": "若有以下情況請立即就醫：請立刻前往急診。",
        "en-US": "Seek emergency care immediately if the following applies: proceed to the ER now.",
    },
    "soap.urgency.24h": {
        "zh-TW": "若有以下情況請立即就醫：請於 24 小時內就醫評估。",
        "en-US": "Seek emergency care immediately if the following applies: obtain medical evaluation within 24 hours.",
    },
    "soap.urgency.this_week": {
        "zh-TW": "若有以下情況請立即就醫：請於本週內安排門診評估。",
        "en-US": "Seek emergency care immediately if the following applies: arrange a clinic visit within this week.",
    },
    "soap.urgency.routine": {
        "zh-TW": "若有以下情況請立即就醫：建議常規門診追蹤即可。",
        "en-US": "Seek emergency care immediately if the following applies: routine outpatient follow-up is sufficient.",
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
        "ja-JP": (
            "こんにちは。泌尿器科のAI問診アシスタントです。本日は初診の問診をお手伝いします。"
            "「{chief_complaint}」の症状はいつから始まりましたか？"
        ),
        "ko-KR": (
            "안녕하세요. 비뇨기과 AI 문진 도우미입니다. 오늘 초기 문진을 도와드리겠습니다."
            "「{chief_complaint}」 증상은 언제부터 시작되었나요?"
        ),
        "vi-VN": (
            "Xin chào! Tôi là trợ lý hỏi bệnh AI chuyên khoa Tiết niệu, "
            "hôm nay tôi sẽ hỗ trợ buổi hỏi bệnh ban đầu của bạn. "
            "Triệu chứng \"{chief_complaint}\" của bạn bắt đầu từ khi nào?"
        ),
    },

    # A1 [D5]：LLM 空回應 retry 後仍空時的在地化 fallback（直接整句 _spawn_tts_task，
    # 不走切句 — _SENTENCE_BOUNDARY_CHARS 是 CJK-only，en/ko/vi 的 '?' 切不出句子）。
    "ws.ai_empty_retry_fallback": {
        "zh-TW": "不好意思，我剛才沒有處理好您的回覆。可以請您再說一次，或再補充一下您的症狀嗎？",
        "en-US": "Sorry, I had trouble processing your last reply. Could you say that again, or tell me a bit more about your symptoms?",
        "ja-JP": "申し訳ありません。先ほどのご回答をうまく処理できませんでした。もう一度お話しいただくか、症状についてもう少し詳しく教えていただけますか？",
        "ko-KR": "죄송합니다. 방금 하신 말씀을 제대로 처리하지 못했습니다. 다시 한번 말씀해 주시거나 증상을 조금 더 설명해 주시겠어요?",
        "vi-VN": "Xin lỗi, tôi chưa xử lý được câu trả lời vừa rồi của bạn. Bạn có thể nói lại, hoặc mô tả thêm một chút về triệu chứng của mình không?",
    },

    # E8-1：場次已進入終態（completed / aborted_red_flag）後仍收到訊息時的唯一回覆
    # （拒收後續訊息，不再重跑紅旗/LLM，也不再重發 abort 事件洪流）。情境＝院內候診
    # （平板/Kiosk）：病患已在現場等看診，故用「請依現場人員安排稍候」而非含糊的
    # 「盡速就醫」；紅旗中止的版本則明確告知「已通知現場醫護人員」。
    "ws.session_terminated_completed_notice": {
        "zh-TW": "本次問診已經結束，感謝您的配合。請依現場人員的安排稍候看診。",
        "en-US": "This intake session has already ended. Thank you for your time — please wait and follow the on-site staff's instructions for your visit.",
        "ja-JP": "今回の問診はすでに終了しました。ご協力ありがとうございました。現場スタッフの案内に従ってお待ちください。",
        "ko-KR": "이번 문진은 이미 종료되었습니다. 협조해 주셔서 감사합니다. 현장 안내에 따라 진료를 기다려 주세요.",
        "vi-VN": "Buổi hỏi bệnh này đã kết thúc. Cảm ơn sự hợp tác của bạn, vui lòng chờ và làm theo hướng dẫn của nhân viên tại chỗ.",
    },
    "ws.session_terminated_aborted_notice": {
        "zh-TW": "本次問診已經結束，系統已將您先前描述、需要留意的症狀通知現場醫護人員，請依現場人員的安排稍候看診。",
        "en-US": "This intake session has already ended. On-site clinical staff have already been notified about the symptoms you described that need attention. Please wait and follow their instructions.",
        "ja-JP": "今回の問診はすでに終了しました。注意が必要な症状については、現場の医療スタッフにすでにお伝えしています。現場スタッフの案内に従ってお待ちください。",
        "ko-KR": "이번 문진은 이미 종료되었습니다. 주의가 필요한 증상은 이미 현장 의료진에게 전달되었습니다. 현장 안내에 따라 기다려 주세요.",
        "vi-VN": "Buổi hỏi bệnh này đã kết thúc. Nhân viên y tế tại chỗ đã được thông báo về triệu chứng cần lưu ý mà bạn đã mô tả. Vui lòng chờ và làm theo hướng dẫn của nhân viên tại chỗ.",
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
