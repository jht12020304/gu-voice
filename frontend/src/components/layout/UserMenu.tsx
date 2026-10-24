// =============================================================================
// 使用者選單（Header / PatientLayout 共用）— 頭像按鈕 + 下拉（姓名/email、自訂項目、登出）
// =============================================================================

import { useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../../stores/authStore';
import { useLocalizedNavigate } from '../../i18n/paths';
import { useClickOutside } from '../../hooks/useClickOutside';

export interface UserMenuItem {
  label: string;
  to: string;
  icon: ReactNode;
  /** 強調樣式（例如「返回管理後台」） */
  emphasized?: boolean;
}

interface UserMenuProps {
  /** user.name 缺省時的顯示文字 */
  fallbackLabel: string;
  /** user.name 缺省時的頭像字母 */
  fallbackInitial: string;
  items: UserMenuItem[];
}

export default function UserMenu({ fallbackLabel, fallbackInitial, items }: UserMenuProps) {
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
    <div className="relative" ref={menuRef}>
      <button
        className="flex h-11 min-w-11 items-center justify-center gap-2 rounded-card px-1 py-1.5 transition-colors hover:bg-surface-tertiary sm:px-2"
        onClick={() => setMenuOpen(!menuOpen)}
        aria-label={user?.name || fallbackLabel}
        aria-expanded={menuOpen}
      >
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-100 text-caption font-semibold text-primary-700 dark:bg-primary-900 dark:text-primary-200">
          {user?.name?.charAt(0) || fallbackInitial}
        </div>
        <span className="hidden max-w-40 truncate text-body font-medium text-ink-heading md:block dark:text-white">
          {user?.name || fallbackLabel}
        </span>
        <svg className={`hidden h-4 w-4 text-ink-muted transition-transform sm:block ${menuOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {menuOpen && (
        <div className="absolute right-0 top-full z-50 mt-1 w-52 rounded-panel border border-edge bg-surface-primary py-1 shadow-elevated animate-slide-down dark:bg-dark-card dark:border-dark-border">
          <div className="border-b border-edge px-4 py-3 dark:border-dark-border">
            <p className="text-body font-medium text-ink-heading dark:text-white">{user?.name}</p>
            <p className="text-tiny text-ink-muted">{user?.email}</p>
          </div>
          {items.map((item) => (
            <button
              key={item.to}
              className={
                item.emphasized
                  ? 'flex w-full items-center gap-2 border-b border-edge px-4 py-2.5 text-body font-medium text-primary-600 hover:bg-surface-tertiary dark:border-dark-border dark:text-primary-400 dark:hover:bg-dark-hover'
                  : 'flex w-full items-center gap-2 px-4 py-2.5 text-body text-ink-body hover:bg-surface-tertiary dark:text-dark-text-secondary dark:hover:bg-dark-hover'
              }
              onClick={() => { navigate(item.to); setMenuOpen(false); }}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
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
  );
}
