// 在真 simulator / 裝置上打**真後端**的登入冒煙測試。
//
// 為什麼需要這支：`test/` 底下的單元測試全是純函式，從來沒有任何測試驗證過
// 「這個 app 真的連得上後端」——dio 設定、iOS 上的 flutter_secure_storage
// token 寫入、bootstrap 流程、以及登入後的導向，全部只在人工目視下運作過。
//
// 跑法（後端位址一定要傳，預設是 localhost）：
//
//   flutter test integration_test/login_smoke_test.dart \
//     -d <simulator-udid> \
//     --dart-define=API_BASE=https://gu-voice-app-production.up.railway.app/api/v1 \
//     --dart-define=WS_BASE=wss://gu-voice-app-production.up.railway.app/api/v1/ws \
//     --dart-define=E2E_EMAIL=doctor@example.com \
//     --dart-define=E2E_PASSWORD=...
//
// ⚠️ 憑證只從 --dart-define 讀，**不寫進碼庫**；沒給就 skip，不會讓 CI 紅。
// ⚠️ 這支會對指定後端建立真實 session（登入的 audit log + refresh token），
//    別對生產無限重跑。

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:gu_voice/app.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

const _email = String.fromEnvironment('E2E_EMAIL');
const _password = String.fromEnvironment('E2E_PASSWORD');

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('login against the real backend lands on a role home', (tester) async {
    if (_email.isEmpty || _password.isEmpty) {
      markTestSkipped('未提供 E2E_EMAIL / E2E_PASSWORD --dart-define，跳過');
      return;
    }

    // 與 main() 同一條啟動路徑，但從乾淨 token 開始，避免沿用裝置上的舊 session。
    ApiClient.instance.init();
    await Locales.loadAll();
    await TokenStore.instance.clear();

    final container = ProviderContainer();
    addTearDown(container.dispose);
    ApiClient.instance.onAuthCleared =
        () => container.read(authProvider.notifier).forceLoggedOut();
    await container.read(authProvider.notifier).bootstrap();

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const App()),
    );
    await tester.pumpAndSettle();

    // 起點必須是登入頁（bootstrap 沒有殘留 session）
    final fields = find.byType(TextField);
    expect(fields, findsAtLeast(2), reason: '登入頁應有 email / password 兩個欄位');

    await tester.enterText(fields.at(0), _email);
    await tester.enterText(fields.at(1), _password);
    await tester.pumpAndSettle();

    await tester.tap(find.byType(FilledButton).first);

    // 真網路來回：pumpAndSettle 會在動畫停下就返回，所以額外給固定時間等 API。
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 500));
      if (container.read(authProvider).user != null) break;
    }
    await tester.pumpAndSettle();

    final auth = container.read(authProvider);
    expect(
      auth.user,
      isNotNull,
      reason: '登入沒成功——可能是後端位址錯（API_BASE 要含 /api/v1）、憑證錯，'
          '或 iOS 上 TokenStore 寫入失敗',
    );
    expect(auth.error, isNull, reason: '登入回了錯誤：${auth.error}');

    // token 真的落到 secure storage，不是只存在記憶體快取：
    // 先清掉 in-memory 欄位再 load()，逼它從 Keychain 讀回來。
    TokenStore.instance.accessToken = null;
    await TokenStore.instance.load();
    expect(
      TokenStore.instance.accessToken,
      isNotNull,
      reason: 'access token 沒真的寫進 secure storage（iOS Keychain）——'
          '重開 app 會直接被登出',
    );
    expect(
      await TokenStore.instance.readRefresh(),
      isNotNull,
      reason: 'refresh token 沒寫進 secure storage → access 過期後無法續期',
    );

    // 已離開登入頁 → 沒有密碼欄位了
    expect(
      find.byType(TextField),
      findsNothing,
      reason: '登入成功後仍停在登入頁',
    );
  }, timeout: const Timeout(Duration(minutes: 2)));
}
