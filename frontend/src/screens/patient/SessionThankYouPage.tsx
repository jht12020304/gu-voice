// =============================================================================
// 問診結束感謝頁 — 顯示感謝訊息後自動回到病患首頁
// 僅用於 ConversationPage 完成問診後導向；歷史紀錄仍使用 SessionCompletePage。
// =============================================================================

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocalizedNavigate } from '../../i18n/paths';

/** 自動跳轉回首頁的延遲（毫秒） */
const AUTO_REDIRECT_MS = 8000;

export default function SessionThankYouPage() {
  const navigate = useLocalizedNavigate();
  const { t } = useTranslation('session');

  useEffect(() => {
    const timer = setTimeout(() => {
      navigate('/patient', { replace: true });
    }, AUTO_REDIRECT_MS);
    return () => clearTimeout(timer);
  }, [navigate]);

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-2xl flex-col items-center justify-center px-6 py-10 text-center animate-fade-in">
      {/* 完成標誌 */}
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30">
        <svg
          className="h-8 w-8 text-green-600 dark:text-green-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
      </div>

      <h1 className="text-h1 font-semibold tracking-tight text-ink-heading dark:text-white">
        {t('thankYou.title')}
      </h1>

      <p className="mt-6 max-w-xl text-body leading-relaxed text-ink-body dark:text-white/80">
        {t('thankYou.message')}
      </p>

      <p className="mt-8 text-small text-ink-muted dark:text-white/40">
        {t('thankYou.autoRedirectHint')}
      </p>

      <button
        className="btn-primary mt-6 px-8 py-3"
        onClick={() => navigate('/patient', { replace: true })}
      >
        {t('thankYou.backNowAction')}
      </button>
    </div>
  );
}
