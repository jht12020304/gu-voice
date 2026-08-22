import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';

// Boot no longer loads all 5 languages before the first frame — it loads the active one
// plus whatever `t()` can fall back through, and warms the rest after the first frame
// (see main.dart / locales_loader.dart). These tests pin the two things that silently
// break if that split is ever got wrong:
//   * boot loading LESS than the fallback chain → a beta-language user gets raw keys or
//     the wrong language on the first frame, then a visible re-render when the warm-up
//     lands. Invisible in dev, where everything is warm and local.
//   * `loadAll()` losing its all-5 contract → 20-odd existing tests assert on languages
//     it was the only thing loading.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(Locales.resetForTest);
  tearDownAll(() async {
    Locales.resetForTest();
    await Locales.loadAll();
  });

  group('loadForBoot 只載第一幀真的用得到的語言', () {
    test('zh-TW（預設語言、自己就是 fallback 終點）只載自己', () async {
      await Locales.loadForBoot('zh-TW');
      expect(Locales.isLoaded('zh-TW'), isTrue);
      for (final other in ['en-US', 'ja-JP', 'ko-KR', 'vi-VN']) {
        expect(Locales.isLoaded(other), isFalse, reason: '$other 不該在開機路徑上');
      }
    });

    test('en-US 載自己 ＋ zh-TW backstop', () async {
      await Locales.loadForBoot('en-US');
      expect(Locales.isLoaded('en-US'), isTrue);
      expect(Locales.isLoaded('zh-TW'), isTrue);
      expect(Locales.isLoaded('ja-JP'), isFalse);
    });

    test('beta 語言載滿整條 fallback 鏈（自己 → en-US → zh-TW）', () async {
      await Locales.loadForBoot('vi-VN');
      for (final needed in ['vi-VN', 'en-US', 'zh-TW']) {
        expect(Locales.isLoaded(needed), isTrue, reason: '$needed 在 vi-VN 的 fallback 鏈上');
      }
      expect(Locales.isLoaded('ja-JP'), isFalse);
      expect(Locales.isLoaded('ko-KR'), isFalse);
    });

    test('每個語言的開機鏈都涵蓋 t() 實際會走的解析順序', () async {
      // 這一條是上面三條的一般化：loadForBoot 少載一個語言，t() 就會在那個
      // 語言上落空。兩邊的鏈定義若各寫一份而漂開，正是這裡會抓到。
      for (final lng in supportedLanguages) {
        Locales.resetForTest();
        await Locales.loadForBoot(lng);
        final chain = <String>[lng, ...?fallbackChain[lng], defaultLanguage];
        for (final step in chain) {
          expect(Locales.isLoaded(step), isTrue, reason: '$lng 的 fallback 鏈缺 $step');
        }
      }
    });
  });

  group('其餘語言與既有契約', () {
    test('warmRemaining 把開機時跳過的補齊', () async {
      await Locales.loadForBoot('zh-TW');
      await Locales.warmRemaining();
      for (final lng in supportedLanguages) {
        expect(Locales.isLoaded(lng), isTrue);
      }
    });

    test('loadAll 仍然載滿五種（既有測試靠這個契約）', () async {
      await Locales.loadAll();
      for (final lng in supportedLanguages) {
        expect(Locales.forLng(lng), isNotNull);
      }
    });

    test('ensure 可重入：併發呼叫共用同一次載入，重複呼叫不重載', () async {
      await Future.wait([
        Locales.ensure('ko-KR'),
        Locales.ensure('ko-KR'),
        Locales.ensure('ko-KR'),
      ]);
      expect(Locales.isLoaded('ko-KR'), isTrue);
      await Locales.ensure('ko-KR'); // 已載入 → 同步 no-op，不得拋
    });
  });

  group('開機語言只載一種時 t() 仍然可用', () {
    test('只載 zh-TW 也解得出字串（不是原始 key）', () async {
      await Locales.loadForBoot('zh-TW');
      setCurrentLng('zh-TW');
      final title = t('common.appTitle');
      expect(title, isNot('common.appTitle'));
      expect(title, isNotEmpty);
    });

    test('未載入的語言退回 zh-TW，而不是吐出 key', () async {
      await Locales.loadForBoot('zh-TW'); // ja-JP 刻意沒載
      expect(t('common.appTitle', lng: 'ja-JP'), equals(t('common.appTitle', lng: 'zh-TW')));
    });
  });
}
