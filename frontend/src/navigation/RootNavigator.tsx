// =============================================================================
// 根路由設定 (React Router v6)
// 支援醫師端、病患端、管理員端角色分流
// =============================================================================

import React, { type ReactNode } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { lazyWithRetry } from '../utils/lazyWithRetry';

// ---- 頁面 lazy load ----
const LoginPage = lazyWithRetry(() => import('../screens/auth/LoginPage'), 'LoginPage');
const RegisterPage = lazyWithRetry(() => import('../screens/auth/RegisterPage'), 'RegisterPage');
const ForgotPasswordPage = lazyWithRetry(() => import('../screens/auth/ForgotPasswordPage'), 'ForgotPasswordPage');
const DashboardPage = lazyWithRetry(() => import('../screens/doctor/DashboardPage'), 'DashboardPage');
const PatientListPage = lazyWithRetry(() => import('../screens/doctor/PatientListPage'), 'PatientListPage');
const SessionDetailPage = lazyWithRetry(() => import('../screens/doctor/SessionDetailPage'), 'SessionDetailPage');
const SOAPReportPage = lazyWithRetry(() => import('../screens/doctor/SOAPReportPage'), 'SOAPReportPage');
const AlertListPage = lazyWithRetry(() => import('../screens/doctor/AlertListPage'), 'AlertListPage');
const AlertDetailPage = lazyWithRetry(() => import('../screens/doctor/AlertDetailPage'), 'AlertDetailPage');
const SessionListPage = lazyWithRetry(() => import('../screens/doctor/SessionListPage'), 'SessionListPage');
const ReportListPage = lazyWithRetry(() => import('../screens/doctor/ReportListPage'), 'ReportListPage');
const NotificationPage = lazyWithRetry(() => import('../screens/doctor/NotificationPage'), 'NotificationPage');
const PatientDetailPage = lazyWithRetry(() => import('../screens/doctor/PatientDetailPage'), 'PatientDetailPage');
const ConversationPage = lazyWithRetry(() => import('../screens/patient/ConversationPage'), 'ConversationPage');
const SettingsPage = lazyWithRetry(() => import('../screens/doctor/SettingsPage'), 'SettingsPage');
const UserManagementPage = lazyWithRetry(() => import('../screens/admin/UserManagementPage'), 'UserManagementPage');
const ComplaintManagementPage = lazyWithRetry(() => import('../screens/admin/ComplaintManagementPage'), 'ComplaintManagementPage');
const SystemHealthPage = lazyWithRetry(() => import('../screens/admin/SystemHealthPage'), 'SystemHealthPage');
const AuditLogsPage = lazyWithRetry(() => import('../screens/admin/AuditLogsPage'), 'AuditLogsPage');

// ---- 病患端頁面 ----
const PatientHomePage = lazyWithRetry(() => import('../screens/patient/PatientHomePage'), 'PatientHomePage');
const SelectComplaintPage = lazyWithRetry(() => import('../screens/patient/SelectComplaintPage'), 'SelectComplaintPage');
const MedicalInfoPage = lazyWithRetry(() => import('../screens/patient/MedicalInfoPage'), 'MedicalInfoPage');
const SessionCompletePage = lazyWithRetry(() => import('../screens/patient/SessionCompletePage'), 'SessionCompletePage');
const SessionThankYouPage = lazyWithRetry(() => import('../screens/patient/SessionThankYouPage'), 'SessionThankYouPage');
const PatientHistoryPage = lazyWithRetry(() => import('../screens/patient/PatientHistoryPage'), 'PatientHistoryPage');
const PatientSessionDetailPage = lazyWithRetry(() => import('../screens/patient/PatientSessionDetailPage'), 'PatientSessionDetailPage');
const PatientSettingsPage = lazyWithRetry(() => import('../screens/patient/PatientSettingsPage'), 'PatientSettingsPage');

// ---- Layout ----
const MainLayout = lazyWithRetry(() => import('../components/layout/MainLayout'), 'MainLayout');
const PatientLayout = lazyWithRetry(() => import('../components/layout/PatientLayout'), 'PatientLayout');

// ---- 受保護路由 ----
function ProtectedRoute({ children }: { children?: ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isLoading = useAuthStore((s) => s.isLoading);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children ? <>{children}</> : <Outlet />;
}

// ---- 角色路由守衛 ----
function RoleGuard({ allowedRoles, children }: { allowedRoles: string[]; children?: ReactNode }) {
  const user = useAuthStore((s) => s.user);

  if (!user || !allowedRoles.includes(user.role)) {
    // 依角色重導到正確首頁
    const home = user?.role === 'patient' ? '/patient' : '/dashboard';
    return <Navigate to={home} replace />;
  }

  return children ? <>{children}</> : <Outlet />;
}

// ---- 根據角色重導首頁 ----
function RoleRedirect() {
  const user = useAuthStore((s) => s.user);
  if (user?.role === 'patient') {
    return <Navigate to="/patient" replace />;
  }
  return <Navigate to="/dashboard" replace />;
}

// ---- Suspense 包裝 ----
function SuspenseWrapper({ children }: { children: ReactNode }) {
  return (
    <React.Suspense
      fallback={
        <div className="flex h-screen items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
        </div>
      }
    >
      {children}
    </React.Suspense>
  );
}

export default function RootNavigator() {
  return (
    <BrowserRouter>
      <SuspenseWrapper>
        <Routes>
          {/* 公開路由 */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />

          {/* 受保護路由 */}
          <Route element={<ProtectedRoute />}>

            {/* ── 病患端路由（PatientLayout：無 Sidebar） ── */}
            <Route element={<RoleGuard allowedRoles={['patient', 'doctor', 'admin']} />}>
              <Route element={<PatientLayout />}>
                <Route path="/patient" element={<PatientHomePage />} />
                <Route path="/patient/start" element={<SelectComplaintPage />} />
                <Route path="/patient/medical-info" element={<MedicalInfoPage />} />
                <Route path="/patient/history" element={<PatientHistoryPage />} />
                <Route path="/patient/history/:sessionId" element={<PatientSessionDetailPage />} />
                <Route path="/patient/settings" element={<PatientSettingsPage />} />
                <Route path="/patient/session/:sessionId/complete" element={<SessionCompletePage />} />
                <Route path="/patient/session/:sessionId/thank-you" element={<SessionThankYouPage />} />
              </Route>
            </Route>

            {/* 病患對話頁（全螢幕，不含 sidebar，病患與醫師都可訪問） */}
            <Route path="/conversation/:sessionId" element={<ConversationPage />} />

            {/* ── 醫師端路由（MainLayout：含 Sidebar） ── */}
            <Route element={<RoleGuard allowedRoles={['doctor', 'admin']} />}>
              <Route element={<MainLayout />}>
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/patients" element={<PatientListPage />} />
                <Route path="/patients/:patientId" element={<PatientDetailPage />} />
                <Route path="/sessions" element={<SessionListPage />} />
                <Route path="/sessions/:sessionId" element={<SessionDetailPage />} />
                <Route path="/reports" element={<ReportListPage />} />
                <Route path="/reports/:sessionId" element={<SOAPReportPage />} />
                <Route path="/alerts" element={<AlertListPage />} />
                <Route path="/alerts/:alertId" element={<AlertDetailPage />} />
                <Route path="/notifications" element={<NotificationPage />} />
                <Route path="/settings" element={<SettingsPage />} />

                {/* 管理員路由 */}
                <Route element={<RoleGuard allowedRoles={['admin']} />}>
                  <Route path="/admin/users" element={<UserManagementPage />} />
                  <Route path="/admin/complaints" element={<ComplaintManagementPage />} />
                  <Route path="/admin/health" element={<SystemHealthPage />} />
                  <Route path="/admin/audit-logs" element={<AuditLogsPage />} />
                </Route>
              </Route>
            </Route>
          </Route>

          {/* 根據角色重導 */}
          <Route path="/" element={<ProtectedRoute><RoleRedirect /></ProtectedRoute>} />
          <Route path="*" element={<ProtectedRoute><RoleRedirect /></ProtectedRoute>} />
        </Routes>
      </SuspenseWrapper>
    </BrowserRouter>
  );
}
