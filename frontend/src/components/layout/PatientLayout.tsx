// =============================================================================
// 病患端版面配置 — 簡潔 Header + 全寬內容（無 Sidebar）
// =============================================================================

import { Suspense } from 'react';
import LoadingSpinner from '../common/LoadingSpinner';
import { Outlet } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../../stores/authStore';
import { useLocalizedNavigate } from '../../i18n/paths';
import LanguageSwitcher from '../common/LanguageSwitcher';
import ThemeToggle from '../common/ThemeToggle';
import UserMenu from './UserMenu';

export default function PatientLayout() {
  const navigate = useLocalizedNavigate();
  const { t } = useTranslation('common');
  const user = useAuthStore((s) => s.user);

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

          <UserMenu
            fallbackLabel={t('patientLayout.patient')}
            fallbackInitial="P"
            items={[
              ...(user?.role && user.role !== 'patient'
                ? [{
                    label: t('patientLayout.backToAdmin'),
                    to: '/dashboard',
                    emphasized: true,
                    icon: (
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
                      </svg>
                    ),
                  }]
                : []),
              {
                label: t('patientLayout.history'),
                to: '/patient/history',
                icon: (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                ),
              },
              {
                label: t('patientLayout.personalSettings'),
                to: '/patient/settings',
                icon: (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
                  </svg>
                ),
              },
            ]}
          />
        </div>
      </header>

      {/* Content */}
      <main className="min-h-0 min-w-0 flex-1 overflow-auto">
          <Suspense fallback={<LoadingSpinner fullPage />}><Outlet /></Suspense>
      </main>
    </div>
  );
}
