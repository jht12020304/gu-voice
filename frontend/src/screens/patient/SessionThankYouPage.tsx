// =============================================================================
// 問診結束感謝頁 — 顯示感謝訊息後自動回到病患首頁
// 僅用於 ConversationPage 完成問診後導向；歷史紀錄仍使用 SessionCompletePage。
// 紅旗中止（location.state.abortedRedFlag）時改顯示「請立即告知現場醫護」且不自動跳轉。
// =============================================================================

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router-dom';
import { useLocalizedNavigate } from '../../i18n/paths';

/** 自動跳轉回首頁的延遲（毫秒） */
const AUTO_REDIRECT_MS = 8000;

export default function SessionThankYouPage() {
  const navigate = useLocalizedNavigate();
  const { t } = useTranslation('session');
  const location = useLocation();
  const abortedRedFlag =
    (location.state as { abortedRedFlag?: boolean } | null)?.abortedRedFlag === true;

  useEffect(() => {
    // 紅旗中止：不自動跳轉，讓病患留在此頁去找現場醫護（安全優先）。
    if (abortedRedFlag) return;
    const timer = setTimeout(() => {
      navigate('/patient', { replace: true });
    }, AUTO_REDIRECT_MS);
    return () => clearTimeout(timer);
  }, [navigate, abortedRedFlag]);

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-2xl flex-col items-center justify-center px-6 py-10 text-center animate-fade-in">
      {abortedRedFlag ? (
        <>
          {/* 紅旗警示標誌 */}
          <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/30">
            <svg
              className="h-8 w-8 text-red-600 dark:text-red-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m0 3.75h.008M10.34 3.94l-8.02 13.9A1.5 1.5 0 003.62 20.1h16.76a1.5 1.5 0 001.3-2.26l-8.02-13.9a1.5 1.5 0 00-2.6 0z"
              />
            </svg>
          </div>

          <h1 className="text-h1 font-semibold tracking-tight text-red-700 dark:text-red-300">
            {t('complete.redFlagTitle')}
          </h1>

          {/* 5 語現成文案：偵測到危急紅旗症狀…請立即告知現場櫃台或醫護人員 */}
          <p
            role="alert"
            aria-live="assertive"
            className="mt-6 max-w-xl text-body font-medium leading-relaxed text-ink-body dark:text-white/90"
          >
            {t('events.session.aborted_red_flag', { ns: 'ws' })}
          </p>

          <button
            className="btn-primary mt-8 px-8 py-3"
            onClick={() => navigate('/patient', { replace: true })}
          >
            {t('thankYou.backNowAction')}
          </button>
        </>
      ) : (
        <>
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
        </>
      )}
    </div>
  );
}
