// iOS 醫師 App 的 FCM 推播 client。
//
// 這裡只驗 PushService／pushRouteFor／啟動閘門這三段純邏輯：Firebase 全部在
// PushBackend 介面後面，測試餵 fake，一個 platform channel 都不碰。
//
// 每一條都對應一個真實會痛的失敗：
//   - simulator 上 getToken() 必拋（沒有 APNS token）→ 不容錯就等於醫師 App 在
//     模擬器上一啟動就死；
//   - 登出沒反註冊 → 下一個登入這台裝置的醫師會收到前一位醫師的病患推播；
//   - 導頁對應自己發明一套 → 報告推播點下去跑到 /sessions（後端 report_ready 的
//     data 根本沒帶 type）。

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/data/api/notifications_api.dart';
import 'package:gu_voice/data/models/user.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/doctor/services/push_backend_stub.dart';
import 'package:gu_voice/features/doctor/services/push_service.dart';

typedef Registration = ({String token, String platform, String? deviceName});

class FakeNotificationsApi extends NotificationsApi {
  final registrations = <Registration>[];
  final removals = <String>[];
  Object? registerError;
  Object? removeError;

  @override
  Future<void> registerFcmToken({
    required String token,
    required String platform,
    String? deviceName,
  }) async {
    if (registerError != null) throw registerError!;
    registrations.add((token: token, platform: platform, deviceName: deviceName));
  }

  @override
  Future<void> removeFcmToken(String token) async {
    if (removeError != null) throw removeError!;
    removals.add(token);
  }
}

class FakePushBackend implements PushBackend {
  FakePushBackend({this.token = 'tok-1', this.tokenError, this.initError});

  String? token;
  Object? tokenError;
  Object? initError;
  Map<String, dynamic>? initialMessage;
  int initializeCalls = 0;
  int permissionCalls = 0;

  final refresh = StreamController<String>.broadcast();
  final opened = StreamController<Map<String, dynamic>>.broadcast();

  @override
  Future<void> initialize() async {
    initializeCalls++;
    if (initError != null) throw initError!;
  }

  @override
  Future<bool> requestPermission() async {
    permissionCalls++;
    return true;
  }

  @override
  Future<String?> getToken() async {
    if (tokenError != null) throw tokenError!;
    return token;
  }

  @override
  Stream<String> get onTokenRefresh => refresh.stream;

  @override
  Stream<Map<String, dynamic>> get onMessageOpenedApp => opened.stream;

  @override
  Future<Map<String, dynamic>?> getInitialMessage() async => initialMessage;

  @override
  String? get deviceName => 'Doctor iPhone';

  void dispose() {
    refresh.close();
    opened.close();
  }
}

void main() {
  late FakePushBackend backend;
  late FakeNotificationsApi api;
  late List<String> routes;

  PushService build() => PushService(
        backend: backend,
        api: api,
        navigate: routes.add,
      );

  setUp(() {
    backend = FakePushBackend();
    api = FakeNotificationsApi();
    routes = [];
  });

  tearDown(() => backend.dispose());

  group('啟動閘門（web / 病患一律不啟動）', () {
    User user(String role) => User(id: 'u1', email: 'a@b.c', name: 'n', role: role);

    test('原生行動平台 × 醫護 → 啟動', () {
      for (final role in ['doctor', 'admin']) {
        expect(shouldEnablePush(user: user(role), nativeMobile: true), isTrue, reason: role);
      }
    });

    test('web（nativeMobile=false）永遠不啟動 —— 瀏覽器上 FCM 註冊沒有意義', () {
      for (final role in ['doctor', 'admin', 'patient']) {
        expect(shouldEnablePush(user: user(role), nativeMobile: false), isFalse, reason: role);
      }
    });

    test('病患帳號不啟動 —— kiosk iPad 是共用機，不得成為任何人的推播端點', () {
      expect(shouldEnablePush(user: user('patient'), nativeMobile: true), isFalse);
    });

    test('未登入不啟動', () {
      expect(shouldEnablePush(user: null, nativeMobile: true), isFalse);
    });
  });

  group('token 註冊', () {
    test('start() 走完 initialize → 權限 → getToken → 後端註冊', () async {
      await build().start();

      expect(backend.initializeCalls, 1);
      expect(backend.permissionCalls, 1);
      expect(api.registrations, [
        (token: 'tok-1', platform: 'ios', deviceName: 'Doctor iPhone'),
      ]);
    });

    test('platform 送的是後端 DevicePlatform enum 的 "ios"', () {
      expect(kPushPlatformIos, 'ios');
    });

    test('重複 start() 不重複註冊', () async {
      final service = build();
      await service.start();
      await service.start();
      expect(api.registrations, hasLength(1));
    });

    test('onTokenRefresh 用新 token 重新註冊，登出時刪的也是新的', () async {
      final service = build();
      await service.start();

      backend.refresh.add('tok-2');
      await pumpEventQueue();

      expect(api.registrations.map((r) => r.token), ['tok-1', 'tok-2']);
      expect(service.registeredToken, 'tok-2');

      await service.unregister();
      expect(api.removals, ['tok-2']);
    });

    test('後端註冊失敗只是沒推播，不拋、也不記成已註冊', () async {
      api.registerError = StateError('500');
      final service = build();

      await service.start();

      expect(service.registeredToken, isNull);
      await service.unregister();
      expect(api.removals, isEmpty, reason: '沒註冊成功就不該去刪');
    });
  });

  group('simulator 容錯（沒有 APNS token）', () {
    test('getToken() 拋例外時 start() 正常完成，且後續串流仍接得上', () async {
      backend.tokenError = StateError('apns-token-not-set');
      final service = build();

      await expectLater(service.start(), completes);
      expect(api.registrations, isEmpty);

      // 之後 APNs 回來了（真機或使用者授權後），onTokenRefresh 仍然要能救回註冊。
      backend.refresh.add('tok-late');
      await pumpEventQueue();
      expect(api.registrations.map((r) => r.token), ['tok-late']);
    });

    test('Firebase 初始化失敗（plist 沒進 bundle）不讓 App 掛掉', () async {
      backend.initError = StateError('no GoogleService-Info.plist');
      final service = build();

      await expectLater(service.start(), completes);
      expect(api.registrations, isEmpty);
    });

    test('getToken() 回 null 或空字串都不打後端', () async {
      backend.token = null;
      await build().start();
      expect(api.registrations, isEmpty);

      backend.token = '';
      await build().start();
      expect(api.registrations, isEmpty);
    });
  });

  group('登出反註冊', () {
    test('unregister() 打 DELETE 並清掉本地 token（重複呼叫不重送）', () async {
      final service = build();
      await service.start();

      await service.unregister();
      await service.unregister();

      expect(api.removals, ['tok-1']);
      expect(service.registeredToken, isNull);
    });

    test('DELETE 失敗不拋 —— 登出不能被推播收尾擋住', () async {
      api.removeError = StateError('network down');
      final service = build();
      await service.start();

      await expectLater(service.unregister(), completes);
    });

    test('AuthNotifier.preLogoutHooks 會跑到，且 hook 爆掉也吞掉', () async {
      addTearDown(AuthNotifier.preLogoutHooks.clear);
      AuthNotifier.preLogoutHooks.clear();

      final service = build();
      await service.start();

      var boomRan = false;
      Future<void> boom() async {
        boomRan = true;
        throw StateError('hook 爆了');
      }

      AuthNotifier.preLogoutHooks
        ..add(boom)
        ..add(service.unregister);

      await expectLater(AuthNotifier.runPreLogoutHooks(), completes);
      expect(boomRan, isTrue);
      expect(api.removals, ['tok-1'], reason: '前一個 hook 拋例外不該吃掉後面的');
    });

    test('tear-off 相等，所以 watcher 移得掉自己掛上去的 hook', () async {
      addTearDown(AuthNotifier.preLogoutHooks.clear);
      AuthNotifier.preLogoutHooks.clear();

      final service = build();
      AuthNotifier.preLogoutHooks.add(service.unregister);
      AuthNotifier.preLogoutHooks.remove(service.unregister);

      expect(AuthNotifier.preLogoutHooks, isEmpty);
    });
  });

  group('通知 tap 導頁（對應規則的權威＝AppNotification.route）', () {
    // 三份 payload 逐字抄自後端：
    //   alert_service.py       → notification_data（唯一帶 type 的）
    //   notification_service.py → notify_session_complete / notify_report_ready
    test('紅旗推播 → /alerts/:alertId', () {
      expect(
        pushRouteFor({
          'type': 'red_flag',
          'alert_id': 'a-1',
          'session_id': 's-1',
          'severity': 'critical',
        }),
        '/alerts/a-1',
      );
    });

    test('報告完成推播 → /reports/:sessionId（後端沒帶 type，靠 report_id 判定）', () {
      expect(
        pushRouteFor({'session_id': 's-1', 'report_id': 'r-1'}),
        '/reports/s-1',
        reason: '掉回 /sessions 就等於醫師點推播看不到報告',
      );
    });

    test('場次完成推播 → /sessions/:sessionId', () {
      expect(pushRouteFor({'session_id': 's-1'}), '/sessions/s-1');
    });

    test('認不得的 payload → null（留在原地，不亂跳）', () {
      expect(pushRouteFor(const {}), isNull);
      expect(pushRouteFor({'type': 'system'}), isNull);
      expect(pushRouteFor({'foo': 'bar'}), isNull);
    });

    test('alert_id 優先於 session_id，與通知中心點擊一致', () {
      expect(pushRouteFor({'alert_id': 'a-9', 'session_id': 's-9'}), '/alerts/a-9');
    });

    test('onMessageOpenedApp（背景點擊）導到對應路由', () async {
      final service = build();
      await service.start();

      backend.opened.add({'session_id': 's-42', 'report_id': 'r-42'});
      await pumpEventQueue();

      expect(routes, ['/reports/s-42']);
    });

    test('getInitialMessage（由推播冷啟動）也導頁', () async {
      backend.initialMessage = {'type': 'red_flag', 'alert_id': 'a-7'};

      await build().start();

      expect(routes, ['/alerts/a-7']);
    });

    test('stop() 之後不再導頁', () async {
      final service = build();
      await service.start();
      service.stop();

      backend.opened.add({'session_id': 's-1'});
      await pumpEventQueue();

      expect(routes, isEmpty);
    });
  });

  group('web 的 no-op backend', () {
    test('每個方法都安靜地什麼都不做（萬一被建出來，代價是沒推播而不是白畫面）', () async {
      const noop = NoopPushBackend();
      final service = PushService(backend: noop, api: api, navigate: routes.add);

      await expectLater(service.start(), completes);
      expect(await noop.getToken(), isNull);
      expect(await noop.requestPermission(), isFalse);
      expect(await noop.getInitialMessage(), isNull);
      expect(noop.deviceName, isNull);
      expect(api.registrations, isEmpty);
      expect(routes, isEmpty);
    });
  });

  group('debugPrint 不會把 token 印出來（token 等同於推播權限）', () {
    test('註冊失敗的 log 不含 token', () async {
      final logs = <String>[];
      final previous = debugPrint;
      debugPrint = (String? message, {int? wrapWidth}) => logs.add(message ?? '');
      addTearDown(() => debugPrint = previous);

      api.registerError = StateError('boom');
      await build().start();

      expect(logs, isNotEmpty);
      expect(logs.any((l) => l.contains('tok-1')), isFalse);
    });
  });
}
