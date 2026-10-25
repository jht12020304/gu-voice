// =============================================================================
// 頂部導航列 — Stripe 精緻邊框 + 藍調陰影
// =============================================================================

import { useTranslation } from 'react-i18next';
import { useNotificationStore } from '../../stores/notificationStore';
import { useLocalizedNavigate } from '../../i18n/paths';
import LanguageSwitcher from '../common/LanguageSwitcher';
import ThemeToggle from '../common/ThemeToggle';
import UserMenu from './UserMenu';

export default function Header({ navigationOpen, onOpenNavigation }: {
  navigationOpen: boolean;
  onOpenNavigation: () => void;
}) {
  const navigate = useLocalizedNavigate();
  const { t } = useTranslation('common');
  const unreadCount = useNotificationStore((s) => s.unreadCount);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-edge bg-surface-primary px-3 shadow-card sm:px-6 dark:bg-dark-bg dark:border-dark-border">
      {/* 左側：標題 */}
      <div className="flex min-w-0 items-center gap-2">
        <button type="button" className="btn-ghost h-11 min-w-11 shrink-0 p-2 md:hidden"
          onClick={onOpenNavigation} aria-label={t('header.navigation')}
          aria-haspopup="dialog" aria-expanded={navigationOpen}>
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <h1 className="truncate text-h3 text-ink-heading dark:text-white">
          <span className="hidden sm:inline">{t('appTitle')}</span><span className="sm:hidden">UroSense</span>
        </h1>
      </div>

      {/* 右側：功能區 */}
      <div className="flex shrink-0 items-center sm:gap-2">
        {/* 語言切換 */}
        <LanguageSwitcher />

        {/* 暗色模式切換 */}
        <ThemeToggle />

        {/* 通知鈴鐺 */}
        <button
          className="btn-ghost relative h-11 min-w-11 p-2"
          onClick={() => navigate('/notifications')}
          aria-label={t('header.notifications')}
        >
          <svg className="h-5 w-5 text-ink-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
          </svg>
          {unreadCount > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4.5 min-w-[18px] items-center justify-center rounded-pill bg-alert-critical px-1 text-tiny font-semibold text-white">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </button>

        {/* 使用者選單 */}
        <UserMenu
          fallbackLabel={t('user')}
          fallbackInitial="U"
          items={[
            {
              label: t('header.settings'),
              to: '/settings',
              icon: (
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              ),
            },
          ]}
        />
      </div>
    </header>
  );
}
