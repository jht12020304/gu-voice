// 「沒有麥克風」的降級路徑回歸測試。
//
// 缺陷 A（blocker，P3 六次重現）：宿主機沒有任何音訊輸入時，`start()` 會無條件
// 走到 `record.startStream`，原生層 `installTapOnBus` 因為 format 是 0Hz/0ch 拋
// NSException → SIGABRT，Dart 攔不到、整個 app 死。所以這裡的核心斷言是
// **「沒有可用輸入時 startStream 一個 byte 都不能送出去」**。
//
// 缺陷 B（minor）：開麥失敗把訊息寫進 `ConversationState.error` 且永不清除，
// 之後一整場成功的純文字問診都掛著錯誤（也讓 e2e 的 `expect(error, isNull)` 誤判）。
// 所以第二組斷言是 **「降級不得佔用 state.error」**。
//
// 注入式回歸（skill §測試設計 4）：把 `openMic` 的 hasUsableInput 守衛刪掉，
// 'startStream 一定不能被呼叫' 會紅；把 `start()` 的 catch 改回寫 error，
// 'state.error 保持 null' 會紅。兩邊都試過。
import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/data/models/session.dart';
import 'package:gu_voice/features/voice/services/audio_stream_service.dart';
import 'package:gu_voice/features/voice/services/tts_playback_controller.dart';
import 'package:gu_voice/features/voice/services/ws_manager.dart';
import 'package:gu_voice/features/voice/state/conversation_controller.dart';
import 'package:just_audio/just_audio.dart';
import 'package:record/record.dart';

void main() {
  const session = Session(id: 's1', status: 'waiting', language: 'zh-TW');

  group('AudioStreamService.openMic 的開麥前置檢查', () {
    test('沒有可用輸入 → 丟 noInputDevice，而且絕不呼叫 startStream', () async {
      final rec = _FakeRecorder(usableInput: false);
      final audio = AudioStreamService(recorder: rec);

      await expectLater(
        audio.openMic(const AudioStreamCallbacks()),
        throwsA(isA<MicUnavailableException>()
            .having((e) => e.reason, 'reason', MicUnavailableReason.noInputDevice)),
      );

      expect(rec.startStreamCalls, 0,
          reason: 'startStream 只要被呼叫到，無輸入裝置的機器就是原生 SIGABRT——'
              'Dart 的 try/catch 攔不到，這條斷言是缺陷 A 的整個防線');
      expect(rec.hasUsableInputCalls, 1);
    });

    test('權限被拒 → 丟 permissionDenied，連問裝置都不必', () async {
      final rec = _FakeRecorder(permission: false);
      final audio = AudioStreamService(recorder: rec);

      await expectLater(
        audio.openMic(const AudioStreamCallbacks()),
        throwsA(isA<MicUnavailableException>()
            .having((e) => e.reason, 'reason', MicUnavailableReason.permissionDenied)),
      );
      expect(rec.hasUsableInputCalls, 0);
      expect(rec.startStreamCalls, 0);
    });

    test('startStream 自己失敗 → 只拋出，不重複打 onError', () async {
      final rec = _FakeRecorder(startStreamThrows: true);
      final audio = AudioStreamService(recorder: rec);
      Object? reported;

      await expectLater(
        audio.openMic(AudioStreamCallbacks(onError: (e) => reported = e)),
        throwsA(isA<StateError>()),
      );
      expect(reported, isNull,
          reason: '同一個開啟失敗經由「拋出」與「onError」兩條通道回報，呼叫端會'
              '一邊降級一邊寫下永不清除的 state.error（缺陷 B）');
    });

    test('有可用輸入 → 錄音參數與修復前逐字相同（熱路徑零改動）', () async {
      final rec = _FakeRecorder();
      final audio = AudioStreamService(recorder: rec);

      await audio.openMic(const AudioStreamCallbacks());

      expect(rec.startStreamCalls, 1);
      final cfg = rec.lastConfig!;
      expect(cfg.encoder, AudioEncoder.pcm16bits);
      expect(cfg.sampleRate, 16000);
      expect(cfg.numChannels, 1);
      expect(cfg.echoCancel, isTrue);
      expect(cfg.noiseSuppress, isTrue);
      expect(cfg.autoGain, isTrue);
      expect(audio.isRecording, isFalse);

      audio.closeMic();
      await audio.dispose();
    });
  });

  group('ConversationController.start 的降級行為', () {
    test('沒有麥克風：不炸、error 保持 null、WS 照連', () async {
      final h = _harness(usableInput: false);

      await h.container.read(conversationControllerProvider.notifier).start(session);
      final s = h.container.read(conversationControllerProvider);

      expect(s.voiceUnavailable, MicUnavailableReason.noInputDevice);
      expect(s.error, isNull,
          reason: '語音降級不是阻斷性錯誤。寫進 error 會讓一整場成功的純文字問診'
              '從頭到尾掛著錯誤橫幅（缺陷 B），而且沒有任何路徑會清掉它');
      expect(h.ws.connectCalls, 1,
          reason: '麥克風壞掉不得擋住 WS：文字輸入走的是同一條紅旗/LLM/TTS 管線');
    });

    test('權限被拒：同樣只降級，理由可分辨（UI 才能給對的提示）', () async {
      final h = _harness(permission: false);

      await h.container.read(conversationControllerProvider.notifier).start(session);
      final s = h.container.read(conversationControllerProvider);

      expect(s.voiceUnavailable, MicUnavailableReason.permissionDenied);
      expect(s.error, isNull);
      expect(h.ws.connectCalls, 1);
    });

    test('audio session 設定失敗：降級成 failed，WS 仍然連', () async {
      final h = _harness(configureThrows: true);

      await h.container.read(conversationControllerProvider.notifier).start(session);
      final s = h.container.read(conversationControllerProvider);

      expect(s.voiceUnavailable, MicUnavailableReason.failed);
      expect(s.error, isNull);
      expect(h.ws.connectCalls, 1);
      expect(h.recorder.startStreamCalls, 0);
    });

    test('有麥克風：路徑與修復前完全一致（開麥、無降級旗標、WS 連線）', () async {
      final h = _harness();

      await h.container.read(conversationControllerProvider.notifier).start(session);
      final s = h.container.read(conversationControllerProvider);

      expect(h.recorder.startStreamCalls, 1, reason: '有裝置就要照常開麥');
      expect(s.voiceUnavailable, isNull);
      expect(s.error, isNull);
      expect(s.session?.id, 's1');
      expect(h.ws.connectCalls, 1);
    });

    test('降級後純文字流程仍然可用，且不會憑空生出 error', () async {
      final h = _harness(usableInput: false);
      final ctrl = h.container.read(conversationControllerProvider.notifier);
      await ctrl.start(session);

      h.ws.fakeState = WsConnState.open;
      ctrl.sendText('三天前開始頻尿');

      final s = h.container.read(conversationControllerProvider);
      expect(s.messages.single.content, '三天前開始頻尿');
      expect(s.sttProcessing, isTrue);
      expect(s.error, isNull);
      expect(h.ws.sent.map((e) => e.$1), contains('text_message'));
    });
  });
}

// ---------------------------------------------------------------------------

class _Harness {
  _Harness(this.container, this.ws, this.recorder);
  final ProviderContainer container;
  final _FakeWs ws;
  final _FakeRecorder recorder;
}

_Harness _harness({
  bool permission = true,
  bool usableInput = true,
  bool configureThrows = false,
}) {
  final recorder = _FakeRecorder(permission: permission, usableInput: usableInput);
  final ws = _FakeWs();
  final container = ProviderContainer(overrides: [
    voiceServicesProvider.overrideWithValue(VoiceServices(
      audio: () => AudioStreamService(recorder: recorder),
      tts: ({required speed}) => TtsPlaybackController(speed: speed, player: _FakePlayer()),
      ws: () => ws,
      configureSession: () async {
        if (configureThrows) throw StateError('audio session unavailable');
      },
    )),
  ]);
  addTearDown(container.dispose);
  return _Harness(container, ws, recorder);
}

class _FakeRecorder implements MicRecorder {
  _FakeRecorder({
    this.permission = true,
    this.usableInput = true,
    this.startStreamThrows = false,
  });
  final bool permission;
  final bool usableInput;
  final bool startStreamThrows;

  int hasUsableInputCalls = 0;
  int startStreamCalls = 0;
  RecordConfig? lastConfig;

  @override
  Future<bool> hasPermission() async => permission;

  @override
  Future<bool> hasUsableInput() async {
    hasUsableInputCalls++;
    return usableInput;
  }

  @override
  Future<Stream<Uint8List>> startStream(RecordConfig config) async {
    startStreamCalls++;
    lastConfig = config;
    if (startStreamThrows) throw StateError('platform refused to start');
    return const Stream<Uint8List>.empty();
  }

  @override
  Future<bool> isRecording() async => startStreamCalls > 0;

  @override
  Future<void> stop() async {}

  @override
  Future<void> dispose() async {}
}

class _FakeWs extends WebSocketManager {
  int connectCalls = 0;
  final sent = <(String, Object)>[];
  WsConnState fakeState = WsConnState.closed;

  @override
  WsConnState get connectionState => fakeState;

  @override
  void connect(String url, TokenProvider token) => connectCalls++;

  @override
  void send(String type, [Object payload = const {}]) => sent.add((type, payload));

  @override
  void disconnect() {}
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
