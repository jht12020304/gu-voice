// The "generate report" gate (TODO §G medium). The old rule keyed off mere existence of
// a report row, so a FAILED generation could never be retried — the button disappeared
// and the doctor had no way to get a report for that consultation at all.
//
// SO-2（2026-08 稽核）補上第二半：閘門放行之後，請求本身也要能過。後端
// `report_service.generate_report` 在該場次**已有 report row** 而請求沒帶 `regenerate`
// 時直接丟 409 ReportAlreadyExists；row 在第一次派工時就建好了，所以「failed 後重試」
// 按下去只會拿到 409——閘門開了、路還是斷的。修法是 generateReport 一律帶
// `{"regenerate": true}`，並在醫師的 SOAP 報告頁補上重新產生入口。

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/data/api/reports_api.dart';
import 'package:gu_voice/features/doctor/screens/session_detail_page.dart';
import 'package:gu_voice/features/doctor/screens/soap_report_page.dart';

import 'support/api_stub.dart';

const _sessionId = 'sess-1';
const _reportId = 'rep-1';

/// 醫師端的報告頁需要 report / session / 逐字稿三支 API。
void _installStub(String reportStatus) {
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
    if (path == '/reports/$_reportId') {
      return {
        'id': _reportId,
        'session_id': _sessionId,
        'status': reportStatus,
        'review_status': 'pending',
        'summary': 'summary',
      };
    }
    if (path == '/sessions/$_sessionId') {
      return {
        'id': _sessionId,
        'status': 'completed',
        'language': 'zh-TW',
        'red_flag': false,
      };
    }
    if (path == '/sessions/$_sessionId/conversations') return [];
    // 重新產生：後端把現有 row 重置為 generating 後回傳它。
    if (path == '/sessions/$_sessionId/reports/generate') {
      return {
        'id': _reportId,
        'session_id': _sessionId,
        'status': 'generating',
        'review_status': 'pending',
      };
    }
    return null;
  });
}

Future<void> _pumpReportPage(WidgetTester tester, String reportStatus) async {
  _installStub(reportStatus);
  await tester.pumpWidget(MaterialApp(
    theme: AppTheme.light,
    home: const SoapReportPage(sessionId: _sessionId),
  ));
  await tester.pumpAndSettle();
}

void main() {
  bool can(String session, String? report) =>
      canGenerateSoapReport(sessionStatus: session, reportStatus: report);

  group('canGenerateSoapReport', () {
    test('offered for a completed session with no report yet', () {
      expect(can('completed', null), isTrue);
    });

    test('offered again after a FAILED generation — this was the dead end', () {
      expect(can('completed', 'failed'), isTrue);
    });

    test('not offered while generating (avoid double-dispatching the Celery task)', () {
      expect(can('completed', 'generating'), isFalse);
    });

    test('not offered once generated', () {
      expect(can('completed', 'generated'), isFalse);
    });

    test('never offered for a non-terminal or aborted session', () {
      for (final st in ['waiting', 'in_progress', 'cancelled', 'aborted_red_flag']) {
        expect(can(st, null), isFalse, reason: '$st 不該能產生報告');
      }
    });
  });

  group('canRegenerateSoapReport（醫師報告頁的重新產生）', () {
    test('已產生的報告可以重跑——這是醫師修正壞報告的唯一入口', () {
      expect(canRegenerateSoapReport('generated'), isTrue);
    });

    test('失敗的報告可以重跑', () {
      expect(canRegenerateSoapReport('failed'), isTrue);
    });

    test('產生中不可重跑（重複派 Celery 任務會讓兩份結果互相覆蓋）', () {
      expect(canRegenerateSoapReport('generating'), isFalse);
    });

    test('沒有報告時這頁根本不會出現，也不放行', () {
      expect(canRegenerateSoapReport(null), isFalse);
    });
  });

  group('generateReport 的請求本身', () {
    test('一律帶 regenerate=true——否則已有 report row 時後端回 409，重試永遠失敗', () async {
      installApiStub((options) => {
            'id': _reportId,
            'session_id': _sessionId,
            'status': 'generating',
            'review_status': 'pending',
          });
      final report = await ReportsApi().generateReport(_sessionId);

      expect(sentRequests, hasLength(1));
      expect(sentRequests.single.method, 'POST');
      expect(sentRequests.single.path, '/sessions/$_sessionId/reports/generate');
      // interceptor 會把 body 轉 snake_case；`regenerate` 沒有大小寫邊界，原樣送出。
      expect(sentRequests.single.data, {'regenerate': true});
      // 後端回傳的是被重置成 generating 的那一列，呼叫端直接吃它。
      expect(report.status, 'generating');
    });
  });

  group('widget：醫師 SOAP 報告頁的重新產生按鈕', () {
    setUpAll(() async {
      TestWidgetsFlutterBinding.ensureInitialized();
      await Locales.loadAll();
      setCurrentLng('zh-TW');
    });

    Future<IconButton> button(WidgetTester tester) async =>
        tester.widget<IconButton>(find.ancestor(
          of: find.byIcon(Icons.refresh),
          matching: find.byType(IconButton),
        ));

    testWidgets('generated → 可按', (tester) async {
      await _pumpReportPage(tester, 'generated');
      expect((await button(tester)).onPressed, isNotNull);
    });

    testWidgets('failed → 可按（這頁是失敗報告的重跑入口）', (tester) async {
      await _pumpReportPage(tester, 'failed');
      expect((await button(tester)).onPressed, isNotNull);
    });

    testWidgets('generating → disabled 而不是消失（按鈕不見等同「沒反應」）', (tester) async {
      await _pumpReportPage(tester, 'generating');
      expect(find.byIcon(Icons.refresh), findsOneWidget, reason: '按鈕不該直接消失');
      expect((await button(tester)).onPressed, isNull);
    });

    testWidgets('按下去先跳確認對話框，取消則不送出任何請求', (tester) async {
      await _pumpReportPage(tester, 'generated');
      final before = sentRequests.length;

      await tester.tap(find.byIcon(Icons.refresh));
      await tester.pumpAndSettle();
      expect(find.text(t('soap.regenerate.title')), findsOneWidget);
      expect(find.text(t('soap.regenerate.description')), findsOneWidget);

      await tester.tap(find.text(t('soap.regenerate.cancel')));
      await tester.pumpAndSettle();
      expect(sentRequests.length, before, reason: '取消卻仍派了 Celery 任務');
    });

    testWidgets('確認後送出 regenerate 請求，狀態轉 generating 並讓按鈕 disabled', (tester) async {
      await _pumpReportPage(tester, 'generated');

      await tester.tap(find.byIcon(Icons.refresh));
      await tester.pumpAndSettle();
      await tester.tap(find.text(t('soap.regenerate.confirm')));
      await tester.pumpAndSettle();

      final post = sentRequests.where((r) => r.method == 'POST').toList();
      expect(post, hasLength(1), reason: '沒送出（或重複送出）重新產生請求');
      expect(post.single.path, '/sessions/$_sessionId/reports/generate');
      expect(post.single.data, {'regenerate': true});
      expect(find.text(t('soap.regenerate.success')), findsOneWidget);
      expect((await button(tester)).onPressed, isNull, reason: '重跑期間仍可再按一次');
    });
  });
}
