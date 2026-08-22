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
      // 2026-08-22 路由樹重構：原本**所有頁面都是 RoleHomePage（Phase-1 佔位頁）的
      // 子路由**，而 go_router 的 pop 不經過 redirect——結果是每一頁左上角都長出
      // 返回鍵，按下去 pop 回佔位頁（使用者回報的「沒必要出現的頁面」）。
      // 重構原則：
      //   1. URL 一個都不變（推播 route、kiosk 書籤、深連結全部照舊）。
      //   2. 佔位頁刪除；'/:lng' 只剩 fallback builder（頂層 redirect 永遠先把它
      //      彈去角色 landing，正常流程到不了）。
      //   3. 巢狀＝語意：詳情頁巢在列表下（返回鍵＝回列表）、intake 巢在病患首頁下
      //      （返回鍵＝回首頁）。
      //   4. 對話頁是**頂層路由**：問診中不得有返回鍵/邊緣滑動返回——kiosk 病患
      //      誤觸就會半途離開問診（場次卡 in_progress 60 分鐘），唯一出口是
      //      結束鈕與語言切換（兩者都會正確收掉場次）。
      //   5. 儀表板區頁面（病患列表/報告/研究/admin）包 DoctorShell(index:0)：
      //      原本既無底部導覽、返回鍵又通向佔位頁＝死路。
      // ---- auth（頂層：登入頁背後不留任何 stack）----
      GoRoute(path: '/:lng/login', builder: (context, state) => _lngKeyed(const LoginPage())),
      GoRoute(path: '/:lng/register', builder: (context, state) => _lngKeyed(const RegisterPage())),
      GoRoute(path: '/:lng/forgot-password', builder: (context, state) => _lngKeyed(const ForgotPasswordPage())),
      GoRoute(
        path: '/:lng/reset-password',
        builder: (context, state) => _lngKeyed(ResetPasswordPage(token: state.uri.queryParameters['token'] ?? '')),
      ),
      // ---- 病患區（intake 流程巢在首頁下）----
      GoRoute(
        path: '/:lng/patient',
        builder: (context, state) => _lngKeyed(const PatientHomePage()),
        routes: [
          GoRoute(path: 'start', builder: (context, state) => _lngKeyed(const SelectComplaintPage())),
          GoRoute(
            path: 'medical-info',
            // Args come from the URL, never `state.extra`: `extra` is in-memory only, so a
            // browser refresh or a shared deep link rebuilt this page with a null
            // complaintId and POST /sessions 422'd (see intake_route.dart).
            builder: (context, state) =>
                _lngKeyed(MedicalInfoPage(args: medicalInfoArgsFromUri(state.uri))),
          ),
          GoRoute(
            path: 'history',
            builder: (context, state) => _lngKeyed(const PatientHistoryPage()),
            routes: [
              GoRoute(
                path: ':sessionId',
                builder: (context, state) =>
                    _lngKeyed(PatientSessionDetailPage(sessionId: state.pathParameters['sessionId']!)),
              ),
            ],
          ),
          GoRoute(path: 'settings', builder: (context, state) => _lngKeyed(const PatientSettingsPage())),
          GoRoute(
            path: 'session/:sessionId/complete',
            builder: (context, state) => _lngKeyed(SessionCompletePage(sessionId: state.pathParameters['sessionId']!)),
          ),
          GoRoute(
            path: 'session/:sessionId/thank-you',
            builder: (context, state) =>
                _lngKeyed(SessionThankYouPage(abortedRedFlag: (state.extra as Map?)?['abortedRedFlag'] == true)),
          ),
        ],
      ),
      // ---- 對話頁（頂層，無父層：見上方原則 4）----
      GoRoute(
        path: '/:lng/conversation/:sessionId',
        builder: (context, state) => _lngKeyed(ConversationPage(
          sessionId: state.pathParameters['sessionId']!,
          session: state.extra as Session?,
        )),
      ),
      // ---- 醫師 5 tab（頂層：tab 間用底部導覽切換，無返回鍵）----
      GoRoute(path: '/:lng/dashboard', builder: (context, state) => _lngKeyed(const DoctorShell(index: 0, child: DashboardPage()))),
      GoRoute(
        path: '/:lng/sessions',
        builder: (context, state) => _lngKeyed(const DoctorShell(index: 1, child: SessionListPage())),
        routes: [
          GoRoute(
            path: ':sessionId',
            builder: (context, state) => _lngKeyed(
                DoctorShell(index: 1, child: SessionDetailPage(sessionId: state.pathParameters['sessionId']!))),
          ),
        ],
      ),
      GoRoute(
        path: '/:lng/alerts',
        builder: (context, state) => _lngKeyed(const DoctorShell(index: 2, child: AlertListPage())),
        routes: [
          GoRoute(
            path: ':alertId',
            builder: (context, state) => _lngKeyed(
                DoctorShell(index: 2, child: AlertDetailPage(alertId: state.pathParameters['alertId']!))),
          ),
        ],
      ),
      GoRoute(path: '/:lng/notifications', builder: (context, state) => _lngKeyed(const DoctorShell(index: 3, child: NotificationPage()))),
      GoRoute(path: '/:lng/settings', builder: (context, state) => _lngKeyed(const DoctorShell(index: 4, child: DoctorSettingsPage()))),
      // ---- 儀表板區（shell index 0：底部導覽在、儀表板 tab 亮著）----
      GoRoute(
        path: '/:lng/patients',
        builder: (context, state) => _lngKeyed(const DoctorShell(index: 0, child: PatientListPage())),
        routes: [
          GoRoute(
            path: ':patientId',
            builder: (context, state) => _lngKeyed(
                DoctorShell(index: 0, child: PatientDetailPage(patientId: state.pathParameters['patientId']!))),
          ),
        ],
      ),
      GoRoute(
        path: '/:lng/reports',
        builder: (context, state) => _lngKeyed(const DoctorShell(index: 0, child: ReportListPage())),
        routes: [
          GoRoute(
            path: ':sessionId',
            builder: (context, state) => _lngKeyed(
                DoctorShell(index: 0, child: SoapReportPage(sessionId: state.pathParameters['sessionId']!))),
          ),
        ],
      ),
      GoRoute(path: '/:lng/research', builder: (context, state) => _lngKeyed(const DoctorShell(index: 0, child: ResearchAnalyticsPage()))),
      // ---- admin（RoleGuard：admin/doctor）----
      GoRoute(path: '/:lng/admin/users', builder: (context, state) => _lngKeyed(const DoctorShell(index: 0, child: UserManagementPage()))),
      GoRoute(path: '/:lng/admin/complaints', builder: (context, state) => _lngKeyed(const DoctorShell(index: 0, child: ComplaintManagementPage()))),
      GoRoute(path: '/:lng/admin/health', builder: (context, state) => _lngKeyed(const DoctorShell(index: 0, child: SystemHealthPage()))),
      GoRoute(path: '/:lng/admin/audit-logs', builder: (context, state) => _lngKeyed(const DoctorShell(index: 0, child: AuditLogsPage()))),
      // ---- root fallback：頂層 redirect 永遠先把 '/:lng' 彈去角色 landing，
      //      這個 builder 正常流程到不了；留空殼只為滿足 GoRoute 的必填 builder。----
      GoRoute(path: '/:lng', builder: (context, state) => _lngKeyed(const SizedBox.shrink())),
    ],
  );
});
