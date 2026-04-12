// =============================================================================
// 認證便利 Hook
// =============================================================================

import { useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';

export function useAuth() {
  const store = useAuthStore();
  const navigate = useNavigate();

  // 初始化時從 localStorage 恢復認證狀態
  useEffect(() => {
    if (!store.isAuthenticated && !store.isLoading) {
      store.hydrateFromStorage();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleLogin = useCallback(
    async (email: string, password: string) => {
      await store.login(email, password);
      // 依角色導向
      const user = useAuthStore.getState().user;
      if (user?.role === 'patient') {
        navigate('/patient/home');
      } else if (user?.role === 'doctor') {
        navigate('/dashboard');
      } else if (user?.role === 'admin') {
        navigate('/admin/users');
      }
    },
    [store, navigate],
  );

  const handleLogout = useCallback(async () => {
    await store.logout();
    navigate('/login');
  }, [store, navigate]);

  return {
    user: store.user,
    isAuthenticated: store.isAuthenticated,
    isLoading: store.isLoading,
    error: store.error,
    isPatient: store.user?.role === 'patient',
    isDoctor: store.user?.role === 'doctor',
    isAdmin: store.user?.role === 'admin',
    login: handleLogin,
    logout: handleLogout,
    clearError: store.clearError,
  };
}
