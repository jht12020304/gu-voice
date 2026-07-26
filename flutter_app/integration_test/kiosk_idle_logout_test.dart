// Kiosk idle auto-logout on a real device (TODO G11).
//
// Why this needs a device: it is a *timing* behaviour wired through
// `MaterialApp.router`'s builder. Pure tests cover the guard predicate, but they cannot
// catch the thing that actually broke — the first version called
// `GoRouterState.of(context)` in that builder, which sits above the Navigator, so the
// app died with `GoError: There is no GoRouterState above the current context` while
// `flutter analyze` and 32 unit tests stayed green.
//
// Run with a short window, otherwise the test is skipped:
//
//   flutter test integration_test/kiosk_idle_logout_test.dart \
//     -d <simulator-udid> \
//     --dart-define=API_BASE=https://.../api/v1 \
//     --dart-define=WS_BASE=wss://.../api/v1/ws \
//     --dart-define=KIOSK_IDLE_TIMEOUT_SECONDS=8 \
//     --dart-define=E2E_PATIENT_EMAIL=patient1@example.com \
//     --dart-define=E2E_PATIENT_PASSWORD=...

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:gu_voice/app.dart';
import 'package:gu_voice/core/config/env.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';

const _email = String.fromEnvironment('E2E_PATIENT_EMAIL');
const _password = String.fromEnvironment('E2E_PATIENT_PASSWORD');

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('an idle patient is logged out; the app does not crash', (tester) async {
    final window = Env.kioskIdleTimeoutSeconds;
    if (_email.isEmpty || _password.isEmpty) {
      markTestSkipped('未提供 E2E_PATIENT_EMAIL / E2E_PATIENT_PASSWORD，跳過');
      return;
    }
    if (window <= 0 || window > 30) {
      markTestSkipped('KIOSK_IDLE_TIMEOUT_SECONDS=$window——需要 1..30 才跑得動，跳過');
      return;
    }

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

    final fields = find.byType(TextField);
    expect(fields, findsAtLeast(2));
    await tester.enterText(fields.at(0), _email);
    await tester.enterText(fields.at(1), _password);
    await tester.pumpAndSettle();
    await tester.tap(find.byType(FilledButton).first);

    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 500));
      if (container.read(authProvider).user != null) break;
    }
    await tester.pumpAndSettle();
    expect(container.read(authProvider).user, isNotNull, reason: '病患登入失敗，無法測閒置');

    // Idle: let real wall-clock time pass with no pointer or key event.
    // `tester.pump()` alone is not enough — the guard uses a real `Timer`, which only
    // fires on the real event loop, and that requires `runAsync`.
    await tester.runAsync(() async {
      await Future<void>.delayed(Duration(seconds: window + 4));
    });
    await tester.pumpAndSettle();

    expect(
      container.read(authProvider).user,
      isNull,
      reason: '閒置 ${window}s 後病患未被登出——下一位病患會看到上一位的姓名與主訴',
    );
    // Logout must also drop the stored tokens, or a relaunch silently restores the
    // previous patient's session.
    TokenStore.instance.accessToken = null;
    await TokenStore.instance.load();
    expect(TokenStore.instance.accessToken, isNull);
  }, timeout: const Timeout(Duration(minutes: 3)));
}
