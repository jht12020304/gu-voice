// 五語系 deep link：以 /{lng}/ 前綴進入登入頁，驗證頁面渲染且關鍵文字確實是那個語言。
//
// 鐵律（見 flutter_app/README.md 與 CLAUDE.md）：URL 是語言唯一權威；`t()` 讀全域
// `currentLng`、不是 reactive 的；新路由要包 `_lngKeyed()`，否則只切語言頁面文字不會變。
// 這支就是在驗這條鐵律有沒有被遵守——如果某語言切過去、畫面文字還是上一個語言，這裡會
// 直接判定為缺陷（不是「web 限制」，是產品邏輯真的漏做）。
//
// 不需要真後端：登入頁在未登入狀態下就看得到，五語都走同一個 App 實例、用同一支
// GoRouter 依序 `.go('/$lng/login')`，比逐語言重開瀏覽器更貼近「使用者在同一個分頁
// 內切語言」的實際場景，也比較快。
//
// 跑法：
//
//   flutter drive --driver=test_driver/integration_test.dart \
//     --target=integration_test/lng_deep_link_test.dart \
//     -d web-server --web-port=5175 --browser-name=chrome \
//     --web-browser-flag=--use-fake-ui-for-media-stream \
//     --web-browser-flag=--use-fake-device-for-media-stream \
//     --dart-define=API_BASE=http://127.0.0.1:8000/api/v1 \
//     --dart-define=WS_BASE=ws://127.0.0.1:8000/api/v1/ws

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:gu_voice/app.dart';
import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/app_router.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/auth/login_page.dart';
import 'package:gu_voice/shared/widgets/language_bar.dart';

// CJK 範圍：中文（含日文漢字共用區）+ 日文假名 + 韓文諺文音節。用來抓 en-US 頁面上
// 「忘了翻、fallback 回中文」的殘留字元。
final _cjk = RegExp(r'[㐀-鿿豈-﫿぀-ヿ가-힣]');

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('login page renders correctly-localized text for all 5 languages via /{lng}/ deep link',
      (tester) async {
    ApiClient.instance.init();
    await Locales.loadAll();
    await TokenStore.instance.clear();

    final container = ProviderContainer();
    addTearDown(container.dispose);
    ApiClient.instance.onAuthCleared = () => container.read(authProvider.notifier).forceLoggedOut();
    await container.read(authProvider.notifier).bootstrap();

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const App()),
    );
    await tester.pumpAndSettle();

    expect(find.byType(LoginPage), findsOneWidget, reason: '未登入時應該先落在登入頁');

    final router = container.read(routerProvider);
    String? lastLng;
    String? lastPrompt;

    for (final lng in supportedLanguages) {
      router.go('/$lng/login');
      await tester.pumpAndSettle();

      expect(currentLng, lng,
          reason: 'go 到 /$lng/login 之後，全域 currentLng 應該同步成 $lng（URL 是語言唯一權威，見 lng.dart）');
      expect(find.byType(LoginPage), findsOneWidget, reason: '/$lng/login 沒有落在登入頁');

      final expectedPrompt = t('common.login.prompt', lng: lng);
      final expectedEmailLabel = t('common.login.emailLabel', lng: lng);
      final expectedSubmit = t('common.login.submit', lng: lng);

      // 先確認這語言的期望字串本身跟上一輪不同（否則下面「沒變=缺陷」的比對沒有意義——
      // 五語系 common.login.* 目前彼此都不同，若哪天巧合撞字，這個前提檢查會先爆炸提醒）。
      if (lastLng != null) {
        expect(expectedPrompt, isNot(equals(lastPrompt)),
            reason: '$lastLng 與 $lng 的 common.login.prompt 翻譯字串一模一樣，'
                '下面「切語言後文字沒變=缺陷」的比對邏輯會失去意義，請檢查翻譯檔');
      }

      expect(find.text(expectedPrompt), findsOneWidget,
          reason: '$lng 的登入頁沒有顯示該語言的提示文字「$expectedPrompt」');
      expect(find.text(expectedEmailLabel), findsWidgets,
          reason: '$lng 的登入頁 email 欄位標籤沒有變成「$expectedEmailLabel」');
      expect(find.text(expectedSubmit), findsWidgets,
          reason: '$lng 的登入頁送出按鈕文字沒有變成「$expectedSubmit」');

      // 鐵律回歸：切到新語言後，上一個語言的文字不該還留在畫面上。
      if (lastPrompt != null) {
        expect(find.text(lastPrompt), findsNothing,
            reason: '切到 $lng 之後，上一個語言（$lastLng）的提示文字「$lastPrompt」還留在畫面上——'
                '代表頁面沒有隨 URL 語言重新渲染，這是真缺陷，不是 web 測試限制'
                '（見 CLAUDE.md「flutter_app 新增路由要用 _lngKeyed() 包住」鐵律）');
      }

      // en-US 頁面上不該出現任何 CJK 字元（沒翻、或翻譯 fallback 鏈掉回中文都會露餡）。
      // 排除 LanguageBar：語言選單本來就會用「該語言自己的名字」標示選項（例如 en-US
      // 頁面上仍會看到「繁體中文」「日本語」這些原生語言名稱），這是設計行為，不是缺陷。
      if (lng == 'en-US') {
        final allTextElements = find.byType(Text).evaluate().toSet();
        final languageBarTextElements =
            find.descendant(of: find.byType(LanguageBar), matching: find.byType(Text)).evaluate().toSet();
        final outside = allTextElements.difference(languageBarTextElements);
        final allTexts = outside.map((e) => (e.widget as Text).data ?? '').join('\n');
        final hits = _cjk.allMatches(allTexts).map((m) => m.group(0)).toSet();
        expect(hits, isEmpty,
            reason: 'en-US 登入頁（排除語言選單本身）出現 CJK 字元 $hits，'
                '可能有字串沒翻或 fallback 掉回中文：\n$allTexts');
      }

      lastLng = lng;
      lastPrompt = expectedPrompt;
    }
  }, timeout: const Timeout(Duration(minutes: 2)));
}
