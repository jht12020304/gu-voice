// L10-7 回歸測試：WS 重連 resume 失敗後的逐字稿重建。
//
// 缺陷：後端在 `?resumeFrom` checksum 對不上且伺服器端 history 非空時，送一則
// `resume_failed` 就**直接進主訊息迴圈**——不補開場白、照樣拿伺服器端 history 繼續
// 問診。兩端前端都沒有訂閱這個事件，所以病患畫面靜默停在斷線前的舊逐字稿，之後的
// AI 追問接在一份錯的上下文後面（不變式 #6：不得靜默吞掉）。
//
// 行為契約（導師定調）：收到 `resume_failed` → REST `GET /sessions/{id}/conversations`
// 重抓完整逐字稿 → **整批取代**本地訊息列表（伺服器為真相源）→ error 保持 null；
// 只有重抓失敗才走既有錯誤顯示路徑。
//
// 注入式回歸（skill §測試設計 4）：把 `_registerWsHandlers` 的 `resume_failed` 那行
// 刪掉 → 前三個案例全紅；把重建改成「以 id 合併」→「樂觀氣泡與 streaming 殘影消失」紅；
// 把 catch 分支的 setError 拿掉 → 「重抓失敗才顯示錯誤」紅。四種都試過。
import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/data/api/sessions_api.dart';
import 'package:gu_voice/data/models/session.dart';
import 'package:gu_voice/data/models/soap_report.dart';
import 'package:gu_voice/features/voice/services/audio_stream_service.dart';
import 'package:gu_voice/features/voice/services/tts_playback_controller.dart';
import 'package:gu_voice/features/voice/services/ws_manager.dart';
import 'package:gu_voice/features/voice/state/conversation_controller.dart';
import 'package:just_audio/just_audio.dart';
import 'package:record/record.dart';

void main() {
  // 伺服器端（DB）的完整逐字稿——重連後唯一的真相源。
  List<ConversationTurn> serverTranscript() => const [
        ConversationTurn(
          id: 'db-1',
          sequenceNumber: 1,
          role: 'assistant',
          contentText: '您好，請問今天哪裡不舒服？',
          createdAt: '2026-08-17T03:00:00Z',
        ),
        ConversationTurn(
          id: 'db-2',
          sequenceNumber: 2,
          role: 'patient',
          contentText: '解尿有血三天了',
          sttConfidence: 0.91,
          createdAt: '2026-08-17T03:00:20Z',
        ),
        ConversationTurn(
          id: 'db-3',
          sequenceNumber: 3,
          role: 'assistant',
          contentText: '請問是整泡尿都紅，還是只有最後一段？',
          createdAt: '2026-08-17T03:00:35Z',
        ),
      ];

  group('resume_failed → REST 重抓 + 整批取代', () {
    test('觸發重抓、列表被伺服器版本取代、error 保持 null', () async {
      final h = await _startedHarness(turns: serverTranscript());

      h.ws.emit('resume_failed', {
        'code': 'events.session.resume_failed',
        'params': {'reason': 'checksum_mismatch_or_empty'},
        'severity': 'warning',
      });
      await pumpEventQueue();

      final s = h.container.read(conversationControllerProvider);
      expect(h.sessions.getConversationsCalls, ['s1'],
          reason: 'resume_failed 必須觸發一次 REST 重抓，不得靜默吞掉（不變式 #6）');
      expect(s.messages.map((m) => m.id).toList(), ['db-1', 'db-2', 'db-3']);
      expect(s.messages.map((m) => m.content).toList(), [
        '您好，請問今天哪裡不舒服？',
        '解尿有血三天了',
        '請問是整泡尿都紅，還是只有最後一段？',
      ]);
      expect(s.messages[1].sender, 'patient');
      expect(s.messages[1].sttConfidence, 0.91);
      expect(s.messages.first.timestamp, '2026-08-17T03:00:00Z',
          reason: '用伺服器的 createdAt，否則重建後所有訊息同一秒');
      expect(s.error, isNull,
          reason: 'resume 失敗但成功復原＝不是錯誤路徑；error 是阻斷性紅色橫幅、'
              '而且沒有任何路徑會清掉它');
    });

    test('樂觀氣泡與被砍斷的 streaming 訊息一併消失（取代語意，不是合併）', () async {
      final h = await _startedHarness(turns: serverTranscript());
      final ctrl = h.container.read(conversationControllerProvider.notifier);

      // 斷線前的本地殘影：一則後端從未收到的樂觀病患氣泡 + 一則 isStreaming 的 AI 訊息
      h.ws.fakeState = WsConnState.open;
      ctrl.sendText('還有點腰痠');
      h.ws.emit('ai_response_start', {'messageId': 'live-ai'});
      h.ws.emit('ai_response_chunk', {'messageId': 'live-ai', 'text': '請問腰痠是'});
      expect(
        h.container.read(conversationControllerProvider).messages.any((m) => m.isStreaming),
        isTrue,
        reason: '前提：重建前確實存在 streaming 殘影',
      );

      h.ws.emit('resume_failed', {'code': 'events.session.resume_failed'});
      await pumpEventQueue();

      final s = h.container.read(conversationControllerProvider);
      expect(s.messages.map((m) => m.id).toList(), ['db-1', 'db-2', 'db-3']);
      expect(s.messages.any((m) => m.content == '還有點腰痠'), isFalse,
          reason: '後端沒收到的樂觀氣泡不得留在畫面上');
      expect(s.messages.any((m) => m.isStreaming), isFalse,
          reason: '被砍斷的 streaming 訊息不得留下殘影');
      expect(s.isAIResponding, isFalse);
      expect(s.aiStreamingText, '');
      expect(s.sttProcessing, isFalse,
          reason: '那一輪的 stt_final/ai_response_end 已隨舊連線消失，'
              '不清旗標狀態列會永遠停在「正在辨識」');
      expect(s.error, isNull);
    });

    test('重建後仍接得住後續 ai_response_*（messageId 銜接）', () async {
      final h = await _startedHarness(turns: serverTranscript());

      h.ws.emit('resume_failed', {'code': 'events.session.resume_failed'});
      await pumpEventQueue();

      // 後端 resume 失敗後沿用伺服器端 history 繼續問診，下一則 AI 訊息帶全新 messageId
      h.ws.emit('ai_response_start', {'messageId': 'after-resume'});
      h.ws.emit('ai_response_chunk', {'messageId': 'after-resume', 'text': '排尿時會痛嗎？'});
      h.ws.emit('ai_response_end', {'messageId': 'after-resume', 'fullText': '排尿時會痛嗎？'});

      final s = h.container.read(conversationControllerProvider);
      expect(s.messages.map((m) => m.id).toList(),
          ['db-1', 'db-2', 'db-3', 'after-resume'],
          reason: '新 messageId 只會 append，不會撞到重建列表裡的 DB id');
      expect(s.messages.last.content, '排尿時會痛嗎？');
      expect(s.messages.last.isStreaming, isFalse);
      expect(s.error, isNull);
    });

    test('重抓失敗 → 才走既有錯誤顯示路徑，且不清空既有列表', () async {
      final h = await _startedHarness(turns: serverTranscript(), fetchThrows: true);
      final ctrl = h.container.read(conversationControllerProvider.notifier);
      h.ws.emit('ai_response_start', {'messageId': 'local-1'});
      h.ws.emit('ai_response_end', {'messageId': 'local-1', 'fullText': '您好'});

      h.ws.emit('resume_failed', {'code': 'events.session.resume_failed'});
      await pumpEventQueue();

      final s = h.container.read(conversationControllerProvider);
      expect(s.error, isNotNull, reason: '無從復原時必須讓病患看得到');
      expect(s.messages.map((m) => m.id).toList(), ['local-1'],
          reason: '重抓失敗不得順手把畫面清空——舊逐字稿仍比空白有用');
      expect(ctrl, isNotNull);
    });

    test('重抓回傳期間病患已離頁（autoDispose）→ 不得寫 state', () async {
      final completer = Completer<List<ConversationTurn>>();
      final h = await _startedHarness(turns: const [], pending: completer);

      h.ws.emit('resume_failed', {'code': 'events.session.resume_failed'});
      await pumpEventQueue();

      h.container.dispose(); // 病患離開對話頁 → provider dispose → _disposed = true
      completer.complete(serverTranscript());
      // 沒有 UnmountedRefException 就算過（_disposed 閘門有守住）
      await expectLater(pumpEventQueue(), completes);
    });
  });
}

// ---------------------------------------------------------------------------

class _Harness {
  _Harness(this.container, this.ws, this.sessions);
  final ProviderContainer container;
  final _FakeWs ws;
  final _FakeSessionsApi sessions;
}

Future<_Harness> _startedHarness({
  required List<ConversationTurn> turns,
  bool fetchThrows = false,
  Completer<List<ConversationTurn>>? pending,
}) async {
  final ws = _FakeWs();
  final sessions = _FakeSessionsApi(turns: turns, throws: fetchThrows, pending: pending);
  final container = ProviderContainer(overrides: [
    voiceServicesProvider.overrideWithValue(VoiceServices(
      audio: () => AudioStreamService(recorder: _FakeRecorder()),
      tts: ({required speed}) => TtsPlaybackController(speed: speed, player: _FakePlayer()),
      ws: () => ws,
      sessions: () => sessions,
      configureSession: () async {},
    )),
  ]);
  addTearDown(() {
    try {
      container.dispose();
    } catch (_) {
      /* 已在測試內 dispose */
    }
  });
  // provider 是 autoDispose：只用 `read` 的話，第一個 `await` 就會讓它沒有 listener
  // 而被回收（`_disposed` 變 true，非同步重抓回來時整段被閘門擋掉）。真實情況是
  // ConversationPage 一直 watch 著它，所以這裡補一個 listener 還原真實生命週期。
  container.listen(conversationControllerProvider, (_, _) {});
  await container
      .read(conversationControllerProvider.notifier)
      .start(const Session(id: 's1', status: 'in_progress', language: 'zh-TW'));
  return _Harness(container, ws, sessions);
}

class _FakeSessionsApi extends SessionsApi {
  _FakeSessionsApi({required this.turns, this.throws = false, this.pending});
  final List<ConversationTurn> turns;
  final bool throws;
  final Completer<List<ConversationTurn>>? pending;
  final getConversationsCalls = <String>[];

  @override
  Future<List<ConversationTurn>> getConversations(String sessionId) async {
    getConversationsCalls.add(sessionId);
    if (throws) throw DioException(requestOptions: RequestOptions(path: '/x'));
    if (pending != null) return pending!.future;
    return turns;
  }

  @override
  Future<String?> reconnectResumeToken(String sessionId) async => null;
}

/// 可注入事件的假 WS：`on` 自己收下 handler，`emit` 直接叫它們（真 `_emit` 是私有的）。
class _FakeWs extends WebSocketManager {
  final _handlers = <String, List<WsHandler>>{};
  final sent = <(String, Object)>[];
  WsConnState fakeState = WsConnState.closed;
  int connectCalls = 0;

  @override
  WsConnState get connectionState => fakeState;

  @override
  void on(String type, WsHandler handler) =>
      _handlers.putIfAbsent(type, () => []).add(handler);

  @override
  void off(String type, WsHandler handler) => _handlers[type]?.remove(handler);

  void emit(String type, Object? payload) {
    for (final h in [...?_handlers[type]]) {
      h(payload, {'type': type, 'payload': payload});
    }
  }

  @override
  void connect(String url, TokenProvider token) => connectCalls++;

  @override
  void send(String type, [Object payload = const {}]) => sent.add((type, payload));

  @override
  void disconnect() {}
}

class _FakeRecorder implements MicRecorder {
  @override
  Future<bool> hasPermission() async => true;

  @override
  Future<bool> hasUsableInput() async => true;

  @override
  Future<Stream<Uint8List>> startStream(RecordConfig config) async =>
      const Stream<Uint8List>.empty();

  @override
  Future<bool> isRecording() async => false;

  @override
  Future<void> stop() async {}

  @override
  Future<void> dispose() async {}
}

class _FakePlayer implements TtsAudioPlayer {
  final _states = StreamController<PlayerState>.broadcast();

  @override
  Stream<PlayerState> get playerStateStream => _states.stream;

  @override
  Future<void> setAudioSource(AudioSource source) async {}

  @override
  Future<void> setSpeed(double speed) async {}

  @override
  Future<void> play() async {}

  @override
  Future<void> stop() async {}

  @override
  Future<void> dispose() async => _states.close();
}
