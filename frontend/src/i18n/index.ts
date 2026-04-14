// =============================================================================
// i18n 初始化 — react-i18next + 瀏覽器語言偵測
// 主語系 zh-TW；en 僅為骨架翻譯，待未來補齊。
// =============================================================================

import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import zhTWCommon from './locales/zh-TW/common.json';
import zhTWConversation from './locales/zh-TW/conversation.json';
import enCommon from './locales/en/common.json';
import enConversation from './locales/en/conversation.json';

export const defaultNS = 'common';

export const resources = {
  'zh-TW': {
    common: zhTWCommon,
    conversation: zhTWConversation,
  },
  en: {
    common: enCommon,
    conversation: enConversation,
  },
} as const;

void i18next
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'zh-TW',
    supportedLngs: ['zh-TW', 'en'],
    defaultNS,
    ns: ['common', 'conversation'],
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

export default i18next;
