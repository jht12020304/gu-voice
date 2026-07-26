import 'dart:async';
import 'dart:math';
import 'dart:typed_data';

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

class AudioStreamService {
  AudioStreamService({this.disableAgc = false});
  final bool disableAgc;

  final _recorder = AudioRecorder();
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

  Future<void> openMic(AudioStreamCallbacks callbacks) async {
    _cb = callbacks;
    if (_sub != null) return; // idempotent: already streaming, just swapped callbacks
    try {
      if (!await _recorder.hasPermission()) {
        throw StateError('microphone permission denied');
      }
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
    } catch (e) {
      await _cleanup();
      _cb.onError?.call(e);
      rethrow;
    }
  }

  void closeMic() {
    _vadEnabled = false;
    if (_isSpeaking) _endSegment(notify: false); // teardown: no WAV, no onSpeechEnd
    unawaited(_cleanup());
  }

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
    _durationTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      _cb.onDurationUpdate?.call((_now - _segmentStartAt) / 1000.0);
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
    const bars = 32;
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
