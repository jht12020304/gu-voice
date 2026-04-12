// =============================================================================
// 根路由設定 (React Router v6)
// 支援醫師端、病患端、管理員端角色分流
// =============================================================================

import React, { type ReactNode } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';

// ---- 頁面 lazy load ----
const LoginPage = React.lazy(() => import('../screens/auth/LoginPage'));
const RegisterPage = React.lazy(() => import('../screens/auth/RegisterPage'));
const ForgotPasswordPage = React.lazy(() => import('../screens/auth/ForgotPasswordPage'));
const DashboardPage = React.lazy(() => import('../screens/doctor/DashboardPage'));
const PatientListPage = React.lazy(() => import('../screens/doctor/PatientListPage'));
const SessionDetailPage = React.lazy(() => import('../screens/doctor/SessionDetailPage'));
const SOAPReportPage = React.lazy(() => import('../screens/doctor/SOAPReportPage'));
const AlertListPage = React.lazy(() => import('../screens/doctor/AlertListPage'));
const AlertDetailPage = React.lazy(() => import('../screens/doctor/AlertDetailPage'));
const SessionListPage = React.lazy(() => import('../screens/doctor/SessionListPage'));
const ReportListPage = React.lazy(() => import('../screens/doctor/ReportListPage'));
const ConversationPage = React.lazy(() => import('../screens/patient/ConversationPage'));
const SettingsPage = React.lazy(() => import('../screens/doctor/SettingsPage'));
const UserManagementPage = React.lazy(() => import('../screens/admin/UserManagementPage'));
const ComplaintManagementPage = React.lazy(() => import('../screens/admin/ComplaintManagementPage'));
const SystemHealthPage = React.lazy(() => import('../screens/admin/SystemHealthPage'));
const AuditLogsPage = React.lazy(() => import('../screens/admin/AuditLogsPage'));

// ---- 病患端頁面 ----
const PatientHomePage = React.lazy(() => import('../screens/patient/PatientHomePage'));
const SelectComplaintPage = React.lazy(() => import('../screens/patient/SelectComplaintPage'));
const MedicalInfoPage = React.lazy(() => import('../screens/patient/MedicalInfoPage'));
const SessionCompletePage = React.lazy(() => import('../screens/patient/SessionCompletePage'));
const PatientHistoryPage = React.lazy(() => import('../screens/patient/PatientHistoryPage'));
const PatientSessionDetailPage = React.lazy(() => import('../screens/patient/PatientSessionDetailPage'));
const PatientSettingsPage = React.lazy(() => import('../screens/patient/PatientSettingsPage'));

// ---- Layout ----
const MainLayout = React.lazy(() => import('../components/layout/MainLayout'));
const PatientLayout = React.lazy(() => import('../components/layout/PatientLayout'));

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
              </Route>
            </Route>

            {/* 病患對話頁（全螢幕，不含 sidebar，病患與醫師都可訪問） */}
            <Route path="/conversation/:sessionId" element={<ConversationPage />} />

            {/* ── 醫師端路由（MainLayout：含 Sidebar） ── */}
            <Route element={<RoleGuard allowedRoles={['doctor', 'admin']} />}>
              <Route element={<MainLayout />}>
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/patients" element={<PatientListPage />} />
                <Route path="/sessions" element={<SessionListPage />} />
                <Route path="/sessions/:sessionId" element={<SessionDetailPage />} />
                <Route path="/reports" element={<ReportListPage />} />
                <Route path="/reports/:sessionId" element={<SOAPReportPage />} />
                <Route path="/alerts" element={<AlertListPage />} />
                <Route path="/alerts/:alertId" element={<AlertDetailPage />} />
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
