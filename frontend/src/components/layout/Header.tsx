// =============================================================================
// 頂部導航列 — 標題（回報告清單）＋語言／主題／使用者選單
// =============================================================================

import { useTranslation } from 'react-i18next';
import { useLocalizedNavigate } from '../../i18n/paths';
import LanguageSwitcher from '../common/LanguageSwitcher';
import ThemeToggle from '../common/ThemeToggle';
import UserMenu from './UserMenu';

export default function Header() {
  const navigate = useLocalizedNavigate();
  const { t } = useTranslation('common');

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-edge bg-surface-primary px-3 shadow-card sm:px-6 dark:bg-dark-bg dark:border-dark-border">
      <button type="button" className="min-w-0 truncate text-left text-h3 text-ink-heading dark:text-white" onClick={() => navigate('/reports')}>
        <span className="hidden sm:inline">{t('appTitle')}</span><span className="sm:hidden">UroSense</span>
      </button>
      <div className="flex shrink-0 items-center sm:gap-2">
        <LanguageSwitcher />
        <ThemeToggle />
        <UserMenu fallbackLabel={t('user')} fallbackInitial="U" />
      </div>
    </header>
  );
}
