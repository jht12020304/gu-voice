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
  /// 語音降級：麥克風開不起來時**只**設這個，不設 `error`。
  ///
  /// `error` 是阻斷性錯誤（會渲染成紅色橫幅、也是 e2e 的失敗判準），而且從來沒有
  /// 任何路徑會清掉它——把「沒有麥克風／權限被拒」寫進去，等於讓一場從頭到尾成功
  /// 的純文字問診全程掛著一則錯誤（缺陷 B）。麥克風不可用不會擋住問診：文字輸入
  /// 走的是同一條紅旗／LLM／TTS 管線。
  final MicUnavailableReason? voiceUnavailable;
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
    this.voiceUnavailable,
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
    MicUnavailableReason? voiceUnavailable,
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
        voiceUnavailable: voiceUnavailable ?? this.voiceUnavailable,
        connection: connection ?? this.connection,
        noSpeechHint: noSpeechHint ?? this.noSpeechHint,
        completed: completed ?? this.completed,
        abortedRedFlag: abortedRedFlag ?? this.abortedRedFlag,
      );
}

/// `start()` 用到的協作者工廠（麥克風／TTS／WS／audio session 設定）——
/// 注入 fake 用的**縫隙**，不是抽象層。
/// 預設值就是正式實作（建構式 tear-off），所以 production 完全不受影響；
/// 有了它，「沒有麥克風 → 降級而不是炸掉、而且 WS 照連」才驗得起來。
class VoiceServices {
  const VoiceServices({
    this.audio = AudioStreamService.new,
    this.tts = TtsPlaybackController.new,
    this.ws = WebSocketManager.new,
    this.sessions = SessionsApi.new,
    this.configureSession = configureVoiceAudioSession,
  });

  final AudioStreamService Function() audio;
  final TtsPlaybackController Function({required double Function() speed}) tts;
  final WebSocketManager Function() ws;
  /// REST 縫隙：`resume_failed` 的逐字稿重抓與 `reconnectResumeToken` 都走它。
  final SessionsApi Function() sessions;
  final Future<void> Function() configureSession;
}

final voiceServicesProvider = Provider<VoiceServices>((ref) => const VoiceServices());

// The interlock: WS events -> state + imperative mic-lock/TTS side effects. Port of the
// ConversationPage WS wiring + conversationStore. The two hard-lock bools are plain
// fields (React refs), NEVER derived from isAIResponding (which flips false at
// ai_response_end while TTS still plays).
class ConversationController extends Notifier<ConversationState> {
  late final AudioStreamService _audio;
  late final TtsPlaybackController _tts;
  late final WebSocketManager _ws;
  // Injected in `start()` alongside the other collaborators (`SessionsApi` itself now
  // builds its Dio lazily, so constructing it costs nothing and needs no platform
  // channels). Fakes come in through `voiceServicesProvider`.
  late final SessionsApi _sessions;

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

    final make = ref.read(voiceServicesProvider);
    _tts = make.tts(speed: () => ref.read(settingsProvider).ttsSpeed);
    _audio = make.audio();
    _ws = make.ws();
    _sessions = make.sessions();
    // Only now is `_started` true: `_teardown` keys off it before touching these
    // `late final` fields, so flipping it earlier would let a dispose racing an
    // early `start()` hit a LateInitializationError instead of a clean no-op.
    _started = true;

    _registerWsHandlers();
    _ws.resumeTokenProvider = () => _sessions.reconnectResumeToken(session.id);
    _ws.authFailureHandler = () => ApiClient.instance.forceRefresh();

    // 麥克風與 WebSocket 是兩件獨立的事。
    // (1) 開麥失敗**不得**擋住 `_ws.connect`：文字輸入走的是同一條紅旗／LLM／TTS
    //     管線，麥克風壞掉只是「不能用講的」，不是「不能問診」。（skill 記載過的
    //     症狀：權限未授時 start() 卡在 openMic，WS 永遠停在 connecting。）
    // (2) 開麥失敗**不得**寫進 `state.error`：那是阻斷性錯誤，而且沒有任何路徑會
    //     清掉它，會讓一場全程成功的純文字問診從頭到尾掛著一則錯誤（缺陷 B）。
    try {
      await make.configureSession();
      await _audio.openMic(_audioCallbacks());
    } on MicUnavailableException catch (e) {
      state = state.copyWith(voiceUnavailable: e.reason);
    } catch (_) {
      state = state.copyWith(voiceUnavailable: MicUnavailableReason.failed);
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
    _wsOn('resume_failed', (_, _) => unawaited(_onResumeFailed()));
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

  /// L10-7：WS 重連時帶的 `?resumeFrom=<checksum>` 對不上伺服器端 history。
  ///
  /// 後端送完這則就**直接進主訊息迴圈**：歷史非空時不補開場白，而且照樣拿伺服器端的
  /// conversation_history 繼續問診（病患下一句正常處理）。所以前端不做事＝畫面靜默停在
  /// 斷線前的舊逐字稿，之後的 AI 追問接在一份錯的上下文後面（不變式 #6：不得靜默吞掉）。
  ///
  /// 伺服器是唯一真相源 → REST 重抓完整逐字稿並**整批取代**本地列表。刻意不合併：
  /// 斷線瞬間本地可能留著 (a) 樂觀送出但後端從未收到的病患氣泡、(b) 被 `_onDisconnected`
  /// 砍斷、`isStreaming` 還是 true 的 AI 訊息；用 id 合併會讓這兩種殘影永遠留在畫面上。
  /// 取代也不會與後續 `ai_response_*` 打架——resume 失敗後的下一則 AI 訊息帶的是全新
  /// messageId，只會 append，不會命中重建列表裡的 DB id。
  Future<void> _onResumeFailed() async {
    final sid = state.session?.id;
    if (sid == null) return;
    try {
      final turns = await _sessions.getConversations(sid);
      if (_disposed) return; // 重抓期間病患可能已離開對話頁（autoDispose）
      state = state.copyWith(
        messages: [
          for (final turn in turns)
            ChatMessage(
              id: turn.id,
              sessionId: sid,
              sender: turn.role,
              content: turn.contentText,
              timestamp: turn.createdAt ?? _nowIso(),
              sttConfidence: turn.sttConfidence,
            ),
        ],
        // 那一輪的 ai_response_end / stt_final 已隨舊連線消失，旗標不清會讓狀態列
        // 永遠停在「AI 回應中」／「正在辨識」。
        isAIResponding: false,
        aiStreamingText: '',
        sttProcessing: false,
      );
    } catch (_) {
      if (_disposed) return;
      // 重抓失敗才走既有錯誤顯示路徑：此時本地列表確實與伺服器分岔且無從修復。
      state = state.copyWith(error: t('conversation.error.loadFailed'));
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
  ///
  /// 斷線守衛（2026-08-22，skill #18 的缺口）：`_ws.send` 在非 open 狀態下**靜默丟包**。
  /// 沒有這個檢查時，病患在重連空窗按「結束問診」＝什麼都沒發生也沒有任何回饋，
  /// 病患以為結束了就走人 → 場次留在 in_progress → 60 分鐘後被 Celery 收成
  /// cancelled，**SOAP 永遠不會生成**。與 [sendText] 的離線守衛同一個道理：
  /// 寧可大聲失敗，也不要假裝成功。重連成功後再按一次即可（error 會被下一輪清掉）。
  void endSession() {
    if (_ws.connectionState != WsConnState.open) {
      state = state.copyWith(error: t('conversation.input.sendOffline'));
      return;
    }
    _ws.send('control', {'action': 'end_session'});
  }

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
