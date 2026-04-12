// =============================================================================
// 認證狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import type { User } from '../types';
import * as authApi from '../services/api/auth';

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
      localStorage.setItem('refresh_token', response.refreshToken);
      set({
        user: response.user,
        accessToken: response.accessToken,
        refreshToken: response.refreshToken,
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
      const rt = get().refreshToken || localStorage.getItem('refresh_token') || undefined;
      await authApi.logout(rt);
    } catch {
      // 忽略登出 API 錯誤
    } finally {
      localStorage.removeItem('access_token');
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
    const token = get().refreshToken || localStorage.getItem('refresh_token');
    if (!token) return;

    try {
      const response = await authApi.refreshToken(token);
      localStorage.setItem('access_token', response.accessToken);
      localStorage.setItem('refresh_token', response.refreshToken);
      set({
        accessToken: response.accessToken,
        refreshToken: response.refreshToken,
      });
    } catch {
      get().logout();
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

    const accessToken = localStorage.getItem('access_token');
    const refreshToken = localStorage.getItem('refresh_token');
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
        refreshToken,
        isAuthenticated: true,
        isLoading: false,
      });
    } catch {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      set({ isLoading: false });
    }
  },
}));

// ---- Selectors ----

export const selectIsPatient = (state: AuthState) => state.user?.role === 'patient';
export const selectIsDoctor = (state: AuthState) => state.user?.role === 'doctor';
export const selectIsAdmin = (state: AuthState) => state.user?.role === 'admin';
