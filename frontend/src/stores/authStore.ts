// =============================================================================
// 認證狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import type { User } from '../types';
import * as authApi from '../services/api/auth';
import { refreshAccessToken } from '../services/api/client';
import i18n from '../i18n';

// 注意：偏好語言（preferredLanguage）刻意「不」在這裡直接寫 i18n。
// 改由 LanguageLayout 於登入 / 還原後把 URL 導到偏好語系，i18n 再由 URL 同步，
// 維持「URL 為語言唯一權威」，避免 i18n 與 URL desync（Accept-Language 讀 URL、畫面讀 i18n）。

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
      localStorage.setItem('access_token', response.accessToken);
      // 雙路徑 refresh：後端 body 與 httpOnly cookie 同時下發；跨站部署只有
      // localStorage 這份能用。sentry 已 redact 'refresh_token'。state 的
      // refreshToken 維持 null——記憶體不留副本，localStorage 為唯一來源。
      if (response.refreshToken) {
        localStorage.setItem('refresh_token', response.refreshToken);
      }
      set({
        user: response.user,
        accessToken: response.accessToken,
        refreshToken: null,
        isAuthenticated: true,
        isLoading: false,
      });
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
      // 雙路徑 refresh：把 localStorage 的 refresh token 放進 body 交給後端黑名單
      // （跨站部署 httpOnly cookie 不會送達，body 是唯一管道；同站部署後端以 cookie
      // 優先）。CSRF header 與 cookie 由 apiClient 攔截器 + withCredentials 自動帶上。
      await authApi.logout(localStorage.getItem('refresh_token') ?? undefined);
    } catch {
      // 忽略登出 API 錯誤
    } finally {
      localStorage.removeItem('access_token');
      // 清除跨站後備 refresh token（httpOnly cookie 那份由後端 /auth/logout 清除）。
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
      // Mock 使用者姓名 / 科別依目前 i18n 語言在地化：英文系 locale 用英文假資料，
      // 其餘沿用 zh-TW —— 這份 mock user 會出現在 PatientLayout / Header 等每個
      // 頁面的頂列，英文頁面若仍顯示中文姓名會被 e2e i18n_en_no_cjk.spec.ts 抓到
      // CJK 洩漏（見 W6 稽核）。
      const isEnglish = !!(i18n.resolvedLanguage || i18n.language)?.startsWith('en');
      const mockUser: User =
        mockRole === 'patient'
          ? {
              id: 'mock-patient-001',
              email: 'patient@gu-voice.local',
              name: isEnglish ? 'Chen Hsiao-Ming' : '陳小明',
              role: 'patient',
              phone: '0987654321',
              isActive: true,
              createdAt: '2024-01-01T00:00:00Z',
              updatedAt: '2024-01-01T00:00:00Z',
            }
          : {
              id: 'mock-doctor-001',
              email: 'doctor@gu-voice.local',
              name: isEnglish ? 'Wang Da-Ming' : '王大明',
              role: 'doctor',
              phone: '0912345678',
              department: isEnglish ? 'Urology' : '泌尿科',
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

    // 只看 access token；refresh token（cookie 或 localStorage 後備）不當作有無
    // session 的判斷。getMe 若因 access token 過期回 401，client.ts 攔截器會走
    // 雙路徑 refresh（cookie 優先、localStorage body 後備）自動續期。
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
        // getMe 可能觸發 401→refresh（client.ts 已把「新」access token 寫回 localStorage
        // 與 store），這裡必須重讀當下值而非進函式時的快取，否則會把 store 蓋回過期舊
        // token —— WS token provider 以 store 優先，語音 WS handshake 會拿舊 token 無限重連。
        accessToken: localStorage.getItem('access_token'),
        refreshToken: null,
        isAuthenticated: true,
        isLoading: false,
      });
    } catch {
      localStorage.removeItem('access_token');
      // 會話已失效：連跨站後備 refresh token 一併清除，避免殘留舊 token。
      localStorage.removeItem('refresh_token');
      set({ isLoading: false });
    }
  },
}));

// ---- Selectors ----

export const selectIsPatient = (state: AuthState) => state.user?.role === 'patient';
export const selectIsDoctor = (state: AuthState) => state.user?.role === 'doctor';
export const selectIsAdmin = (state: AuthState) => state.user?.role === 'admin';
