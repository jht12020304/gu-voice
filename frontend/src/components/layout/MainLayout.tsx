// =============================================================================
// 主版面配置（Header + Sidebar + Content）
// Stripe 風格背景 + 精緻邊框層級
// =============================================================================

import { Suspense, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import LoadingSpinner from '../common/LoadingSpinner';
import Modal from '../common/Modal';
import { useDashboardConnection } from '../../hooks/useWebSocket';
import Header from './Header';
import Sidebar from './Sidebar';
import DoctorAlertPoller from '../DoctorAlertPoller';

export default function MainLayout() {
  useDashboardConnection();
  const { t } = useTranslation('common');
  const [navigationOpen, setNavigationOpen] = useState(false);
  const closeNavigation = () => setNavigationOpen(false);
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-surface-secondary dark:bg-dark-bg">
      {/* 醫師 shell 常駐：新紅旗全域提示 + Sidebar 徽章即時更新 */}
      <DoctorAlertPoller />
      <Header navigationOpen={navigationOpen} onOpenNavigation={() => setNavigationOpen(true)} />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="hidden shrink-0 md:flex"><Sidebar /></div>
        <main className="min-w-0 flex-1 overflow-auto">
          <div className="mx-auto max-w-content px-4 py-6 md:px-8">
            <Suspense fallback={<LoadingSpinner fullPage />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>
      <Modal visible={navigationOpen} onClose={closeNavigation} title={t('header.navigation')} size="sm">
        <div className="flex max-h-[65dvh] overflow-y-auto overscroll-contain">
          <Sidebar onNavigate={closeNavigation} />
        </div>
      </Modal>
    </div>
  );
}
