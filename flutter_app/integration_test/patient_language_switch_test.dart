// M16 / G34：**問診中**切語言的守衛，對真後端跑一遍。
//
// 為什麼需要這支：`LanguageAction` 與 `switchLanguage()` 的邏輯早就做好了，
// 但入口一直沒掛進 `ConversationPage` 的 AppBar，所以「問診中切語言」這條路徑
// 從來沒有被真的走過——`language_switch_guard_test.dart` 只驗到路徑判斷純函式
// 與五語文案，驗不到「確認框會不會出現」「取消後 WS 還在不在」「確認後場次有沒有
// 真的變 cancelled」。
//
// 驗到什麼：
//   1. 問診頁 AppBar 有 LanguageAction，且原本的「結束問診」按鈕沒被擠掉
//   2. 選新語言 → 出現 M16 確認框（不是直接切走）
//   3. 取消 → 停在原問診頁、語言不變、WS 仍 open、還能繼續送文字並收到 AI 回覆
//      （對稱條款：取消不得順手把 controller 拆掉或斷 WS）
//   4. 確認 → REST 成功後才導頁，落在**新語言的病患首頁**，場次轉 cancelled
//   5. 全程沒有 UnmountedRefException（離頁時 autoDispose 的清理閘門）
//
// 跑法（web，對本機 e2e 後端；會消耗真 OpenAI 額度）：
//
//   chromedriver --port=4444 &
//   flutter drive --driver=test_driver/integration_test.dart \
//     --target=integration_test/patient_language_switch_test.dart \
//     -d web-server --web-port=5175 --browser-name=chrome \
//     --web-browser-flag=--use-fake-ui-for-media-stream \
//     --web-browser-flag=--use-fake-device-for-media-stream \
//     --web-browser-flag=--autoplay-policy=no-user-gesture-required \
//     --dart-define=API_BASE=http://localhost:8000/api/v1 \
//     --dart-define=WS_BASE=ws://localhost:8000/api/v1/ws \
//     --dart-define=E2E_PATIENT_EMAIL=... --dart-define=E2E_PATIENT_PASSWORD=...
//
// ⚠️ 這支會把該帳號的 `preferred_language` 改成 en-US（端點的既定行為）。重跑前
// 若要從 zh-TW 開始，先把偏好改回去，否則登入後路由會直接落在 en-US、
// 「切到 en-US」變成同語言 no-op，確認框自然不會出現。

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:integration_test/integration_test.dart';

import 'package:gu_voice/app.dart';
import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/sessions_api.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/patient/patient_home_page.dart';
import 'package:gu_voice/features/voice/screens/conversation_page.dart';
import 'package:gu_voice/features/voice/services/ws_manager.dart';
import 'package:gu_voice/features/voice/state/conversation_controller.dart';
import 'package:gu_voice/shared/widgets/language_action.dart';

const _email = String.fromEnvironment('E2E_PATIENT_EMAIL');
const _password = String.fromEnvironment('E2E_PATIENT_PASSWORD');

Future<void> _pumpFor(WidgetTester tester, Duration total,
    {bool Function()? until}) async {
  final deadline = total.inMilliseconds ~/ 250;
  for (var i = 0; i < deadline; i++) {
    await tester.pump(const Duration(milliseconds: 250));
    if (until != null && until()) return;
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('mid-consultation language switch: confirm dialog, cancel keeps the session, confirm ends it',
      (tester) async {
    if (_email.isEmpty || _password.isEmpty) {
      markTestSkipped('未提供 E2E_PATIENT_EMAIL / E2E_PATIENT_PASSWORD，跳過');
      return;
    }
    tester.view.physicalSize = const Size(1200, 3000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    ApiClient.instance.init();
    await Locales.loadAll();
    await TokenStore.instance.clear();

    final container = ProviderContainer();
    addTearDown(container.dispose);
    ApiClient.instance.onAuthCleared =
        () => container.read(authProvider.notifier).forceLoggedOut();
    await container.read(authProvider.notifier).bootstrap();

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const App()),
    );
    await tester.pumpAndSettle();

    // ── 登入 ────────────────────────────────────────────────
    final fields = find.byType(TextField);
    expect(fields, findsAtLeast(2), reason: '登入頁應有 email / password');
    await tester.enterText(fields.at(0), _email);
    await tester.enterText(fields.at(1), _password);
    await tester.pumpAndSettle();
    await tester.tap(find.byType(FilledButton).first);
    await _pumpFor(tester, const Duration(seconds: 15),
        until: () => container.read(authProvider).user != null);
    await tester.pumpAndSettle();
    expect(container.read(authProvider).user, isNotNull, reason: '病患登入失敗');

    final startLng = currentLng;
    expect(startLng, isNot('en-US'),
        reason: '這支要從非 en-US 出發（帳號 preferred_language 可能被上一輪改成 en-US 了）');

    // ── 建場次、進對話（與 patient_text_flow_test 同一條路徑）────────
    final ctx = tester.element(find.byType(Scaffold).first);
    GoRouter.of(ctx).go('/$currentLng/patient/start');
    await _pumpFor(tester, const Duration(seconds: 12));
    await tester.pumpAndSettle();

    final listTiles = find.byType(ListTile);
    expect(listTiles, findsAtLeast(1), reason: '主訴清單沒載出來');
    await tester.tap(listTiles.first, warnIfMissed: false);
    await tester.pumpAndSettle();
    await tester.tap(find.byType(FilledButton).last);
    await _pumpFor(tester, const Duration(seconds: 5));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField).first, 'E2E 切語言測試');
    await tester.pumpAndSettle();
    await tester.tap(find.byType(ChoiceChip).first);
    await tester.pumpAndSettle();
    await tester.tap(find.byType(OutlinedButton).first);
    await tester.pumpAndSettle();
    final okBtn = find.text('OK');
    await tester.tap(okBtn.evaluate().isNotEmpty ? okBtn : find.byType(TextButton).last);
    await tester.pumpAndSettle();

    await tester.tap(find.byType(FilledButton).last, warnIfMissed: false);
    await _pumpFor(tester, const Duration(seconds: 20),
        until: () => container.read(conversationControllerProvider).session != null);
    await tester.pumpAndSettle();

    final session = container.read(conversationControllerProvider).session;
    expect(session, isNotNull, reason: '沒有進入 conversation');
    final sessionId = session!.id;

    await _pumpFor(tester, const Duration(seconds: 20),
        until: () =>
            container.read(conversationControllerProvider).connection == WsConnState.open);
    expect(container.read(conversationControllerProvider).connection, WsConnState.open,
        reason: 'WebSocket 沒連上');

    await _pumpFor(tester, const Duration(seconds: 45),
        until: () => container
            .read(conversationControllerProvider)
            .messages
            .any((m) => m.sender != 'patient'));
    expect(
        container.read(conversationControllerProvider).messages.where((m) => m.sender != 'patient'),
        isNotEmpty,
        reason: 'AI 開場白沒出現');

    // ── 1. AppBar 上兩顆入口都在 ────────────────────────────
    expect(find.byType(ConversationPage), findsOneWidget);
    expect(
        find.descendant(of: find.byType(AppBar), matching: find.byType(LanguageAction)),
        findsOneWidget,
        reason: '問診頁 AppBar 沒有 LanguageAction（M16 入口沒掛上）');
    expect(
        find.descendant(of: find.byType(AppBar), matching: find.byType(TextButton)),
        findsOneWidget,
        reason: '加了語言入口後「結束問診」按鈕被擠掉了');

    // ── 2. 選新語言 → 出現確認框 ────────────────────────────
    Future<void> openLanguageMenuAndPickEnglish() async {
      await tester.tap(find.descendant(
          of: find.byType(LanguageAction), matching: find.byIcon(Icons.language)));
      await tester.pumpAndSettle();
      // PopupMenu 的項目文字是「English」（common.language.names.en-US，五語同字）
      await tester.tap(find.text(t('common.language.names.en-US')).last);
      await tester.pumpAndSettle();
    }

    await openLanguageMenuAndPickEnglish();
    expect(find.text(t('common.language.switchModal.title')), findsOneWidget,
        reason: '進行中場次切語言沒有出現 M16 確認框 → 會留下孤兒 in_progress 場次');
    expect(find.text(t('common.language.switchModal.confirm')), findsOneWidget);
    expect(find.text(t('common.language.switchModal.cancel')), findsOneWidget);

    // ── 3. 取消 → 什麼都不動 ────────────────────────────────
    await tester.tap(find.text(t('common.language.switchModal.cancel')));
    await tester.pumpAndSettle();
    expect(find.text(t('common.language.switchModal.title')), findsNothing,
        reason: '取消後確認框沒關掉');
    expect(find.byType(ConversationPage), findsOneWidget, reason: '取消後不該離開問診頁');
    expect(currentLng, startLng, reason: '取消後語言不該改變');
    expect(container.read(conversationControllerProvider).connection, WsConnState.open,
        reason: '取消卻把 WS 斷掉了（對稱條款：取消是 no-op）');

    final serverBefore = await SessionsApi().getSession(sessionId);
    expect(serverBefore.status, 'in_progress', reason: '取消卻把後端場次收掉了');

    // 續談一輪，證明 WS 雙向仍活、controller 沒被拆
    final beforeLen = container.read(conversationControllerProvider).messages.length;
    final input = find.byType(TextField);
    await tester.tap(input.last);
    await tester.pump();
    await tester.enterText(input.last, '大概三天前開始，白天小便次數變多，一天大概十幾次。');
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.send));
    await _pumpFor(tester, const Duration(seconds: 90), until: () {
      final s = container.read(conversationControllerProvider);
      return s.completed || s.messages.length > beforeLen + 1;
    });
    await tester.pumpAndSettle();
    expect(container.read(conversationControllerProvider).messages.length,
        greaterThan(beforeLen + 1),
        reason: '取消後問診接不下去（送出的話沒有被 AI 接住）');
    expect(container.read(conversationControllerProvider).error, isNull,
        reason: '續談過程出錯：${container.read(conversationControllerProvider).error}');

    // ── 4. 確認 → REST 成功才導頁，落在新語言的病患首頁 ────────
    await openLanguageMenuAndPickEnglish();
    expect(find.text(t('common.language.switchModal.title')), findsOneWidget);
    await tester.tap(find.text(t('common.language.switchModal.confirm')));
    await _pumpFor(tester, const Duration(seconds: 30),
        until: () => find.byType(PatientHomePage).evaluate().isNotEmpty);
    await tester.pumpAndSettle();

    expect(find.byType(ConversationPage), findsNothing, reason: '確認後仍停在問診頁');
    expect(find.byType(PatientHomePage), findsOneWidget,
        reason: '確認後沒有導到病患首頁（回到已 cancelled 的問診頁等於畫面壞掉）');
    expect(currentLng, 'en-US', reason: '導頁後語言權威（URL）沒有變成 en-US');

    final serverAfter = await SessionsApi().getSession(sessionId);
    expect(serverAfter.status, 'cancelled',
        reason: '場次沒有被收掉 → 後端仍以舊語言在跑（孤兒場次）');

    // ── 5. 離頁清理沒有丟例外（autoDispose / _disposed 閘門）────
    await _pumpFor(tester, const Duration(seconds: 5));
    expect(tester.takeException(), isNull,
        reason: '離開問診頁時有未捕捉例外（多半是 UnmountedRefException）');
  }, timeout: const Timeout(Duration(minutes: 12)));
}
