import 'package:flutter/material.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../data/models/session.dart';
import '../../features/admin/screens/audit_logs_page.dart';
import '../../features/admin/screens/complaint_management_page.dart';
import '../../features/admin/screens/system_health_page.dart';
import '../../features/admin/screens/user_management_page.dart';
import '../../features/auth/auth_notifier.dart';
import '../../features/auth/forgot_password_page.dart';
import '../../features/auth/login_page.dart';
import '../../features/auth/register_page.dart';
import '../../features/auth/reset_password_page.dart';
import '../../features/doctor/screens/alert_detail_page.dart';
import '../../features/doctor/screens/alert_list_page.dart';
import '../../features/doctor/screens/dashboard_page.dart';
import '../../features/doctor/screens/doctor_settings_page.dart';
import '../../features/doctor/screens/doctor_shell.dart';
import '../../features/doctor/screens/notification_page.dart';
import '../../features/doctor/screens/patient_detail_page.dart';
import '../../features/doctor/screens/patient_list_page.dart';
import '../../features/doctor/screens/report_list_page.dart';
import '../../features/doctor/screens/research_analytics_page.dart';
import '../../features/doctor/screens/session_detail_page.dart';
import '../../features/doctor/screens/session_list_page.dart';
import '../../features/doctor/screens/soap_report_page.dart';
import '../../features/home/role_home_page.dart';
import '../../features/patient/intake_route.dart';
import '../../features/patient/medical_info_page.dart';
import '../../features/patient/patient_history_page.dart';
import '../../features/patient/patient_home_page.dart';
import '../../features/patient/patient_session_detail_page.dart';
import '../../features/patient/patient_settings_page.dart';
import '../../features/patient/select_complaint_page.dart';
import '../../features/patient/session_complete_page.dart';
import '../../features/patient/session_thank_you_page.dart';
import '../../features/voice/screens/conversation_page.dart';
import 'lng.dart';
import 'route_guard.dart';

// Re-key each routed page on the active lng. Our bare t() reads the global currentLng;
// widgets that don't depend on GoRouterState wouldn't otherwise rebuild on an lng-only
// route change (and const page builders return an unchanged instance go_router reuses).
// A ValueKey(currentLng) below the navigator forces a fresh build so t() re-resolves.
Widget _lngKeyed(Widget page) => KeyedSubtree(key: ValueKey(currentLng), child: page);

// go_router where the `/:lng/*` prefix is the SINGLE language authority.
// The redirect both syncs currentLng (used by Dio Accept-Language + t()) and does
// the auth/role gate. Language switch = navigate to the same route under a new lng.
final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier(0);
  ref.listen(authProvider, (_, _) => refresh.value++);
  ref.onDispose(refresh.dispose);

  return GoRouter(
    initialLocation: '/',
    refreshListenable: refresh,
    // An unmatched route used to fall through to go_router's built-in error page, which
    // is untranslated English and unusable on a clinic kiosk (TODO #23 / §G). Redirect to
    // the language-prefixed root instead: the router's own guards then land the user on
    // whichever home their role has. No new copy needed, so nothing to translate.
    onException: (context, state, router) =>
        router.go(prefixLngToPath('/', currentLng)),
    redirect: (context, state) {
      final path = state.uri.path;
      final lng = extractLngFromPath(path);

      // No valid lng segment: seed from device locale (first route only), then prefix.
      if (lng == null) {
        final seed = normalizeLanguage(
              WidgetsBinding.instance.platformDispatcher.locale.toLanguageTag(),
            ) ??
            defaultLanguage;
        // Rebuild off `state.uri` so query + fragment survive. Returning a bare path
        // dropped them — the password-reset mail links to `/reset-password?token=...`
        // with no lng segment, so the redirect silently ate the token and the whole
        // flow dead-ended on "invalid link" (TODO G6).
        return state.uri
            .replace(path: prefixLngToPath(path == '/' ? '/' : path, seed))
            .toString();
      }

      setCurrentLng(lng); // authority sync (also notifies App for Material localizations)

      final auth = ref.read(authProvider);
      if (!auth.booted) return null;

      // 登入 / 角色 / 平台三層規則都在 route_guard.dart 的純函式裡（測試直接驗那一份）。
      return resolveGuardRedirect(
        path: path,
        lng: lng,
        rest: stripLngFromPath(path), // path without the lng segment
        isAuthenticated: auth.isAuthenticated,
        isPatient: auth.user?.isPatient ?? false,
        isAdmin: auth.user?.isAdmin ?? false,
        nativeMobile: isNativeMobile,
      );
    },
    routes: [
      GoRoute(
        path: '/:lng',
        builder: (context, state) => _lngKeyed(const RoleHomePage()),
        routes: [
          GoRoute(path: 'login', builder: (context, state) => _lngKeyed(const LoginPage())),
          GoRoute(path: 'register', builder: (context, state) => _lngKeyed(const RegisterPage())),
          GoRoute(path: 'forgot-password', builder: (context, state) => _lngKeyed(const ForgotPasswordPage())),
          GoRoute(
            path: 'reset-password',
            builder: (context, state) => _lngKeyed(ResetPasswordPage(token: state.uri.queryParameters['token'] ?? '')),
          ),
          GoRoute(path: 'patient', builder: (context, state) => _lngKeyed(const PatientHomePage())),
          GoRoute(path: 'patient/start', builder: (context, state) => _lngKeyed(const SelectComplaintPage())),
          GoRoute(
            path: 'patient/medical-info',
            // Args come from the URL, never `state.extra`: `extra` is in-memory only, so a
            // browser refresh or a shared deep link rebuilt this page with a null
            // complaintId and POST /sessions 422'd (see intake_route.dart).
            builder: (context, state) =>
                _lngKeyed(MedicalInfoPage(args: medicalInfoArgsFromUri(state.uri))),
          ),
          GoRoute(path: 'patient/history', builder: (context, state) => _lngKeyed(const PatientHistoryPage())),
          GoRoute(
            path: 'patient/history/:sessionId',
            builder: (context, state) =>
                _lngKeyed(PatientSessionDetailPage(sessionId: state.pathParameters['sessionId']!)),
          ),
          GoRoute(path: 'patient/settings', builder: (context, state) => _lngKeyed(const PatientSettingsPage())),
          GoRoute(
            path: 'patient/session/:sessionId/complete',
            builder: (context, state) => _lngKeyed(SessionCompletePage(sessionId: state.pathParameters['sessionId']!)),
          ),
          GoRoute(
            path: 'patient/session/:sessionId/thank-you',
            builder: (context, state) =>
                _lngKeyed(SessionThankYouPage(abortedRedFlag: (state.extra as Map?)?['abortedRedFlag'] == true)),
          ),
          GoRoute(
            path: 'conversation/:sessionId',
            builder: (context, state) => _lngKeyed(ConversationPage(
              sessionId: state.pathParameters['sessionId']!,
              session: state.extra as Session?,
            )),
          ),
          // ---- doctor / admin ----
          GoRoute(path: 'dashboard', builder: (context, state) => _lngKeyed(const DoctorShell(index: 0, child: DashboardPage()))),
          GoRoute(path: 'sessions', builder: (context, state) => _lngKeyed(const DoctorShell(index: 1, child: SessionListPage()))),
          GoRoute(
            path: 'sessions/:sessionId',
            builder: (context, state) => _lngKeyed(SessionDetailPage(sessionId: state.pathParameters['sessionId']!)),
          ),
          GoRoute(path: 'alerts', builder: (context, state) => _lngKeyed(const DoctorShell(index: 2, child: AlertListPage()))),
          GoRoute(
            path: 'alerts/:alertId',
            builder: (context, state) => _lngKeyed(AlertDetailPage(alertId: state.pathParameters['alertId']!)),
          ),
          GoRoute(path: 'notifications', builder: (context, state) => _lngKeyed(const DoctorShell(index: 3, child: NotificationPage()))),
          GoRoute(path: 'settings', builder: (context, state) => _lngKeyed(const DoctorShell(index: 4, child: DoctorSettingsPage()))),
          GoRoute(path: 'patients', builder: (context, state) => _lngKeyed(const PatientListPage())),
          GoRoute(
            path: 'patients/:patientId',
            builder: (context, state) => _lngKeyed(PatientDetailPage(patientId: state.pathParameters['patientId']!)),
          ),
          GoRoute(path: 'reports', builder: (context, state) => _lngKeyed(const ReportListPage())),
          GoRoute(
            path: 'reports/:sessionId',
            builder: (context, state) => _lngKeyed(SoapReportPage(sessionId: state.pathParameters['sessionId']!)),
          ),
          GoRoute(path: 'research', builder: (context, state) => _lngKeyed(const ResearchAnalyticsPage())),
          // ---- admin (RoleGuard: admin only) ----
          GoRoute(path: 'admin/users', builder: (context, state) => _lngKeyed(const UserManagementPage())),
          GoRoute(path: 'admin/complaints', builder: (context, state) => _lngKeyed(const ComplaintManagementPage())),
          GoRoute(path: 'admin/health', builder: (context, state) => _lngKeyed(const SystemHealthPage())),
          GoRoute(path: 'admin/audit-logs', builder: (context, state) => _lngKeyed(const AuditLogsPage())),
        ],
      ),
    ],
  );
});
