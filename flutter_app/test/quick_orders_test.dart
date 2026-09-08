// 快速開單頁（2026-09-09）：醫師點「SOAP 報告已生成」推播 → 看摘要 → 勾選 AI 建議
// 檢查 → 確認送出。
//
// 這頁的風險全都在「勾了什麼、送出去的就是什麼」這條線上，所以測試從 Dio adapter
// 注入後端原樣的 snake_case JSON，讓 camelCase interceptor 一起走過一遍，最後直接對
// **真正送出的 request body** 斷言。守四件事：
//
//  1. 預設一項都不勾——預先勾好等於把 AI 建議變成預設醫囑。
//  2. 空的送出是合法的，且送出的是空陣列而不是「什麼都不送」。
//  3. 上一張單會回填勾選狀態；其中已不在 AI 清單的項目仍要列出（報告可被重新生成，
//     只畫現在的清單會讓醫師無聲地把上次開的項目取消掉）。
//  4. items 送出的是快照（名稱／緊急度／理由），不是只有名稱。

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/data/models/notification.dart';
import 'package:gu_voice/features/doctor/screens/quick_orders_page.dart';

import 'support/api_stub.dart';

const _sessionId = 'sess-1';
const _reportId = 'rep-1';

Map<String, Object?> _report({List<Object?>? tests}) => {
      'id': _reportId,
      'session_id': _sessionId,
      'status': 'generated',
      'review_status': 'pending',
      'summary': '病患主訴頻尿一週，無發燒。',
      'plan': {
        'recommended_tests': tests ??
            [
              {
                'test_name': '尿液常規',
                'urgency': 'routine',
                'rationale': '排除泌尿道感染',
              },
              {'test_name': '腎臟超音波', 'urgency': 'this_week'},
            ],
      },
    };

/// 這頁要三支：report（先 list 後 detail）、latest 醫囑、session（標題列，失敗不致命）。
void _installStub({Object? latestOrder, List<Object?>? tests}) {
  installApiStub((options) {
    final path = options.path;
    if (path == '/reports') {
      return {
        'data': [
          {'id': _reportId}
        ],
        'pagination': {'hasMore': false, 'totalCount': 1},
      };
    }
    if (path == '/reports/$_reportId') return _report(tests: tests);
    if (path == '/sessions/$_sessionId') {
      return {
        'id': _sessionId,
        'status': 'completed',
        'language': 'zh-TW',
        'patient_name': '王小明',
        'chief_complaint_text': '頻尿',
      };
    }
    if (path == '/sessions/$_sessionId/exam-orders/latest') return latestOrder;
    if (path == '/sessions/$_sessionId/exam-orders') {
      return {
        'id': 'order-new',
        'session_id': _sessionId,
        'report_id': _reportId,
        'ordered_by': 'doc-1',
        'items': [],
        'created_at': '2026-09-09T01:00:00Z',
      };
    }
    return null;
  });
}

Future<void> _pump(WidgetTester tester) async {
  await tester.pumpWidget(const MaterialApp(
    home: QuickOrdersPage(sessionId: _sessionId),
  ).withTheme());
  await tester.pumpAndSettle();
}

extension on MaterialApp {
  MaterialApp withTheme() => MaterialApp(theme: AppTheme.light, home: home);
}

/// 最後一次 POST 到 exam-orders 的 body。
Map _lastSubmittedBody() {
  final posts = sentRequests.where(
      (r) => r.method == 'POST' && r.path == '/sessions/$_sessionId/exam-orders');
  expect(posts, isNotEmpty, reason: '沒有送出任何檢查單');
  return posts.last.data as Map;
}

void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    await Locales.loadAll();
  });

  tearDown(() => setCurrentLng(defaultLanguage));

  group('推播落點', () {
    test('report_ready 導到快速開單頁，不是完整報告頁', () {
      final n = AppNotification(
        id: 'n-1',
        type: 'report_ready',
        title: '',
        createdAt: '',
        data: const {'sessionId': _sessionId, 'reportId': _reportId},
      );
      expect(n.route(), '/orders/$_sessionId');
    });

    test('session_complete 仍落在場次詳情（那時報告還沒生成）', () {
      final n = AppNotification(
        id: 'n-2',
        type: 'session_complete',
        title: '',
        createdAt: '',
        data: const {'sessionId': _sessionId},
      );
      expect(n.route(), '/sessions/$_sessionId');
    });
  });

  group('畫面', () {
    testWidgets('顯示摘要與 AI 建議檢查', (tester) async {
      _installStub();
      await _pump(tester);

      expect(find.text('病患主訴頻尿一週，無發燒。'), findsOneWidget);
      expect(find.text('尿液常規'), findsOneWidget);
      expect(find.text('腎臟超音波'), findsOneWidget);
      expect(find.text('排除泌尿道感染'), findsOneWidget);
    });

    testWidgets('預設一項都不勾——不得把 AI 建議變成預設醫囑', (tester) async {
      _installStub();
      await _pump(tester);

      final boxes = tester.widgetList<CheckboxListTile>(find.byType(CheckboxListTile));
      expect(boxes, hasLength(2));
      expect(boxes.every((b) => b.value == false), isTrue);
    });

    testWidgets('AI 沒建議任何檢查時仍可進來，並說明空送出的意義', (tester) async {
      _installStub(tests: const []);
      await _pump(tester);

      expect(find.text(t('soap.quickOrders.noTests')), findsOneWidget);
      expect(find.byType(CheckboxListTile), findsNothing);
      expect(find.byKey(const Key('exam-order-submit')), findsOneWidget);
    });
  });

  group('送出', () {
    testWidgets('只送出勾選的項目，且帶完整快照', (tester) async {
      _installStub();
      await _pump(tester);

      await tester.tap(find.byKey(const Key('exam-item-尿液常規')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('exam-order-submit')));
      await tester.pumpAndSettle();

      final body = _lastSubmittedBody();
      final items = body['items'] as List;
      expect(items, hasLength(1));
      expect(items.first['test_name'], '尿液常規');
      expect(items.first['urgency'], 'routine');
      expect(items.first['rationale'], '排除泌尿道感染');
      expect(body['report_id'], _reportId);
    });

    testWidgets('一項都沒勾也能送出，送的是空陣列（＝這次不開檢查）', (tester) async {
      _installStub();
      await _pump(tester);

      await tester.tap(find.byKey(const Key('exam-order-submit')));
      await tester.pumpAndSettle();

      expect(_lastSubmittedBody()['items'], isEmpty);
    });

    testWidgets('全選後送出兩項', (tester) async {
      _installStub();
      await _pump(tester);

      await tester.tap(find.text(t('soap.quickOrders.selectAll')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('exam-order-submit')));
      await tester.pumpAndSettle();

      final items = _lastSubmittedBody()['items'] as List;
      expect(items.map((i) => i['test_name']), ['尿液常規', '腎臟超音波']);
    });
  });

  group('已開立過的場次', () {
    Object latest() => {
          'id': 'order-1',
          'session_id': _sessionId,
          'report_id': _reportId,
          'ordered_by': 'doc-1',
          'items': [
            {'test_name': '尿液常規', 'urgency': 'routine', 'rationale': '排除泌尿道感染'},
            {'test_name': '尿液細菌培養', 'urgency': '24h'},
          ],
          'note': '先看培養結果',
          'created_at': '2026-09-09T01:00:00Z',
        };

    testWidgets('回填上次的勾選與備註', (tester) async {
      _installStub(latestOrder: latest());
      await _pump(tester);

      final byName = {
        for (final b in tester.widgetList<CheckboxListTile>(find.byType(CheckboxListTile)))
          ((b.key as ValueKey).value as String): b.value,
      };
      expect(byName['exam-item-尿液常規'], isTrue);
      expect(byName['exam-item-尿液細菌培養'], isTrue);
      expect(byName['exam-item-腎臟超音波'], isFalse);

      // 備註欄在建議檢查清單下方，長清單時不在首屏——先捲到它再讀 controller，
      // 否則 find.text 只是「沒 build 出來」而不是「沒回填」。
      final note = find.byKey(const Key('exam-order-note'));
      await tester.scrollUntilVisible(note, 200);
      expect(tester.widget<TextField>(note).controller?.text, '先看培養結果');
    });

    testWidgets('上次開過、AI 現在不再建議的項目仍要列出並標記', (tester) async {
      _installStub(latestOrder: latest());
      await _pump(tester);

      // 尿液細菌培養不在 recommended_tests 裡，但上次開過 → 必須看得到，
      // 否則醫師重送時會無聲地把它取消掉。
      expect(find.text('尿液細菌培養'), findsOneWidget);
      expect(find.text(t('soap.quickOrders.previouslyOrdered')), findsOneWidget);
    });

    testWidgets('可以取消上次的項目再送（以最新一次為準）', (tester) async {
      _installStub(latestOrder: latest());
      await _pump(tester);

      await tester.tap(find.byKey(const Key('exam-item-尿液細菌培養')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('exam-order-submit')));
      await tester.pumpAndSettle();

      final items = _lastSubmittedBody()['items'] as List;
      expect(items.map((i) => i['test_name']), ['尿液常規']);
    });
  });
}
