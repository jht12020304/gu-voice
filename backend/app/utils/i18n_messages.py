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
- **新增 key 時 5 個 locale（zh-TW / en-US / ja-JP / ko-KR / vi-VN）全都要填。**
  缺譯不會 raise、只會靜靜退回中文 —— 日/韓/越場次會拿到中文字串並寫進 DB
  （例：`alert.rule_match_reason` 曾只有兩語，導致 `red_flag_alerts.trigger_reason`
  在日文場次寫入「關鍵字比對：「尿閉」」）。
  `tests/unit/utils/test_i18n_message_locale_parity.py` 會在 CI 擋下這種缺譯。
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
        "ja-JP": "認証されていないか、トークンの有効期限が切れています",
        "ko-KR": "인증되지 않았거나 토큰이 만료되었습니다",
        "vi-VN": "Chưa xác thực hoặc token đã hết hạn",
    },
    "errors.invalid_auth_header": {
        "zh-TW": "Authorization header 格式錯誤",
        "en-US": "Invalid authorization header format",
        "ja-JP": "Authorization ヘッダーの形式が正しくありません",
        "ko-KR": "Authorization 헤더 형식이 올바르지 않습니다",
        "vi-VN": "Định dạng header Authorization không hợp lệ",
    },
    "errors.token_invalid_or_expired": {
        "zh-TW": "Token 無效或已過期",
        "en-US": "Token is invalid or expired",
        "ja-JP": "トークンが無効か、有効期限が切れています",
        "ko-KR": "토큰이 유효하지 않거나 만료되었습니다",
        "vi-VN": "Token không hợp lệ hoặc đã hết hạn",
    },
    "errors.token_payload_missing_sub": {
        "zh-TW": "Token payload 缺少 sub",
        "en-US": "Token payload missing subject",
        "ja-JP": "トークンのペイロードに sub がありません",
        "ko-KR": "토큰 페이로드에 sub가 없습니다",
        "vi-VN": "Payload của token thiếu trường sub",
    },
    "errors.token_revoked": {
        "zh-TW": "Token 已失效",
        "en-US": "Token has been revoked",
        "ja-JP": "トークンは失効しています",
        "ko-KR": "토큰이 무효화되었습니다",
        "vi-VN": "Token đã bị thu hồi",
    },
    "errors.token_payload_incomplete": {
        "zh-TW": "Token payload 不完整",
        "en-US": "Token payload is incomplete",
        "ja-JP": "トークンのペイロードが不完全です",
        "ko-KR": "토큰 페이로드가 완전하지 않습니다",
        "vi-VN": "Payload của token không đầy đủ",
    },
    "errors.refresh_token_invalid": {
        "zh-TW": "Refresh token 無效或已過期",
        "en-US": "Refresh token is invalid or expired",
        "ja-JP": "リフレッシュトークンが無効か、有効期限が切れています",
        "ko-KR": "리프레시 토큰이 유효하지 않거나 만료되었습니다",
        "vi-VN": "Refresh token không hợp lệ hoặc đã hết hạn",
    },
    "errors.refresh_token_reused": {
        "zh-TW": "Refresh token 重複使用，請重新登入",
        "en-US": "Refresh token reuse detected; please sign in again",
        "ja-JP": "リフレッシュトークンの再使用を検出しました。もう一度ログインしてください",
        "ko-KR": "리프레시 토큰 재사용이 감지되었습니다. 다시 로그인해 주세요",
        "vi-VN": "Phát hiện refresh token bị dùng lại; vui lòng đăng nhập lại",
    },
    "errors.password_reset_link_invalid": {
        "zh-TW": "重設密碼連結已過期或無效",
        "en-US": "Password reset link is expired or invalid",
        "ja-JP": "パスワード再設定リンクの有効期限が切れているか、無効です",
        "ko-KR": "비밀번호 재설정 링크가 만료되었거나 유효하지 않습니다",
        "vi-VN": "Liên kết đặt lại mật khẩu đã hết hạn hoặc không hợp lệ",
    },
    "errors.forbidden": {
        "zh-TW": "權限不足",
        "en-US": "Permission denied",
        "ja-JP": "権限がありません",
        "ko-KR": "권한이 없습니다",
        "vi-VN": "Không đủ quyền",
    },
    "errors.complaint_default_forbidden": {
        "zh-TW": "系統預設主訴僅限管理員修改或刪除",
        "en-US": "Only an administrator may modify or delete a system default chief complaint",
        "ja-JP": "システム既定の主訴は管理者のみが変更・削除できます",
        "ko-KR": "시스템 기본 주 증상은 관리자만 수정하거나 삭제할 수 있습니다",
        "vi-VN": "Chỉ quản trị viên mới có thể sửa hoặc xóa lý do khám mặc định của hệ thống",
    },
    "errors.account_disabled": {
        "zh-TW": "帳號已停用",
        "en-US": "Account has been disabled",
        "ja-JP": "アカウントは無効化されています",
        "ko-KR": "계정이 비활성화되었습니다",
        "vi-VN": "Tài khoản đã bị vô hiệu hóa",
    },
    "errors.role_required": {
        "zh-TW": "需要角色: {roles}",
        "en-US": "Required role: {roles}",
        "ja-JP": "必要なロール: {roles}",
        "ko-KR": "필요한 역할: {roles}",
        "vi-VN": "Cần vai trò: {roles}",
    },
    "errors.session_access_no_principal": {
        "zh-TW": "缺少認證主體，無法判定場次存取權限",
        "en-US": "Missing authenticated principal; cannot authorize session access",
        "ja-JP": "認証主体がないため、セッションのアクセス権限を判定できません",
        "ko-KR": "인증 주체가 없어 세션 접근 권한을 확인할 수 없습니다",
        "vi-VN": "Thiếu chủ thể xác thực; không thể xác định quyền truy cập phiên khám",
    },
    "errors.session_list_no_principal": {
        "zh-TW": "缺少認證主體，無法列出場次",
        "en-US": "Missing authenticated principal; cannot list sessions",
        "ja-JP": "認証主体がないため、セッション一覧を取得できません",
        "ko-KR": "인증 주체가 없어 세션 목록을 조회할 수 없습니다",
        "vi-VN": "Thiếu chủ thể xác thực; không thể liệt kê phiên khám",
    },
    "errors.session_unknown_role": {
        "zh-TW": "未知角色，無法列出場次",
        "en-US": "Unknown role; cannot list sessions",
        "ja-JP": "不明なロールのため、セッション一覧を取得できません",
        "ko-KR": "알 수 없는 역할이므로 세션 목록을 조회할 수 없습니다",
        "vi-VN": "Vai trò không xác định; không thể liệt kê phiên khám",
    },
    "errors.session_forbidden_other_doctor": {
        "zh-TW": "此場次已由其他醫師負責",
        "en-US": "This session is already assigned to another doctor",
        "ja-JP": "このセッションは他の医師が担当しています",
        "ko-KR": "이 세션은 다른 의사가 담당하고 있습니다",
        "vi-VN": "Phiên khám này do bác sĩ khác phụ trách",
    },
    "errors.session_forbidden_patient": {
        "zh-TW": "您沒有權限存取此場次",
        "en-US": "You do not have permission to access this session",
        "ja-JP": "このセッションにアクセスする権限がありません",
        "ko-KR": "이 세션에 접근할 권한이 없습니다",
        "vi-VN": "Bạn không có quyền truy cập phiên khám này",
    },
    "errors.session_unknown_role_access": {
        "zh-TW": "未知角色，拒絕存取",
        "en-US": "Unknown role; access denied",
        "ja-JP": "不明なロールのため、アクセスを拒否しました",
        "ko-KR": "알 수 없는 역할이므로 접근이 거부되었습니다",
        "vi-VN": "Vai trò không xác định; truy cập bị từ chối",
    },
    "errors.patient_access_no_principal": {
        "zh-TW": "缺少認證主體，無法判定病患存取權限",
        "en-US": "Missing authenticated principal; cannot authorize patient access",
        "ja-JP": "認証主体がないため、患者へのアクセス権限を判定できません",
        "ko-KR": "인증 주체가 없어 환자 접근 권한을 확인할 수 없습니다",
        "vi-VN": "Thiếu chủ thể xác thực; không thể xác định quyền truy cập bệnh nhân",
    },
    "errors.patient_forbidden_other_doctor": {
        "zh-TW": "此病患已由其他醫師負責",
        "en-US": "This patient is assigned to another doctor",
        "ja-JP": "この患者は他の医師が担当しています",
        "ko-KR": "이 환자는 다른 의사가 담당하고 있습니다",
        "vi-VN": "Bệnh nhân này do bác sĩ khác phụ trách",
    },
    "errors.patient_forbidden_role": {
        "zh-TW": "您沒有權限存取此病患",
        "en-US": "You do not have permission to access this patient",
        "ja-JP": "この患者にアクセスする権限がありません",
        "ko-KR": "이 환자에 접근할 권한이 없습니다",
        "vi-VN": "Bạn không có quyền truy cập bệnh nhân này",
    },
    "errors.assign_doctor_conflict": {
        "zh-TW": "此場次已由其他醫師負責，無法重新指派",
        "en-US": "This session is already assigned to another doctor; cannot reassign",
        "ja-JP": "このセッションは他の医師が担当しているため、再割り当てできません",
        "ko-KR": "이 세션은 다른 의사가 담당하고 있어 재배정할 수 없습니다",
        "vi-VN": "Phiên khám này do bác sĩ khác phụ trách; không thể phân công lại",
    },
    "errors.assign_doctor_role_required": {
        "zh-TW": "僅 doctor / admin 可指派醫師",
        "en-US": "Only doctor or admin can assign a doctor",
        "ja-JP": "医師の割り当ては doctor / admin のみ実行できます",
        "ko-KR": "의사 배정은 doctor / admin만 할 수 있습니다",
        "vi-VN": "Chỉ doctor / admin mới có thể phân công bác sĩ",
    },
    "errors.session_patient_unresolved": {
        "zh-TW": "無法決定場次對應的病患",
        "en-US": "Cannot determine the patient associated with this session",
        "ja-JP": "このセッションに対応する患者を特定できません",
        "ko-KR": "이 세션에 해당하는 환자를 확인할 수 없습니다",
        "vi-VN": "Không xác định được bệnh nhân tương ứng với phiên khám này",
    },
    "errors.session_not_found": {
        "zh-TW": "場次不存在",
        "en-US": "Session not found",
        "ja-JP": "セッションが見つかりません",
        "ko-KR": "세션을 찾을 수 없습니다",
        "vi-VN": "Không tìm thấy phiên khám",
    },
    "errors.session_not_active": {
        "zh-TW": "場次非活躍狀態",
        "en-US": "Session is not active",
        "ja-JP": "セッションは進行中ではありません",
        "ko-KR": "세션이 활성 상태가 아닙니다",
        "vi-VN": "Phiên khám không ở trạng thái hoạt động",
    },
    "errors.session_not_switchable": {
        "zh-TW": "目前場次狀態無法切換語言",
        "en-US": "Cannot switch language on a session in the current state",
        "ja-JP": "現在のセッション状態では言語を切り替えられません",
        "ko-KR": "현재 세션 상태에서는 언어를 전환할 수 없습니다",
        "vi-VN": "Không thể đổi ngôn ngữ ở trạng thái hiện tại của phiên khám",
    },
    "errors.invalid_status_transition": {
        "zh-TW": "不合法的狀態轉移",
        "en-US": "Invalid status transition",
        "ja-JP": "不正な状態遷移です",
        "ko-KR": "허용되지 않는 상태 전환입니다",
        "vi-VN": "Chuyển trạng thái không hợp lệ",
    },
    "errors.status_transition_not_allowed": {
        "zh-TW": "無法從 {current} 轉移至 {target}",
        "en-US": "Cannot transition from {current} to {target}",
        "ja-JP": "{current} から {target} へは遷移できません",
        "ko-KR": "{current}에서 {target}(으)로 전환할 수 없습니다",
        "vi-VN": "Không thể chuyển từ {current} sang {target}",
    },
    "errors.report_not_found": {
        "zh-TW": "報告不存在",
        "en-US": "Report not found",
        "ja-JP": "レポートが見つかりません",
        "ko-KR": "보고서를 찾을 수 없습니다",
        "vi-VN": "Không tìm thấy báo cáo",
    },
    "errors.report_not_ready": {
        "zh-TW": "報告尚未產生完成",
        "en-US": "Report is not ready yet",
        "ja-JP": "レポートはまだ生成中です",
        "ko-KR": "보고서가 아직 생성되지 않았습니다",
        "vi-VN": "Báo cáo chưa được tạo xong",
    },
    "errors.report_already_exists": {
        "zh-TW": "報告已存在",
        "en-US": "Report already exists",
        "ja-JP": "レポートは既に存在します",
        "ko-KR": "보고서가 이미 존재합니다",
        "vi-VN": "Báo cáo đã tồn tại",
    },
    "errors.alert_not_found": {
        "zh-TW": "警示不存在",
        "en-US": "Alert not found",
        "ja-JP": "警告が見つかりません",
        "ko-KR": "경고를 찾을 수 없습니다",
        "vi-VN": "Không tìm thấy cảnh báo",
    },
    "errors.alert_already_acknowledged": {
        "zh-TW": "警示已確認",
        "en-US": "Alert has already been acknowledged",
        "ja-JP": "警告は既に確認済みです",
        "ko-KR": "경고가 이미 확인되었습니다",
        "vi-VN": "Cảnh báo đã được xác nhận",
    },
    "errors.red_flag_rule_not_found": {
        "zh-TW": "紅旗規則不存在",
        "en-US": "Red flag rule not found",
        "ja-JP": "レッドフラグのルールが見つかりません",
        "ko-KR": "레드플래그 규칙을 찾을 수 없습니다",
        "vi-VN": "Không tìm thấy quy tắc cờ đỏ",
    },
    "errors.complaint_not_found": {
        "zh-TW": "主訴不存在",
        "en-US": "Chief complaint not found",
        "ja-JP": "主訴が見つかりません",
        "ko-KR": "주 증상을 찾을 수 없습니다",
        "vi-VN": "Không tìm thấy lý do khám",
    },
    "errors.notification_not_found": {
        "zh-TW": "通知不存在",
        "en-US": "Notification not found",
        "ja-JP": "通知が見つかりません",
        "ko-KR": "알림을 찾을 수 없습니다",
        "vi-VN": "Không tìm thấy thông báo",
    },
    "errors.patient_not_found": {
        "zh-TW": "病患不存在",
        "en-US": "Patient not found",
        "ja-JP": "患者が見つかりません",
        "ko-KR": "환자를 찾을 수 없습니다",
        "vi-VN": "Không tìm thấy bệnh nhân",
    },
    "errors.conversation_not_found": {
        "zh-TW": "對話紀錄不存在",
        "en-US": "Conversation record not found",
        "ja-JP": "会話記録が見つかりません",
        "ko-KR": "대화 기록을 찾을 수 없습니다",
        "vi-VN": "Không tìm thấy bản ghi hội thoại",
    },
    "errors.audit_log_not_found": {
        "zh-TW": "稽核日誌不存在",
        "en-US": "Audit log not found",
        "ja-JP": "監査ログが見つかりません",
        "ko-KR": "감사 로그를 찾을 수 없습니다",
        "vi-VN": "Không tìm thấy nhật ký kiểm toán",
    },
    "errors.user_not_found": {
        "zh-TW": "使用者不存在",
        "en-US": "User not found",
        "ja-JP": "ユーザーが見つかりません",
        "ko-KR": "사용자를 찾을 수 없습니다",
        "vi-VN": "Không tìm thấy người dùng",
    },
    "errors.cannot_toggle_self": {
        "zh-TW": "無法變更自己的帳號啟用狀態",
        "en-US": "You cannot change the active status of your own account",
        "ja-JP": "自分のアカウントの有効・無効状態は変更できません",
        "ko-KR": "본인 계정의 활성 상태는 변경할 수 없습니다",
        "vi-VN": "Không thể thay đổi trạng thái kích hoạt tài khoản của chính bạn",
    },
    "errors.cannot_reset_own_password": {
        "zh-TW": "無法重設自己的密碼，請改用「變更密碼」（需驗證舊密碼）",
        "en-US": "You cannot reset your own password here — use Change Password instead (it verifies your current password)",
        "ja-JP": "自分のパスワードはここでは再設定できません。「パスワード変更」（現在のパスワードの確認あり）をご利用ください",
        "ko-KR": "본인 비밀번호는 여기서 재설정할 수 없습니다. 현재 비밀번호를 확인하는 '비밀번호 변경'을 사용하세요",
        "vi-VN": "Không thể đặt lại mật khẩu của chính bạn ở đây — hãy dùng \"Đổi mật khẩu\" (có xác minh mật khẩu hiện tại)",
    },
    "errors.not_found": {
        "zh-TW": "資源不存在",
        "en-US": "Resource not found",
        "ja-JP": "リソースが見つかりません",
        "ko-KR": "리소스를 찾을 수 없습니다",
        "vi-VN": "Không tìm thấy tài nguyên",
    },
    "errors.validation_failed": {
        "zh-TW": "請求參數驗證失敗",
        "en-US": "Request validation failed",
        "ja-JP": "リクエスト内容の検証に失敗しました",
        "ko-KR": "요청 값 검증에 실패했습니다",
        "vi-VN": "Xác thực tham số yêu cầu thất bại",
    },
    "errors.invalid_date_format": {
        "zh-TW": "日期格式無效，必須為 ISO-8601",
        "en-US": "Invalid date format; must be ISO-8601",
        "ja-JP": "日付の形式が無効です。ISO-8601 形式である必要があります",
        "ko-KR": "날짜 형식이 잘못되었습니다. ISO-8601 형식이어야 합니다",
        "vi-VN": "Định dạng ngày không hợp lệ; phải theo chuẩn ISO-8601",
    },
    "errors.invalid_severity": {
        "zh-TW": "警示嚴重度數值無效",
        "en-US": "Invalid alert severity value",
        "ja-JP": "アラートの重大度の値が無効です",
        "ko-KR": "경보 심각도 값이 잘못되었습니다",
        "vi-VN": "Giá trị mức độ nghiêm trọng của cảnh báo không hợp lệ",
    },
    "errors.invalid_status": {
        "zh-TW": "狀態數值無效",
        "en-US": "Invalid status value",
        "ja-JP": "ステータスの値が無効です",
        "ko-KR": "상태 값이 잘못되었습니다",
        "vi-VN": "Giá trị trạng thái không hợp lệ",
    },
    "errors.conflict": {
        "zh-TW": "資源衝突",
        "en-US": "Resource conflict",
        "ja-JP": "リソースが競合しています",
        "ko-KR": "리소스 충돌이 발생했습니다",
        "vi-VN": "Xung đột tài nguyên",
    },
    "errors.invalid_credentials": {
        "zh-TW": "帳號或密碼錯誤",
        "en-US": "Invalid credentials",
        "ja-JP": "メールアドレスまたはパスワードが正しくありません",
        "ko-KR": "이메일 또는 비밀번호가 올바르지 않습니다",
        "vi-VN": "Email hoặc mật khẩu không đúng",
    },
    "errors.current_password_incorrect": {
        "zh-TW": "目前密碼不正確",
        "en-US": "Current password is incorrect",
        "ja-JP": "現在のパスワードが正しくありません",
        "ko-KR": "현재 비밀번호가 올바르지 않습니다",
        "vi-VN": "Mật khẩu hiện tại không đúng",
    },
    "errors.email_already_exists": {
        "zh-TW": "Email 已註冊",
        "en-US": "Email is already registered",
        "ja-JP": "このメールアドレスは既に登録されています",
        "ko-KR": "이미 등록된 이메일입니다",
        "vi-VN": "Email đã được đăng ký",
    },
    "errors.ai_service_unavailable": {
        "zh-TW": "AI 服務不可用",
        "en-US": "AI service is unavailable",
        "ja-JP": "AI サービスを利用できません",
        "ko-KR": "AI 서비스를 사용할 수 없습니다",
        "vi-VN": "Dịch vụ AI không khả dụng",
    },
    "errors.service_unavailable": {
        "zh-TW": "服務暫時不可用，請稍後重試",
        "en-US": "Service is temporarily unavailable; please retry later",
        "ja-JP": "サービスは一時的に利用できません。しばらくしてからもう一度お試しください",
        "ko-KR": "서비스를 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요",
        "vi-VN": "Dịch vụ tạm thời không khả dụng; vui lòng thử lại sau",
    },
    "errors.ai_chat_unavailable": {
        "zh-TW": "AI 對話服務暫時不可用，請稍後重試",
        "en-US": "AI chat service is temporarily unavailable; please retry later",
        "ja-JP": "AI 対話サービスは一時的に利用できません。しばらくしてからもう一度お試しください",
        "ko-KR": "AI 대화 서비스를 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요",
        "vi-VN": "Dịch vụ hội thoại AI tạm thời không khả dụng; vui lòng thử lại sau",
    },
    "errors.soap_generation_bad_format": {
        "zh-TW": "SOAP 報告生成失敗：回應格式異常",
        "en-US": "SOAP report generation failed: unexpected response format",
        "ja-JP": "SOAP レポートの生成に失敗しました：応答形式が不正です",
        "ko-KR": "SOAP 보고서 생성에 실패했습니다: 응답 형식이 올바르지 않습니다",
        "vi-VN": "Tạo báo cáo SOAP thất bại: định dạng phản hồi không hợp lệ",
    },
    "errors.soap_generation_unavailable": {
        "zh-TW": "SOAP 報告生成服務暫時不可用，請稍後重試",
        "en-US": "SOAP report generation is temporarily unavailable; please retry later",
        "ja-JP": "SOAP レポート生成サービスは一時的に利用できません。しばらくしてからもう一度お試しください",
        "ko-KR": "SOAP 보고서 생성 서비스를 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요",
        "vi-VN": "Dịch vụ tạo báo cáo SOAP tạm thời không khả dụng; vui lòng thử lại sau",
    },
    "errors.rate_limit_exceeded": {
        "zh-TW": "超過速率限制",
        "en-US": "Rate limit exceeded",
        "ja-JP": "リクエスト回数の上限を超えました",
        "ko-KR": "요청 한도를 초과했습니다",
        "vi-VN": "Đã vượt quá giới hạn tần suất",
    },
    "errors.login_ip_rate_limited": {
        "zh-TW": "登入嘗試過於頻繁，請於 {retry_after} 秒後再試",
        "en-US": "Too many login attempts; please retry in {retry_after} seconds",
        "ja-JP": "ログインの試行が多すぎます。{retry_after} 秒後にもう一度お試しください",
        "ko-KR": "로그인 시도가 너무 잦습니다. {retry_after}초 후에 다시 시도해 주세요",
        "vi-VN": "Đăng nhập quá nhiều lần; vui lòng thử lại sau {retry_after} giây",
    },
    "errors.account_locked": {
        "zh-TW": "帳號因連續登入失敗已暫時鎖定，請於 {retry_after} 秒後再試",
        "en-US": "Account is temporarily locked due to repeated failures; please retry in {retry_after} seconds",
        "ja-JP": "ログインの連続失敗によりアカウントを一時的にロックしました。{retry_after} 秒後にもう一度お試しください",
        "ko-KR": "로그인 실패가 반복되어 계정이 일시적으로 잠겼습니다. {retry_after}초 후에 다시 시도해 주세요",
        "vi-VN": "Tài khoản tạm khóa do đăng nhập sai nhiều lần; vui lòng thử lại sau {retry_after} giây",
    },
    "errors.llm_rate_limited": {
        "zh-TW": "AI 呼叫過於頻繁，請於 {retry_after} 秒後再試",
        "en-US": "AI calls are too frequent; please retry in {retry_after} seconds",
        "ja-JP": "AI の呼び出しが多すぎます。{retry_after} 秒後にもう一度お試しください",
        "ko-KR": "AI 호출이 너무 잦습니다. {retry_after}초 후에 다시 시도해 주세요",
        "vi-VN": "Gọi AI quá thường xuyên; vui lòng thử lại sau {retry_after} giây",
    },
    "errors.internal_error": {
        "zh-TW": "內部伺服器錯誤",
        "en-US": "Internal server error",
        "ja-JP": "サーバー内部エラーが発生しました",
        "ko-KR": "서버 내부 오류가 발생했습니다",
        "vi-VN": "Lỗi máy chủ nội bộ",
    },
    "errors.dashboard_date_format": {
        "zh-TW": "date 必須為 YYYY-MM-DD",
        "en-US": "date must be in YYYY-MM-DD format",
        "ja-JP": "date は YYYY-MM-DD 形式で指定してください",
        "ko-KR": "date는 YYYY-MM-DD 형식이어야 합니다",
        "vi-VN": "date phải theo định dạng YYYY-MM-DD",
    },
    "errors.dashboard_month_format": {
        "zh-TW": "month 必須為 YYYY-MM",
        "en-US": "month must be in YYYY-MM format",
        "ja-JP": "month は YYYY-MM 形式で指定してください",
        "ko-KR": "month는 YYYY-MM 형식이어야 합니다",
        "vi-VN": "month phải theo định dạng YYYY-MM",
    },

    # ── Auth 成功訊息（MessageResponse body） ─────────
    "messages.logout_success": {
        "zh-TW": "登出成功",
        "en-US": "Logged out successfully",
        "ja-JP": "ログアウトしました",
        "ko-KR": "로그아웃되었습니다",
        "vi-VN": "Đã đăng xuất",
    },
    "messages.password_changed": {
        "zh-TW": "密碼變更成功",
        "en-US": "Password changed successfully",
        "ja-JP": "パスワードを変更しました",
        "ko-KR": "비밀번호가 변경되었습니다",
        "vi-VN": "Đã đổi mật khẩu thành công",
    },
    "messages.password_reset_link_sent": {
        "zh-TW": "若此電子郵件已註冊，密碼重設連結已寄出",
        "en-US": "If this email is registered, a password reset link has been sent",
        "ja-JP": "このメールアドレスが登録されている場合、パスワード再設定リンクを送信しました",
        "ko-KR": "이 이메일이 등록되어 있다면 비밀번호 재설정 링크를 보냈습니다",
        "vi-VN": "Nếu email này đã được đăng ký, liên kết đặt lại mật khẩu đã được gửi",
    },
    "messages.password_reset_success": {
        "zh-TW": "密碼重設成功，請使用新密碼登入",
        "en-US": "Password reset successful; please sign in with your new password",
        "ja-JP": "パスワードを再設定しました。新しいパスワードでログインしてください",
        "ko-KR": "비밀번호가 재설정되었습니다. 새 비밀번호로 로그인해 주세요",
        "vi-VN": "Đặt lại mật khẩu thành công; vui lòng đăng nhập bằng mật khẩu mới",
    },

    # ── Alert / Red Flag 固定模板 ────────────────────
    # 這幾條會直接寫進 `red_flag_alerts.trigger_reason` / `title`（DB 持久化），
    # 並在醫師端 UI 與推播中顯示 → 5 語必備，缺一語該語系場次就會落回中文。
    # 術語對齊 frontend locales：ja「レッドフラグ」／ko「레드플래그」／vi「cờ đỏ」。
    "alert.rule_match_reason": {
        "zh-TW": "關鍵字比對：「{keyword}」",
        "en-US": "Keyword match: \"{keyword}\"",
        "ja-JP": "キーワード一致：「{keyword}」",
        "ko-KR": "키워드 일치: '{keyword}'",
        "vi-VN": "Khớp từ khóa: \"{keyword}\"",
    },
    "alert.regex_match_reason": {
        "zh-TW": "模式比對：「{match}」",
        "en-US": "Pattern match: \"{match}\"",
        "ja-JP": "パターン一致：「{match}」",
        "ko-KR": "패턴 일치: '{match}'",
        "vi-VN": "Khớp mẫu: \"{match}\"",
    },
    "alert.combined_trigger_reason": {
        "zh-TW": "[規則] {rule_reason} | [語意] {semantic_reason}",
        "en-US": "[Rule] {rule_reason} | [Semantic] {semantic_reason}",
        "ja-JP": "[ルール] {rule_reason} | [意味解析] {semantic_reason}",
        "ko-KR": "[규칙] {rule_reason} | [의미 분석] {semantic_reason}",
        "vi-VN": "[Quy tắc] {rule_reason} | [Ngữ nghĩa] {semantic_reason}",
    },
    "alert.unknown_title": {
        "zh-TW": "未知紅旗",
        "en-US": "Unknown red flag",
        "ja-JP": "不明なレッドフラグ",
        "ko-KR": "알 수 없는 레드플래그",
        "vi-VN": "Cờ đỏ không xác định",
    },
    "alert.semantic_default_title": {
        "zh-TW": "語意偵測紅旗",
        "en-US": "Semantic-detected red flag",
        "ja-JP": "意味解析で検出したレッドフラグ",
        "ko-KR": "의미 분석으로 감지된 레드플래그",
        "vi-VN": "Cờ đỏ phát hiện bằng phân tích ngữ nghĩa",
    },
    "alert.push_notification_title": {
        "zh-TW": "紅旗警示: {title}",
        "en-US": "Red flag alert: {title}",
        "ja-JP": "レッドフラグ警告: {title}",
        "ko-KR": "레드플래그 경고: {title}",
        "vi-VN": "Cảnh báo cờ đỏ: {title}",
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
    # next_focus 自檢命中時的替代指令（app/pipelines/next_focus_guard.py）。
    # Supervisor 的 next_focus 文字若在重問已從 missing_hpi 移除的欄位（已回答或病患已
    # 表示不知道），不是把 next_focus 清空——那會退化成「無指導、對話 LLM 自由發揮」的
    # 已知缺陷（TODO R19）——而是換成指向仍缺失欄位的中性推進指令。
    # {fields} 是 HPI 欄位的英文顯示名（Onset / Duration / Severity…，與對話端 prompt 的
    # HPI 清單標題同名），刻意不翻譯也刻意不帶中文——它會進對話 LLM 的 system prompt。
    "llm.supervisor_next_focus_redirect": {
        "zh-TW": "請改問下列尚未釐清的 HPI 面向中的**一項**（每次只問一題）：{fields}。病患已回答過、或已表示不知道／記不得的面向，不得以任何換句話形式重問。",
        "en-US": "Ask about exactly ONE of these still-unclarified HPI aspects (one question only): {fields}. Do not re-ask, in any rephrased form, aspects the patient has already answered or said they do not know / cannot remember.",
        "ja-JP": "まだ確認できていない次の HPI 項目のうち**1 つだけ**を尋ねてください（1 回につき 1 問）：{fields}。患者がすでに回答した、または「分からない・覚えていない」と述べた項目は、言い換えを含めて再質問しないでください。",
        "ko-KR": "아직 확인되지 않은 다음 HPI 항목 중 **하나만** 질문하세요(한 번에 한 문항): {fields}. 환자가 이미 답했거나 모른다·기억나지 않는다고 밝힌 항목은 표현을 바꾸어서도 다시 묻지 마세요.",
        "vi-VN": "Hãy hỏi ĐÚNG MỘT trong các khía cạnh HPI chưa được làm rõ sau (mỗi lần một câu): {fields}. Không hỏi lại, dưới bất kỳ cách diễn đạt nào, những khía cạnh bệnh nhân đã trả lời hoặc đã nói không biết / không nhớ.",
    },
    "llm.supervisor_next_focus_wrap_up": {
        "zh-TW": "HPI 面向皆已覆蓋（含病患已表示無法回答的項目）。請做一次簡短確認後收尾，不要再追問已覆蓋的面向。",
        "en-US": "All HPI aspects are covered (including those the patient said they could not answer). Do a brief confirmation and wrap up; do not probe covered aspects again.",
        "ja-JP": "HPI の各項目はすべて確認済みです（患者が「答えられない」と述べた項目を含む）。短く確認したうえで締めくくり、確認済みの項目を再度尋ねないでください。",
        "ko-KR": "HPI 항목이 모두 확인되었습니다(환자가 답할 수 없다고 밝힌 항목 포함). 간단히 확인한 뒤 마무리하고, 이미 확인된 항목을 다시 묻지 마세요.",
        "vi-VN": "Tất cả các khía cạnh HPI đã được bao phủ (kể cả những mục bệnh nhân nói không thể trả lời). Hãy xác nhận ngắn gọn rồi kết thúc, không hỏi lại các khía cạnh đã bao phủ.",
    },
    # 本輪限定的「剛被拒答的面向禁止再問」禁令（app/pipelines/next_focus_guard.py
    # build_dont_know_ban）。前後夾擊注入 system prompt——實測靜態問診準則裡那條
    # 「不得換句話重問」在長 prompt 中段競爭不過當下語境，LLM 仍會問出
    # 「是一直都有還是有時候才出現」。{fields} 是英文欄位名、{examples} 是**該欄位**
    # 的換句話例句（逐欄給，順手多列別欄的句式會把那一欄變成永遠問不出來的漏問）。
    "llm.dont_know_turn_ban": {
        "zh-TW": "【本輪硬性禁令，優先於其他所有指導】病患剛剛已明確表示對「{fields}」這個面向無法回答。本輪絕對禁止再以任何形式詢問這一面向——換句話、二選一句式、確認式問法都禁止（例如：{examples}）。請直接改問其他尚未釐清的面向。",
        "en-US": "[Hard ban for THIS turn — overrides every other instruction] The patient has just said they cannot answer about \"{fields}\". Do NOT ask about this aspect again in any form this turn — no rephrasing, no either/or framing, no confirmation-style questions (e.g. {examples}). Move straight to another aspect that is still unclear.",
        "ja-JP": "【今回のみの絶対禁止事項：他のすべての指示より優先】患者は「{fields}」について答えられないと明言しました。今回はこの面をいかなる形でも再質問しないでください——言い換え、二者択一の問い方、確認的な問い方はすべて禁止です（例：{examples}）。まだ明らかでない別の面に進んでください。",
        "ko-KR": "[이번 턴 한정 절대 금지 — 다른 모든 지시보다 우선] 환자가 방금 \"{fields}\" 항목에 대해 답할 수 없다고 밝혔습니다. 이번 턴에는 이 항목을 어떤 형태로도 다시 묻지 마세요 — 표현 바꾸기, 양자택일 질문, 확인식 질문 모두 금지입니다(예: {examples}). 아직 확인되지 않은 다른 항목으로 바로 넘어가세요.",
        "vi-VN": "[Cấm tuyệt đối trong lượt này — ưu tiên hơn mọi hướng dẫn khác] Bệnh nhân vừa nói rằng họ không thể trả lời về \"{fields}\". Trong lượt này, KHÔNG hỏi lại khía cạnh đó dưới bất kỳ hình thức nào — không diễn đạt lại, không hỏi kiểu chọn một trong hai, không hỏi kiểu xác nhận (ví dụ: {examples}). Hãy chuyển ngay sang khía cạnh khác chưa rõ.",
    },
    "llm.dont_know_ban_examples.onset": {
        "zh-TW": "「是突然發生的還是慢慢變明顯的」「什麼時候開始的」",
        "en-US": "\"did it start suddenly or gradually\", \"when did it start\"",
        "ja-JP": "「急に始まったのか、徐々にはっきりしてきたのか」「いつから始まったのか」",
        "ko-KR": "\"갑자기 시작됐는지 서서히 뚜렷해졌는지\", \"언제부터 시작됐는지\"",
        "vi-VN": "\"bắt đầu đột ngột hay từ từ rõ dần\", \"bắt đầu từ khi nào\"",
    },
    "llm.dont_know_ban_examples.duration": {
        "zh-TW": "「是一直都有，還是間歇／有時候才出現」「持續性還是間歇性」「大概多久了」",
        "en-US": "\"is it constant or does it come and go / only sometimes\", \"continuous or intermittent\", \"how long has it lasted\"",
        "ja-JP": "「ずっと続いているのか、時々だけ出るのか」「持続的か間欠的か」「どのくらい続いているのか」",
        "ko-KR": "\"계속 있는지 가끔씩만 나타나는지\", \"지속적인지 간헐적인지\", \"얼마나 지속됐는지\"",
        "vi-VN": "\"liên tục hay lúc có lúc không / thỉnh thoảng mới có\", \"liên tục hay ngắt quãng\", \"kéo dài bao lâu rồi\"",
    },
    "llm.dont_know_ban_examples.severity": {
        "zh-TW": "「大概幾分」「有多痛」「多嚴重」",
        "en-US": "\"on a scale of 0 to 10\", \"how painful is it\", \"how severe is it\"",
        "ja-JP": "「10段階でどのくらいか」「どのくらい痛いか」「どのくらいひどいか」",
        "ko-KR": "\"0에서 10 중 몇 점인지\", \"얼마나 아픈지\", \"얼마나 심한지\"",
        "vi-VN": "\"trên thang điểm 0 đến 10 là bao nhiêu\", \"đau đến mức nào\", \"nặng đến mức nào\"",
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
            "- 本輪**絕對不要**再提出任何問題——包含用藥、病史、次要補問、風險因子等**任何"
            "臨床問題**。即使系統先前指示某些項目『必問』、或 Supervisor 指定了下一題，本輪"
            "一律以收尾為準、不得發問；尚未問到的留待醫師面診時補齊。你這一輪只能輸出感謝與"
            "請病患稍候的話。\n"
            "- 若先前對話出現需緊急處理的徵象，請提醒病患立即告知現場櫃台或醫護人員。\n"
            "- 保持 1-2 句、口語化。"
        ),
        "en-US": (
            "\n\n## Wrap up the interview (strict, this turn only)\n"
            "- You have collected enough history. Close the conversation: briefly thank "
            "the patient and ask them to wait where they are; a physician will see them "
            "shortly using this information.\n"
            "- Do NOT ask ANY question this turn — including medications, past history, "
            "secondary follow-ups, or risk factors, i.e. **any clinical question**. Even if "
            "the system earlier marked some item as 'must ask', or the Supervisor set a next "
            "question, this turn is strictly a wrap-up; leave anything un-asked for the "
            "physician to cover in person. Output only thanks and a request to wait.\n"
            "- If earlier symptoms warranted urgent attention, tell the patient to notify "
            "the front desk or on-site staff right away.\n"
            "- Keep it to 1-2 conversational sentences."
        ),
        "ja-JP": (
            "\n\n## 問診の締めくくり（本ターンのみ・必須）\n"
            "- 十分な病歴が得られました。本ターンは締めくくり、患者へ簡潔に感謝し、"
            "その場でお待ちいただくよう伝えてください。医師がこの情報をもとに間もなく診察します。\n"
            "- 本ターンでは**一切の質問をしないでください**——服薬・既往歴・二次的な追加質問・"
            "リスク因子など**あらゆる臨床的質問**を含みます。たとえ特定の項目が事前に"
            "『必須質問』と指示されていても、または Supervisor が次の質問を指定していても、"
            "本ターンは締めくくり優先です。未確認の項目は医師の対面診察に委ねます。"
            "本ターンは感謝とお待ちいただく旨のみを述べてください。\n"
            "- 緊急の対応が必要な兆候があれば、受付または現場の医療スタッフにすぐ伝えるよう促してください。\n"
            "- 1〜2文の会話調で。"
        ),
        "ko-KR": (
            "\n\n## 문진 마무리(이번 턴 한정·필수)\n"
            "- 충분한 병력을 수집했습니다. 이번 턴은 마무리로, 환자에게 간단히 감사하고 "
            "그 자리에서 잠시 기다려 달라고 안내하세요. 의사가 이 정보를 바탕으로 곧 진료합니다.\n"
            "- 이번 턴에는 **어떤 질문도 하지 마세요**——복약·과거력·이차 추가 질문·위험 요인 등 "
            "**모든 임상 질문**을 포함합니다. 특정 항목이 사전에 '필수 질문'으로 지시되었거나 "
            "Supervisor가 다음 질문을 지정했더라도, 이번 턴은 마무리 우선입니다. 아직 확인하지 "
            "못한 항목은 의사의 대면 진료에서 보완합니다. 이번 턴은 감사와 대기 안내만 하세요.\n"
            "- 긴급 대응이 필요한 징후가 있었다면 접수처나 현장 의료진에게 즉시 알리도록 안내하세요.\n"
            "- 1~2문장 구어체로."
        ),
        "vi-VN": (
            "\n\n## Kết thúc buổi hỏi bệnh (bắt buộc, chỉ lượt này)\n"
            "- Đã thu thập đủ tiền sử. Lượt này hãy kết thúc: cảm ơn ngắn gọn và mời "
            "bệnh nhân chờ tại chỗ; bác sĩ sẽ sớm thăm khám dựa trên thông tin này.\n"
            "- KHÔNG đặt BẤT KỲ câu hỏi nào ở lượt này — bao gồm thuốc đang dùng, tiền sử, "
            "câu hỏi bổ sung thứ yếu, hay yếu tố nguy cơ, tức **bất kỳ câu hỏi lâm sàng nào**. "
            "Dù trước đó hệ thống đã đánh dấu mục nào là 'bắt buộc hỏi', hoặc Supervisor đã chỉ "
            "định câu hỏi tiếp theo, lượt này vẫn ưu tiên kết thúc; những mục chưa hỏi để bác "
            "sĩ bổ sung khi khám trực tiếp. Lượt này chỉ nói lời cảm ơn và mời chờ.\n"
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
    # 語意層紅旗偵測的輸出語言指示。缺譯 → get_message 退回 zh-TW → 日/韓/越場次的
    # description / suggested_actions（以及 LLM 自創非目錄紅旗的 title）會整段變中文，
    # 而 title 因為另有 display_title_by_lang 反而是對的，肉眼極易誤判成「已在地化」。
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
        "ja-JP": (
            "\n\n## 出力言語(必須)\n"
            "- title / description / suggested_actions などのフィールドは必ず**日本語**で記述してください。\n"
            "- trigger_reason は原文(患者が実際に話した言語)のまま保持し、翻訳しないでください。"
        ),
        "ko-KR": (
            "\n\n## 출력 언어(필수)\n"
            "- title / description / suggested_actions 등의 필드는 반드시 **한국어**로 작성하세요.\n"
            "- trigger_reason은 원문(환자가 실제로 말한 언어)을 그대로 유지하고 번역하지 마세요."
        ),
        "vi-VN": (
            "\n\n## Ngôn ngữ đầu ra (bắt buộc)\n"
            "- Các trường title / description / suggested_actions phải được viết bằng **tiếng Việt**.\n"
            "- Giữ nguyên trigger_reason theo nguyên văn (ngôn ngữ bệnh nhân thực sự nói), không dịch."
        ),
    },

    # ── SOAP Plan urgency（TODO-M13 enum 化 4 級）────
    # UI 渲染 Plan 的 urgency 時依 locale 取此字串，再與 boilerplate 組合。
    # 新增 urgency 必須同時更新 `Urgency` enum 與此表（測試有守護）。
    # 注意：soap.* 是**醫師端報告**用語（SOAP_REPORT_LANGUAGE 目前硬鎖 zh-TW），
    # 不是病患 kiosk 畫面用語，故保留「就醫 / 急診」等臨床指示措辭；
    # 病患面措辭鐵律（「請稍候等看診 / 請告知現場醫護」）適用的是 ws.* 與 llm.conversation_*。
    # 補齊 5 語是為了 SOAP_REPORT_LANGUAGE 一旦被覆寫（config 註記可恢復「報告跟問診語言」）
    # 時不會退回中文。
    "soap.red_flag_impression_prefix": {
        "zh-TW": "偵測到紅旗徵象，需優先緊急評估。",
        "en-US": "Red flag detected — requires urgent priority evaluation.",
        "ja-JP": "レッドフラグを検出しました。緊急の優先評価が必要です。",
        "ko-KR": "위험 징후가 감지되었습니다. 긴급 우선 평가가 필요합니다.",
        "vi-VN": "Đã phát hiện dấu hiệu cờ đỏ — cần đánh giá ưu tiên khẩn cấp.",
    },
    "soap.urgency.er_now": {
        "zh-TW": "若有以下情況請立即就醫：請立刻前往急診。",
        "en-US": "Seek emergency care immediately if the following applies: proceed to the ER now.",
        "ja-JP": "以下に該当する場合は直ちに受診してください：今すぐ救急外来を受診してください。",
        "ko-KR": "다음에 해당하면 즉시 진료를 받으세요: 지금 바로 응급실로 가세요.",
        "vi-VN": "Nếu có tình huống sau, hãy đi khám ngay: đến khoa cấp cứu ngay lập tức.",
    },
    "soap.urgency.24h": {
        "zh-TW": "若有以下情況請立即就醫：請於 24 小時內就醫評估。",
        "en-US": "Seek emergency care immediately if the following applies: obtain medical evaluation within 24 hours.",
        "ja-JP": "以下に該当する場合は直ちに受診してください：24 時間以内に医療機関の評価を受けてください。",
        "ko-KR": "다음에 해당하면 즉시 진료를 받으세요: 24시간 이내에 진료 평가를 받으세요.",
        "vi-VN": "Nếu có tình huống sau, hãy đi khám ngay: được đánh giá y tế trong vòng 24 giờ.",
    },
    "soap.urgency.this_week": {
        "zh-TW": "若有以下情況請立即就醫：請於本週內安排門診評估。",
        "en-US": "Seek emergency care immediately if the following applies: arrange a clinic visit within this week.",
        "ja-JP": "以下に該当する場合は直ちに受診してください：今週中に外来受診を予約してください。",
        "ko-KR": "다음에 해당하면 즉시 진료를 받으세요: 이번 주 안에 외래 진료를 예약하세요.",
        "vi-VN": "Nếu có tình huống sau, hãy đi khám ngay: sắp xếp khám ngoại trú trong tuần này.",
    },
    "soap.urgency.routine": {
        "zh-TW": "若有以下情況請立即就醫：建議常規門診追蹤即可。",
        "en-US": "Seek emergency care immediately if the following applies: routine outpatient follow-up is sufficient.",
        "ja-JP": "以下に該当する場合は直ちに受診してください：通常の外来フォローアップで差し支えありません。",
        "ko-KR": "다음에 해당하면 즉시 진료를 받으세요: 일반 외래 추적 관찰로 충분합니다.",
        "vi-VN": "Nếu có tình huống sau, hãy đi khám ngay: theo dõi ngoại trú thường quy là đủ.",
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
    # BLOCKER #2：上面那則明說「已通知現場醫護人員」。這句話只有在真的建立了
    # `notifications` 列時才成立 —— 院內 kiosk 場次 `sessions.doctor_id` 恆為 NULL，
    # 若 fan-out 因「查無在職醫師 / DB 失敗」建了 0 筆，上面那句就是對病患說謊。
    # `_notify_session_already_terminated` 依 `session_context["_red_flag_notified"]`
    # （建立筆數 > 0 的實測結果）在兩則之間二選一；本則只陳述必然為真的事：
    # 警示已寫進 `red_flag_alerts` 並可在醫師端查看。
    "ws.session_terminated_aborted_notice_unnotified": {
        "zh-TW": "本次問診已經結束。您先前描述、需要留意的症狀已為您標記在紀錄中，供現場醫護人員查看；請依現場人員的安排稍候看診，若不適加劇請主動告知現場櫃台或醫護人員。",
        "en-US": "This intake session has already ended. The symptoms you described that need attention are flagged in your record for the on-site clinical staff to review. Please wait and follow the on-site staff's instructions; if you feel worse, tell the front desk or on-site staff yourself.",
        "ja-JP": "今回の問診はすでに終了しました。注意が必要な症状は、現場の医療スタッフが確認できるよう記録に残しています。現場スタッフの案内に従ってお待ちください。症状が悪化した場合は、ご自身から受付または現場の医療スタッフにお知らせください。",
        "ko-KR": "이번 문진은 이미 종료되었습니다. 주의가 필요한 증상은 현장 의료진이 확인할 수 있도록 기록에 남겼습니다. 현장 안내에 따라 기다려 주세요. 증상이 심해지면 직접 접수처나 현장 의료진에게 알려 주세요.",
        "vi-VN": "Buổi hỏi bệnh này đã kết thúc. Triệu chứng cần lưu ý mà bạn đã mô tả đã được ghi nhận để nhân viên y tế tại chỗ xem. Vui lòng chờ và làm theo hướng dẫn của nhân viên tại chỗ; nếu thấy nặng hơn, hãy chủ động báo cho quầy tiếp nhận hoặc nhân viên y tế.",
    },

    # ── 紅旗警示的「病患面」提示（BLOCKER #2 / #3）────────────────
    # 送往病患 WS 的 `red_flag_alert` payload 只帶 alertId / severity / title
    # ＋這一段固定提示。`description` 與 `suggested_actions` 是 LLM 自由生成的
    # **醫師向**臨床內容（真跑實測含「立即安排急診評估」「排除惡性腫瘤」），
    # 結構性地不送給病患，而不是靠禁字黑名單事後過濾。
    #
    # 兩則的差別＝「有沒有真的建立醫師通知」，由 `_notify_doctors_red_flag`
    # 實際建立的筆數決定，不是文案作者的假設：
    #   notified → 確實有 notifications 列（已指派醫師，或未指派時 fan-out 成功）
    #   flagged  → 一筆都沒建（查無在職醫師 / 通知寫入失敗）→ 只講必然為真的事
    "ws.red_flag_patient_notice_notified": {
        "zh-TW": "我們已將這項需要留意的症狀通知現場醫護人員。請在原處稍候等看診；若不適加劇，請立即告知現場櫃台或醫護人員。",
        "en-US": "We have notified the on-site clinical staff about this symptom. Please stay where you are and wait to be seen; if you feel worse, tell the front desk or on-site staff right away.",
        "ja-JP": "この症状は現場の医療スタッフにお伝えしました。そのままの場所で診察をお待ちください。症状が悪化した場合は、受付または現場の医療スタッフにすぐお知らせください。",
        "ko-KR": "이 증상을 현장 의료진에게 전달했습니다. 자리에서 그대로 진료를 기다려 주세요. 증상이 심해지면 접수처나 현장 의료진에게 바로 알려 주세요.",
        "vi-VN": "Chúng tôi đã báo triệu chứng này cho nhân viên y tế tại chỗ. Vui lòng ngồi tại chỗ chờ đến lượt khám; nếu thấy nặng hơn, hãy báo ngay cho quầy tiếp nhận hoặc nhân viên y tế tại chỗ.",
    },
    "ws.red_flag_patient_notice_flagged": {
        "zh-TW": "我們已為您標記這項需要留意的症狀，供現場醫護人員在看診時查看。請在原處稍候等看診；若不適加劇，請主動告知現場櫃台或醫護人員。",
        "en-US": "We have flagged this symptom in your record for the on-site clinical staff to review at your visit. Please stay where you are and wait to be seen; if you feel worse, tell the front desk or on-site staff right away.",
        "ja-JP": "この症状は、現場の医療スタッフが診察時に確認できるよう記録しました。そのままの場所で診察をお待ちください。症状が悪化した場合は、受付または現場の医療スタッフにご自身からお知らせください。",
        "ko-KR": "이 증상은 현장 의료진이 진료 때 확인할 수 있도록 기록해 두었습니다. 자리에서 그대로 진료를 기다려 주세요. 증상이 심해지면 접수처나 현장 의료진에게 직접 알려 주세요.",
        "vi-VN": "Chúng tôi đã ghi nhận triệu chứng này để nhân viên y tế tại chỗ xem khi khám. Vui lòng ngồi tại chỗ chờ đến lượt khám; nếu thấy nặng hơn, hãy chủ động báo cho quầy tiếp nhận hoặc nhân viên y tế tại chỗ.",
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
