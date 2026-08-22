import 'dart:async';
import 'dart:math';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:record/record.dart';

import 'pcm_ring_buffer.dart';
import 'wav_encoder.dart';

// Native (iOS/Android) port of frontend/src/services/audioStream.ts.
// record.startStream() delivers raw PCM16 @ a directly-requested 16000 Hz, so we OWN
// the true sample rate — the web getUserMedia hint-vs-actual bug is deleted. Per
// utterance we emit ONE self-contained WAV (pre-roll + live) as a single chunk.
//
// The web 250ms MediaRecorder streaming/fallback path does not exist here.

enum MuteMode { none, hard, soft }

// RMS on a PCM16 frame, normalized to 0..1 — same domain as the web (byte-128)/128 path
// so the 0.035 / 0.06 VAD thresholds transfer unchanged.
double pcmRms(Int16List frame) {
  if (frame.isEmpty) return 0;
  var sum = 0.0;
  for (final s in frame) {
    final v = s / 32768.0;
    sum += v * v;
  }
  return sqrt(sum / frame.length);
}

// VAD numeric params (identical domain to the web RMS 0..1 scale).
const _threshold = 0.035; // normal-mode RMS gate
const _bargeInThreshold = 0.06; // soft-mute: loud user can still interrupt
const _minSpeechMs = 90; // debounce before a segment opens
const _silenceEndMs = 2000; // trailing silence that ends a segment
const _sampleRate = 16000;
const _preRollSamples = 6400; // 16000 * 0.4s
const _ringSamples = 16000; // 1.0s ring

class AudioStreamCallbacks {
  final void Function(String base64Wav, int chunkIndex)? onChunk;
  final void Function(List<double> bars)? onWaveformData;
  final void Function(double seconds)? onDurationUpdate;
  final void Function()? onSpeechStart;
  final void Function()? onSpeechEnd;
  final void Function(Object error)? onError;

  const AudioStreamCallbacks({
    this.onChunk,
    this.onWaveformData,
    this.onDurationUpdate,
    this.onSpeechStart,
    this.onSpeechEnd,
    this.onError,
  });
}

/// 麥克風開不起來的可分類原因。呼叫端據此決定「降級」還是「阻斷性錯誤」——
/// 這兩種不是同一件事，過去全部塞進 `ConversationState.error` 讓純文字問診
/// 全程掛著一則永不消失的錯誤（缺陷 B）。
enum MicUnavailableReason {
  /// 這台機器上沒有可用的音訊輸入。**必須在 `startStream` 之前擋下**：
  /// 沒有可用輸入時 record 的原生層 `installTapOnBus` 會因為
  /// `IsFormatSampleRateAndChannelCountValid(format)` 為 false 直接拋 NSException
  /// → SIGABRT，Dart 的 try/catch 攔不到、整個 app 當場死掉（缺陷 A）。
  noInputDevice,

  /// 使用者拒絕（或尚未授予）麥克風權限。
  permissionDenied,

  /// 其他開啟失敗（audio session 設定失敗、平台丟出非預期錯誤等）。
  failed,
}

/// 麥克風不可用（開啟前就判定）。與「開啟後的執行期錯誤」刻意分開：後者走
/// `AudioStreamCallbacks.onError`，前者由 `openMic()` 拋出交給呼叫端決定降級策略。
class MicUnavailableException implements Exception {
  const MicUnavailableException(this.reason);
  final MicUnavailableReason reason;

  @override
  String toString() => 'MicUnavailableException(${reason.name})';
}

/// `AudioStreamService` 真正用到的平台麥克風切片——注入 fake 用的**縫隙**，不是抽象層，
/// 所以只放實際用到的成員（與 `TtsAudioPlayer` 同一個做法）。有了它，
/// 「沒有可用輸入 → 不得呼叫 startStream」才驗得起來（真麥克風路徑零實測，見 TODO §V1）。
abstract class MicRecorder {
  Future<bool> hasPermission();

  /// 這台機器上「真的錄得到音」嗎？各平台語意見 [RecordMicRecorder.hasUsableInput]。
  /// 呼叫時機必須在 audio session 已設成 playAndRecord 並啟用之後。
  Future<bool> hasUsableInput();

  Future<Stream<Uint8List>> startStream(RecordConfig config);
  Future<bool> isRecording();
  Future<void> stop();
  Future<void> dispose();
}

/// 正式綁定。除了 [hasUsableInput] 以外都是純轉呼叫，沒有自己的行為，
/// 所以這道縫隙不可能改變已出貨的錄音行為。
class RecordMicRecorder implements MicRecorder {
  RecordMicRecorder({@visibleForTesting MethodChannel? iosProbeChannel})
      : _iosProbe = iosProbeChannel ?? const MethodChannel(iosProbeChannelName);

  /// iOS Runner 端的原生探針（`ios/Runner/MicProbe.swift`）。
  static const iosProbeChannelName = 'gu_voice/mic_probe';

  final AudioRecorder _recorder = AudioRecorder();
  final MethodChannel _iosProbe;

  @override
  Future<bool> hasPermission() => _recorder.hasPermission();

  /// **iOS 一定要走原生探針。** 2026-08-17 在無麥克風的 Mac mini 上實測，
  /// iOS Simulator 對每一個純 Dart 訊號都回報一支**幽靈**內建麥克風：
  /// `record.listInputDevices()`、`AVAudioSession.availableInputs`、
  /// `currentRoute.inputs`、`AudioSession.getDevices()` 全部都是
  /// `1 [MicrophoneBuiltIn]`，但 `AVAudioEngine.inputNode` 的 format 是 0Hz/0ch，
  /// 於是 `installTap` 一定 SIGABRT。原生探針讀的就是那個 format 本身，
  /// 與 record 的實際前置條件一字不差，不是猜的代理訊號。
  ///
  /// Android／Web 沒有這個幽靈問題，用 `listInputDevices()` 即可：
  /// Android 走 `AudioManager.getDevices(GET_DEVICES_INPUTS)`、
  /// Web 走 `enumerateDevices()`（`--use-fake-device-for-media-stream` 下有裝置）。
  /// 原生探針缺席（理論上不會發生）時退回同一條路，也就是維持修復前的行為。
  @override
  Future<bool> hasUsableInput() async {
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.iOS) {
      try {
        final usable = await _iosProbe.invokeMethod<bool>('hasUsableInput');
        if (usable != null) return usable;
      } catch (_) {
        // 探針沒註冊或失敗 → 落到下面的裝置列舉。
      }
    }
    final devices = await _recorder.listInputDevices();
    return devices.isNotEmpty;
  }

  @override
  Future<Stream<Uint8List>> startStream(RecordConfig config) => _recorder.startStream(config);

  @override
  Future<bool> isRecording() => _recorder.isRecording();

  @override
  Future<void> stop() => _recorder.stop(); // 回傳的檔名沒人讀（stream 模式一律 null）

  @override
  Future<void> dispose() => _recorder.dispose();
}

class AudioStreamService {
  AudioStreamService({this.disableAgc = false, MicRecorder? recorder})
      : _recorder = recorder ?? RecordMicRecorder();
  final bool disableAgc;

  final MicRecorder _recorder;
  AudioStreamCallbacks _cb = const AudioStreamCallbacks();
  StreamSubscription<Uint8List>? _sub;
  PcmRingBuffer? _ring;
  Timer? _durationTimer;

  bool _vadEnabled = false;
  MuteMode _muteMode = MuteMode.none;
  bool _isSpeaking = false;
  bool _capturingPcm = false;
  List<Int16List> _liveFrames = [];

  int _candidateStartAt = 0;
  int _lastAboveThresholdAt = 0;
  int _segmentStartAt = 0;
  // ponytail: the web activeSegmentId late-chunk guard is unnecessary here — native
  // encoding inside _endSegment is synchronous, so no stale deferred emit can exist.
  // Re-add if a web/async capture path is ever introduced.

  bool get isRecording => _isSpeaking;

  int get _now => DateTime.now().millisecondsSinceEpoch;

  /// 開麥。失敗時**一定**拋例外，呼叫端要自己決定降級策略（見
  /// [MicUnavailableException]）——絕對不要讓它擋住 WebSocket 連線：
  /// 沒有麥克風時病患仍然可以用文字走完整條問診管線。
  Future<void> openMic(AudioStreamCallbacks callbacks) async {
    _cb = callbacks;
    if (_sub != null) return; // idempotent: already streaming, just swapped callbacks
    // 權限與「有沒有可用輸入」都必須在 startStream 之前解決，而且順序固定：
    // 先權限（iOS/web 未授權時裝置列舉本來就不可靠），再問輸入。
    if (!await _recorder.hasPermission()) {
      throw const MicUnavailableException(MicUnavailableReason.permissionDenied);
    }
    if (!await _recorder.hasUsableInput()) {
      // 缺陷 A：這一步就是那個 blocker 的全部。少了它，宿主機沒有音訊輸入時
      // 下面那行 startStream 會在原生層 SIGABRT，Dart 一點機會都沒有。
      throw const MicUnavailableException(MicUnavailableReason.noInputDevice);
    }
    try {
      final stream = await _recorder.startStream(RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: _sampleRate,
        numChannels: 1,
        echoCancel: true,
        noiseSuppress: true,
        autoGain: !disableAgc,
      ));
      _ring = PcmRingBuffer(_ringSamples);
      _vadEnabled = true;
      _muteMode = MuteMode.none;
      _isSpeaking = false;
      _candidateStartAt = 0;
      _lastAboveThresholdAt = _now;
      _sub = stream.listen(_onFrame, onError: (e) => _cb.onError?.call(e));
    } catch (_) {
      // 開啟階段的失敗只走「拋出」這一條路，不再同時打 `onError`：同一個失敗經由兩
      // 條通道回報，呼叫端會同時降級**又**寫一則永不清除的 `state.error`（缺陷 B）。
      // 開起來之後的執行期錯誤仍然走 `onError`（上一行的 stream onError）。
      await _cleanup();
      rethrow;
    }
  }

  void closeMic() {
    _vadEnabled = false;
    if (_isSpeaking) _endSegment(notify: false); // teardown: no WAV, no onSpeechEnd
    unawaited(_cleanup());
  }

  /// Current mute mode. The controller needs it to tell a leaked hard lock (re-assert)
  /// from a deliberate soft-mute barge-in (let it through).
  MuteMode get muteMode => _muteMode;

  void setMuted(bool muted, {MuteMode mode = MuteMode.hard}) {
    final next = muted ? mode : MuteMode.none;
    if (next == _muteMode) return;
    final prev = _muteMode;
    _muteMode = next;

    // Entering hard while a segment is open -> end it (notify).
    if (next == MuteMode.hard && _isSpeaking) {
      _endSegment(notify: true);
      return;
    }
    // Entering none, OR hard->soft: reset speaking state WITHOUT endSegment, and drop
    // any in-flight capture so no orphan PCM leaks into the next utterance.
    if (next == MuteMode.none || (prev == MuteMode.hard && next == MuteMode.soft)) {
      _isSpeaking = false;
      _candidateStartAt = 0;
      _lastAboveThresholdAt = _now;
      _capturingPcm = false;
      _liveFrames = [];
    }
  }

  void forceEndSegment() {
    if (_isSpeaking) _endSegment(notify: true);
  }

  // ---- internals ----

  void _onFrame(Uint8List bytes) {
    // Frame data is transient — copy into an owned Int16List (record PCM16 is LE).
    final n = bytes.lengthInBytes ~/ 2;
    final frame = Int16List(n);
    final bd = ByteData.sublistView(bytes);
    for (var i = 0; i < n; i++) {
      frame[i] = bd.getInt16(i * 2, Endian.little);
    }

    _ring?.write(frame);
    if (_capturingPcm) _liveFrames.add(frame);
    _emitWaveform(frame);
    if (_vadEnabled) _processVad(pcmRms(frame));
  }

  // Waveform emission is cosmetic-only; VAD reads every raw frame regardless (see
  // `_onFrame` — `_processVad` must stay outside this throttle or speech onset is
  // missed and the patient's first words are cut).
  static const _waveformBars = 32;
  static const _waveformMinIntervalMs = 50;
  int _lastWaveformAt = 0;
  bool _waveformSilenced = false;
  int _lastEmittedWholeSecond = 0;

  void _processVad(double rms) {
    if (_muteMode == MuteMode.hard) return; // no detection at all
    final effective = _muteMode == MuteMode.soft ? _bargeInThreshold : _threshold;

    if (rms > effective) {
      if (_isSpeaking) {
        _lastAboveThresholdAt = _now;
      } else {
        if (_candidateStartAt == 0) _candidateStartAt = _now;
        if (_now - _candidateStartAt >= _minSpeechMs) _beginSegment();
      }
    } else {
      if (_isSpeaking) {
        if (_now - _lastAboveThresholdAt >= _silenceEndMs) _endSegment(notify: true);
      } else {
        _candidateStartAt = 0;
      }
    }
  }

  void _beginSegment() {
    if (_isSpeaking || _sub == null) return;
    _isSpeaking = true;
    _segmentStartAt = _now;
    _lastAboveThresholdAt = _now;
    final preroll = _ring?.readLast(_preRollSamples) ?? Int16List(0);
    _liveFrames = preroll.isNotEmpty ? [preroll] : [];
    _capturingPcm = true;
    // 100 ms cadence is kept so the counter never looks like it skipped a second, but
    // only whole-second changes are pushed. conversation_page.dart:364 renders this with
    // `toStringAsFixed(0)`, so nine of every ten emissions produced a byte-identical
    // string — and each one wrote ConversationState, which the page watches whole, so
    // each one rebuilt the entire intake screen for nothing.
    _lastEmittedWholeSecond = 0;
    _durationTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      final elapsed = (_now - _segmentStartAt) / 1000.0;
      final whole = elapsed.floor();
      if (whole == _lastEmittedWholeSecond) return;
      _lastEmittedWholeSecond = whole;
      _cb.onDurationUpdate?.call(elapsed);
    });
    _cb.onSpeechStart?.call();
  }

  void _endSegment({required bool notify}) {
    if (!_isSpeaking) return;
    _isSpeaking = false;
    _candidateStartAt = 0;
    _ring?.clear(); // drop trailing tail so it can't pollute the next pre-roll
    _durationTimer?.cancel();
    _durationTimer = null;
    _lastEmittedWholeSecond = 0;
    _cb.onDurationUpdate?.call(0);

    _capturingPcm = false;
    final frames = _liveFrames;
    _liveFrames = [];

    if (!notify) return; // teardown: drop silently
    final totalSamples = frames.fold<int>(0, (n, f) => n + f.length);
    if (totalSamples > 0) {
      _cb.onChunk?.call(bytesToBase64(encodeWav(frames, _sampleRate)), 0);
    }
    _cb.onSpeechEnd?.call(); // even for empty utterance, so the consumer re-arms VAD
  }

  void _emitWaveform(Int16List frame) {
    final cb = _cb.onWaveformData;
    if (cb == null || frame.isEmpty) return;

    // Hard mute means the AI is speaking: `_processVad` returns immediately, so
    // whatever the mic hears here is speaker echo. Drawing it is meaningless, and it is
    // also the app's most expensive UI write — one whole-page rebuild per mic buffer
    // (~47/s on iOS, where `record_ios` taps 1024 frames at the 48 kHz input rate).
    // Flush one flat frame first so the bars settle instead of freezing mid-shape.
    if (_muteMode == MuteMode.hard) {
      if (!_waveformSilenced) {
        _waveformSilenced = true;
        cb(List<double>.filled(_waveformBars, 0));
      }
      return;
    }
    _waveformSilenced = false;

    // 20 Hz is past the point where more frames read as smoother motion, and every
    // extra frame is a full rebuild of the intake screen while the patient is talking —
    // which is exactly when they are watching it and tapping 「我說完了」.
    final now = _now;
    if (now - _lastWaveformAt < _waveformMinIntervalMs) return;
    _lastWaveformAt = now;

    const bars = _waveformBars;
    final out = List<double>.filled(bars, 0);
    final bucket = (frame.length / bars).ceil();
    for (var b = 0; b < bars; b++) {
      var peak = 0.0;
      final start = b * bucket;
      for (var i = start; i < start + bucket && i < frame.length; i++) {
        final a = frame[i].abs() / 32768.0;
        if (a > peak) peak = a;
      }
      out[b] = peak;
    }
    cb(out);
  }

  Future<void> _cleanup() async {
    await _sub?.cancel();
    _sub = null;
    try {
      if (await _recorder.isRecording()) await _recorder.stop();
    } catch (_) {}
    _ring = null;
    _liveFrames = [];
    _capturingPcm = false;
    _isSpeaking = false;
    _durationTimer?.cancel();
    _durationTimer = null;
  }

  Future<void> dispose() async {
    await _cleanup();
    await _recorder.dispose();
  }
}
