// 手機版面走查（2026-08-22，iOS 單一 App 拍板後）。
//
// 醫師端與 admin 的每一頁，過去只在桌面瀏覽器寬度下用過；iOS 成為唯一 App 之後
// 它們要在 390pt 的 iPhone 上能用。這支在真 simulator × 本機後端 × 真資料下逐頁走：
//
//   1. 每一頁 push 進去、pump 到安定，**任何 RenderFlex overflow 都會以例外浮出**
//      （debug build 下 overflow 是 FlutterError；tester.takeException 收得到）。
//   2. 逐頁截圖到 build/layout_shots/，人眼複核用。
//
// 跑法（先 docker compose up -d，需要 testdoctor / testadmin 帳號）：
//   fvm flutter test integration_test/mobile_layout_walkthrough_test.dart -d <udid> \
//     --dart-define=API_BASE=http://localhost:8000/api/v1 \
//     --dart-define=WS_BASE=ws://localhost:8000/api/v1/ws \
//     --dart-define=E2E_DOCTOR_EMAIL=... --dart-define=E2E_DOCTOR_PASSWORD=... \
//     --dart-define=E2E_ADMIN_EMAIL=...  --dart-define=E2E_ADMIN_PASSWORD=...

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:gu_voice/app.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/app_router.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';

const _doctorEmail = String.fromEnvironment('E2E_DOCTOR_EMAIL');
const _doctorPassword = String.fromEnvironment('E2E_DOCTOR_PASSWORD');
const _adminEmail = String.fromEnvironment('E2E_ADMIN_EMAIL');
const _adminPassword = String.fromEnvironment('E2E_ADMIN_PASSWORD');

bool _apiInited = false;

Future<void> _pumpFor(WidgetTester tester, Duration total) async {
  final steps = total.inMilliseconds ~/ 250;
  for (var i = 0; i < steps; i++) {
    await tester.pump(const Duration(milliseconds: 250));
  }
}

Future<ProviderContainer> _boot(WidgetTester tester) async {
  // iPhone 17 的邏輯尺寸。這支的重點就是「在手機寬度下」，別用平板尺寸騙自己。
  tester.view.physicalSize = const Size(1179, 2556);
  tester.view.devicePixelRatio = 3.0;
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
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const App()));
  await tester.pumpAndSettle();
  return container;
}

Future<void> _login(WidgetTester tester, ProviderContainer c, String email, String pw) async {
  final fields = find.byType(TextField);
  await tester.enterText(fields.at(0), email);
  await tester.pump();
  await tester.enterText(fields.at(1), pw);
  await tester.pumpAndSettle();
  await tester.tap(find.byType(FilledButton).first);
  for (var i = 0; i < 80 && c.read(authProvider).user == null; i++) {
    await tester.pump(const Duration(milliseconds: 250));
  }
  expect(c.read(authProvider).user, isNotNull,
      reason: '登入失敗（error=${c.read(authProvider).error}）');
  await tester.pumpAndSettle();
}

/// 走一頁：導航 → 等資料 → 收例外。overflow / assert 都會在這裡浮出成測試失敗。
Future<void> _visit(
  WidgetTester tester,
  ProviderContainer c,
  IntegrationTestWidgetsFlutterBinding binding,
  String rest, {
  Duration settle = const Duration(seconds: 6),
}) async {
  c.read(routerProvider).go('/zh-TW$rest');
  await _pumpFor(tester, settle);
  // pumpAndSettle 在有動畫/輪詢的頁面會 timeout，改用固定 pump；再收一次例外。
  final e = tester.takeException();
  expect(e, isNull, reason: '$rest 在手機寬度下拋出例外（多半是 RenderFlex overflow）：$e');
}

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('醫師端全頁面在 iPhone 寬度下無 overflow', (tester) async {
    if (_doctorEmail.isEmpty) {
      markTestSkipped('未提供 E2E_DOCTOR_EMAIL');
      return;
    }
    final c = await _boot(tester);
    await _login(tester, c, _doctorEmail, _doctorPassword);

    for (final rest in [
      '/notifications',
      '/dashboard',
      '/sessions',
      '/alerts',
      '/reports',
      '/patients',
      '/research',
      '/settings',
    ]) {
      await _visit(tester, c, binding, rest,
          settle: rest == '/research' ? const Duration(seconds: 12) : const Duration(seconds: 6));
    }
  }, timeout: const Timeout(Duration(minutes: 6)));

  testWidgets('admin 四頁在 iPhone 寬度下無 overflow', (tester) async {
    if (_adminEmail.isEmpty) {
      markTestSkipped('未提供 E2E_ADMIN_EMAIL');
      return;
    }
    final c = await _boot(tester);
    await _login(tester, c, _adminEmail, _adminPassword);

    for (final rest in [
      '/admin/users',
      '/admin/complaints',
      '/admin/health',
      '/admin/audit-logs',
    ]) {
      await _visit(tester, c, binding, rest);
    }
  }, timeout: const Timeout(Duration(minutes: 5)));
}
