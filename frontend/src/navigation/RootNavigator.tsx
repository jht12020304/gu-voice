// =============================================================================
// 根路由設定 (React Router v6)
// 網頁版只給醫師看問診報告：登入 → 報告清單 → 報告（SOAP＋逐字稿＋快速開單）。
// 病患問診只在 iOS kiosk App 進行。以 `/:lng/*` 為語言前綴；無 lng 的訪問會自動推算並 redirect。
// =============================================================================

import React from 'react';
import { useTranslation } from 'react-i18next';
import ErrorState from '../components/common/ErrorState';
import { BrowserRouter, Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { lazyWithRetry } from '../utils/lazyWithRetry';
import LanguageLayout from '../components/layout/LanguageLayout';
import { detectInitialLanguage, useCurrentLng } from '../i18n/paths';

// ---- 頁面 lazy load ----
const LoginPage = lazyWithRetry(() => import('../screens/auth/LoginPage'), 'LoginPage');
const ForgotPasswordPage = lazyWithRetry(() => import('../screens/auth/ForgotPasswordPage'), 'ForgotPasswordPage');
const ResetPasswordPage = lazyWithRetry(() => import('../screens/auth/ResetPasswordPage'), 'ResetPasswordPage');
const ReportListPage = lazyWithRetry(() => import('../screens/doctor/ReportListPage'), 'ReportListPage');
const SOAPReportPage = lazyWithRetry(() => import('../screens/doctor/SOAPReportPage'), 'SOAPReportPage');
const MainLayout = lazyWithRetry(() => import('../components/layout/MainLayout'), 'MainLayout');

function Spinner() {
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
    </div>
  );
}

// ---- 受保護路由：僅醫師／管理員 ----
function DoctorRoute() {
  const { t } = useTranslation('common');
  const recoveryRequired = useAuthStore((s) => s.recoveryRequired);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isLoading = useAuthStore((s) => s.isLoading);
  const user = useAuthStore((s) => s.user);
  const lng = useCurrentLng();
  const location = useLocation();

  if (isLoading) return <Spinner />;
  if (recoveryRequired) {
    return <ErrorState message={t('common.errorTitle')} onRetry={() => void useAuthStore.getState().hydrateFromStorage()} />;
  }
  // 帶著原網址去登入：iOS App「在網頁開啟」直接開 /reports/:id，登入後要回到那份報告。
  if (!isAuthenticated) return <Navigate to={`/${lng}/login`} state={{ from: location.pathname }} replace />;
  if (user && user.role === 'patient') {
    // 病患帳號在網頁版沒有任何頁面可看；登出讓登入頁接手（避免卡在無路可走的畫面）。
    void useAuthStore.getState().logout();
    return <Navigate to={`/${lng}/login`} replace />;
  }
  return <Outlet />;
}

// ---- 根路徑重導（`/` → `/<lng>/...`） ----
function RootRedirect() {
  const location = useLocation();
  const target = detectInitialLanguage();
  const tail = location.pathname === '/' ? '' : location.pathname;
  return (
    <Navigate to={`/${target}${tail}${location.search || ''}${location.hash || ''}`} replace />
  );
}

function ReportsRedirect() {
  const lng = useCurrentLng();
  return <Navigate to={`/${lng}/reports`} replace />;
}

export default function RootNavigator() {
  return (
    <BrowserRouter>
      <React.Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="/" element={<RootRedirect />} />

          <Route path="/:lng" element={<LanguageLayout />}>
            <Route path="login" element={<LoginPage />} />
            <Route path="forgot-password" element={<ForgotPasswordPage />} />
            <Route path="reset-password" element={<ResetPasswordPage />} />

            <Route element={<DoctorRoute />}>
              <Route element={<MainLayout />}>
                <Route path="reports" element={<ReportListPage />} />
                <Route path="reports/:sessionId" element={<SOAPReportPage />} />
              </Route>
              <Route index element={<ReportsRedirect />} />
              <Route path="*" element={<ReportsRedirect />} />
            </Route>
          </Route>

          <Route path="*" element={<RootRedirect />} />
        </Routes>
      </React.Suspense>
    </BrowserRouter>
  );
}
