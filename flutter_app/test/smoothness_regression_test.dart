import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/app_router.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/data/models/user.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/doctor/services/dashboard_ws.dart';
import 'package:gu_voice/features/doctor/state/sessions_list_controller.dart';
import 'package:gu_voice/features/voice/services/ws_manager.dart';
import 'support/api_stub.dart';
import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/features/doctor/screens/session_calendar_view.dart';
import 'package:gu_voice/features/doctor/screens/patient_list_page.dart';
import 'package:gu_voice/features/doctor/screens/report_list_page.dart';
import 'package:gu_voice/features/doctor/screens/alert_list_page.dart';

class AuditAuth extends AuthNotifier {
  void switchUser(String id) => state = AuthState(
    booted: true,
    user: User(id: id, email: "$id@example.invalid", name: id, role: "doctor"),
  );
  @override
  AuthState build() => const AuthState(
    booted: true,
    user: User(id: 'audit', email: 'audit@example.invalid', name: 'Audit', role: 'doctor'),
  );
}

class AuditSocket extends DashboardWs {
  final listeners = <String, List<WsHandler>>{};
  @override
  void ensureConnected() {}
  @override
  void on(String type, WsHandler handler) => listeners.putIfAbsent(type, () => []).add(handler);
  @override
  void off(String type, WsHandler handler) => listeners[type]?.remove(handler);
  void emit(String type) {
    for (final h in List<WsHandler>.of(listeners[type] ?? [])) {
      h({'sessionId': 'audit-s', 'status': 'in_progress'}, {'type': type});
    }
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    await Locales.loadAll();
    setCurrentLng('zh-TW');
  });
  testWidgets('retained tabs preserve search, month, scroll and request budget', (tester) async {
    final calls = <String>[];
    installApiStub((r) {
      calls.add(r.path);
      if (r.path.endsWith('count')) return {'count': 0};
      if (r.path == '/dashboard/monthly-summary') {
        return {
          'month': r.queryParameters['month'],
          'total_sessions': 1,
          'total_red_flag_alerts': 0,
          'chief_complaint_distribution': [],
          'daily_trend': [],
        };
      }
      return {
        'data': r.path == '/sessions'
            ? List.generate(50, (i) => {'id': 'tab-$i', 'patient_name': 'AUDIT search $i', 'status': 'completed'})
            : [],
        'pagination': {'has_more': false, 'total_count': 50},
      };
    });
    final ws = AuditSocket();
    final c = ProviderContainer(
      overrides: [authProvider.overrideWith(AuditAuth.new), dashboardWsProvider.overrideWithValue(ws)],
    );
    final router = c.read(routerProvider);
    router.go('/zh-TW/dashboard');
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: c,
        child: MaterialApp.router(theme: AppTheme.light, routerConfig: router),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip(t('common.doctor.dashboard.prevMonth')));
    await tester.pumpAndSettle();
    final now = DateTime.now();
    final previousMonth = DateTime(now.year, now.month - 1);
    final monthLabel = t(
      'common.doctor.dashboard.monthFormat',
      args: {'year': previousMonth.year, 'month': previousMonth.month},
    );
    expect(find.text(monthLabel), findsOneWidget);
    final initial = calls.where((p) => p == '/dashboard/monthly-summary').length;
    router.go('/zh-TW/sessions');
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'AUDIT search');
    await tester.pump();
    final listScroll = tester.state<ScrollableState>(find.byType(Scrollable).last).position;
    listScroll.jumpTo(300);
    await tester.pump();
    for (var i = 0; i < 20; i++) {
      router.go('/zh-TW/dashboard');
      await tester.pumpAndSettle();
      expect(find.text(monthLabel), findsOneWidget);
      router.go('/zh-TW/sessions');
      await tester.pumpAndSettle();
    }
    final returned = calls.where((p) => p == '/dashboard/monthly-summary').length;
    router.go('/zh-TW/sessions');
    await tester.pumpAndSettle();
    final search = tester.widget<EditableText>(find.byType(EditableText)).controller.text;
    final before = calls.where((p) => p == '/sessions').length;
    for (final e in ['session_created', 'session_status_changed', 'queue_updated']) {
      ws.emit(e);
    }
    await tester.pump(const Duration(milliseconds: 150));
    await tester.pumpAndSettle();
    final after = calls.where((p) => p == '/sessions').length;
    expect(initial, 2); // initial month + deliberate previous-month selection
    expect(returned, initial);
    expect(tester.state<ScrollableState>(find.byType(Scrollable).last).position.pixels, 300);
    expect(search, 'AUDIT search');
    expect(after - before, 1);
    await tester.pumpWidget(const SizedBox());
    c.dispose();
  });
  test('late list result cannot revert fresher data within one account', () async {
    final older = Completer<Object?>(), newer = Completer<Object?>();
    var count = 0;
    installApiStub((r) {
      if (++count == 1) return {'data': []};
      return count == 2 ? older.future : newer.future;
    });
    final c = ProviderContainer(overrides: [dashboardWsProvider.overrideWithValue(AuditSocket())]);
    c.listen(sessionsListProvider, (_, _) {});
    await pumpEventQueue();
    final controller = c.read(sessionsListProvider.notifier);
    final a = controller.reload(), b = controller.reload();
    await pumpEventQueue();
    newer.complete({
      'data': [
        {'id': 'new', 'status': 'completed'},
      ],
    });
    await b;
    older.complete({
      'data': [
        {'id': 'old', 'status': 'waiting'},
      ],
    });
    await a;
    final id = c.read(sessionsListProvider).sessions.single.id;
    expect(id, "new");
    c.dispose();
  });

  testWidgets('switching language and accounts clears retained navigators safely', (tester) async {
    installApiStub(
      (r) => r.path.endsWith('count')
          ? {'count': 0}
          : {
              'data': [],
              'pagination': {'has_more': false},
            },
    );
    final c = ProviderContainer(
      overrides: [authProvider.overrideWith(AuditAuth.new), dashboardWsProvider.overrideWithValue(AuditSocket())],
    );
    c.read(routerProvider).go('/zh-TW/sessions');
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: c,
        child: Consumer(
          builder: (_, ref, _) => MaterialApp.router(theme: AppTheme.light, routerConfig: ref.watch(routerProvider)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'private A search');
    c.read(routerProvider).go('/en-US/sessions');
    await tester.pumpAndSettle();
    expect(currentLng, 'en-US');
    expect(tester.takeException(), isNull);
    (c.read(authProvider.notifier) as AuditAuth).switchUser('B');
    await tester.pumpAndSettle();
    c.read(routerProvider).go('/zh-TW/sessions');
    await tester.pumpAndSettle();
    expect(tester.widget<EditableText>(find.byType(EditableText)).controller.text, isEmpty);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    c.dispose();
  });

  testWidgets('calendar uses one aggregate and one day page; totals exceed 1000', (tester) async {
    final today = DateTime(2026, 10, 3);
    installApiStub((r) {
      if (r.path == '/dashboard/calendar') {
        return [
          {
            'day_index': 2,
            'total': 1001,
            'completed': 1001,
            'red_flags': 0,
            'busy_seconds': 60060,
            'duration_count': 1001,
          },
        ];
      }
      if (r.path == '/sessions') {
        final more = r.queryParameters['cursor'] != null;
        return {
          'data': List.generate(
            more ? 1 : 20,
            (i) => {
              'id': 'day-${more ? 20 : i}',
              'patient_name': 'Calendar ${more ? 20 : i}',
              'status': 'completed',
              'created_at': today.toIso8601String(),
            },
          ),
          'pagination': {'has_more': !more, 'next_cursor': more ? null : 'next-day-page', 'total_count': 1001},
        };
      }
      return {'count': 0};
    });
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AppTheme.light,
          home: Scaffold(body: SessionCalendarView(today: today)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(sentRequests.where((r) => r.path == '/dashboard/calendar').length, 1);
    expect(sentRequests.where((r) => r.path == '/sessions').length, 1);
    expect(find.text('1001'), findsWidgets);
    final calendar = sentRequests.firstWhere((r) => r.path == '/dashboard/calendar');
    final boundaries = calendar.queryParameters['day_starts'] as List;
    expect(boundaries.length, 32);
    expect(DateTime.parse(boundaries.first), DateTime(2026, 10, 1).toUtc());
    for (var i = 0; i < 15 && find.text(t('common.pagination.loadMore')).hitTestable().evaluate().isEmpty; i++) {
      await tester.drag(find.byType(ListView), const Offset(0, -500));
      await tester.pumpAndSettle();
    }
    await tester.tap(find.text(t('common.pagination.loadMore')));
    await tester.pumpAndSettle();
    expect(sentRequests.where((r) => r.path == '/sessions').length, 2);
    expect(find.text('Calendar 20'), findsOneWidget);
    tester.state<ScrollableState>(find.byType(Scrollable).first).position.jumpTo(0);
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip(t('session.doctor.calendar.nextMonth')));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip(t('session.doctor.calendar.previousMonth')));
    await tester.pumpAndSettle();
    expect(
      sentRequests.where((r) => r.path == '/dashboard/calendar').length,
      2,
      reason: 'Returning to a fresh cached month needs no new aggregate',
    );

    expect(tester.takeException(), isNull);
  });

  for (final kind in ['patients', 'reports', 'alerts']) {
    testWidgets('$kind builds visible rows from a 1000 row data set', (tester) async {
      final now = DateTime.now().toIso8601String();
      installApiStub((r) {
        if (r.path.endsWith('count')) return {'count': 1000};
        if (r.path.startsWith('/sessions/')) {
          return {'id': r.path.split('/').last, 'patient_name': 'Synthetic', 'status': 'completed'};
        }
        return {
          'data': List.generate(
            1000,
            (i) => {
              'id': 'row-$i',
              'session_id': 's$i',
              'name': 'Patient $i',
              'patient_name': 'Patient $i',
              'chief_complaint_text': 'Synthetic',
              'title': 'Alert $i',
              'severity': 'medium',
              'status': 'generated',
              'review_status': 'pending',
              'session_status': 'completed',
              'session_red_flag': false,
              'created_at': now,
            },
          ),
          'review_counts': {'pending': 1000},
          'pagination': {'has_more': false, 'total_count': 1000},
        };
      });
      final widget = switch (kind) {
        'patients' => const PatientListPage(),
        'reports' => const ReportListPage(),
        _ => const AlertListPage(),
      };
      await tester.pumpWidget(
        ProviderScope(
          overrides: [dashboardWsProvider.overrideWithValue(AuditSocket())],
          child: MaterialApp(theme: AppTheme.light, home: widget),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(Card).evaluate().length, lessThan(30));
      expect(find.byType(ListView), findsWidgets);
      await tester.drag(find.byType(ListView).last, const Offset(0, -1000));
      await tester.pumpAndSettle();
      expect(find.byType(Card).evaluate().length, lessThan(30));
      expect(tester.takeException(), isNull);
      if (kind == 'reports') expect(sentRequests.where((r) => r.path == '/reports').length, 1);
    });
  }
  test('events during a pending request produce one follow-up', () async {
    var calls = 0;
    final gate = Completer<Object?>();
    installApiStub((r) => ++calls == 2 ? gate.future : {'data': []});
    final ws = AuditSocket();
    final c = ProviderContainer(overrides: [dashboardWsProvider.overrideWithValue(ws)]);
    c.listen(sessionsListProvider, (_, _) {});
    await pumpEventQueue();
    final pending = c.read(sessionsListProvider.notifier).reload();
    await pumpEventQueue();
    for (final event in ['session_created', 'queue_updated', 'report_generated']) {
      ws.emit(event);
    }
    await Future<void>.delayed(const Duration(milliseconds: 150));
    expect(calls, 2);
    gate.complete({'data': []});
    await pending;
    await pumpEventQueue();
    expect(calls, 3);
    c.dispose();
  });
}
