// =============================================================================
// i18n 初始化 — react-i18next + 瀏覽器語言偵測
// 主語系 zh-TW；en 僅為骨架翻譯，待未來補齊。
// =============================================================================

import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import zhTWCommon from './locales/zh-TW/common.json';
import zhTWConversation from './locales/zh-TW/conversation.json';
import zhTWWs from './locales/zh-TW/ws.json';
import enUSCommon from './locales/en-US/common.json';
import enUSConversation from './locales/en-US/conversation.json';
import enUSWs from './locales/en-US/ws.json';

export const defaultNS = 'common';

// 與後端 settings.SUPPORTED_LANGUAGES 一致（BCP-47 完整 locale code）
export const SUPPORTED_LANGUAGES = ['zh-TW', 'en-US'] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export const resources = {
  'zh-TW': {
    common: zhTWCommon,
    conversation: zhTWConversation,
    ws: zhTWWs,
  },
  'en-US': {
    common: enUSCommon,
    conversation: enUSConversation,
    ws: enUSWs,
  },
} as const;

void i18next
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'zh-TW',
    // 注意：i18next v26 的 isSupportedCode 對 `zh-TW` 比對會返回 false，
    // 讓 toResolveHierarchy 回空陣列導致 t() 完全失靈。既然 resources 已
    // inline 載入，不設 supportedLngs 改由 fallbackLng + LanguageDetector 控制。
    defaultNS,
    ns: ['common', 'conversation', 'ws'],
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
