// =============================================================================
// 忘記密碼頁
// =============================================================================

import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { validateEmail } from '../../utils/validation';
import { useCurrentLng } from '../../i18n/paths';
import * as authApi from '../../services/api/auth';

export default function ForgotPasswordPage() {
  const lng = useCurrentLng();
  const [email, setEmail] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSent, setIsSent] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    const emailError = validateEmail(email);
    if (emailError) {
      setError(emailError);
      return;
    }

    setIsLoading(true);
    try {
      await authApi.forgotPassword(email);
      setIsSent(true);
    } catch {
      setError('發送重設連結失敗，請稍後再試');
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
          <h1 className="mt-4 text-h1 text-ink-heading dark:text-white">忘記密碼</h1>
          <p className="mt-1 text-body text-ink-secondary">
            輸入您的電子郵件，我們將寄送重設密碼連結
          </p>
        </div>

        <div className="card p-8">
          {isSent ? (
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
              <h2 className="text-h3 text-ink-heading dark:text-white">已寄送重設連結</h2>
              <p className="mt-2 text-body text-ink-secondary">
                請檢查 <span className="font-medium text-ink-heading dark:text-white">{email}</span> 的收件匣，
                並依照信件中的指示重設密碼。
              </p>
              <Link
                to={`/${lng}/login`}
                className="mt-6 inline-block text-caption font-medium text-primary-600 hover:text-primary-700 transition-colors"
              >
                返回登入
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
                  電子郵件
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
                  '發送重設連結'
                )}
              </button>

              <div className="text-center">
                <Link to={`/${lng}/login`} className="text-caption text-primary-600 hover:text-primary-700 font-medium transition-colors">
                  返回登入
                </Link>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
