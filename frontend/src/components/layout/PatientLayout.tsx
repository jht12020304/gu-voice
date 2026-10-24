// =============================================================================
// 病患端版面配置 — 簡潔 Header + 全寬內容（無 Sidebar）
// =============================================================================

import { Suspense, useState, useRef } from 'react';
import LoadingSpinner from '../common/LoadingSpinner';
import { Outlet } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../../stores/authStore';
import { useLocalizedNavigate } from '../../i18n/paths';
import { useClickOutside } from '../../hooks/useClickOutside';
import LanguageSwitcher from '../common/LanguageSwitcher';
import ThemeToggle from '../common/ThemeToggle';

export default function PatientLayout() {
  const navigate = useLocalizedNavigate();
  const { t } = useTranslation('common');
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useClickOutside(menuRef, () => setMenuOpen(false));

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-surface-secondary dark:bg-dark-bg">
      {/* Header */}
      <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-edge bg-surface-primary px-3 shadow-card sm:px-6 dark:bg-dark-bg dark:border-dark-border">
        <button
          className="flex min-w-0 items-center gap-2.5 transition-opacity hover:opacity-80"
          onClick={() => navigate(user?.role && user.role !== 'patient' ? '/dashboard' : '/patient')}
        >
          <img src="/logo.png" alt="UroSense" className="h-8 w-8 shrink-0 object-contain" />
          <span className="truncate text-h3 font-semibold text-ink-heading dark:text-white">UroSense</span>
        </button>

        <div className="flex shrink-0 items-center sm:gap-2">
          <LanguageSwitcher />
          <ThemeToggle />

          <div className="relative" ref={menuRef}>
            <button
              className="flex h-11 min-w-11 items-center justify-center gap-2 rounded-card px-1 py-1.5 transition-colors hover:bg-surface-tertiary sm:px-2"
              onClick={() => setMenuOpen(!menuOpen)}
              aria-label={user?.name || t('patientLayout.patient')}
              aria-expanded={menuOpen}
            >
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-100 text-caption font-semibold text-primary-700 dark:bg-primary-900 dark:text-primary-200">
                {user?.name?.charAt(0) || 'P'}
              </div>
              <span className="hidden max-w-40 truncate text-body font-medium text-ink-heading md:block dark:text-white">
                {user?.name || t('patientLayout.patient')}
              </span>
              <svg className={`hidden h-4 w-4 text-ink-muted transition-transform sm:block ${menuOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {menuOpen && (
              <div className="absolute right-0 top-full z-50 mt-1 w-48 rounded-panel border border-edge bg-surface-primary py-1 shadow-elevated animate-slide-down dark:bg-dark-card dark:border-dark-border">
                <div className="border-b border-edge px-4 py-3 dark:border-dark-border">
                  <p className="text-body font-medium text-ink-heading dark:text-white">{user?.name}</p>
                  <p className="text-tiny text-ink-muted">{user?.email}</p>
                </div>
                {user?.role && user.role !== 'patient' && (
                  <button
                    className="flex w-full items-center gap-2 border-b border-edge px-4 py-2.5 text-body font-medium text-primary-600 hover:bg-surface-tertiary dark:border-dark-border dark:text-primary-400 dark:hover:bg-dark-hover"
                    onClick={() => { navigate('/dashboard'); setMenuOpen(false); }}
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
                    </svg>
                    {t('patientLayout.backToAdmin')}
                  </button>
                )}
                <button
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-body text-ink-body hover:bg-surface-tertiary dark:text-dark-text-secondary dark:hover:bg-dark-hover"
                  onClick={() => { navigate('/patient/history'); setMenuOpen(false); }}
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {t('patientLayout.history')}
                </button>
                <button
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-body text-ink-body hover:bg-surface-tertiary dark:text-dark-text-secondary dark:hover:bg-dark-hover"
                  onClick={() => { navigate('/patient/settings'); setMenuOpen(false); }}
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
                  </svg>
                  {t('patientLayout.personalSettings')}
                </button>
                <button
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-body text-alert-critical hover:bg-alert-critical-bg"
                  onClick={handleLogout}
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
                  </svg>
                  {t('header.logout')}
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="min-h-0 min-w-0 flex-1 overflow-auto">
          <Suspense fallback={<LoadingSpinner fullPage />}><Outlet /></Suspense>
      </main>
    </div>
  );
}
