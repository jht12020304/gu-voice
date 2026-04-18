// =============================================================================
// 應用程式進入點
// =============================================================================

import React, { Suspense } from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import './i18n';
import { initSentry } from './services/sentry';

initSentry();

// 簡易 i18n 載入 fallback：i18next-http-backend 首次載入 locale JSON 時，
// useTranslation 會觸發 Suspense；這裡以極簡 fallback 避免整頁白屏。
// 直接 inline JSX（而非額外 component）以避免破壞 react-refresh。
const i18nLoadingFallback = (
  <div
    style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#ffffff',
      color: '#64748b',
      fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
      fontSize: '14px',
    }}
    role="status"
    aria-live="polite"
  >
    <span>Loading…</span>
  </div>
);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Suspense fallback={i18nLoadingFallback}>
      <App />
    </Suspense>
  </React.StrictMode>,
);
