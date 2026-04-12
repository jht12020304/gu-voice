// =============================================================================
// 根元件
// =============================================================================

import { useEffect } from 'react';
import RootNavigator from './navigation/RootNavigator';
import { useAuthStore } from './stores/authStore';
import { useSettingsStore } from './stores/settingsStore';

export default function App() {
  const hydrateFromStorage = useAuthStore((s) => s.hydrateFromStorage);
  const theme = useSettingsStore((s) => s.theme);

  // 初始化時恢復認證狀態
  useEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  // 初始化 theme
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  return <RootNavigator />;
}
