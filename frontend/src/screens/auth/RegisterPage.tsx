import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Mail, Lock, User, FileText, ArrowRight } from 'lucide-react';
import { useAuthStore } from '../../stores/authStore';
import { useCurrentLng, useLocalizedNavigate } from '../../i18n/paths';
import * as authApi from '../../services/api/auth';

export default function RegisterPage() {
  const { t } = useTranslation('common');
  const navigate = useLocalizedNavigate();
  const lng = useCurrentLng();
  const hydrateFromStorage = useAuthStore((state) => state.hydrateFromStorage);
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    password: '',
    confirmPassword: '',
    mrrn: '', // Medical Record Number (optional)
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  // 與 ResetPasswordPage（utils/validation.validatePassword）一致的密碼強度規則：
  // 至少 8 字元，且包含大寫、小寫與數字。回傳已 i18n 的錯誤訊息或 null。
  const validatePasswordStrength = (password: string): string | null => {
    if (!password) return t('auth:password.required', '請輸入密碼');
    if (password.length < 8) return t('auth:password.minLength', '密碼至少需要 8 個字元');
    if (!/[A-Z]/.test(password)) return t('auth:password.needUppercase', '密碼需包含大寫字母');
    if (!/[a-z]/.test(password)) return t('auth:password.needLowercase', '密碼需包含小寫字母');
    if (!/[0-9]/.test(password)) return t('auth:password.needDigit', '密碼需包含數字');
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const passwordError = validatePasswordStrength(formData.password);
    if (passwordError) {
      setError(passwordError);
      return;
    }

    if (formData.password !== formData.confirmPassword) {
      setError(t('auth:password.mismatch', '密碼與確認密碼不一致'));
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      const response = await authApi.register({
        email: formData.email,
        password: formData.password,
        name: formData.name,
        role: 'patient',
      });

      // 雙路徑 refresh（與 authStore.login 同契約）：後端 body 與 httpOnly cookie 同時
      // 下發 refresh token；跨站部署（Vercel↔Railway，SameSite=lax cookie 送不出去）只有
      // localStorage 這份能用，漏存會讓新註冊者在 access token 過期後被踢回登入頁。
      localStorage.setItem('access_token', response.accessToken);
      if (response.refreshToken) {
        localStorage.setItem('refresh_token', response.refreshToken);
      }
      await hydrateFromStorage();
      navigate('/patient');
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error
          ?.message || t('auth:register.failed', '註冊失敗，請稍後再試');
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid grid-cols-1 md:grid-cols-2">
      {/* 左半部：表單區域 */}
      <div className="flex items-center justify-center p-8 bg-surface-50">
        <div className="w-full max-w-md">
          <div className="mb-10 text-center">
            <h1 className="text-3xl font-bold tracking-tight text-primary-900 mb-2">
              {t('auth:register.title', '建立新帳號')}
            </h1>
            <p className="text-surface-500">
              {t('auth:register.subtitle', '快速註冊，體驗智慧醫療助理服務')}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
              <div className="p-4 rounded-xl bg-red-50 border border-red-200">
                <p className="text-sm font-medium text-red-600">{error}</p>
              </div>
            )}

            <div className="space-y-4">
              {/* 姓名 */}
              <div>
                <label className="block text-sm font-medium text-surface-700 mb-1">
                  {t('auth:register.nameLabel', '真實姓名')}
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <User className="h-5 w-5 text-surface-400" />
                  </div>
                  <input
                    type="text"
                    name="name"
                    required
                    value={formData.name}
                    onChange={handleChange}
                    className="block w-full pl-10 pr-3 py-3 border border-surface-200 rounded-xl bg-white shadow-sm placeholder-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors sm:text-sm"
                    placeholder={t('auth:register.namePlaceholder', '王小明')}
                  />
                </div>
              </div>

              {/* Email */}
              <div>
                <label className="block text-sm font-medium text-surface-700 mb-1">
                  {t('auth:register.emailLabel', '電子信箱')}
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Mail className="h-5 w-5 text-surface-400" />
                  </div>
                  <input
                    type="email"
                    name="email"
                    required
                    value={formData.email}
                    onChange={handleChange}
                    className="block w-full pl-10 pr-3 py-3 border border-surface-200 rounded-xl bg-white shadow-sm placeholder-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors sm:text-sm"
                    placeholder="your@email.com"
                  />
                </div>
              </div>

              {/* 身分證號 / 病歷號 (選填) */}
              <div>
                <label className="block text-sm font-medium text-surface-700 mb-1">
                  {t('auth:register.mrrnLabel', '病歷號 / 身分證字號 (選填)')}
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <FileText className="h-5 w-5 text-surface-400" />
                  </div>
                  <input
                    type="text"
                    name="mrrn"
                    value={formData.mrrn}
                    onChange={handleChange}
                    className="block w-full pl-10 pr-3 py-3 border border-surface-200 rounded-xl bg-white shadow-sm placeholder-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors sm:text-sm"
                    placeholder={t('auth:register.mrrnPlaceholder', '若您已有本院病歷號請填寫')}
                  />
                </div>
              </div>

              {/* 密碼 */}
              <div>
                <label className="block text-sm font-medium text-surface-700 mb-1">
                  {t('auth:register.passwordLabel', '設定密碼')}
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Lock className="h-5 w-5 text-surface-400" />
                  </div>
                  <input
                    type="password"
                    name="password"
                    required
                    value={formData.password}
                    onChange={handleChange}
                    autoComplete="new-password"
                    className="block w-full pl-10 pr-3 py-3 border border-surface-200 rounded-xl bg-white shadow-sm placeholder-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors sm:text-sm"
                    placeholder={t('auth:password.hint', '至少 8 個字元，含大小寫與數字')}
                  />
                </div>
                <p className="mt-1 text-xs text-surface-400">
                  {t('auth:password.hint', '至少 8 個字元，含大小寫與數字')}
                </p>
              </div>

              {/* 確認密碼 */}
              <div>
                <label className="block text-sm font-medium text-surface-700 mb-1">
                  {t('auth:register.confirmPasswordLabel', '確認密碼')}
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Lock className="h-5 w-5 text-surface-400" />
                  </div>
                  <input
                    type="password"
                    name="confirmPassword"
                    required
                    value={formData.confirmPassword}
                    onChange={handleChange}
                    autoComplete="new-password"
                    className="block w-full pl-10 pr-3 py-3 border border-surface-200 rounded-xl bg-white shadow-sm placeholder-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors sm:text-sm"
                    placeholder={t('auth:register.confirmPasswordPlaceholder', '再次輸入密碼')}
                  />
                </div>
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full flex items-center justify-center py-3.5 px-4 border border-transparent rounded-xl shadow-sm text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all active:scale-[0.98]"
            >
              {isLoading ? (
                <div className="h-5 w-5 border-2 border-white/20 border-t-white rounded-full animate-spin" />
              ) : (
                <>
                  {t('auth:register.submit', '註冊帳號')}
                  <ArrowRight className="ml-2 h-4 w-4" />
                </>
              )}
            </button>

            <div className="text-center mt-6">
              <p className="text-surface-500 text-sm">
                {t('auth:register.haveAccount', '已經有帳號了嗎？')}{' '}
                <Link to={`/${lng}/login`} className="font-medium text-primary-600 hover:text-primary-500 transition-colors cursor-pointer">
                  {t('auth:register.loginNow', '立即登入')}
                </Link>
              </p>
            </div>
          </form>
        </div>
      </div>

      {/* 右半部：視覺裝飾 */}
      <div className="hidden md:block relative bg-primary-600 overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-primary-500 to-primary-800" />
        <div className="absolute inset-0 bg-[url('https://images.unsplash.com/photo-1576091160550-2173ff9e5ee5?q=80&w=2069&auto=format&fit=crop')] bg-cover bg-center mix-blend-overlay opacity-20" />
        <div className="absolute inset-0 flex flex-col items-center justify-center p-12 text-center text-white">
          <div className="w-20 h-20 bg-white/10 backdrop-blur-md rounded-3xl flex items-center justify-center mb-8 border border-white/20 shadow-2xl">
            <span className="text-4xl">🏥</span>
          </div>
          <h2 className="text-3xl font-bold tracking-tight mb-4 text-white">
            {t('auth:register.heroTitle', '智慧就醫第一步')}
          </h2>
          <p className="text-primary-100 text-lg max-w-md font-medium leading-relaxed">
            {t('auth:register.heroLine1', '加入我們的系統，體驗精準醫療與高效問診流程。')}
            <br />
            {t('auth:register.heroLine2', '您的健康紀錄將獲得最妥善的保護。')}
          </p>
        </div>
      </div>
    </div>
  );
}
