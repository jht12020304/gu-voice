// =============================================================================
// 主版面配置（Header + Sidebar + Content）
// Stripe 風格背景 + 精緻邊框層級
// =============================================================================

import { Outlet } from 'react-router-dom';
import Header from './Header';
import Sidebar from './Sidebar';
import DoctorAlertPoller from '../DoctorAlertPoller';

export default function MainLayout() {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-secondary dark:bg-dark-bg">
      {/* 醫師 shell 常駐：新紅旗全域提示 + Sidebar 徽章即時更新（§1c 低風險版） */}
      <DoctorAlertPoller />
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-auto">
          <div className="mx-auto max-w-content px-8 py-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
