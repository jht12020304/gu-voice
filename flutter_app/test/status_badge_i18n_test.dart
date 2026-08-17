// StatusBadge 的 i18n 迴歸守衛。
//
// 背景：徽章的 label key 曾經少了 `common.` namespace 前綴（寫成
// `patient.home.statusXxx`）。lib/core/i18n/loc.dart 的 t() 拿 key 的第一個 dot 段落
// 當 namespace，而 lib/core/router/lng.dart 的 allNamespaces 裡沒有 `patient`，所以
// 查不到就照 t() 的設計回傳 key 本身 —— 病患首頁／醫師場次列表／場次詳情 AppBar 的
// 徽章，全五語系、每一種狀態都直接印出 `patient.home.statusAbortedRedFlag` 這種字串。
// analyze 與型別都不會抓到（key 是普通字串），只有渲染出來才看得見，所以釘在這裡。

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/shared/widgets/status_badge.dart';

const _statuses = ['completed', 'in_progress', 'waiting', 'aborted_red_flag', 'cancelled'];

/// status -> common.json 裡對應的 key 尾段（`patient.home.<suffix>`）。
const _suffix = {
  'completed': 'statusCompleted',
  'in_progress': 'statusInProgress',
  'waiting': 'statusWaiting',
  'aborted_red_flag': 'statusAbortedRedFlag',
  'cancelled': 'statusCancelled',
};

void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    await Locales.loadAll();
  });

  // t() 讀全域 currentLng（URL 是唯一權威），測完復原避免污染其他測試。
  tearDown(() => setCurrentLng(defaultLanguage));

  Future<void> pumpBadge(WidgetTester tester, String status) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(body: Center(child: StatusBadge(status))),
      ),
    );
    await tester.pump();
  }

  testWidgets('五語 × 每種狀態都渲染翻譯文字，而不是原始 i18n key', (tester) async {
    for (final lng in supportedLanguages) {
      setCurrentLng(lng);
      for (final status in _statuses) {
        await pumpBadge(tester, status);

        // 直接查該語言自己的 JSON（不經 t()）：t() 有 fallback chain，
        // 若哪天 key 從 common.json 消失，只比對 t() 會兩邊一起壞掉而假通過。
        final home = (Locales.forLng(lng)!['common'] as Map)['patient']['home'] as Map;
        final expected = home[_suffix[status]] as String;

        expect(find.text(expected), findsOneWidget,
            reason: '$lng / $status 的徽章沒有顯示翻譯文字「$expected」');

        final rawKey = find.byWidgetPredicate(
          (w) => w is Text && (w.data ?? '').contains('.status'),
        );
        expect(rawKey, findsNothing,
            reason: '$lng / $status 的徽章印出了原始 i18n key '
                '—— common. namespace 前綴又掉了');
      }
    }
  });

  testWidgets('未知狀態退回 completed 的翻譯文字，不是 raw key', (tester) async {
    await pumpBadge(tester, 'some_status_from_a_newer_backend');
    expect(find.text(t('common.patient.home.statusCompleted')), findsOneWidget,
        reason: '未知狀態的 fallback label 也必須是翻譯文字（web fallback 對齊）');
  });
}
