// =============================================================================
// LanguageSwitcher — UI 語言切換按鈕（下拉式）
// 點擊切換介面語言；同步 i18next / settingsStore / <html lang>，toast 告知。
// =============================================================================

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import toast from 'react-hot-toast';

import { SUPPORTED_LANGUAGES, type SupportedLanguage } from '../../i18n';
import { useSettingsStore } from '../../stores/settingsStore';
import { useAuthStore } from '../../stores/authStore';
import * as authApi from '../../services/api/auth';

interface LanguageSwitcherProps {
  /** 緊湊模式（只顯示 icon + 兩字縮寫），預設 true — 適合 Header */
  compact?: boolean;
}

const SHORT_LABELS: Record<SupportedLanguage, string> = {
  'zh-TW': '繁',
  'en-US': 'EN',
};

export default function LanguageSwitcher({ compact = true }: LanguageSwitcherProps) {
  const { t } = useTranslation('common');
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, []);

  const handleSelect = (lng: SupportedLanguage) => {
    setOpen(false);
    if (lng === language) return;
    setLanguage(lng);
    toast.success(t('language.switched', { name: t(`language.names.${lng}`) }));

    // 已登入 → PATCH /auth/me 持久化偏好，失敗不擋 UI 切換
    if (isAuthenticated && user && user.preferredLanguage !== lng) {
      void authApi
        .updateMe({ preferredLanguage: lng })
        .then((updated) => {
          useAuthStore.setState({ user: updated });
        })
        .catch(() => {
          // 後端寫入失敗不 toast error — 下次登入仍會用本地設定；避免切語言變成阻斷操作
        });
    }
  };

  const currentName = t(`language.names.${language}`);

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        className="btn-ghost flex items-center gap-1.5 px-2 py-1.5"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('language.current', { name: currentName })}
        data-testid="language-switcher"
      >
        <svg
          className="h-5 w-5 text-ink-secondary"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 21a9 9 0 100-18 9 9 0 000 18zm0 0c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3s-4.5 4.03-4.5 9 2.015 9 4.5 9zM3 12h18"
          />
        </svg>
        {compact ? (
          <span className="text-caption font-semibold text-ink-body dark:text-dark-text-secondary">
            {SHORT_LABELS[language]}
          </span>
        ) : (
          <span className="text-body font-medium text-ink-body dark:text-dark-text-secondary">
            {currentName}
          </span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 w-44 rounded-panel border border-edge bg-surface-primary py-1 shadow-elevated animate-slide-down dark:bg-dark-card dark:border-dark-border"
        >
          {SUPPORTED_LANGUAGES.map((lng) => {
            const isActive = lng === language;
            const name = t(`language.names.${lng}`);
            return (
              <button
                key={lng}
                role="menuitemradio"
                aria-checked={isActive}
                type="button"
                className={`flex w-full items-center justify-between px-4 py-2.5 text-body transition-colors hover:bg-surface-tertiary dark:hover:bg-dark-hover ${
                  isActive
                    ? 'text-primary-700 dark:text-primary-200 font-medium'
                    : 'text-ink-body dark:text-dark-text-secondary'
                }`}
                onClick={() => handleSelect(lng)}
                data-testid={`language-option-${lng}`}
                aria-label={t('language.switchTo', { name })}
              >
                <span>{name}</span>
                {isActive && (
                  <svg
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                    aria-hidden="true"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
