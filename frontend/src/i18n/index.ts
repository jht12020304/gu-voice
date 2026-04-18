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
import zhTWIntake from './locales/zh-TW/intake.json';
import enUSCommon from './locales/en-US/common.json';
import enUSConversation from './locales/en-US/conversation.json';
import enUSWs from './locales/en-US/ws.json';
import enUSIntake from './locales/en-US/intake.json';
// Phase C beta locales：完整翻譯未就位前，僅提供骨架 common.json（至少讓
// LanguageSwitcher 切語言不崩），缺 key 靠下方 fallbackLng chain 往 en-US / zh-TW 退。
import jaJPCommon from './locales/ja-JP/common.json';
import koKRCommon from './locales/ko-KR/common.json';
import viVNCommon from './locales/vi-VN/common.json';

export const defaultNS = 'common';

// 與後端 settings.LANGUAGE_MAP 一致（BCP-47 完整 locale code）。
// status=active：zh-TW / en-US；status=beta：ja-JP / ko-KR / vi-VN（前端可切、翻譯未齊）。
export const SUPPORTED_LANGUAGES = ['zh-TW', 'en-US', 'ja-JP', 'ko-KR', 'vi-VN'] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

// 標示哪些 locale 是 beta（UI 用於加 "(beta)" 標籤）；上線 active 清單由後端 API 權威。
export const BETA_LANGUAGES: readonly SupportedLanguage[] = ['ja-JP', 'ko-KR', 'vi-VN'];

export const resources = {
  'zh-TW': {
    common: zhTWCommon,
    conversation: zhTWConversation,
    ws: zhTWWs,
    intake: zhTWIntake,
  },
  'en-US': {
    common: enUSCommon,
    conversation: enUSConversation,
    ws: enUSWs,
    intake: enUSIntake,
  },
  // Beta locales：intake / conversation / ws 都走 fallbackLng 退回 en-US → zh-TW，
  // 不在此 inline 以保持 bundle 輕量；補齊翻譯後再在各 locale 目錄建同名 JSON。
  'ja-JP': { common: jaJPCommon },
  'ko-KR': { common: koKRCommon },
  'vi-VN': { common: viVNCommon },
} as const;

void i18next
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    // 三層 fallback：選 locale 缺 key → en-US → zh-TW（active locale 是翻譯最完整的後盾）
    fallbackLng: {
      'ja-JP': ['en-US', 'zh-TW'],
      'ko-KR': ['en-US', 'zh-TW'],
      'vi-VN': ['en-US', 'zh-TW'],
      default: ['zh-TW'],
    },
    // 注意：i18next v26 的 isSupportedCode 對 `zh-TW` 比對會返回 false，
    // 讓 toResolveHierarchy 回空陣列導致 t() 完全失靈。既然 resources 已
    // inline 載入，不設 supportedLngs 改由 fallbackLng + LanguageDetector 控制。
    defaultNS,
    ns: ['common', 'conversation', 'ws', 'intake'],
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
