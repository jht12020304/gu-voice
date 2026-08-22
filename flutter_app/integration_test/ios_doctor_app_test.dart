// 原生 iOS＝醫師專用 App 的三項端到端驗證（打**真後端**、真 simulator）。
//
// 對應 branch `feat/ios-doctor-app` 的三個 commit：
//   224f979 backend：session_complete/report_ready 通知接上 FCM 推播
//   8ee725d flutter：iOS 平台分流（醫師 landing→通知頁、病患→patient-unsupported）
//   a394f78 flutter：通知頁訂閱 dashboard WS，即時反映新通知
//
// `test/` 底下的守衛測試是用 `debugDefaultTargetPlatformOverride` 假裝 iOS 的純函式測試；
// 這支才是「真的在 iOS build 上，`kIsWeb==false` 且 `defaultTargetPlatform==iOS`，
// 走完整個 App 啟動 → 登入 → go_router redirect」的驗證。
//
// ── 三個 test ────────────────────────────────────────────────────────────
//  A. doctor landing        — 醫師登入後停在 /notifications（不是 /dashboard）
//  B. patient unsupported   — 病患帳號登入後停在 /patient-unsupported，按登出回登入頁
//  C. notifications live    — 醫師停在通知頁不動，後端建立一筆新通知並廣播 dashboard WS
//                             事件，列表要在數秒內自己長出那筆（不重進頁面、不下拉重整）
//
// ── 跑法 ────────────────────────────────────────────────────────────────
//
//   A + B（不需要外部觸發，可直接跑）：
//
//     fvm flutter test integration_test/ios_doctor_app_test.dart \
//       -d D347B013-6B9F-4965-BC75-43487654884B \
//       --dart-define=API_BASE=http://localhost:8000/api/v1 \
//       --dart-define=WS_BASE=ws://localhost:8000/api/v1/ws \
//       --dart-define=E2E_DOCTOR_EMAIL=testdoctor@example.com \
//   （踩過的坑：2026-08-20 這台機器上另一個專案的 uvicorn 佔著 IPv4 `*:8000`，
//    docker 的 backend 只在 IPv6 上。curl 的 `localhost` 解到 ::1 所以看起來正常，
//    但 iOS simulator 解到 127.0.0.1 → 打到別人的服務，症狀是登入回
//    `Method Not Allowed`。先 `lsof -nP -iTCP:8000 -sTCP:LISTEN` 確認只有 docker，
//    有衝突就把兩個 BASE 改成 `http://[::1]:8000/api/v1` / `ws://[::1]:8000/api/v1/ws`。）
//       --dart-define=E2E_DOCTOR_PASSWORD=... \
//       --dart-define=E2E_PATIENT_EMAIL=testpatient@example.com \
//       --dart-define=E2E_PATIENT_PASSWORD=...
//
//   C 另外需要 `E2E_NOTIF_MARKER`，且需要 host 端在測試喊 ready 之後去「戳後端」。
//   測試會在 stdout 印：
//
//     NOTIF_READY_FOR_EXTERNAL_TRIGGER marker=<E2E_NOTIF_MARKER>
//
//   看到這行之後（同一台機器、後端跑在 docker compose 上），host 執行：
//
//     docker compose exec -T backend python - "<marker>" <<'PY'
//     import asyncio, sys, uuid
//     from sqlalchemy import select
//     from app.core.database import async_session_factory
//     from app.models.enums import NotificationType
//     from app.models.user import User
//     from app.services.notification_service import NotificationService
//     from app.websocket.connection_manager import publish_dashboard_event
//     MARKER = sys.argv[1]
//     async def main():
//         async with async_session_factory() as db:
//             uid = (await db.execute(select(User.id).where(
//                 User.email == "testdoctor@example.com"))).scalar_one()
//             n = await NotificationService.create(db, user_id=uid,
//                 type=NotificationType.REPORT_READY, title=MARKER,
//                 body="integration_test trigger", data={})
//             assert n is not None, "被通知偏好抑制"
//             await db.commit()
//         await publish_dashboard_event("report_generated", {
//             "reportId": str(uuid.uuid4()), "sessionId": str(uuid.uuid4()),
//             "patientName": "", "status": "generated"})
//     asyncio.run(main())
//     PY
//
//   這段刻意走**後端自己的**兩條路：`NotificationService.create` 寫真的 notifications 列，
//   `publish_dashboard_event` publish 到 Redis `gu:dashboard:events`，由 API 行程的
//   subscriber task（main.py lifespan）fan-out 給 dashboard WS 連線——與 Celery worker
//   完成 SOAP 後 `report_queue._publish_report_generated` 完全同一條路徑。**不是**前端假資料。
//
//   反向對照（2026-08-20 真跑過）：同樣的觸發但**只寫 DB、不 publish**，test C 會在
//   60 秒後失敗（`+0 -1`）。也就是說 C 綠燈確實來自 WS 推播，不是初載入或任何輪詢
//   湊巧撿到——這條對照是這支測試有意義的前提，改動等待邏輯後請重做一次。
//
// ⚠️ 憑證只從 --dart-define 讀；沒給就 skip。
// ⚠️ 這三頁都不用麥克風，不必先 `xcrun simctl privacy ... grant microphone`。
// ⚠️ marker 每次要換（帶時間戳），重用會讓 test C 的「觸發前不存在」前置斷言直接失敗。

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:gu_voice/app.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/app_router.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/core/router/route_guard.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/doctor/screens/dashboard_page.dart';
import 'package:gu_voice/features/doctor/screens/notification_page.dart';
import 'package:gu_voice/features/doctor/state/notifications_controller.dart';
import 'package:gu_voice/features/patient/patient_home_page.dart';

const _doctorEmail = String.fromEnvironment('E2E_DOCTOR_EMAIL');
const _doctorPassword = String.fromEnvironment('E2E_DOCTOR_PASSWORD');
const _patientEmail = String.fromEnvironment('E2E_PATIENT_EMAIL');
const _patientPassword = String.fromEnvironment('E2E_PATIENT_PASSWORD');
const _marker = String.fromEnvironment('E2E_NOTIF_MARKER');

// `ApiClient.dio` 是 `late final`——第二次 `init()` 會丟 LateInitializationError，
// 所以同一支檔案裡的多個 test 只能初始化一次。
bool _apiInited = false;

Future<void> _pumpFor(WidgetTester tester, Duration total, {bool Function()? until}) async {
  final steps = total.inMilliseconds ~/ 250;
  for (var i = 0; i < steps; i++) {
    await tester.pump(const Duration(milliseconds: 250));
    if (until != null && until()) return;
  }
}

Future<void> _typeInto(WidgetTester tester, Finder field, String text) async {
  await tester.tap(field);
  await tester.pump();
  await tester.enterText(field, text);
  await tester.pumpAndSettle();
}

/// 乾淨啟動一次 App（清 token → bootstrap → pumpWidget），回傳 container。
Future<ProviderContainer> _bootApp(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  if (!_apiInited) {
    ApiClient.instance.init();
    _apiInited = true;
  }
  await Locales.loadAll();
  await TokenStore.instance.clear();

  final container = ProviderContainer();
  addTearDown(container.dispose);
  ApiClient.instance.onAuthCleared = () => container.read(authProvider.notifier).forceLoggedOut();
  await container.read(authProvider.notifier).bootstrap();

  await tester.pumpWidget(
    UncontrolledProviderScope(container: container, child: const App()),
  );
  await tester.pumpAndSettle();
  return container;
}

Future<void> _login(WidgetTester tester, ProviderContainer container, String email, String password) async {
  final fields = find.byType(TextField);
  expect(fields, findsAtLeast(2), reason: '登入頁應有 email / password 兩個欄位');
  await _typeInto(tester, fields.at(0), email);
  await _typeInto(tester, fields.at(1), password);
  await tester.tap(find.byType(FilledButton).first);
  await _pumpFor(tester, const Duration(seconds: 20),
      until: () => container.read(authProvider).user != null);
  await tester.pumpAndSettle();
  final auth = container.read(authProvider);
  expect(auth.user, isNotNull,
      reason: '登入沒成功（error=${auth.error}）——檢查 API_BASE 是否含 /api/v1、後端是否在跑');
}

String _currentPath(ProviderContainer container) =>
    container.read(routerProvider).routerDelegate.currentConfiguration.uri.path;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  // 三支 test 的共同前提：這是原生行動 build（2026-08-22 起 iOS 是完整 App，
  // 醫師 landing = 通知頁、病患 landing = 病患首頁）。誤用 web 跑這支，
  // 底下所有斷言都會變成在驗別的東西，先在這裡擋掉。
  setUp(() {
    expect(kIsWeb, isFalse, reason: '這支只在原生 build 上有意義');
    expect(isNativeMobile, isTrue,
        reason: 'isNativeMobile=false —— 請用 iOS simulator（-d <udid>）跑這支，'
            'defaultTargetPlatform=$defaultTargetPlatform');
  });

  // ── A ───────────────────────────────────────────────────────────────────
  testWidgets('A. 醫師登入 iOS → landing 是通知頁（不是 dashboard）', (tester) async {
    if (_doctorEmail.isEmpty || _doctorPassword.isEmpty) {
      markTestSkipped('未提供 E2E_DOCTOR_EMAIL / E2E_DOCTOR_PASSWORD，跳過');
      return;
    }
    final container = await _bootApp(tester);
    await _login(tester, container, _doctorEmail, _doctorPassword);

    final user = container.read(authProvider).user!;
    expect(user.isPatient, isFalse, reason: 'E2E_DOCTOR_* 給的不是醫師/管理者帳號');

    // 通知頁初載入會打 /notifications 與 /notifications/unread-count，給它時間回來。
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(NotificationPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();

    expect(find.byType(NotificationPage), findsOneWidget,
        reason: '醫師登入後沒落在通知頁（實際路徑 ${_currentPath(container)}）');
    expect(find.byType(DashboardPage), findsNothing,
        reason: 'iOS 上醫師 landing 仍是 dashboard —— 平台分流沒生效');
    expect(_currentPath(container), endsWith('/notifications'),
        reason: 'router 路徑不是 /{lng}/notifications：${_currentPath(container)}');
  }, timeout: const Timeout(Duration(minutes: 3)));

  // ── B ───────────────────────────────────────────────────────────────────
  testWidgets('B. 病患帳號登入 iOS → 病患首頁（2026-08-22 起問診區在 iOS 開放）', (tester) async {
    if (_patientEmail.isEmpty || _patientPassword.isEmpty) {
      markTestSkipped('未提供 E2E_PATIENT_EMAIL / E2E_PATIENT_PASSWORD，跳過');
      return;
    }
    final container = await _bootApp(tester);
    await _login(tester, container, _patientEmail, _patientPassword);

    final user = container.read(authProvider).user!;
    expect(user.isPatient, isTrue, reason: 'E2E_PATIENT_* 給的不是病患帳號');

    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(PatientHomePage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();

    expect(find.byType(PatientHomePage), findsOneWidget,
        reason: '病患帳號沒落在病患首頁（實際路徑 ${_currentPath(container)}）——'
            '若看到的是登入頁或通知頁，檢查 route_guard 的 landing 規則');
    expect(_currentPath(container), endsWith('/patient'),
        reason: 'router 路徑不是 /{lng}/patient：${_currentPath(container)}');

    // 角色守衛仍在：病患 deep link 到醫師的病患清單必須被彈回自己的首頁。
    // 這正是 2026-08-22 修掉的 `/patients` 前綴洞——閘門拆掉後它是唯一防線。
    container.read(routerProvider).go('/$currentLng/patients');
    await tester.pumpAndSettle();
    expect(_currentPath(container), endsWith('/patient'),
        reason: '病患走進了 /patients（醫師的病患清單）—— 越權洞回歸！');
  }, timeout: const Timeout(Duration(minutes: 3)));

  // ── C ───────────────────────────────────────────────────────────────────
  testWidgets('C. 通知頁停著不動，後端新建的通知靠 dashboard WS 自己出現', (tester) async {
    if (_doctorEmail.isEmpty || _doctorPassword.isEmpty) {
      markTestSkipped('未提供 E2E_DOCTOR_EMAIL / E2E_DOCTOR_PASSWORD，跳過');
      return;
    }
    if (_marker.isEmpty) {
      markTestSkipped('未提供 E2E_NOTIF_MARKER，跳過（這支需要 host 端外部觸發後端）');
      return;
    }
    final container = await _bootApp(tester);
    await _login(tester, container, _doctorEmail, _doctorPassword);

    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(NotificationPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    expect(find.byType(NotificationPage), findsOneWidget, reason: '沒進到通知頁');

    // 初載入完成（loading 轉圈消失）。順帶驗「通知頁初載入抓得到既有通知」。
    await _pumpFor(tester, const Duration(seconds: 15),
        until: () => find.byType(CircularProgressIndicator).evaluate().isEmpty);
    await tester.pumpAndSettle();
    final initialCount = container.read(notificationsProvider).notifications.length;
    // ignore: avoid_print
    print('NOTIF_INITIAL_LOAD count=$initialCount');
    expect(container.read(notificationsProvider).error, isNull,
        reason: '通知頁初載入就錯了：${container.read(notificationsProvider).error}');

    expect(find.textContaining(_marker), findsNothing,
        reason: 'marker=$_marker 在外部觸發之前就已經在列表裡了 —— 這個 marker 用過，換一個重跑');

    // ignore: avoid_print
    print('NOTIF_READY_FOR_EXTERNAL_TRIGGER marker=$_marker');

    // ── 之後**完全不碰 App**：不呼叫 API、不 router.go、不下拉重整，只等畫面自己變 ──
    var found = false;
    for (var i = 0; i < 120; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 500)));
      await tester.pump();
      if (find.textContaining(_marker).evaluate().isNotEmpty) {
        found = true;
        // ignore: avoid_print
        print('NOTIF_APPEARED after=${(i + 1) * 500}ms');
        break;
      }
    }
    await tester.pumpAndSettle();

    expect(found, isTrue,
        reason: '等了 60 秒，後端建立並廣播的通知（marker=$_marker）沒有自己出現在通知列表。'
            '可能是：dashboard WS 沒連上、後端 report_generated 沒經 Redis fan-out 到這條連線、'
            '或 NotificationsController 的 WS 訂閱／debounce 沒有觸發 refetch。');
    expect(find.textContaining(_marker), findsWidgets);
    // 不能斷言「筆數變多」——列表一頁 20 筆且本機 DB 早就滿頁，新的一筆只會把最舊的擠掉。
    // 改斷言「重抓後最新一筆就是它」，同時證明真的重打了 API 而不是本地插入。
    expect(container.read(notificationsProvider).notifications.first.title, _marker,
        reason: '畫面找得到 marker，但 state 最新一筆不是它 —— 斷言路徑可疑');
  }, timeout: const Timeout(Duration(minutes: 4)));
}
