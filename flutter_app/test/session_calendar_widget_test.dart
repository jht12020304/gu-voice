// 日曆檢視的互動守衛：點日期 → 換成那天的問診（含時間管理那半）。
//
// 純函式的規則在 session_calendar_test.dart；這一支釘的是**接線**：分桶結果有沒有
// 真的接到畫面上、點格子會不會換天、空檔標記有沒有出現、沒問診的日子會不會退回
// 空狀態。資料由 `fetchMonth` 注入，不打網路。

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/data/models/session.dart';
import 'package:gu_voice/features/doctor/screens/session_calendar_view.dart';

Session _s({
  required DateTime created,
  DateTime? completed,
  int? duration,
  String status = 'completed',
  bool redFlag = false,
  required String name,
}) =>
    Session(
      id: 'id-${created.microsecondsSinceEpoch}',
      status: status,
      language: 'zh-TW',
      redFlag: redFlag,
      patientName: name,
      chiefComplaintText: '主訴 $name',
      createdAt: created.toIso8601String(),
      startedAt: created.toIso8601String(),
      completedAt: completed?.toIso8601String(),
      durationSeconds: duration,
    );

final _today = DateTime(2026, 8, 23);

final _sessions = <Session>[
  // 8/23（預設選中的那天）：兩場已完成 + 一場進行中
  _s(created: DateTime(2026, 8, 23, 9, 5), completed: DateTime(2026, 8, 23, 9, 21), duration: 960, name: '王小明'),
  _s(created: DateTime(2026, 8, 23, 9, 48), completed: DateTime(2026, 8, 23, 10, 2), duration: 840, name: '陳美玲'),
  _s(created: DateTime(2026, 8, 23, 14, 10), status: 'in_progress', name: '張淑芬'),
  // 8/19：另一天，用來驗「點下去就換那天」
  _s(created: DateTime(2026, 8, 19, 9, 0), completed: DateTime(2026, 8, 19, 9, 12), duration: 720, name: '林志豪', redFlag: true),
];

Future<void> _pump(WidgetTester tester, {List<Session>? sessions}) async {
  await tester.pumpWidget(ProviderScope(
    child: MaterialApp(
      theme: AppTheme.light,
      home: Scaffold(
        body: SessionCalendarView(
          today: _today,
          fetchMonth: (_) async => sessions ?? _sessions,
        ),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    await Locales.loadAll();
  });

  testWidgets('預設落在今天，列出當天的問診', (tester) async {
    await _pump(tester);
    expect(find.text('王小明'), findsOneWidget);
    expect(find.text('陳美玲'), findsOneWidget);
    expect(find.text('張淑芬'), findsOneWidget);
    // 別天的病患不該出現
    expect(find.text('林志豪'), findsNothing);
  });

  testWidgets('點另一個日期 → 換成那天的問診', (tester) async {
    await _pump(tester);
    // 日曆格子上的「19」
    await tester.tap(find.text('19').first);
    await tester.pumpAndSettle();
    expect(find.text('林志豪'), findsOneWidget);
    expect(find.text('王小明'), findsNothing,
        reason: '換日之後上一天的場次還留在畫面上＝日曆沒有真的切換');
  });

  testWidgets('沒問診的日子退回空狀態，不是留著上一天的清單', (tester) async {
    await _pump(tester);
    await tester.tap(find.text('20').first); // 8/20 沒有任何場次
    await tester.pumpAndSettle();
    expect(find.text(t('session.doctor.calendar.emptyDayTitle')), findsOneWidget);
    expect(find.text('王小明'), findsNothing);
  });

  testWidgets('時間管理：空檔標在兩場之間（09:21 → 09:48 ＝ 27 分）', (tester) async {
    await _pump(tester);
    expect(
      find.text(t('session.doctor.calendar.gap', args: {'minutes': 27})),
      findsOneWidget,
    );
  });

  testWidgets('時間管理：當天總時長與平均（進行中那場不算進平均）', (tester) async {
    await _pump(tester);
    // 960 + 840 = 1800 秒 = 30 分；平均 = 900 秒 = 15 分
    expect(find.text(t('session.doctor.calendar.minutesShort', args: {'minutes': 30})),
        findsWidgets);
    expect(find.text(t('session.doctor.calendar.minutesShort', args: {'minutes': 15})),
        findsWidgets);
  });

  testWidgets('一整個月都沒問診也不會壞', (tester) async {
    await _pump(tester, sessions: const []);
    expect(find.text(t('session.doctor.calendar.emptyDayTitle')), findsOneWidget);
  });
}
