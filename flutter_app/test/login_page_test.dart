// 登入頁 widget smoke（D23 前置）：拆 build 之前先釘住「欄位有畫出來、空欄位送出會
// 行內驗證、不打 auth」。authProvider 以固定狀態覆寫，整個測試零網路。

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/auth/login_page.dart';

class _FixedAuth extends AuthNotifier {
  final loginCalls = <(String, String)>[];

  @override
  AuthState build() => const AuthState(booted: true);

  @override
  Future<void> login(String email, String password) async =>
      loginCalls.add((email, password));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() async {
    // AuthApi captures ApiClient.instance.dio in a field initialiser (see boot_gate_test).
    ApiClient.instance.init();
    await Locales.loadAll();
  });

  Future<_FixedAuth> pump(WidgetTester tester) async {
    final auth = _FixedAuth();
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [authProvider.overrideWith(() => auth)],
        child: const MaterialApp(home: LoginPage()),
      ),
    );
    await tester.pumpAndSettle();
    return auth;
  }

  testWidgets('renders email + password fields and the submit button', (
    tester,
  ) async {
    await pump(tester);
    expect(find.text(t('common.appTitle')), findsOneWidget);
    expect(find.text(t('common.login.emailLabel')), findsOneWidget);
    expect(find.text(t('common.login.passwordLabel')), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(2));
    expect(find.byKey(const Key('login-submit')), findsOneWidget);
    expect(find.text(t('common.login.submit')), findsOneWidget);
  });

  testWidgets(
    'submit with empty fields shows inline validation and never calls login',
    (tester) async {
      final auth = await pump(tester);

      await tester.tap(find.byKey(const Key('login-submit')));
      await tester.pumpAndSettle();
      expect(find.text(t('common.login.emailRequired')), findsOneWidget);
      expect(auth.loginCalls, isEmpty);

      await tester.enterText(
        find.byType(TextField).first,
        'doctor@example.com',
      );
      await tester.tap(find.byKey(const Key('login-submit')));
      await tester.pumpAndSettle();
      expect(find.text(t('common.login.emailRequired')), findsNothing);
      expect(find.text(t('common.login.passwordRequired')), findsOneWidget);
      expect(auth.loginCalls, isEmpty);

      await tester.enterText(find.byType(TextField).last, 'secret');
      await tester.tap(find.byKey(const Key('login-submit')));
      await tester.pumpAndSettle();
      expect(find.text(t('common.login.passwordRequired')), findsNothing);
      expect(auth.loginCalls, [('doctor@example.com', 'secret')]);
    },
  );
}
