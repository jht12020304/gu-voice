// G35b：切語言前「要不要先收掉場次」的守衛。判斷錯哪一邊都有代價：
//   - 漏判（問診中卻直接切）→ 後端留下孤兒 in_progress 場次，仍用舊語言在跑
//   - 誤判（不在問診頁卻擋）→ 一般頁面切語言被莫名其妙的確認框攔住
// 另外驗確認框/錯誤訊息 5 語系齊備 —— 少一個語言，病患看到的就是 key 本身。

import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/shared/widgets/language_action.dart';

void main() {
  group('conversationSessionIdInPath', () {
    test('回傳問診場次 id，五種語言前綴都認得', () {
      for (final lng in supportedLanguages) {
        expect(conversationSessionIdInPath('/$lng/conversation/abc-123'), 'abc-123',
            reason: '$lng 的問診頁沒被認出來 → 切語言會留下孤兒場次');
      }
    });

    test('沒有 lng 前綴也認得（路由 redirect 補前綴前的短暫狀態）', () {
      expect(conversationSessionIdInPath('/conversation/abc-123'), 'abc-123');
    });

    test('尾端斜線不影響', () {
      expect(conversationSessionIdInPath('/zh-TW/conversation/abc-123/'), 'abc-123');
    });

    test('非問診頁一律 null', () {
      for (final path in [
        '/zh-TW',
        '/zh-TW/',
        '/zh-TW/patient',
        '/zh-TW/patient/start',
        '/zh-TW/patient/history/abc-123',
        '/zh-TW/patient/session/abc-123/complete',
        '/zh-TW/dashboard',
      ]) {
        expect(conversationSessionIdInPath(path), isNull, reason: '$path 不該被當成進行中的問診');
      }
    });

    test('只是字串裡有 conversation 的路徑不算（避免 contains 誤判）', () {
      expect(conversationSessionIdInPath('/zh-TW/patient/conversations-archive'), isNull);
      expect(conversationSessionIdInPath('/zh-TW/conversations'), isNull);
    });

    test('沒有 session id 就沒有東西可收，回 null 而不是空字串', () {
      expect(conversationSessionIdInPath('/zh-TW/conversation'), isNull);
      expect(conversationSessionIdInPath('/zh-TW/conversation/'), isNull);
    });

    test('多餘的路徑段不算（路由表沒有這種 route）', () {
      expect(conversationSessionIdInPath('/zh-TW/conversation/abc-123/extra'), isNull);
    });
  });

  group('切語言確認框文案', () {
    setUpAll(() async {
      TestWidgetsFlutterBinding.ensureInitialized();
      await Locales.loadAll();
    });

    // 直接查該語言自己的 JSON，不經過 t() —— t() 有 fallback chain，
    // ja/ko/vi 缺 key 也會回英文而讓測試假通過。
    Object? read(String lng, List<String> path) {
      dynamic node = Locales.forLng(lng)?['common'];
      for (final seg in path) {
        if (node is! Map || !node.containsKey(seg)) return null;
        node = node[seg];
      }
      return node;
    }

    test('五語系都有自己的 switchModal 文案', () {
      const keys = [
        'title',
        'description',
        'confirm',
        'cancel',
        'switching',
        'switchedEnded',
        'switchFailed',
      ];
      for (final lng in supportedLanguages) {
        for (final key in keys) {
          final value = read(lng, ['language', 'switchModal', key]);
          expect(value, isA<String>(), reason: '$lng 缺 language.switchModal.$key');
          expect((value as String).trim(), isNotEmpty, reason: '$lng 的 $key 是空字串');
        }
      }
    });

    test('description 保留 {{from}} / {{to}} 佔位符', () {
      for (final lng in supportedLanguages) {
        final desc = read(lng, ['language', 'switchModal', 'description']) as String;
        expect(desc, contains('{{from}}'), reason: '$lng 的說明沒告訴病患目前是哪個語言');
        expect(desc, contains('{{to}}'), reason: '$lng 的說明沒告訴病患要切到哪個語言');
      }
    });

    test('switchedEnded 保留 {{name}} 佔位符', () {
      for (final lng in supportedLanguages) {
        expect(read(lng, ['language', 'switchModal', 'switchedEnded']), contains('{{name}}'));
      }
    });

    test('文案不得出現含糊的「盡速就醫」（部署情境是院內候診 kiosk）', () {
      // 不變式 #11：病患已在現場，措辭要導向「告知現場醫護 / 稍候等看診」。
      const banned = ['盡速就醫', '尽速就医', '儘速就醫'];
      for (final lng in supportedLanguages) {
        for (final key in ['title', 'description', 'switchedEnded', 'switchFailed']) {
          final value = read(lng, ['language', 'switchModal', key]) as String;
          for (final phrase in banned) {
            expect(value.contains(phrase), isFalse, reason: '$lng.$key 用了被禁止的措辭「$phrase」');
          }
        }
      }
    });
  });
}
