import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/doctor/services/dashboard_ws.dart';
import 'package:gu_voice/features/doctor/state/alerts_controller.dart';
import 'package:gu_voice/features/doctor/state/notifications_controller.dart';
import 'package:gu_voice/features/doctor/state/sessions_list_controller.dart';
import 'package:gu_voice/features/voice/state/settings_notifier.dart';

import 'support/api_stub.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late ProviderContainer container;
  late AuthNotifier auth;
  Completer<void>? gate;
  final waiting = <String>[];

  setUp(() async {
    FlutterSecureStorage.setMockInitialValues({});
    await TokenStore.instance.clear();
    gate = null;
    waiting.clear();
    installApiStub((request) async {
      if (request.path == '/auth/login') {
        final id = (request.data as Map)['email'] as String;
        return {
          'access_token': id,
          'refresh_token': '$id-refresh',
          'user': {'id': id, 'role': id == 'patient' ? 'patient' : 'doctor'},
        };
      }
      if (request.path == '/auth/logout') return <String, dynamic>{};
      final owner = request.headers['Authorization'].toString().replaceFirst(
        'Bearer ',
        '',
      );
      if (request.path == '/auth/me') {
        return {'id': owner, 'name': 'updated', 'role': 'doctor'};
      }
      final pending = gate;
      if (pending != null && owner == 'doctor-A') {
        waiting.add(request.path);
        await pending.future;
      }
      if (request.path.endsWith('count')) {
        return {'count': owner == 'doctor-A' ? 1 : 2};
      }
      if (request.path == '/notifications/read-all') return <String, dynamic>{};
      if (request.path == '/alerts/acknowledge-all') return {'acknowledged': 1};
      if (request.path.endsWith('/acknowledge')) {
        return {'acknowledged_at': '2026-10-03T00:00:00Z'};
      }
      return {
        'data': [
          {'id': owner, 'title': owner},
        ],
        'pagination': {
          'has_more': true,
          'next_cursor': 'next',
          'total_count': 1,
        },
      };
    });
    container = ProviderContainer();
    addTearDown(() {
      container.dispose();
      ApiClient.instance.onAuthCleared = null;
    });
    auth = container.read(authProvider.notifier);
    ApiClient.instance.onAuthCleared = auth.forceLoggedOut;
    await auth.login('doctor-A', 'test');
    container.listen(notificationsProvider, (_, _) {});
    container.listen(alertsProvider, (_, _) {});
    container.listen(sessionsListProvider, (_, _) {});
    await pumpEventQueue();
  });

  void expectOwner(String id) {
    expect(container.read(notificationsProvider).notifications.single.id, id);
    expect(container.read(alertsProvider).alerts.single.id, id);
    expect(container.read(sessionsListProvider).sessions.single.id, id);
    expect(container.read(notificationsProvider).error, isNull);
    expect(container.read(alertsProvider).error, isNull);
    expect(container.read(sessionsListProvider).hasError, isFalse);
  }

  void expectEmpty() {
    expect(container.read(dashboardWsProvider), isNull);
    expect(container.read(notificationsProvider).notifications, isEmpty);
    expect(container.read(notificationsProvider).unreadCount, 0);
    expect(container.read(alertsProvider).alerts, isEmpty);
    expect(container.read(alertsProvider).unacknowledgedCount, 0);
    expect(container.read(sessionsListProvider).sessions, isEmpty);
  }

  for (final forced in [false, true]) {
    test('${forced ? '認證失效' : '主動登出'}清空所有醫師資料，B 登入重建連線與資料', () async {
      expectOwner('doctor-A');
      final oldWs = container.read(dashboardWsProvider)!;
      container.read(settingsProvider.notifier).toggleTtsMuted();
      if (forced) {
        await TokenStore.instance.clear();
        auth.forceLoggedOut();
      } else {
        await auth.logout();
      }
      expectEmpty();
      expect(oldWs.isDisposed, isTrue);
      expect(container.read(settingsProvider).ttsMuted, isFalse,
          reason: 'kiosk 跨病患：上一位的靜音／字級不得留給下一位');
      await auth.login('doctor-B', 'test');
      await pumpEventQueue();
      expectOwner('doctor-B');
      expect(container.read(dashboardWsProvider), isNot(same(oldWs)));
      expect(container.read(notificationsProvider).unreadCount, 2);
    });
  }

  test('直接切換醫師或病患也隔離資料，更新同帳號個人資料不重連', () async {
    final original = container.read(dashboardWsProvider)!;
    await auth.updateProfile({'name': 'updated'});
    expect(container.read(dashboardWsProvider), same(original));
    expectOwner('doctor-A');
    await auth.login('doctor-B', 'test');
    await pumpEventQueue();
    expectOwner('doctor-B');
    expect(original.isDisposed, isTrue);
    final doctorWs = container.read(dashboardWsProvider)!;
    await auth.login('patient', 'test');
    expectEmpty();
    expect(doctorWs.isDisposed, isTrue);
  });

  test('A 的清單、分頁、計數與寫入延遲完成，不污染 B 或觸發 B 的後續請求', () async {
    gate = Completer<void>();
    final notifications = container.read(notificationsProvider.notifier);
    final alerts = container.read(alertsProvider.notifier);
    final pending = Future.wait([
      notifications.fetchMore(),
      notifications.fetch(),
      notifications.fetchUnreadCount(),
      notifications.markAllRead(),
      alerts.fetchMore(),
      alerts.fetchAlerts(),
      alerts.fetchUnacknowledgedCount(),
      alerts.acknowledge('doctor-A'),
      alerts.acknowledgeAll(),
      container.read(sessionsListProvider.notifier).reload(),
    ]);
    await pumpEventQueue();
    expect(waiting.length, 10);
    await auth.logout();
    await auth.login('doctor-B', 'test');
    await pumpEventQueue();
    expectOwner('doctor-B');
    final requestsBefore = sentRequests.length;
    gate!.complete();
    await pending;
    await pumpEventQueue();
    expectOwner('doctor-B');
    expect(sentRequests.length, requestsBefore);
    expect(container.read(notificationsProvider).unreadCount, 2);
    expect(container.read(alertsProvider).unacknowledgedCount, 2);
  });
}
