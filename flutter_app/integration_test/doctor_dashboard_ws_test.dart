// 醫師端 dashboard WebSocket 即時性驗證（P4b-L6）：不重新進頁面的情況下，外部（病患角色）
// 透過 REST 建立一場新場次時，醫師端 sessions 列表要能單靠 dashboard WS 推播自動刷新、
// 顯示出新場次——這是跟 P4a 同時在跑的 Flutter Web 聯動測試互補的「真的有另一個角色在
// 背景動作」場景，比同一支測試自己呼叫 API 再斷言更有說服力。
//
// 佐證 TODO G12：`alertsProvider` 是惰性的，只有被 `watch` 才會建立 controller、才會呼叫
// `DashboardWs.ensureConnected()`。本測試不繞過這個限制——`features/doctor/doctor_alert_watcher.dart`
// 掛在 `MaterialApp.router` 的 `builder`（lib/app.dart:39），只要有已認證的 doctor/admin
// `user`，不論在哪個路由都會 watch 到，所以登入完成的那一刻 dashboard WS 就已經在連了；
// 到 `/sessions` 後 `SessionsListController.build()`（sessions_list_controller.dart:29）
// 又呼叫一次 `ensureConnected()`（`_connected` 旗標保證 idempotent）。這支測試的斷言路徑
// 剛好會先掛 watcher 再進 sessions 列表，等同覆蓋了 G12 這個惰性連線的坑。
//
// `_reloadEvents`（sessions_list_controller.dart:9）含 `session_created`，後端
// `POST /api/v1/sessions` 成功 commit 後會透過 `_broadcast_session_created`
// （backend/app/services/session_service.py:37-61）把它推給 dashboard WS 訂閱者，
// 不分角色（只要是該連線的訂閱範圍）。所以理論上：外部建一場新場次 → 後端推播
// `session_created` → `SessionsListController._onEvent` → `reload()` → HTTP 重新整批拉
// sessions → 畫面出現新卡片，全程沒有本測試主動呼叫任何 API、也沒有 `router.go` 重進頁面。
//
// 跑法（需要「外部觸發」配合，兩段分開跑）：
//
//   1) 先跑這支測試，等它印出 stdout 這行：
//        L6_READY_FOR_EXTERNAL_TRIGGER marker=<E2E_L6_MARKER 的值>
//      （這代表已經登入、已經在 /sessions 列表、且列表裡還沒有這個 marker）
//
//   2) 看到那行之後，host 端立刻用 testpatient 帳號打：
//        POST {API_BASE}/sessions
//        Authorization: Bearer <patient JWT>
//        {"chiefComplaintId":"00000000-0000-4000-8000-0000000000c1",
//         "chiefComplaintText":"<跟 E2E_L6_MARKER 完全一樣的字串>","language":"zh-TW"}
//      （00000000-0000-4000-8000-0000000000c1 是種子資料裡「血尿」這個系統預設主訴的固定
//      id，見 `GET /api/v1/complaints` 回應——用它只是為了滿足 schema 必填欄位，跟斷言無關，
//      斷言只認 chiefComplaintText 的 marker）
//
//   3) 這支測試接下來 45 秒內只會 `tester.pump()`，不會呼叫任何 API、不會 `router.go`，
//      純等 WS 推播把新卡片刷出來。
//
// 指令：
//
//   flutter test integration_test/doctor_dashboard_ws_test.dart -d <udid> \
//     --dart-define=API_BASE=http://127.0.0.1:8000/api/v1 \
//     --dart-define=WS_BASE=ws://127.0.0.1:8000/api/v1/ws \
//     --dart-define=E2E_DOCTOR_EMAIL=... --dart-define=E2E_DOCTOR_PASSWORD=... \
//     --dart-define=E2E_L6_MARKER=L6WS<不會撞到既有資料的唯一字串，例如帶時間戳>

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:gu_voice/app.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/app_router.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/doctor/screens/session_list_page.dart';

const _email = String.fromEnvironment('E2E_DOCTOR_EMAIL');
const _password = String.fromEnvironment('E2E_DOCTOR_PASSWORD');
const _marker = String.fromEnvironment('E2E_L6_MARKER');

Future<void> _pumpFor(WidgetTester tester, Duration total, {bool Function()? until}) async {
  final deadline = total.inMilliseconds ~/ 250;
  for (var i = 0; i < deadline; i++) {
    await tester.pump(const Duration(milliseconds: 250));
    if (until != null && until()) return;
  }
}

// Web 陷阱（見 patient_text_flow_test.dart）：合成 tap 不等於真實 DOM focus。用不到 web 的
// iOS 路徑上這招無害，跟 doctor_walkthrough_test.dart 保持同一套習慣即可。
Future<void> _typeInto(WidgetTester tester, Finder field, String text) async {
  await tester.tap(field);
  await tester.pump();
  await tester.enterText(field, text);
  await tester.pumpAndSettle();
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('dashboard WS: 外部建立的新場次不重進頁面就會出現在 sessions 列表', (tester) async {
    if (_email.isEmpty || _password.isEmpty || _marker.isEmpty) {
      markTestSkipped('未提供 E2E_DOCTOR_EMAIL / E2E_DOCTOR_PASSWORD / E2E_L6_MARKER，跳過');
      return;
    }
    tester.view.physicalSize = const Size(1400, 3200);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    ApiClient.instance.init();
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

    // ── 登入（醫師）：登入成功那一刻 DoctorAlertWatcher 就開始 watch alertsProvider，
    // dashboard WS 理論上已經在連線中，不必等到進 /sessions ──
    final loginFields = find.byType(TextField);
    expect(loginFields, findsAtLeast(2), reason: '登入頁應有 email / password');
    await _typeInto(tester, loginFields.at(0), _email);
    await _typeInto(tester, loginFields.at(1), _password);
    await tester.tap(find.byType(FilledButton).first);
    await _pumpFor(tester, const Duration(seconds: 15), until: () => container.read(authProvider).user != null);
    await tester.pumpAndSettle();
    final user = container.read(authProvider).user;
    expect(user, isNotNull, reason: '醫師登入失敗');
    expect(user!.isPatient, isFalse, reason: '這支測的是醫師/管理者帳號');

    final router = container.read(routerProvider);

    // ── Sessions 列表：先確認 marker 還沒出現（避免同一個 marker 被重跑污染）──
    router.go(prefixLngToPath('/sessions', currentLng));
    await _pumpFor(tester, const Duration(seconds: 10),
        until: () => find.byType(SessionListPage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    await _pumpFor(tester, const Duration(seconds: 8),
        until: () => find.byType(CircularProgressIndicator).evaluate().isEmpty);
    await tester.pumpAndSettle();

    expect(find.textContaining(_marker), findsNothing,
        reason: 'marker=$_marker 在外部觸發之前就已經出現在列表——這個 marker 被用過了，'
            '換一個沒撞過的字串重跑（例如帶目前時間戳）');

    // ignore: avoid_print
    print('L6_READY_FOR_EXTERNAL_TRIGGER marker=$_marker');

    // ── 純靠 WS 推播等新卡片出現：不呼叫任何 API、不 router.go 重進頁面 ──
    // 真實裝置上的 dashboard WS 走真正的 IO/Timer，`tester.pump()` 本身不會推進真實時間，
    // 要靠 `runAsync` 讓真正的 Future/Timer（含 WebSocketManager 的事件迴圈）在真實事件圈
    // 上跑，同一個模式見 kiosk_idle_logout_test.dart。
    var found = false;
    await tester.runAsync(() async {
      final deadline = DateTime.now().add(const Duration(seconds: 45));
      while (DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(milliseconds: 500));
        found = find.textContaining(_marker).evaluate().isNotEmpty;
        if (found) return;
      }
    });
    await tester.pump();
    await tester.pumpAndSettle();

    expect(found || find.textContaining(_marker).evaluate().isNotEmpty, isTrue,
        reason: '等了 45 秒，外部用 patient 帳號建立的新場次（marker=$_marker）沒有透過 '
            'dashboard WS 自動出現在醫師端 sessions 列表——WS 可能沒連上（見 TODO G12：'
            'alertsProvider 惰性連線）、或後端 session_created 事件沒有推播、或前端 '
            'SessionsListController 沒有正確 reload。');
  }, timeout: const Timeout(Duration(minutes: 2)));
}
