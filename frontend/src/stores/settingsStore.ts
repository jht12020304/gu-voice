// =============================================================================
// 設定狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import i18n, { SUPPORTED_LANGUAGES, type SupportedLanguage } from '../i18n';

type Theme = 'light' | 'dark';
type Language = SupportedLanguage;

// 病患語音問診的 AI 語音（TTS）偏好。預設出聲（ttsMuted=false）：文字與紅旗 banner
// 永遠看得到，但對低識字/視障病患語音更友善，故不預設靜音。ttsSpeed 為前端 playbackRate
// 倍率（1.0 = 不加速；上限 1.5，避免句子聽不清）。兩者經 persist 存進 'gu-settings'。
const TTS_SPEED_MIN = 0.75;
const TTS_SPEED_MAX = 1.5;

interface SettingsState {
  theme: Theme;
  language: Language;
  audioInputDevice: string;
  notificationsEnabled: boolean;
  soundEnabled: boolean;
  ttsMuted: boolean;
  ttsSpeed: number;
}

interface SettingsActions {
  setTheme: (theme: Theme) => void;
  setLanguage: (language: Language) => void;
  setAudioDevice: (deviceId: string) => void;
  setNotificationsEnabled: (enabled: boolean) => void;
  setSoundEnabled: (enabled: boolean) => void;
  setTtsMuted: (muted: boolean) => void;
  toggleTtsMuted: () => void;
  setTtsSpeed: (speed: number) => void;
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
      ttsMuted: false,
      ttsSpeed: 1.0,

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
      setTtsMuted: (muted) => set({ ttsMuted: muted }),
      toggleTtsMuted: () => set((s) => ({ ttsMuted: !s.ttsMuted })),
      setTtsSpeed: (speed) =>
        set({ ttsSpeed: Math.min(TTS_SPEED_MAX, Math.max(TTS_SPEED_MIN, speed)) }),
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
