// DoctorAlertWatcher 坐在 MaterialApp.router 的 `builder` 裡——Router **之上**。
// 那一層拿不到 GoRouter，toast 的「查看」按鈕若走 `context.go` 會拋
// 「No GoRouter found in context」，醫師點了什麼都不會發生。這裡把導頁釘在
// routerProvider 上：按鈕按下去真的要換頁。

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:gu_voice/core/router/app_router.dart';
import 'package:gu_voice/data/models/user.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/doctor/doctor_alert_watcher.dart';
import 'package:gu_voice/features/doctor/state/alerts_controller.dart';

import 'support/api_stub.dart';

class _DoctorAuth extends AuthNotifier {
  @override
  AuthState build() => const AuthState(
        user: User(id: 'd1', email: 'd@x.y', name: 'Dr', role: 'doctor'),
        booted: true,
      );
}

class _FakeAlerts extends AlertsController {
  @override
  AlertsState build() => const AlertsState();

  void bump() => state = state.copyWith(newAlertSeq: state.newAlertSeq + 1);
}

void main() {
  testWidgets('新紅旗 toast 的「查看」按鈕從 Router 之上也導得到 /alerts', (tester) async {
    installApiStub((_) => null); // 只為了初始化 ApiClient；fake 不打網路
    final router = GoRouter(
      initialLocation: '/',
      routes: [
        GoRoute(path: '/', builder: (_, _) => const Scaffold(body: Text('home'))),
        GoRoute(path: '/:lng/alerts', builder: (_, _) => const Scaffold(body: Text('alerts page'))),
      ],
    );
    final container = ProviderContainer(overrides: [
      authProvider.overrideWith(_DoctorAuth.new),
      alertsProvider.overrideWith(_FakeAlerts.new),
      routerProvider.overrideWithValue(router),
    ]);
    addTearDown(container.dispose);

    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(
        routerConfig: router,
        builder: (context, child) => DoctorAlertWatcher(child: child!),
      ),
    ));
    expect(find.text('home'), findsOneWidget);

    (container.read(alertsProvider.notifier) as _FakeAlerts).bump();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300)); // SnackBar 進場動畫
    expect(find.byType(SnackBarAction), findsOneWidget);

    await tester.tap(find.byType(SnackBarAction));
    await tester.pumpAndSettle();

    expect(find.text('alerts page'), findsOneWidget,
        reason: 'builder 層沒有 GoRouter；導頁必須走 routerProvider');
  });
}
