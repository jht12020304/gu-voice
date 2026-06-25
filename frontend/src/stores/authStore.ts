// =============================================================================
// 認證狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import type { User } from '../types';
import * as authApi from '../services/api/auth';
import { refreshAccessToken } from '../services/api/client';
import i18n, { SUPPORTED_LANGUAGES, type SupportedLanguage } from '../i18n';

/**
 * 若 server 回傳的 preferredLanguage 在白名單內，切換 i18n + settingsStore。
 * 透過 i18n.changeLanguage 就好，settingsStore 已透過 i18n 的 languageChanged 事件同步。
 */
function applyPreferredLanguage(lang: string | null | undefined): void {
  if (!lang) return;
  const allowed = SUPPORTED_LANGUAGES as readonly string[];
  if (!allowed.includes(lang)) return;
  if (i18n.language === lang) return;
  void i18n.changeLanguage(lang as SupportedLanguage);
}

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
}

interface AuthActions {
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
  updateProfile: (data: Partial<User>) => Promise<void>;
  clearError: () => void;
  setLoading: (loading: boolean) => void;
  hydrateFromStorage: () => Promise<void>;
}

export const useAuthStore = create<AuthState & AuthActions>((set, get) => ({
  // ---- State ----
  user: null,
  accessToken: null,
  refreshToken: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,

  // ---- Actions ----

  login: async (email, password) => {
    set({ isLoading: true, error: null });
    try {
      const response = await authApi.login(email, password);
      // M-22：access token 維持 localStorage（既有處理）；refresh token 不再持久化到
      // localStorage，改由後端以 httpOnly cookie 下發、瀏覽器自動保管（防 XSS 竊取）。
      localStorage.setItem('access_token', response.accessToken);
      set({
        user: response.user,
        accessToken: response.accessToken,
        refreshToken: null,
        isAuthenticated: true,
        isLoading: false,
      });
      applyPreferredLanguage(response.user.preferredLanguage);
    } catch (error: unknown) {
      const message =
        (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error
          ?.message || '登入失敗';
      set({ isLoading: false, error: message });
      throw error;
    }
  },

  logout: async () => {
    try {
      // M-22：refresh token 由後端 httpOnly cookie 管理，前端不再傳；呼叫後端 /auth/logout
      // 由它清除 cookie（含黑名單 access/refresh）。CSRF header 與 cookie 由 apiClient
      // 攔截器 + withCredentials 自動帶上。
      await authApi.logout();
    } catch {
      // 忽略登出 API 錯誤
    } finally {
      localStorage.removeItem('access_token');
      // M-22：清掉升級前舊 session 殘留的 legacy refresh_token key（現已不寫入）；無殘留時 no-op。
      localStorage.removeItem('refresh_token');
      set({
        user: null,
        accessToken: null,
        refreshToken: null,
        isAuthenticated: false,
        error: null,
      });
    }
  },

  refreshSession: async () => {
    // M-22：refresh token 改由 httpOnly cookie 持有，前端讀不到，故不再以 localStorage
    // 的 refresh_token 當作有無 session 的判斷；是否有有效 refresh cookie 交由後端裁定
    // （無 cookie 時 /auth/refresh 會 401，下方 catch 走 logout）。
    //
    // M-20：收斂到 client.ts 的單一共享 refresh 入口。後端有 refresh token rotation +
    // reuse detection（舊 token 只能用一次），若 authStore 自行打 POST /auth/refresh，
    // 會和 response 攔截器 401 自動重試的那套並發、共用同一顆舊 refresh token，被
    // reuse detection 判定重放而把使用者踢登出。改呼叫 refreshAccessToken() 共用
    // in-flight promise；它已寫回 localStorage 的新 access token（refresh token 由後端
    // 以 Set-Cookie 旋轉），這裡再同步回 store state。
    try {
      const accessToken = await refreshAccessToken();
      set({ accessToken });
    } catch {
      await get().logout();
    }
  },

  updateProfile: async (data) => {
    set({ isLoading: true });
    try {
      const updatedUser = await authApi.updateMe(data);
      set({ user: updatedUser, isLoading: false });
    } catch {
      set({ isLoading: false, error: '更新失敗' });
    }
  },

  clearError: () => set({ error: null }),
  setLoading: (loading) => set({ isLoading: loading }),

  hydrateFromStorage: async () => {
    // === DEV MOCK MODE ===
    if (import.meta.env.VITE_ENABLE_MOCK === 'true') {
      // 透過 VITE_MOCK_ROLE 切換角色: 'patient' | 'doctor' (預設 doctor)
      const mockRole = import.meta.env.VITE_MOCK_ROLE || 'doctor';
      const mockUser: User =
        mockRole === 'patient'
          ? {
              id: 'mock-patient-001',
              email: 'patient@gu-voice.local',
              name: '陳小明',
              role: 'patient',
              phone: '0987654321',
              isActive: true,
              createdAt: '2024-01-01T00:00:00Z',
              updatedAt: '2024-01-01T00:00:00Z',
            }
          : {
              id: 'mock-doctor-001',
              email: 'doctor@gu-voice.local',
              name: '王大明',
              role: 'doctor',
              phone: '0912345678',
              department: '泌尿科',
              licenseNumber: 'D-2024-001',
              isActive: true,
              createdAt: '2024-01-01T00:00:00Z',
              updatedAt: '2024-01-01T00:00:00Z',
            };
      set({
        user: mockUser,
        accessToken: 'mock-token',
        refreshToken: 'mock-refresh',
        isAuthenticated: true,
        isLoading: false,
      });
      return;
    }
    // === END MOCK ===

    // M-22：只看 access token；refresh token 已改由 httpOnly cookie 管理，前端讀不到，
    // 不再從 localStorage 還原。getMe 若因 access token 過期回 401，client.ts 攔截器會
    // 走 cookie-based refresh 自動續期。
    const accessToken = localStorage.getItem('access_token');
    if (!accessToken) {
      set({ isLoading: false });
      return;
    }

    set({ isLoading: true });
    try {
      const user = await authApi.getMe();
      set({
        user,
        accessToken,
        refreshToken: null,
        isAuthenticated: true,
        isLoading: false,
      });
      applyPreferredLanguage(user.preferredLanguage);
    } catch {
      localStorage.removeItem('access_token');
      // 清掉升級前殘留的 legacy refresh_token key（現已不寫入）；無殘留時 no-op。
      localStorage.removeItem('refresh_token');
      set({ isLoading: false });
    }
  },
}));

// ---- Selectors ----

export const selectIsPatient = (state: AuthState) => state.user?.role === 'patient';
export const selectIsDoctor = (state: AuthState) => state.user?.role === 'doctor';
export const selectIsAdmin = (state: AuthState) => state.user?.role === 'admin';
