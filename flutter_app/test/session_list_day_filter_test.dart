// 問診場次清單的日期篩選：預設今天、換日帶裝置時區的日界線、「全部」回到最新 50 筆。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/features/doctor/screens/session_list_page.dart';
import 'package:gu_voice/features/doctor/services/dashboard_ws.dart';
import 'package:gu_voice/features/doctor/state/sessions_list_controller.dart';
import 'package:gu_voice/features/voice/services/ws_manager.dart';

import 'support/api_stub.dart';

class _Ws extends DashboardWs {
  @override
  void ensureConnected() {}
  @override
  void on(String type, WsHandler handler) {}
  @override
  void off(String type, WsHandler handler) {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('defaults to today, shifts by local day, "all" drops the date range', () async {
    installApiStub((_) => {'data': []});
    final c = ProviderContainer(overrides: [dashboardWsProvider.overrideWithValue(_Ws())]);
    addTearDown(c.dispose);
    c.listen(sessionsListProvider, (_, _) {});
    await pumpEventQueue();

    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    expect(c.read(sessionsListProvider).day, today);
    var q = sentRequests.last.queryParameters;
    expect(q['limit'], 100);
    expect(DateTime.parse(q['date_from'] as String).toLocal(), today);
    expect(DateTime.parse(q['date_to'] as String).toLocal(), DateTime(now.year, now.month, now.day + 1).subtract(const Duration(microseconds: 1)));
    // 必須帶時區位移，否則後端當 UTC 切日
    expect(q['date_from'], matches(RegExp(r'[+-]\d\d:\d\d$')));

    final yesterday = DateTime(today.year, today.month, today.day - 1);
    c.read(sessionsListProvider.notifier).setDay(yesterday);
    await pumpEventQueue();
    q = sentRequests.last.queryParameters;
    expect(DateTime.parse(q['date_from'] as String).toLocal(), yesterday);
    expect(DateTime.parse(q['date_to'] as String).toLocal().isBefore(today), isTrue);

    c.read(sessionsListProvider.notifier).setDay(null);
    await pumpEventQueue();
    q = sentRequests.last.queryParameters;
    expect(q['limit'], 50);
    expect(q.containsKey('date_from'), isFalse);
    expect(c.read(sessionsListProvider).day, isNull);
  });

  group('day bar fits iPhone width', () {
    setUpAll(() async {
      await Locales.loadAll();
    });
    tearDown(() => setCurrentLng('zh-TW'));
    for (final lng in supportedLanguages) {
      testWidgets(lng, (tester) async {
        setCurrentLng(lng);
        tester.view.physicalSize = const Size(375 * 3, 812 * 3);
        tester.view.devicePixelRatio = 3;
        addTearDown(tester.view.reset);
        installApiStub((_) => {
              'data': [
                {'id': 's1', 'status': 'completed', 'patient_name': '王小明', 'chief_complaint_text': '頻尿', 'created_at': DateTime.now().toUtc().toIso8601String(), 'duration_seconds': 420},
              ],
            });
        await tester.pumpWidget(ProviderScope(
          overrides: [dashboardWsProvider.overrideWithValue(_Ws())],
          child: MaterialApp(theme: AppTheme.light, home: const SessionListPage()),
        ));
        await tester.pumpAndSettle();
        expect(find.text('王小明 · ${'${DateTime.now().hour}'.padLeft(2, '0')}:${'${DateTime.now().minute}'.padLeft(2, '0')} · 7 min'), findsOneWidget);
        // 今天：後一天停用
        expect(tester.widget<IconButton>(find.byKey(const Key('session-day-next'))).onPressed, isNull);
        await tester.tap(find.byKey(const Key('session-day-prev')));
        await tester.pumpAndSettle();
        expect(tester.widget<IconButton>(find.byKey(const Key('session-day-next'))).onPressed, isNotNull);
        await tester.tap(find.byKey(const Key('session-day-all')));
        await tester.pumpAndSettle();
        expect(sentRequests.last.queryParameters.containsKey('date_from'), isFalse);
        expect(tester.takeException(), isNull);
      });
    }
  });
}
