// =============================================================================
// 設定狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import { persist } from 'zustand/middleware';


type Theme = 'light' | 'dark';

// 病患語音問診的 AI 語音（TTS）偏好。預設出聲（ttsMuted=false）：文字與紅旗 banner
// 永遠看得到，但對低識字/視障病患語音更友善，故不預設靜音。ttsSpeed 為前端 playbackRate
// 倍率（1.0 = 不加速；上限 1.5，避免句子聽不清）。兩者經 persist 存進 'gu-settings'。
const TTS_SPEED_MIN = 0.75;
const TTS_SPEED_MAX = 1.5;

interface SettingsState {
  theme: Theme;
  audioInputDevice: string;
  notificationsEnabled: boolean;
  soundEnabled: boolean;
  ttsMuted: boolean;
  ttsSpeed: number;
}

interface SettingsActions {
  setTheme: (theme: Theme) => void;
  setAudioDevice: (deviceId: string) => void;
  setNotificationsEnabled: (enabled: boolean) => void;
  setSoundEnabled: (enabled: boolean) => void;
  setTtsMuted: (muted: boolean) => void;
  toggleTtsMuted: () => void;
  setTtsSpeed: (speed: number) => void;
}

export const useSettingsStore = create<SettingsState & SettingsActions>()(
  persist(
    (set) => ({
      // ---- State ----
      theme: 'light',
      // 語言不在這裡：URL `/:lng` 是唯一權威（CLAUDE.md），讀 `useCurrentLng()`，
      // i18next 由 LanguageLayout 依 URL 同步。
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
      // v1：移除 persisted `language`（舊版把語言存進 localStorage，與「URL 唯一權威」衝突）。
      version: 1,
      migrate: (persisted) => {
        const state = { ...(persisted as Record<string, unknown>) };
        delete state.language;
        return state as unknown as SettingsState & SettingsActions;
      },
    },
  ),
);
