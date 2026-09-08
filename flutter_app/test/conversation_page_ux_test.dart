import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/data/models/session.dart';
import 'package:gu_voice/features/voice/models/chat_message.dart';
import 'package:gu_voice/features/voice/screens/conversation_page.dart';
import 'package:gu_voice/features/voice/services/ws_manager.dart';
import 'package:gu_voice/features/voice/state/conversation_controller.dart';
import 'package:gu_voice/features/voice/state/vad_logic.dart';

void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    await Locales.loadAll();
  });

  setUp(() => setCurrentLng('en-US'));
  tearDown(() => setCurrentLng('zh-TW'));

  testWidgets('English controls fit a narrow phone and speed stays numeric', (
    tester,
  ) async {
    final fake = _FakeConversationController(_state());
    await _pumpPage(tester, fake);

    expect(find.text('1.0x'), findsOneWidget);
    expect(
      find.text('Speed 1.0x'),
      findsNothing,
      reason: '完整英文語速標籤放在窄控制列會造成 RenderFlex overflow',
    );
    expect(find.byKey(const ValueKey('tts-speed-control')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('keyboard compacts guidance and sending releases text focus', (
    tester,
  ) async {
    final fake = _FakeConversationController(_state());
    await _pumpPage(tester, fake);

    expect(
      find.byKey(const ValueKey('supervisor-guidance-expanded')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('supervisor-guidance-compact')),
      findsNothing,
    );

    final field = find.byKey(const ValueKey('conversation-text-input'));
    await tester.tap(field);
    await tester.showKeyboard(field);
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    addTearDown(tester.view.resetViewInsets);
    await tester.pump();

    expect(
      find.byKey(const ValueKey('supervisor-guidance-compact')),
      findsOneWidget,
    );
    expect(find.text('2 left'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('supervisor-guidance-expanded')),
      findsNothing,
    );

    await tester.enterText(field, 'It started yesterday');
    await tester.testTextInput.receiveAction(TextInputAction.send);
    await tester.pump();

    expect(fake.sent, ['It started yesterday']);
    expect(
      tester.widget<EditableText>(find.byType(EditableText)).focusNode.hasFocus,
      isFalse,
      reason: '送出後仍保有焦點，iOS 鍵盤就會一直佔住對話畫面',
    );

    tester.view.resetViewInsets();
    await tester.pump();
    expect(
      find.byKey(const ValueKey('supervisor-guidance-expanded')),
      findsOneWidget,
    );
  });

  testWidgets('only assistant messages render the UroSense mascot', (
    tester,
  ) async {
    final fake = _FakeConversationController(_state());
    await _pumpPage(tester, fake);

    expect(find.byKey(const ValueKey('urosense-avatar-ai-1')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('urosense-avatar-patient-1')),
      findsNothing,
    );
    expect(
      find.byKey(const ValueKey('urosense-avatar-system-1')),
      findsNothing,
    );

    final list = tester.widget<ListView>(find.byType(ListView));
    expect(
      list.keyboardDismissBehavior,
      ScrollViewKeyboardDismissBehavior.onDrag,
      reason: '拖曳逐字稿必須能收起鍵盤，不能只靠送出按鈕',
    );
  });
}

ConversationState _state() => ConversationState(
  session: const Session(id: 's1', status: 'in_progress', language: 'en-US'),
  connection: WsConnState.open,
  guidance: const SupervisorGuidance(
    nextFocus: 'When the symptom began and how severe it is',
    missingHpi: ['onset', 'severity'],
    hpiCompletionPercentage: 40,
    fallback: false,
  ),
  messages: [
    ChatMessage(
      id: 'system-1',
      sessionId: 's1',
      sender: 'system',
      content: 'Consultation started',
      timestamp: '2026-08-25T00:00:00Z',
    ),
    ChatMessage(
      id: 'ai-1',
      sessionId: 's1',
      sender: 'assistant',
      content: 'Hello, when did your symptom begin?',
      timestamp: '2026-08-25T00:00:01Z',
    ),
    ChatMessage(
      id: 'patient-1',
      sessionId: 's1',
      sender: 'patient',
      content: 'Yesterday',
      timestamp: '2026-08-25T00:00:02Z',
    ),
  ],
);

Future<void> _pumpPage(
  WidgetTester tester,
  _FakeConversationController fake,
) async {
  tester.view.physicalSize = const Size(375, 812);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [conversationControllerProvider.overrideWith(() => fake)],
      child: MaterialApp(
        theme: AppTheme.light,
        home: const ConversationPage(
          sessionId: 's1',
          session: Session(id: 's1', status: 'in_progress', language: 'en-US'),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

class _FakeConversationController extends ConversationController {
  _FakeConversationController(this.initial);

  final ConversationState initial;
  final sent = <String>[];

  @override
  ConversationState build() => initial;

  @override
  Future<void> start(Session session) async {}

  @override
  void sendText(String text) => sent.add(text);

  @override
  void pause() {}

  @override
  void resume() {}

  @override
  void finishSpeaking() {}

  @override
  void endSession() {}

  @override
  void onTtsMuteToggled(bool nowMuted) {}

  @override
  void replay(String messageId) {}
}
