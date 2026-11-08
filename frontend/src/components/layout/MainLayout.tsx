// =============================================================================
// 醫師端版面（Header + Content）— 網頁版只剩報告，不需要 Sidebar
// =============================================================================

import { Suspense } from 'react';
import { Outlet } from 'react-router-dom';
import LoadingSpinner from '../common/LoadingSpinner';
import { useDashboardConnection } from '../../hooks/useWebSocket';
import Header from './Header';

export default function MainLayout() {
  // 報告清單靠 dashboard WS 的 report_generated 事件即時刷新
  useDashboardConnection();
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-surface-secondary dark:bg-dark-bg">
      <Header />
      <main className="min-w-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-content px-4 py-6 md:px-8">
          <Suspense fallback={<LoadingSpinner fullPage />}>
            <Outlet />
          </Suspense>
        </div>
      </main>
    </div>
  );
}
