// =============================================================================
// 病患端版面配置 — 簡潔 Header + 全寬內容（無 Sidebar）
// =============================================================================

import { useState, useRef, useEffect } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';
import { useSettingsStore } from '../../stores/settingsStore';

export default function PatientLayout() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const { theme, setTheme } = useSettingsStore();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-secondary dark:bg-dark-bg">
      {/* Header */}
      <header className="flex h-14 items-center justify-between border-b border-edge bg-surface-primary px-6 shadow-card dark:bg-dark-bg dark:border-dark-border">
        <button
          className="flex items-center gap-2.5 transition-opacity hover:opacity-80"
          onClick={() => navigate(user?.role && user.role !== 'patient' ? '/dashboard' : '/patient')}
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-card bg-primary-600 text-white">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
            </svg>
          </div>
          <span className="text-h3 font-semibold text-ink-heading dark:text-white">GU Voice</span>
        </button>

        <div className="flex items-center gap-2">
          <button
            className="btn-ghost p-2"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            {theme === 'dark' ? (
              <svg className="h-5 w-5 text-ink-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
              </svg>
            ) : (
              <svg className="h-5 w-5 text-ink-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
              </svg>
            )}
          </button>

          <div className="relative" ref={menuRef}>
            <button
              className="flex items-center gap-2 rounded-card px-2 py-1.5 transition-colors hover:bg-surface-tertiary"
              onClick={() => setMenuOpen(!menuOpen)}
            >
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-100 text-caption font-semibold text-primary-700 dark:bg-primary-900 dark:text-primary-200">
                {user?.name?.charAt(0) || 'P'}
              </div>
              <span className="text-body font-medium text-ink-heading dark:text-white">
                {user?.name || '病患'}
              </span>
              <svg className={`h-4 w-4 text-ink-muted transition-transform ${menuOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
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
                    返回管理後台
                  </button>
                )}
                <button
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-body text-ink-body hover:bg-surface-tertiary dark:text-dark-text-secondary dark:hover:bg-dark-hover"
                  onClick={() => { navigate('/patient/history'); setMenuOpen(false); }}
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  問診紀錄
                </button>
                <button
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-body text-ink-body hover:bg-surface-tertiary dark:text-dark-text-secondary dark:hover:bg-dark-hover"
                  onClick={() => { navigate('/patient/settings'); setMenuOpen(false); }}
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
                  </svg>
                  個人設定
                </button>
                <button
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-body text-alert-critical hover:bg-alert-critical-bg"
                  onClick={handleLogout}
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
                  </svg>
                  登出
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
