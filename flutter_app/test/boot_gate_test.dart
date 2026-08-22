import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/app.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/app_router.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';

// `main()` no longer awaits bootstrap() before runApp(), so `booted` is what decides
// whether the app shows the boot screen or the router. The load-bearing half of that is
// negative and therefore easy to regress silently: while boot is unresolved the router
// must NOT be constructed. If it is, go_router builds the matched route immediately —
// a deep-linked doctor page would fire its API calls before TokenStore.load() has put a
// token on the Dio client, take a 401, and race bootstrap's own getMe() through the
// refresh-once interceptor. Nothing about that shows up as a test failure elsewhere; it
// shows up as a tester being logged out on launch.
//
// `routerProvider` is overridden to throw, so "was the router built" is an assertion
// rather than something inferred from the rendered tree.
class _FixedAuth extends AuthNotifier {
  _FixedAuth(this._initial);

  final AuthState _initial;
  int bootstrapCalls = 0;

  @override
  AuthState build() => _initial;

  @override
  Future<void> bootstrap() async => bootstrapCalls++;

  @override
  Future<void> retryBootstrap() async => bootstrapCalls++;
}

Future<void> _pumpApp(WidgetTester tester, AuthState state, {_FixedAuth? notifier}) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        authProvider.overrideWith(() => notifier ?? _FixedAuth(state)),
        routerProvider.overrideWith(
          (ref) => throw StateError('routerProvider built while booted=false'),
        ),
      ],
      child: const App(),
    ),
  );
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() async {
    // AuthApi captures ApiClient.instance.dio in a field initialiser, so the client has
    // to exist before an AuthNotifier is constructed. No request is ever sent here.
    ApiClient.instance.init();
    await Locales.loadAll();
  });

  testWidgets('boot 未完成時不建 router，畫面是開機頁', (tester) async {
    await _pumpApp(tester, const AuthState(booted: false));

    // 沒有拋 StateError ＝ routerProvider 沒被讀到。
    expect(tester.takeException(), isNull);
    expect(find.text(zhAppTitle), findsOneWidget);
  });

  testWidgets('開機頁前 450ms 不顯示 spinner（快的開機不該閃一下）', (tester) async {
    await _pumpApp(tester, const AuthState(booted: false));

    final opacityAt0 = tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity)).opacity;
    expect(opacityAt0, 0, reason: '第一幀就轉圈＝多數情況只會閃一下');

    await tester.pump(const Duration(milliseconds: 500));
    final opacityAfter = tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity)).opacity;
    expect(opacityAfter, 1, reason: '真的在等的時候必須給回饋');
    // 不用 pumpAndSettle：CircularProgressIndicator 是無限動畫，settle 永遠等不到。
  });

  testWidgets('boot 因網路失敗時給重試，不是把人丟回登入頁', (tester) async {
    final auth = _FixedAuth(const AuthState(booted: true, bootOffline: true));
    // booted=true 但 bootOffline=true 仍走 BootGate（App 兩個條件都看），router 不該被建。
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authProvider.overrideWith(() => auth),
          routerProvider.overrideWith((ref) => throw StateError('router built')),
        ],
        child: const App(),
      ),
    );
    await tester.pump();

    final retry = find.byType(FilledButton);
    expect(retry, findsOneWidget);

    await tester.tap(retry);
    await tester.pump();
    expect(auth.bootstrapCalls, 1, reason: '重試要真的重跑 bootstrap');
  });

  testWidgets('重試畫面有出口：網路救不回來時仍能離開', (tester) async {
    // 沒有這個出口，「有存著的 token ＋ 連不上後端」就是死路——登入頁在 router
    // 後面，router 在 boot 後面。這條測的是那個死路不存在。
    await _pumpApp(tester, const AuthState(booted: true, bootOffline: true));
    expect(find.byType(TextButton), findsOneWidget);
  });
}

// 直接讀 zh-TW 的 appTitle，避免測試自己重抄一份文案。
final zhAppTitle = ((Locales.forLng('zh-TW')!['common'] as Map)['appTitle']) as String;
