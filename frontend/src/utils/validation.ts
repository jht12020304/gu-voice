// =============================================================================
// 驗證工具函式
// =============================================================================

/**
 * 驗證 Email 格式
 */
export function validateEmail(email: string): string | null {
  if (!email) return '請輸入電子郵件';
  const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!re.test(email)) return '電子郵件格式不正確';
  return null;
}

/**
 * 驗證密碼強度
 * 至少 8 字元，包含大小寫字母與數字
 */
export function validatePassword(password: string): string | null {
  if (!password) return '請輸入密碼';
  if (password.length < 8) return '密碼至少需要 8 個字元';
  if (!/[A-Z]/.test(password)) return '密碼需包含大寫字母';
  if (!/[a-z]/.test(password)) return '密碼需包含小寫字母';
  if (!/[0-9]/.test(password)) return '密碼需包含數字';
  return null;
}

/**
 * 驗證手機號碼（台灣格式）
 */
export function validatePhone(phone: string): string | null {
  if (!phone) return null; // 手機非必填
  const re = /^09\d{8}$/;
  if (!re.test(phone)) return '手機號碼格式不正確（例：0912345678）';
  return null;
}

/**
 * 驗證必填欄位
 */
export function validateRequired(value: string, fieldName: string): string | null {
  if (!value || !value.trim()) return `請輸入${fieldName}`;
  return null;
}

/**
 * 驗證確認密碼
 */
export function validateConfirmPassword(password: string, confirmPassword: string): string | null {
  if (!confirmPassword) return '請確認密碼';
  if (password !== confirmPassword) return '密碼不一致';
  return null;
}
