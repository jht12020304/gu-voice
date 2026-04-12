// =============================================================================
// 設定狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

type Theme = 'light' | 'dark';
type Language = 'zh-TW' | 'en';

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

export const useSettingsStore = create<SettingsState & SettingsActions>()(
  persist(
    (set) => ({
      // ---- State ----
      theme: 'light',
      language: 'zh-TW',
      audioInputDevice: 'default',
      notificationsEnabled: true,
      soundEnabled: true,

      // ---- Actions ----
      setTheme: (theme) => {
        document.documentElement.classList.toggle('dark', theme === 'dark');
        set({ theme });
      },
      setLanguage: (language) => set({ language }),
      setAudioDevice: (deviceId) => set({ audioInputDevice: deviceId }),
      setNotificationsEnabled: (enabled) => set({ notificationsEnabled: enabled }),
      setSoundEnabled: (enabled) => set({ soundEnabled: enabled }),
    }),
    {
      name: 'gu-settings',
    },
  ),
);
