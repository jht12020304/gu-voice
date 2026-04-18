// =============================================================================
// i18n 初始化 — react-i18next + HTTP Backend（動態載入 locale JSON）+ 瀏覽器語言偵測
// 主語系 zh-TW；en-US 為 active 第二語系；ja-JP / ko-KR / vi-VN 為 beta。
//
// 載入機制：
//   - i18next-http-backend 在執行期向 /locales/<lng>/<ns>.json 取資料，
//     初始 bundle 僅下載當下語言/命名空間，減少 first paint bytes。
//   - Source of truth 是 src/i18n/locales/；Vite plugin（定義於
//     vite.config.ts 的 i18nLocalesSync）會在 dev / build 時把檔案
//     同步到 public/locales/，讓瀏覽器可透過 HTTP 直接讀取。
//   - beta locale 未補齊的 namespace 透過 fallbackLng 退回 en-US → zh-TW。
// =============================================================================

import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import HttpBackend from 'i18next-http-backend';

export const defaultNS = 'common';

// 與後端 settings.LANGUAGE_MAP 一致（BCP-47 完整 locale code）。
// status=active：zh-TW / en-US；status=beta：ja-JP / ko-KR / vi-VN（前端可切、翻譯未齊）。
export const SUPPORTED_LANGUAGES = ['zh-TW', 'en-US', 'ja-JP', 'ko-KR', 'vi-VN'] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

// 標示哪些 locale 是 beta（UI 用於加 "(beta)" 標籤）；上線 active 清單由後端 API 權威。
export const BETA_LANGUAGES: readonly SupportedLanguage[] = ['ja-JP', 'ko-KR', 'vi-VN'];

// 所有頁面 / 元件可能會 useTranslation 的 namespace。未列出的會在首次
// 被引用時才以 loadNamespaces() 補抓；列在這裡會在 init 時預載。
// NOTE: 新增 namespace 時務必：
//   1) 在 src/i18n/locales/<lng>/ 建對應 .json（Vite plugin 會同步到 public/）
//   2) 加進下方 ALL_NAMESPACES 陣列
export const ALL_NAMESPACES = [
  'common',
  'conversation',
  'ws',
  'intake',
  'soap',
  'dashboard',
  'session',
] as const;

void i18next
  .use(HttpBackend)
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    // 三層 fallback：選 locale 缺 key → en-US → zh-TW（active locale 是翻譯最完整的後盾）
    fallbackLng: {
      'ja-JP': ['en-US', 'zh-TW'],
      'ko-KR': ['en-US', 'zh-TW'],
      'vi-VN': ['en-US', 'zh-TW'],
      default: ['zh-TW'],
    },
    // 注意：i18next v26 的 isSupportedCode 對 `zh-TW` 比對會返回 false，
    // 讓 toResolveHierarchy 回空陣列導致 t() 完全失靈。這裡沿用舊實作：
    // 不設 supportedLngs，改由 fallbackLng + LanguageDetector 控制。
    defaultNS,
    ns: ALL_NAMESPACES as unknown as string[],
    // 讓 react-i18next 透過 Suspense 等待 namespace 載入完成（main.tsx 有 <Suspense>）
    react: {
      useSuspense: true,
    },
    backend: {
      // Vite 會把 frontend/public/ 當 static root；build 後也會 copy 到 dist/。
      // i18next-http-backend 會將 {{lng}} / {{ns}} 替換掉。
      loadPath: '/locales/{{lng}}/{{ns}}.json',
      requestOptions: {
        cache: 'default',
      },
    },
    interpolation: {
      escapeValue: false, // React already escapes
    },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'urosense:lng',
    },
    returnNull: false,
  });

// i18next 切換時同步 <html lang=""> 以利 screen reader / SEO
i18next.on('languageChanged', (lng) => {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = lng;
  }
});

// Dev-only: 讓 console 直接操作 i18next 方便除錯
if (import.meta.env.DEV && typeof window !== 'undefined') {
  (window as unknown as { i18next: typeof i18next }).i18next = i18next;
}

export default i18next;
