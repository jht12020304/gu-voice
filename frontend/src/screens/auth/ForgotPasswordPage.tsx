// =============================================================================
// 忘記密碼頁
// =============================================================================

import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useCurrentLng } from '../../i18n/paths';
import * as authApi from '../../services/api/auth';

export default function ForgotPasswordPage() {
  const { t } = useTranslation('common');
  const lng = useCurrentLng();
  const [email, setEmail] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSent, setIsSent] = useState(false);
  // 後端沒設 SENDGRID/SMTP 時為 'onsite'：信不會寄出，要引導使用者找現場醫護／管理員
  const [delivery, setDelivery] = useState<'email' | 'onsite'>('onsite');
  const [error, setError] = useState('');

  // 與 utils/validation.validateEmail 一致的格式檢查，回傳已 i18n 的訊息或 null。
  const validateEmailField = (value: string): string | null => {
    if (!value) return t('auth:email.required', '請輸入電子郵件');
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      return t('auth:email.invalid', '電子郵件格式不正確');
    }
    return null;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    const emailError = validateEmailField(email);
    if (emailError) {
      setError(emailError);
      return;
    }

    setIsLoading(true);
    try {
      const { delivery: mode } = await authApi.forgotPassword(email);
      setDelivery(mode);
      setIsSent(true);
    } catch {
      setError(t('auth:forgot.failed', '發送重設連結失敗，請稍後再試'));
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
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
            </svg>
          </div>
          <h1 className="mt-4 text-h1 text-ink-heading dark:text-white">
            {t('auth:forgot.title', '忘記密碼')}
          </h1>
          <p className="mt-1 text-body text-ink-secondary">
            {t('auth:forgot.subtitle', '輸入您的電子郵件，我們將寄送重設密碼連結')}
          </p>
        </div>

        <div className="card p-8">
          {isSent ? (
            /* 成功畫面 */
            <div className="text-center">
              <div
                className={`mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full ${
                  delivery === 'email' ? 'bg-alert-success-bg' : 'bg-alert-medium-bg'
                }`}
              >
                <svg
                  className={`h-6 w-6 ${
                    delivery === 'email' ? 'text-alert-success' : 'text-alert-medium'
                  }`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  {/* onsite 沒有「完成」任何事，不該給打勾 → 改資訊圖示 */}
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d={
                      delivery === 'email'
                        ? 'M5 13l4 4L19 7'
                        : 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
                    }
                  />
                </svg>
              </div>
              {delivery === 'email' ? (
                <>
                  <h2 className="text-h3 text-ink-heading dark:text-white">
                    {t('auth:forgot.sentTitle', '已寄送重設連結')}
                  </h2>
                  <p className="mt-2 text-body text-ink-secondary">
                    {t('auth:forgot.sentPrefix', '請檢查 ')}
                    <span className="font-medium text-ink-heading dark:text-white">{email}</span>
                    {t('auth:forgot.sentSuffix', ' 的收件匣，並依照信件中的指示重設密碼。')}
                  </p>
                </>
              ) : (
                /* 後端無 email transport：不謊稱已寄出，引導找現場人員（院內 kiosk 情境） */
                <>
                  <h2 className="text-h3 text-ink-heading dark:text-white">
                    {t('auth:forgot.onsiteTitle', '請找現場人員協助重設')}
                  </h2>
                  <p className="mt-2 text-body text-ink-secondary">
                    {t(
                      'auth:forgot.onsiteBody',
                      '目前系統無法寄送重設信。請告知現場醫護或系統管理員，由他們協助您重設密碼。',
                    )}
                  </p>
                </>
              )}
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
                <label htmlFor="email" className="block text-caption font-medium text-ink-body dark:text-dark-border">
                  {t('auth:forgot.emailLabel', '電子郵件')}
                </label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  className="input-base mt-1 py-2.5"
                  autoFocus
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
                  t('auth:forgot.submit', '發送重設連結')
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
