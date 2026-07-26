// 病患端完整問診流程，用**文字**取代語音（TODO §V2；§V1 只涵蓋一部分，見下）。
//
// 為什麼需要這支：`integration_test/` 先前只有登入與 kiosk 閒置登出，
// conversation 頁 → 對話 → SOAP → 感謝頁**整段從未跑過**。這支用 `text_message`
// 路徑走完全程，對真後端 + 真 OpenAI。
//
// ⚠️ **這支驗不到什麼**（別把它當成 V1 已完成）：
// 文字輸入繞過麥克風，所以 G3（onSpeechEnd 缺 hard-mute）、G14（pause 順序）、
// G15（onSpeechStart 硬鎖 re-assert）**仍然沒有被驗證**——那三條都是 VAD 段落行為。
// 有被順帶驗到的：WS 連線與 auth handshake、text_message 往返、AI 串流回應、
// TTS 實際播放（AI 回應的音訊不分輸入模式都會回來）、紅旗橫幅與中止導向、SOAP 生成。
//
// 跑法（對本機 e2e 後端，避免汙染生產）：
//
//   flutter test integration_test/patient_text_flow_test.dart \
//     -d <simulator-udid> \
//     --dart-define=API_BASE=http://127.0.0.1:8000/api/v1 \
//     --dart-define=WS_BASE=ws://127.0.0.1:8000/api/v1/ws \
//     --dart-define=E2E_PATIENT_EMAIL=... --dart-define=E2E_PATIENT_PASSWORD=... \
//     --dart-define=E2E_SCENARIO=normal|redflag
//
// 會消耗真 OpenAI 額度（每輪 LLM + TTS）。

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:integration_test/integration_test.dart';

import 'package:gu_voice/app.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';
import 'package:gu_voice/features/patient/session_thank_you_page.dart';
import 'package:gu_voice/features/voice/services/ws_manager.dart';
import 'package:gu_voice/features/voice/state/conversation_controller.dart';

const _email = String.fromEnvironment('E2E_PATIENT_EMAIL');
const _password = String.fromEnvironment('E2E_PATIENT_PASSWORD');
const _scenario = String.fromEnvironment('E2E_SCENARIO', defaultValue: 'normal');

/// 病患台詞。redflag 情境第一句就講 critical 症狀（睪丸扭轉），
/// 對齊 scripts/e2e_realopenai 的 torsion_critical_zh。
const _lines = <String, List<String>>{
  'normal': [
    '大概三天前開始，白天小便次數變多，一天大概十幾次。',
    '沒有發燒，排尿時不會痛，尿的顏色正常。',
    '晚上會起來上兩三次廁所，喝水量跟平常差不多。',
    '沒有在吃任何藥物，也沒有開過刀。',
  ],
  'redflag': [
    '大約兩小時前左邊睪丸突然劇烈疼痛，陰囊腫起來，痛到想吐，走路都有困難。',
  ],
};

Future<void> _pumpFor(WidgetTester tester, Duration total,
    {bool Function()? until}) async {
  final deadline = total.inMilliseconds ~/ 250;
  for (var i = 0; i < deadline; i++) {
    await tester.pump(const Duration(milliseconds: 250));
    if (until != null && until()) return;
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('patient text consultation runs end to end', (tester) async {
    if (_email.isEmpty || _password.isEmpty) {
      markTestSkipped('未提供 E2E_PATIENT_EMAIL / E2E_PATIENT_PASSWORD，跳過');
      return;
    }
    // 對話頁很長；小畫布會讓 off-screen widget 點不到。
    tester.view.physicalSize = const Size(1200, 3000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

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

    // ── 登入 ────────────────────────────────────────────────
    final fields = find.byType(TextField);
    expect(fields, findsAtLeast(2), reason: '登入頁應有 email / password');
    await tester.enterText(fields.at(0), _email);
    await tester.enterText(fields.at(1), _password);
    await tester.pumpAndSettle();
    await tester.tap(find.byType(FilledButton).first);
    await _pumpFor(tester, const Duration(seconds: 15),
        until: () => container.read(authProvider).user != null);
    await tester.pumpAndSettle();
    expect(container.read(authProvider).user, isNotNull, reason: '病患登入失敗');

    // ── 選主訴 ──────────────────────────────────────────────
    // 病患首頁的 CTA 是 InkWell（不是 Button），直接走路由比猜 widget 型別穩。
    final ctx = tester.element(find.byType(Scaffold).first);
    GoRouter.of(ctx).go('/$currentLng/patient/start');
    await _pumpFor(tester, const Duration(seconds: 12));
    await tester.pumpAndSettle();

    // 主訴清單是 API 來的，每項是 ListTile（select_complaint_page._complaintTile）。
    final listTiles = find.byType(ListTile);
    expect(listTiles, findsAtLeast(1), reason: '主訴清單沒載出來（後端 /complaints 或 seed 問題）');
    await tester.tap(listTiles.first, warnIfMissed: false);
    await tester.pumpAndSettle();

    // 下一步（選了主訴後 CTA 才 enabled）
    await tester.tap(find.byType(FilledButton).last);
    await _pumpFor(tester, const Duration(seconds: 5));
    await tester.pumpAndSettle();

    // ── 基本資料 ────────────────────────────────────────────
    // medical_info_page._valid 三項全required：姓名、性別 ChoiceChip、生日。
    await tester.enterText(find.byType(TextField).first, 'E2E 文字測試');
    await tester.pumpAndSettle();

    final chips = find.byType(ChoiceChip);
    expect(chips, findsAtLeast(1), reason: 'intake 沒有性別 ChoiceChip');
    await tester.tap(chips.first);
    await tester.pumpAndSettle();

    // 生日：開 showDatePicker，直接確認 initialDate(1980)
    await tester.tap(find.byType(OutlinedButton).first);
    await tester.pumpAndSettle();
    final ok = find.text('OK');
    await tester.tap(ok.evaluate().isNotEmpty ? ok : find.byType(TextButton).last);
    await tester.pumpAndSettle();

    // ── 進入對話 ────────────────────────────────────────────
    await tester.tap(find.byType(FilledButton).last, warnIfMissed: false);
    await _pumpFor(tester, const Duration(seconds: 20), until: () {
      final s = container.read(conversationControllerProvider);
      return s.session != null;
    });
    await tester.pumpAndSettle();

    final entered = container.read(conversationControllerProvider).session != null;
    expect(entered, isTrue,
        reason: '沒有進入 conversation（intake 必填欄位可能未滿足）——'
            '這正是 §V2 要驗的那段，失敗要看畫面上停在哪一頁');

    // WS 要連上，否則後面都沒意義
    await _pumpFor(tester, const Duration(seconds: 20), until: () {
      return container.read(conversationControllerProvider).connection ==
          WsConnState.open;
    });
    expect(container.read(conversationControllerProvider).connection,
        WsConnState.open,
        reason: 'WebSocket 沒連上（auth handshake 或 resume 失敗）');

    // 等 AI 開場白
    await _pumpFor(tester, const Duration(seconds: 45), until: () {
      return container
          .read(conversationControllerProvider)
          .messages
          .any((m) => m.sender != 'patient');
    });
    final greeting = container.read(conversationControllerProvider).messages;
    expect(greeting.where((m) => m.sender != 'patient'), isNotEmpty,
        reason: 'AI 開場白沒出現');

    // ── 用文字回答 ──────────────────────────────────────────
    final lines = _lines[_scenario]!;
    for (var i = 0; i < lines.length; i++) {
      final state = container.read(conversationControllerProvider);
      if (state.completed) break; // 紅旗可能提早中止

      final before = container.read(conversationControllerProvider).messages.length;
      final input = find.byType(TextField);
      expect(input, findsAtLeast(1), reason: '對話頁找不到文字輸入框');
      await tester.enterText(input.last, lines[i]);
      await tester.pumpAndSettle();
      // 用送出鍵，不用 receiveAction：送出後輸入框失焦，第二句起 receiveAction 會靜默失效
      // （第一次跑就是這樣只有一句進逐字稿）。
      await tester.tap(find.byIcon(Icons.send));

      // 等 AI 回應（真 OpenAI，慢）
      await _pumpFor(tester, const Duration(seconds: 90), until: () {
        final s = container.read(conversationControllerProvider);
        return s.completed || s.messages.length > before + 1;
      });
      await tester.pumpAndSettle();
    }

    final finalState = container.read(conversationControllerProvider);

    // ── 斷言 ────────────────────────────────────────────────
    final patientTurns = finalState.messages.where((m) => m.sender == 'patient').length;
    expect(patientTurns, greaterThanOrEqualTo(_lines[_scenario]!.length),
        reason: '只有 $patientTurns 句進逐字稿，少於送出的 ${_lines[_scenario]!.length} 句');
    expect(finalState.messages.where((m) => m.sender != 'patient').length,
        greaterThan(1),
        reason: 'AI 沒有針對回答追問（只有開場白）');
    expect(finalState.error, isNull, reason: '對話過程出錯：${finalState.error}');

    // ── 結束問診 → 感謝頁 ────────────────────────────────────
    // normal 情境不會在四輪內自動結束，用 AppBar 的「結束問診」把
    // completed → thank-you 導向 + SOAP 觸發這一段真的走一次。
    if (_scenario == 'normal' && !finalState.completed) {
      // AppBar 內那顆才是「結束問診」；用 byType().first 會抓到 body 裡的按鈕（上一輪就是這樣沒送出）。
      final endBtn = find.descendant(
          of: find.byType(AppBar), matching: find.byType(TextButton));
      expect(endBtn, findsOneWidget, reason: '對話頁 AppBar 找不到結束問診按鈕');
      await tester.tap(endBtn);
      // ⚠️ 不要用 `container.read(conversationControllerProvider).completed` 驗：
      // 導頁後 ConversationPage 卸載，autoDispose 把 controller 丟掉，再 read 會拿到
      // 全新的 initial state（completed=false）。要看的是「有沒有離開對話頁」。
      await _pumpFor(tester, const Duration(seconds: 30),
          until: () => find.byType(SessionThankYouPage).evaluate().isNotEmpty);
      await tester.pumpAndSettle();
      expect(find.byType(SessionThankYouPage), findsOneWidget,
          reason: '按了結束問診沒導到感謝頁（React 版是送出即導頁）');
    }

    if (_scenario == 'redflag') {
      // G1：critical 紅旗必須中止，且要標記 abortedRedFlag（否則病患會被導到
      // 一般感謝頁 + 8 秒自動回首頁，看不到「告知現場醫護」）
      await _pumpFor(tester, const Duration(seconds: 60),
          until: () => container.read(conversationControllerProvider).completed);
      final s = container.read(conversationControllerProvider);
      expect(s.redFlags, isNotEmpty, reason: '紅旗情境沒有偵測到任何紅旗');
      expect(s.completed, isTrue, reason: 'critical 紅旗沒有中止問診');
      expect(s.abortedRedFlag, isTrue,
          reason: 'abortedRedFlag 沒被設起來 → 病患會拿到一般感謝頁（TODO G1 的回歸）');
    }
  }, timeout: const Timeout(Duration(minutes: 12)));
}
