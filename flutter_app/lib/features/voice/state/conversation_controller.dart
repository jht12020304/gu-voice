import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../../core/config/env.dart';
import '../../../core/i18n/loc.dart';
import '../../../data/api/dio_client.dart';
import '../../../data/api/sessions_api.dart';
import '../../../data/api/token_store.dart';
import '../../../data/models/session.dart';
import '../models/chat_message.dart';
import '../services/audio_session_config.dart';
import '../services/audio_stream_service.dart';
import '../services/tts_playback_controller.dart';
import '../services/ws_manager.dart';
import 'settings_notifier.dart';
import 'vad_logic.dart';

const _uuid = Uuid();

class ConversationState {
  final Session? session;
  final List<ChatMessage> messages;
  final bool isRecording;
  final bool isAIResponding;
  final bool sttProcessing;
  final bool userPaused;
  final String aiStreamingText;
  final double recordingDuration;
  final List<double> waveform;
  final List<RedFlagEvent> redFlags;
  final SupervisorGuidance? guidance;
  final bool supervisorDegraded;
  final String? error;
  final WsConnState connection;
  final bool noSpeechHint;
  final bool completed;
  final bool abortedRedFlag;

  const ConversationState({
    this.session,
    this.messages = const [],
    this.isRecording = false,
    this.isAIResponding = false,
    this.sttProcessing = false,
    this.userPaused = false,
    this.aiStreamingText = '',
    this.recordingDuration = 0,
    this.waveform = const [],
    this.redFlags = const [],
    this.guidance,
    this.supervisorDegraded = false,
    this.error,
    this.connection = WsConnState.connecting,
    this.noSpeechHint = false,
    this.completed = false,
    this.abortedRedFlag = false,
  });

  ConversationState copyWith({
    Session? session,
    List<ChatMessage>? messages,
    bool? isRecording,
    bool? isAIResponding,
    bool? sttProcessing,
    bool? userPaused,
    String? aiStreamingText,
    double? recordingDuration,
    List<double>? waveform,
    List<RedFlagEvent>? redFlags,
    SupervisorGuidance? guidance,
    bool? supervisorDegraded,
    String? error,
    bool clearError = false,
    WsConnState? connection,
    bool? noSpeechHint,
    bool? completed,
    bool? abortedRedFlag,
  }) =>
      ConversationState(
        session: session ?? this.session,
        messages: messages ?? this.messages,
        isRecording: isRecording ?? this.isRecording,
        isAIResponding: isAIResponding ?? this.isAIResponding,
        sttProcessing: sttProcessing ?? this.sttProcessing,
        userPaused: userPaused ?? this.userPaused,
        aiStreamingText: aiStreamingText ?? this.aiStreamingText,
        recordingDuration: recordingDuration ?? this.recordingDuration,
        waveform: waveform ?? this.waveform,
        redFlags: redFlags ?? this.redFlags,
        guidance: guidance ?? this.guidance,
        supervisorDegraded: supervisorDegraded ?? this.supervisorDegraded,
        error: clearError ? null : (error ?? this.error),
        connection: connection ?? this.connection,
        noSpeechHint: noSpeechHint ?? this.noSpeechHint,
        completed: completed ?? this.completed,
        abortedRedFlag: abortedRedFlag ?? this.abortedRedFlag,
      );
}

// The interlock: WS events -> state + imperative mic-lock/TTS side effects. Port of the
// ConversationPage WS wiring + conversationStore. The two hard-lock bools are plain
// fields (React refs), NEVER derived from isAIResponding (which flips false at
// ai_response_end while TTS still plays).
class ConversationController extends Notifier<ConversationState> {
  late final AudioStreamService _audio;
  late final TtsPlaybackController _tts;
  late final WebSocketManager _ws;
  // Lazy: `SessionsApi()` reaches for `ApiClient.dio`, which needs platform channels.
  // Building it eagerly made the controller unconstructible in unit tests (and did
  // no work until `start()` anyway).
  late final _sessions = SessionsApi();

  bool _pendingAiUnmute = false;
  bool _pendingReplayUnmute = false;
  bool _redFlagAnnounced = false;
  Timer? _noSpeechTimer;
  bool _started = false;
  // 一旦 provider 開始 dispose 就不能再碰 `state`（Riverpod 會拋 UnmountedRefException）。
  // 在飛的 mic frame 與 `_ws.disconnect()` 自己發出的 _statechange 都會晚於 dispose 抵達，
  // 病患一離開對話頁就炸——這是 simulator 真跑才抓到的（TODO §V2）。
  bool _disposed = false;

  @override
  ConversationState build() {
    ref.onDispose(_teardown);
    return const ConversationState();
  }

  Future<void> start(Session session) async {
    // Re-entrancy guard for ONE controller instance (e.g. `_init` firing twice).
    // It is NOT a cross-session guard: the provider is autoDispose, so leaving the
    // page throws this instance away and the next patient gets a fresh one with
    // `_started == false`. See the provider declaration for why that matters.
    if (_started) return;
    state = state.copyWith(session: session);

    _tts = TtsPlaybackController(speed: () => ref.read(settingsProvider).ttsSpeed);
    _audio = AudioStreamService();
    _ws = WebSocketManager();
    // Only now is `_started` true: `_teardown` keys off it before touching these
    // `late final` fields, so flipping it earlier would let a dispose racing an
    // early `start()` hit a LateInitializationError instead of a clean no-op.
    _started = true;

    _registerWsHandlers();
    _ws.resumeTokenProvider = () => _sessions.reconnectResumeToken(session.id);
    _ws.authFailureHandler = () => ApiClient.instance.forceRefresh();

    try {
      await configureVoiceAudioSession();
      await _audio.openMic(_audioCallbacks());
    } catch (e) {
      state = state.copyWith(error: _micError(e));
    }

    _ws.connect('${Env.wsBase}/sessions/${session.id}/stream', () => TokenStore.instance.accessToken);
  }

  // ---- audio (mic) side ----

  AudioStreamCallbacks _audioCallbacks() => AudioStreamCallbacks(
        onChunk: (b64, idx) =>
            _ws.send('audio_chunk', {'audioData': b64, 'chunkIndex': idx, 'isFinal': false}),
        onSpeechStart: () {
          if (_disposed) return;
          // Re-assert the lock. A segment opening while any gate is set means the mute
          // leaked (the gates ARE "the mic must not be open"): `userPaused` is an
          // independent gate no automatic flow may lift (invariant #4), and the two
          // pending-unmute flags mean the AI still owns the turn (invariant #3).
          // Soft mute is excluded so a deliberate barge-in still gets through — that
          // path is currently dormant because AI turns hard-mute.
          final softMuteBargeIn = _audio.muteMode == MuteMode.soft;
          if (!softMuteBargeIn &&
              (state.userPaused || _pendingAiUnmute || _pendingReplayUnmute)) {
            _muteVad();
            return;
          }
          state = state.copyWith(isRecording: true, noSpeechHint: false);
          if (state.isAIResponding) _bargeIn(); // only reachable in soft-mute mode
        },
        onSpeechEnd: () {
          if (_disposed) return;
          // terminal marker -> backend joins buffer and runs STT
          _ws.send('audio_chunk', {'audioData': '', 'chunkIndex': -1, 'isFinal': true});
          state = state.copyWith(isRecording: false, sttProcessing: true);
          // Hard-mute until the AI turn resolves — the React original does the same
          // right after the final chunk (useAudioStream.ts: "送出後即暫停 VAD").
          // Without it the mic stays live through STT + LLM + TTS, so the speaker
          // echo of the AI's own reply gets captured as the patient's next answer
          // (invariant #3). Every resume path re-arms: aiTtsDone / emptyStt /
          // wsError / reconnected / userResume / ttsMuteToggle / replayEnd. (TODO G3)
          _muteVad();
        },
        onWaveformData: (bars) { if (!_disposed) state = state.copyWith(waveform: bars); },
        onDurationUpdate: (s) { if (!_disposed) state = state.copyWith(recordingDuration: s); },
        onError: (e) { if (!_disposed) state = state.copyWith(error: _micError(e)); },
      );

  void _muteVad() => _audio.setMuted(true, mode: MuteMode.hard);

  void _unmuteIfAllowed(VadResumeTrigger trigger) {
    final ctx = VadResumeContext(
      userPaused: state.userPaused,
      aiTurnLocked: _pendingAiUnmute || _pendingReplayUnmute,
      wsDown: _ws.connectionState != WsConnState.open, // SYNCHRONOUS state, never lagged
    );
    if (shouldUnmuteVAD(trigger, ctx)) _audio.setMuted(false);
  }

  void _bargeIn() {
    _tts.stopActive();
    _tts.clearQueue();
  }

  // ---- WS event wiring ----

  /// 所有 WS 回呼的唯一入口：dispose 後一律丟棄。
  void _wsOn(String type, void Function(Object?, Object?) handler) =>
      _ws.on(type, (p, m) { if (_disposed) return; handler(p, m); });

  void _registerWsHandlers() {
    _wsOn('_statechange', (p, _) {
      final s = WsConnState.values.firstWhere(
        (e) => e.name == (p as Map)['state'],
        orElse: () => WsConnState.closed,
      );
      state = state.copyWith(connection: s);
    });
    _wsOn('_connected', (_, _) => _onConnected());
    _wsOn('_disconnected', (_, _) => _onDisconnected());
    _wsOn('connection_ack', (_, _) {
      if (state.session?.status == 'waiting') {
        state = state.copyWith(session: state.session!.copyWith(status: 'in_progress'));
      }
    });
    _wsOn('ai_response_start', (p, _) => _onAiStart(p as Map));
    _wsOn('ai_response_chunk', (p, _) => _onAiChunk(p as Map));
    _wsOn('ai_response_end', (p, _) => _onAiEnd(p as Map));
    _wsOn('stt_final', (p, _) => _onSttFinal(p as Map));
    _wsOn('red_flag_alert', (p, _) => _onRedFlag(p as Map));
    _wsOn('supervisor_guidance', (p, _) =>
        state = state.copyWith(guidance: normalizeSupervisorGuidance(p as Map), supervisorDegraded: false));
    _wsOn('supervisor_degraded', (_, _) => state = state.copyWith(supervisorDegraded: true));
    _wsOn('session_status', (p, _) => _onSessionStatus(p as Map));
    _wsOn('error', (p, _) => _onWsError(p as Map));
    _wsOn('_auth_exhausted', (_, _) => state = state.copyWith(error: t('conversation.error.sessionInterrupted')));
  }

  void _onAiStart(Map p) {
    final messageId = (p['messageId'] ?? _uuid.v4()) as String;
    state = state.copyWith(sttProcessing: false, isAIResponding: true, aiStreamingText: '');
    _addMessage(ChatMessage(
      id: messageId,
      sessionId: state.session?.id ?? '',
      sender: 'assistant',
      content: '',
      timestamp: _nowIso(),
      isStreaming: true,
    ));
    if (ref.read(settingsProvider).ttsMuted) {
      _pendingAiUnmute = false; // no TTS => no echo, open mic at normal threshold
      _unmuteIfAllowed(VadResumeTrigger.aiStartTtsMuted);
    } else {
      _pendingAiUnmute = true; // hard-lock the WHOLE AI turn
      _muteVad();
    }
  }

  void _onAiChunk(Map p) {
    final id = p['messageId'] as String?;
    final text = (p['text'] ?? '') as String;
    final audioB64 = p['audioB64'] as String?;
    final ttsFailed = (p['ttsFailed'] ?? false) as bool;

    state = state.copyWith(aiStreamingText: state.aiStreamingText + text);
    _mutateMessage(id, (m) {
      if (audioB64 != null && audioB64.isNotEmpty) m.ttsAudioChunks.add(audioB64); // cache always
      return m.copyWith(content: m.content + text, hasTtsFailure: ttsFailed ? true : m.hasTtsFailure);
    });
    if (audioB64 != null && audioB64.isNotEmpty && !ref.read(settingsProvider).ttsMuted) {
      _tts.enqueue(audioB64); // auto-play only when not muted
    }
  }

  void _onAiEnd(Map p) {
    final id = p['messageId'] as String?;
    final fullText = (p['fullText'] ?? '') as String;
    state = state.copyWith(isAIResponding: false, aiStreamingText: '');
    _mutateMessage(id, (m) => m.copyWith(content: fullText.isNotEmpty ? fullText : m.content, isStreaming: false));
    // Tail = LAST queue step: clear lock + unmute, but only if the epoch still matches
    // (a barge-in/mute/replay that bumped the epoch means a new owner released instead).
    final capturedEpoch = _tts.epoch;
    _tts.appendTail(capturedEpoch, () {
      _pendingAiUnmute = false;
      _unmuteIfAllowed(VadResumeTrigger.aiTtsDone);
    });
  }

  void _onSttFinal(Map p) {
    final text = ((p['text'] ?? '') as String).trim();
    state = state.copyWith(sttProcessing: false);
    if (text.isEmpty) {
      if (!state.userPaused) _flashNoSpeechHint();
      _unmuteIfAllowed(VadResumeTrigger.emptyStt); // backend sends no AI reply for empty STT
    } else {
      final conf = p['confidence'];
      _addMessage(ChatMessage(
        id: (p['messageId'] ?? _uuid.v4()) as String,
        sessionId: state.session?.id ?? '',
        sender: 'patient',
        content: text,
        timestamp: _nowIso(),
        sttConfidence: conf is num ? conf.toDouble() : null,
      ));
    }
  }

  void _onRedFlag(Map p) {
    // 結構性防線：payload 的醫師向欄位（description / suggestedActions）一個都不
    // 讀進 state。後端已不送，但這裡不讀才是不變式——就算日後後端又送回來，
    // 病患端也拿不到。與 React ConversationPage 的 ingest 行為一致。
    final notice = p['patientNotice'];
    state = state.copyWith(redFlags: [
      ...state.redFlags,
      RedFlagEvent(
        id: (p['alertId'] ?? _uuid.v4()) as String,
        title: (p['title'] ?? '') as String,
        severity: (p['severity'] ?? 'medium') as String,
        patientNotice: notice is String && notice.trim().isNotEmpty ? notice.trim() : null,
      ),
    ]);
    // ponytail: critical red-flag spoken alert (flutter_tts) deferred — the banner + the
    // aborted_red_flag thank-you page already surface it. One-shot guard preserved so a
    // future spoken alert fires exactly once per session.
    if (p['severity'] == 'critical' && !_redFlagAnnounced) {
      _redFlagAnnounced = true;
      // TODO(voice): speak ws.events.session.aborted_red_flag once (flutter_tts).
    }
  }

  void _onSessionStatus(Map p) {
    final status = p['status'] as String?;
    if (status == 'completed') {
      state = state.copyWith(completed: true);
    } else if (status == 'aborted_red_flag') {
      state = state.copyWith(completed: true, abortedRedFlag: true);
    } else if (status == 'failed') {
      state = state.copyWith(error: _wsCode(p));
    }
  }

  void _onWsError(Map p) {
    state = state.copyWith(sttProcessing: false, error: _wsCode(p));
    _pendingAiUnmute = false;
    _pendingReplayUnmute = false;
    _unmuteIfAllowed(VadResumeTrigger.wsError);
  }

  void _onConnected() {
    _pendingAiUnmute = false;
    _pendingReplayUnmute = false;
    _tts.stopActive();
    _tts.clearQueue();
    if (state.userPaused) {
      _ws.send('control', {'action': 'pause_recording'}); // backend is_paused resets per connection
    } else {
      _unmuteIfAllowed(VadResumeTrigger.reconnected);
    }
  }

  void _onDisconnected() {
    _tts.stopActive();
    _tts.clearQueue();
    _muteVad(); // mute LAST: the dead connection must not capture speaker echo
    state = state.copyWith(sttProcessing: false);
  }

  // ---- user controls ----

  void pause() {
    // Order is load-bearing. `_muteVad()` hard-mutes, and hard-muting an OPEN segment
    // calls `_endSegment(notify: true)` → `onSpeechEnd` → the final `audio_chunk`.
    // Sending `pause_recording` first meant that flush arrived after the backend had
    // already paused, so it was discarded: the patient lost the half sentence they were
    // mid-way through, and `sttProcessing` stayed true forever because no STT result was
    // ever coming — the status bar sat on "正在辨識" for the rest of the session (TODO G-medium).
    _muteVad();
    _ws.send('control', {'action': 'pause_recording'});
    state = state.copyWith(userPaused: true);
  }

  void resume() {
    state = state.copyWith(userPaused: false);
    _ws.send('control', {'action': 'resume_recording'});
    _unmuteIfAllowed(VadResumeTrigger.userResume);
  }

  /// "我說完了" — end the current utterance now instead of waiting out the 2s silence
  /// window. The translation (`voiceControl.finishSpeaking`) and
  /// `AudioStreamService.forceEndSegment()` both already existed; nothing called them,
  /// so every turn cost the patient a needless 2s wait (TODO G-medium).
  void finishSpeaking() {
    if (state.userPaused || !state.isRecording) return;
    _audio.forceEndSegment();
  }

  /// 導頁由伺服器確認驅動（`session_status` 帶 `status: completed`），**不要**在這裡本地設
  /// `completed`：那會讓 ConversationPage 立刻導頁 → autoDispose 拆掉 controller →
  /// `_ws.disconnect()` 在 end_session 送達前就關掉 socket，場次永遠停在 in_progress、
  /// SOAP 不會生成（真跑抓到）。
  void endSession() => _ws.send('control', {'action': 'end_session'});

  // Text-input fallback (noisy kiosk / STT failure / speech impairment): runs the SAME
  // red-flag/LLM/TTS pipeline as voice. Optimistically add the patient bubble.
  void sendText(String text) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;
    // Offline: `_ws.send` drops silently, so the bubble appeared as if it had been sent
    // while the backend never saw it — meaning the text also never went through red-flag
    // screening. Fail loudly instead of showing a fake bubble (TODO G-medium).
    if (_ws.connectionState != WsConnState.open) {
      state = state.copyWith(error: t('conversation.input.sendOffline'));
      return;
    }
    _addMessage(ChatMessage(
      id: _uuid.v4(),
      sessionId: state.session?.id ?? '',
      sender: 'patient',
      content: trimmed,
      timestamp: _nowIso(),
    ));
    _ws.send('text_message', {'text': trimmed});
    state = state.copyWith(sttProcessing: true);
  }

  void acknowledgeRedFlag(String id) {
    state = state.copyWith(redFlags: [
      for (final f in state.redFlags)
        if (f.id == id) (f..isAcknowledged = true) else f,
    ]);
  }

  // Called after settings.toggleTtsMuted(). Toggling INTO mute must let the patient keep
  // talking: stop + flush the queue, drop the AI lock, and unmute.
  void onTtsMuteToggled(bool nowMuted) {
    if (nowMuted) {
      _tts.stopActive();
      _tts.clearQueue();
      _pendingAiUnmute = false;
      _unmuteIfAllowed(VadResumeTrigger.ttsMuteToggle);
    }
  }

  void replay(String messageId) {
    final msg = state.messages.where((m) => m.id == messageId).firstOrNull;
    if (msg == null || msg.ttsAudioChunks.isEmpty) return;
    _tts.stopActive();
    _tts.clearQueue();
    if (!state.isAIResponding) _pendingAiUnmute = false; // its stale tail was just invalidated
    _pendingReplayUnmute = true;
    _muteVad();
    for (final chunk in msg.ttsAudioChunks) {
      _tts.enqueue(chunk);
    }
    final capturedEpoch = _tts.epoch;
    _tts.appendTail(capturedEpoch, () {
      _pendingReplayUnmute = false;
      _unmuteIfAllowed(VadResumeTrigger.replayEnd);
    });
  }

  // ---- helpers ----

  void _addMessage(ChatMessage m) => state = state.copyWith(messages: [...state.messages, m]);

  void _mutateMessage(String? id, ChatMessage Function(ChatMessage) f) {
    if (id == null) return;
    state = state.copyWith(
      messages: [for (final m in state.messages) if (m.id == id) f(m) else m],
    );
  }

  void _flashNoSpeechHint() {
    state = state.copyWith(noSpeechHint: true);
    _noSpeechTimer?.cancel();
    _noSpeechTimer = Timer(const Duration(seconds: 4), () {
      state = state.copyWith(noSpeechHint: false);
    });
  }

  String _wsCode(Map p) {
    final code = p['code'] as String?;
    if (code == null) return t('conversation.error.aiUnavailable');
    return t('ws.$code', args: (p['params'] as Map?)?.cast<String, Object?>());
  }

  String _micError(Object e) => t('conversation.error.micGeneric', args: {'message': e.toString()});

  String _nowIso() => DateTime.now().toUtc().toIso8601String();

  Future<void> _teardown() async {
    _disposed = true;
    _noSpeechTimer?.cancel();
    if (!_started) return;
    _ws.disconnect();
    _audio.closeMic();
    await _tts.dispose();
    await _audio.dispose();
  }
}

/// autoDispose is load-bearing, not a micro-optimisation.
///
/// Without it the notifier outlives the page: leaving the conversation leaves the
/// mic open and the WebSocket connected (`ref.onDispose(_teardown)` never fires),
/// and the `_started` latch makes the next `start()` a no-op — so on a shared clinic
/// kiosk the SECOND patient inherits the first patient's session, transcript, red
/// flags and mute state. autoDispose tears the instance down when the page unmounts,
/// giving every patient a clean controller.
///
/// Keep it autoDispose. If something ever needs to survive navigation, hold that
/// state in a separate provider rather than making this one long-lived.
final conversationControllerProvider =
    NotifierProvider.autoDispose<ConversationController, ConversationState>(
  ConversationController.new,
);

extension _FirstOrNull<E> on Iterable<E> {
  E? get firstOrNull => isEmpty ? null : first;
}
