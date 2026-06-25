// =============================================================================
// 重設密碼頁
// 從 URL query param 讀取 reset token（/reset-password?token=...），
// 輸入新密碼 + 確認密碼，呼叫 authApi.resetPassword(token, newPassword)。
// =============================================================================

import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useCurrentLng } from '../../i18n/paths';
import * as authApi from '../../services/api/auth';

export default function ResetPasswordPage() {
  const { t } = useTranslation('common');
  const lng = useCurrentLng();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isDone, setIsDone] = useState(false);
  const [error, setError] = useState('');

  // 與 utils/validation.validatePassword 一致的密碼強度規則：
  // 至少 8 字元，且包含大寫、小寫與數字。回傳已 i18n 的訊息或 null。
  const validatePasswordStrength = (value: string): string | null => {
    if (!value) return t('auth:password.required', '請輸入密碼');
    if (value.length < 8) return t('auth:password.minLength', '密碼至少需要 8 個字元');
    if (!/[A-Z]/.test(value)) return t('auth:password.needUppercase', '密碼需包含大寫字母');
    if (!/[a-z]/.test(value)) return t('auth:password.needLowercase', '密碼需包含小寫字母');
    if (!/[0-9]/.test(value)) return t('auth:password.needDigit', '密碼需包含數字');
    return null;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    if (!token) {
      setError(t('auth:reset.invalidToken', '重設連結無效或已過期，請重新申請'));
      return;
    }

    const passwordError = validatePasswordStrength(password);
    if (passwordError) {
      setError(passwordError);
      return;
    }

    if (!confirmPassword) {
      setError(t('auth:password.confirmRequired', '請確認密碼'));
      return;
    }
    if (password !== confirmPassword) {
      setError(t('auth:password.confirmMismatch', '密碼不一致'));
      return;
    }

    setIsLoading(true);
    try {
      await authApi.resetPassword(token, password);
      setIsDone(true);
    } catch {
      setError(t('auth:reset.failed', '重設密碼失敗，請確認連結是否有效或稍後再試'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-secondary px-4 dark:bg-dark-bg">
      <div className="w-full max-w-md animate-fade-in">
        {/* 標題 */}
        <div className="mb-8 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-card bg-primary-600 text-xl font-bold text-white shadow-card">
            <svg className="h-7 w-7" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
            </svg>
          </div>
          <h1 className="mt-4 text-h1 text-ink-heading dark:text-white">
            {t('auth:reset.title', '重設密碼')}
          </h1>
          <p className="mt-1 text-body text-ink-secondary">
            {t('auth:reset.subtitle', '請輸入您的新密碼')}
          </p>
        </div>

        <div className="card p-8">
          {isDone ? (
            /* 成功畫面 */
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-alert-success-bg">
                <svg
                  className="h-6 w-6 text-alert-success"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h2 className="text-h3 text-ink-heading dark:text-white">
                {t('auth:reset.doneTitle', '密碼已重設')}
              </h2>
              <p className="mt-2 text-body text-ink-secondary">
                {t('auth:reset.doneMessage', '您的密碼已成功更新，請使用新密碼登入。')}
              </p>
              <Link
                to={`/${lng}/login`}
                className="mt-6 inline-block text-caption font-medium text-primary-600 hover:text-primary-700 transition-colors"
              >
                {t('auth:backToLogin', '返回登入')}
              </Link>
            </div>
          ) : (
            /* 表單 */
            <form onSubmit={handleSubmit} className="space-y-5">
              {error && (
                <div className="rounded-card bg-alert-critical-bg border border-alert-critical-border p-3 text-body text-alert-critical-text">
                  {error}
                </div>
              )}

              <div>
                <label htmlFor="password" className="block text-caption font-medium text-ink-body dark:text-dark-border">
                  {t('auth:reset.newPasswordLabel', '新密碼')}
                </label>
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t('auth:password.hint', '至少 8 個字元，含大小寫與數字')}
                  className="input-base mt-1 py-2.5"
                  autoComplete="new-password"
                  autoFocus
                />
              </div>

              <div>
                <label htmlFor="confirmPassword" className="block text-caption font-medium text-ink-body dark:text-dark-border">
                  {t('auth:reset.confirmPasswordLabel', '確認新密碼')}
                </label>
                <input
                  id="confirmPassword"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder={t('auth:reset.confirmPasswordPlaceholder', '再次輸入新密碼')}
                  className="input-base mt-1 py-2.5"
                  autoComplete="new-password"
                />
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="btn-primary w-full py-2.5"
              >
                {isLoading ? (
                  <div className="h-5 w-5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                ) : (
                  t('auth:reset.submit', '重設密碼')
                )}
              </button>

              <div className="text-center">
                <Link to={`/${lng}/login`} className="text-caption text-primary-600 hover:text-primary-700 font-medium transition-colors">
                  {t('auth:backToLogin', '返回登入')}
                </Link>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
