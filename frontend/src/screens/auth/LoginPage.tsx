// =============================================================================
// 登入頁 — Stripe 風格信任感設計
// =============================================================================

import { useState, type FormEvent } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';

export default function LoginPage() {
  const { isAuthenticated, isLoading, error, login, clearError, user } = useAuthStore();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [localError, setLocalError] = useState('');

  // 已認證則重導
  if (isAuthenticated && user) {
    const target =
      user.role === 'patient' ? '/patient/home' : user.role === 'admin' ? '/admin/users' : '/dashboard';
    return <Navigate to={target} replace />;
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLocalError('');
    clearError();

    if (!email.trim()) {
      setLocalError('請輸入電子郵件');
      return;
    }
    if (!password) {
      setLocalError('請輸入密碼');
      return;
    }

    try {
      await login(email, password);
    } catch {
      // error 由 store 管理
    }
  };

  const displayError = localError || error;

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-secondary px-4 dark:bg-dark-bg">
      <div className="w-full max-w-md animate-fade-in">
        {/* Logo + 標題 */}
        <div className="mb-8 text-center">
          <img src="/logo.png" alt="UroSense" className="mx-auto h-20 w-20 object-contain" />
          <h1 className="mt-3 text-h1 text-ink-heading dark:text-white">UroSense</h1>
          <p className="mt-1 text-body text-ink-secondary">請登入您的帳號</p>
        </div>

        {/* 登入表單 */}
        <div className="card p-8">
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* 錯誤訊息 */}
            {displayError && (
              <div className="rounded-card bg-alert-critical-bg border border-alert-critical-border p-3 text-body text-alert-critical-text">
                {displayError}
              </div>
            )}

            {/* Email */}
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
                autoComplete="email"
                autoFocus
              />
            </div>

            {/* 密碼 */}
            <div>
              <label htmlFor="password" className="block text-caption font-medium text-ink-body dark:text-dark-border">
                密碼
              </label>
              <div className="relative mt-1">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="輸入密碼"
                  className="input-base py-2.5 pr-10"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-placeholder hover:text-ink-secondary transition-colors"
                  onClick={() => setShowPassword(!showPassword)}
                  tabIndex={-1}
                >
                  {showPassword ? (
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L6.59 6.59m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                    </svg>
                  ) : (
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            {/* 忘記密碼 */}
            <div className="text-right">
              <Link to="/forgot-password" className="text-caption text-primary-600 hover:text-primary-700 font-medium transition-colors">
                忘記密碼？
              </Link>
            </div>

            {/* 登入按鈕 */}
            <button
              type="submit"
              disabled={isLoading}
              className="btn-primary w-full py-2.5"
            >
              {isLoading ? (
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                '登入'
              )}
            </button>
          </form>
        </div>

        {/* 底部資訊 */}
        <p className="mt-6 text-center text-small text-ink-muted">
          UroSense v1.0 — 泌尿科 AI 語音問診系統
        </p>
      </div>
    </div>
  );
}
