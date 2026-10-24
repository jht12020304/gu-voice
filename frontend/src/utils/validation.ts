// =============================================================================
// 表單驗證（i18n-aware）— Register / ResetPassword / ForgotPassword 共用
// 回傳已翻譯的錯誤訊息，或 null 表示通過。
// =============================================================================

import type { TFunction } from 'i18next';

/** 密碼強度：至少 8 字元，含大寫、小寫與數字。 */
export function passwordStrengthError(password: string, t: TFunction): string | null {
  if (!password) return t('auth:password.required', '請輸入密碼');
  if (password.length < 8) return t('auth:password.minLength', '密碼至少需要 8 個字元');
  if (!/[A-Z]/.test(password)) return t('auth:password.needUppercase', '密碼需包含大寫字母');
  if (!/[a-z]/.test(password)) return t('auth:password.needLowercase', '密碼需包含小寫字母');
  if (!/[0-9]/.test(password)) return t('auth:password.needDigit', '密碼需包含數字');
  return null;
}

/** 基本 email 格式檢查。 */
export function emailFormatError(email: string, t: TFunction): string | null {
  if (!email) return t('auth:email.required', '請輸入電子郵件');
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return t('auth:email.invalid', '電子郵件格式不正確');
  return null;
}
