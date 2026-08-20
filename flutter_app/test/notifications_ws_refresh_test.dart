// 醫師端通知頁（iOS 首頁）的即時性回歸測試。
//
// 缺陷：`NotificationsController` 只在掛載時 HTTP pull 一次，完全沒接 dashboard WS。
// App 開著的時候，新通知（問診完成 / 報告完成 / 紅旗）不會出現，底部 tab 的未讀
// badge 也不會動——醫師要手動離開再回來才看得到。後端在建立通知的同一條路徑上其實
// 已經廣播了 dashboard 事件（Redis fan-out）。
//
// 行為契約：收到 `session_status_changed`（終態）／`report_generated`／`new_red_flag`
// → 重抓第一頁 + 未讀數；事件連發只打一次；`in_progress` 不觸發；WS 重連的
// `initial_state` 才補抓（掛載後的第一則已由 build() 的初抓涵蓋）；dispose 取消訂閱。
//
// 不變式 #27（WS 事件兩端訂閱清單同步）：事件字串是手抄的，沒有 codegen 也沒有型別
// 訊號。這裡對後端實際廣播的字串做一次硬編碼比對，抄錯會紅。核實來源見 controller
// 內的註解。
//
// 注入式回歸：把 `_scheduleRefresh` 的 debounce 拿掉改直呼 → 「事件連發只打一次」紅；
// 把 `_terminalStatuses` 換成「任何 status 都抓」→「in_progress 不觸發」紅；
// 把 `_skipNextInitialState` 拿掉 → 「首則 initial_state 不重抓」紅；
// 把 onDispose 的 `ws.off` 拿掉 → 「dispose 後事件不再打 API」紅。四種都試過。
import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/data/api/notifications_api.dart';
import 'package:gu_voice/data/models/notification.dart';
import 'package:gu_voice/features/doctor/services/dashboard_ws.dart';
import 'package:gu_voice/features/doctor/state/notifications_controller.dart';
import 'package:gu_voice/features/voice/services/ws_manager.dart';

void main() {
  group('dashboard WS → 通知列表 / 未讀數重抓', () {
    test('訂閱的事件字串與後端廣播的一致（不變式 #27）', () async {
      final h = await _mounted();
      expect(
        h.ws.subscribed,
        {'session_status_changed', 'report_generated', 'new_red_flag', 'initial_state'},
        reason: '兩端手抄、沒有 codegen：抄錯字串不會有任何編譯訊號，只會靜默不更新',
      );
      expect(h.ws.connectCalls, 1, reason: '通知頁是 iOS 首頁，得自己確保 WS 連著');
    });

    test('session_status_changed（終態）→ 重抓列表與未讀數', () async {
      final h = await _mounted();
      expect((h.api.listCalls, h.api.unreadCalls), (1, 1), reason: '掛載時的初抓');

      h.api.items = [_notif('n-2', 'session_complete'), _notif('n-1', 'report_ready')];
      h.api.unread = 2;
      h.emitStatus('completed');
      await pumpEventQueue();

      expect((h.api.listCalls, h.api.unreadCalls), (2, 2));
      final s = h.state;
      expect(s.notifications.map((n) => n.id).toList(), ['n-2', 'n-1']);
      expect(s.unreadCount, 2, reason: 'tab badge 讀的就是這個欄位（doctor_shell）');
      expect(s.isLoading, isFalse);
    });

    test('aborted_red_flag / cancelled 也是終態', () async {
      for (final status in ['aborted_red_flag', 'cancelled']) {
        final h = await _mounted();
        h.emitStatus(status);
        await pumpEventQueue();
        expect(h.api.listCalls, 2, reason: '$status 是終態，後端在這條路徑上建了通知');
      }
    });

    test('session_status_changed（in_progress）→ 不重抓', () async {
      final h = await _mounted();
      h.emitStatus('in_progress');
      await pumpEventQueue();
      expect((h.api.listCalls, h.api.unreadCalls), (1, 1),
          reason: '病患 WS 連上不會建通知，重抓只是白打一次 API');
    });

    test('report_generated / new_red_flag 各自會重抓', () async {
      for (final event in ['report_generated', 'new_red_flag']) {
        final h = await _mounted();
        h.ws.emit(event, const {'sessionId': 's1'});
        await pumpEventQueue();
        expect((h.api.listCalls, h.api.unreadCalls), (2, 2), reason: '$event 應觸發重抓');
      }
    });

    test('事件連發只打一次 API（去重）', () async {
      final h = await _mounted();

      // 一次終態轉移的真實序列：狀態、紅旗、報告完成連著來。
      h.emitStatus('aborted_red_flag');
      h.ws.emit('new_red_flag', const {'alertId': 'a1', 'sessionId': 's1'});
      h.ws.emit('report_generated', const {'reportId': 'r1', 'sessionId': 's1'});
      await pumpEventQueue();

      expect((h.api.listCalls, h.api.unreadCalls), (2, 2),
          reason: '一次終態會連發三個事件，重抓三次是白打兩次 API');
    });

    test('首則 initial_state 不重抓，重連的第二則才補抓', () async {
      final h = await _mounted();

      h.ws.emit('initial_state', const {'sessions': [], 'alerts': []});
      await pumpEventQueue();
      expect(h.api.listCalls, 1, reason: '掛載時已經抓過，WS 剛連上的快照不必再抓一次');

      // 斷線重連 → 後端再送一次 initial_state；離線期間漏掉的事件要補回來。
      h.ws.emit('initial_state', const {'sessions': [], 'alerts': []});
      await pumpEventQueue();
      expect((h.api.listCalls, h.api.unreadCalls), (2, 2));
    });

    test('dispose 取消訂閱，之後的事件不再打 API', () async {
      final h = await _mounted();
      expect(h.ws.subscribed, isNotEmpty);

      h.container.dispose();
      expect(h.ws.subscribed, isEmpty, reason: 'handler 留在共用 WS 上＝洩漏 + 對死掉的 state 寫入');

      h.emitStatus('completed');
      h.ws.emit('report_generated', const {'reportId': 'r1'});
      await pumpEventQueue();
      expect(h.api.listCalls, 1, reason: '只剩掛載時那一次');
    });

    test('dispose 時已排程的重抓被取消，回應也不寫進 state', () async {
      final gate = Completer<void>();
      final h = await _mounted(gate: gate);

      h.emitStatus('completed'); // debounce timer 起跑
      h.container.dispose(); // 醫師登出：timer 應被取消
      await pumpEventQueue();
      expect(h.api.listCalls, 1, reason: '排程中的重抓要跟著 dispose 一起取消');

      // 掛載時那次初抓還卡在網路上，dispose 後才回來——不得寫 state（Riverpod 會拋）。
      gate.complete();
      await expectLater(pumpEventQueue(), completes);
    });
  });
}

// ---------------------------------------------------------------------------

AppNotification _notif(String id, String type) =>
    AppNotification(id: id, type: type, title: id, createdAt: '2026-08-20T00:00:00Z');

class _Harness {
  _Harness(this.container, this.ws, this.api);
  final ProviderContainer container;
  final _FakeDashboardWs ws;
  final _FakeNotificationsApi api;

  NotifState get state => container.read(notificationsProvider);

  void emitStatus(String status) => ws.emit('session_status_changed', {
        'code': 'events.session.completed_normal',
        'params': const {},
        'severity': 'info',
        'sessionId': 's1',
        'status': status,
        'previousStatus': 'in_progress',
      });
}

Future<_Harness> _mounted({Completer<void>? gate}) async {
  final ws = _FakeDashboardWs();
  final api = _FakeNotificationsApi(gate: gate);
  final container = ProviderContainer(overrides: [
    dashboardWsProvider.overrideWithValue(ws),
    notificationsProvider.overrideWith(
      // debounce 歸零：真實的 400ms 只是為了等後端的第二段交易 commit，
      // 去重語意來自「重排同一個 timer」，Duration.zero 一樣測得到。
      () => NotificationsController(api: api, refreshDebounce: Duration.zero),
    ),
  ]);
  addTearDown(() {
    try {
      container.dispose();
    } catch (_) {
      /* 已在測試內 dispose */
    }
  });
  // 真實情況是 DoctorShell 一直 watch 著它；補一個 listener 還原生命週期。
  container.listen(notificationsProvider, (_, _) {});
  await pumpEventQueue();
  return _Harness(container, ws, api);
}

class _FakeNotificationsApi extends NotificationsApi {
  _FakeNotificationsApi({this.gate});

  /// 若不為 null，第一次 `list()` 會卡在這裡直到測試放行（模擬在飛的請求）。
  final Completer<void>? gate;
  int listCalls = 0;
  int unreadCalls = 0;
  int unread = 0;
  List<AppNotification> items = const [];

  @override
  Future<NotifPage> list({String? cursor, int limit = 20, String? type, bool? isRead}) async {
    listCalls++;
    if (listCalls == 1 && gate != null) await gate!.future;
    return (data: items, nextCursor: null, hasMore: false);
  }

  @override
  Future<int> unreadCount() async {
    unreadCalls++;
    return unread;
  }
}

/// 可注入事件的假 dashboard WS：`on` 自己收下 handler，`emit` 直接叫它們。
class _FakeDashboardWs extends DashboardWs {
  final _handlers = <String, List<WsHandler>>{};
  int connectCalls = 0;

  Set<String> get subscribed =>
      _handlers.entries.where((e) => e.value.isNotEmpty).map((e) => e.key).toSet();

  @override
  void ensureConnected() => connectCalls++;

  @override
  void on(String type, WsHandler handler) => _handlers.putIfAbsent(type, () => []).add(handler);

  @override
  void off(String type, WsHandler handler) => _handlers[type]?.remove(handler);

  void emit(String type, Map<String, Object?> payload) {
    for (final h in [...?_handlers[type]]) {
      h(payload, {'type': type, 'payload': payload});
    }
  }

  @override
  void dispose() {}
}
