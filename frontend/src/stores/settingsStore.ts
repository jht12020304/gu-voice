// =============================================================================
// 設定狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import i18n, { SUPPORTED_LANGUAGES, type SupportedLanguage } from '../i18n';

type Theme = 'light' | 'dark';
type Language = SupportedLanguage;

interface SettingsState {
  theme: Theme;
  language: Language;
  audioInputDevice: string;
  notificationsEnabled: boolean;
  soundEnabled: boolean;
}

interface SettingsActions {
  setTheme: (theme: Theme) => void;
  setLanguage: (language: Language) => void;
  setAudioDevice: (deviceId: string) => void;
  setNotificationsEnabled: (enabled: boolean) => void;
  setSoundEnabled: (enabled: boolean) => void;
}

function isSupportedLanguage(v: unknown): v is Language {
  return typeof v === 'string' && (SUPPORTED_LANGUAGES as readonly string[]).includes(v);
}

export const useSettingsStore = create<SettingsState & SettingsActions>()(
  persist(
    (set) => ({
      // ---- State ----
      theme: 'light',
      // 初始值從 i18next 讀，確保與 localStorage/navigator 偵測結果一致
      language: isSupportedLanguage(i18n.language) ? i18n.language : 'zh-TW',
      audioInputDevice: 'default',
      notificationsEnabled: true,
      soundEnabled: true,

      // ---- Actions ----
      setTheme: (theme) => {
        document.documentElement.classList.toggle('dark', theme === 'dark');
        set({ theme });
      },
      setLanguage: (language) => {
        // 雙向同步 i18next — store 改值立即生效到 UI
        void i18n.changeLanguage(language);
        set({ language });
      },
      setAudioDevice: (deviceId) => set({ audioInputDevice: deviceId }),
      setNotificationsEnabled: (enabled) => set({ notificationsEnabled: enabled }),
      setSoundEnabled: (enabled) => set({ soundEnabled: enabled }),
    }),
    {
      name: 'gu-settings',
    },
  ),
);

// i18next 若因其他來源（如 LanguageSwitcher 直接呼叫）改變，同步回 store
i18n.on('languageChanged', (lng) => {
  if (isSupportedLanguage(lng)) {
    const current = useSettingsStore.getState().language;
    if (current !== lng) {
      useSettingsStore.setState({ language: lng });
    }
  }
});
