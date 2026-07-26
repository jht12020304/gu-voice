// ignore_for_file: experimental_member_use — just_audio's StreamAudioSource (bytes
// playback without temp files) is the intended API; the experimental tag is upstream.
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:just_audio/just_audio.dart';

// Port of the ConversationPage TTS chain (ttsChainRef + ttsEpochRef) onto ONE just_audio
// player. Sentences play strictly sequentially; the epoch counter is the load-bearing
// cancel primitive — a sentence or tail enqueued before clearQueue() must never
// play/release afterward. stopActive() force-completes the in-flight step so the chain
// always advances (prevents the VAD deadlock the web onended-fire fixes).
class TtsPlaybackController {
  TtsPlaybackController({required this.speed});

  // Read fresh at play time so a mid-turn speed change applies to later sentences.
  final double Function() speed;

  final AudioPlayer _player = AudioPlayer();
  int _epoch = 0;
  Future<void> _chain = Future.value();
  Completer<void>? _activeStep;

  int get epoch => _epoch;

  void enqueue(String b64) {
    final e = _epoch;
    _chain = _chain.then((_) => _playStep(b64, e)).catchError((_) {});
  }

  // Append a tail step (turn-end / replay-end unmute). Runs after every queued sentence,
  // but only fires onRelease if the epoch it captured is still current (a newer owner
  // taking over bumps the epoch and this stale tail must NOT punch through its lock).
  void appendTail(int capturedEpoch, void Function() onRelease) {
    _chain = _chain.then((_) {
      if (_epoch == capturedEpoch) onRelease();
    }).catchError((_) {});
  }

  void clearQueue() {
    _epoch++;
    _chain = Future.value();
  }

  Future<void> stopActive() async {
    // Capture BEFORE the await. `_player.stop()` yields, and if the player-state
    // listener completes the current step in that gap, `_chain` advances and the next
    // `_playStep` reassigns `_activeStep` — reading it afterwards would complete the
    // NEW step, firing its `appendTail` onRelease (the VAD unlock) while that audio is
    // still playing, and leaking the original completer so the chain never advances
    // (VAD deadlock). Invariants #3/#5. (TODO G4)
    final s = _activeStep;
    _activeStep = null;
    try {
      await _player.stop();
    } catch (_) {}
    // Still force-complete: invariant #5 — an interrupted step MUST release the chain.
    if (s != null && !s.isCompleted) s.complete();
  }

  Future<void> _playStep(String b64, int e) async {
    if (_epoch != e) return;
    final Uint8List bytes = base64Decode(b64);
    if (_epoch != e) return; // decode is async; a mute/barge-in may have landed

    final done = Completer<void>();
    _activeStep = done;
    StreamSubscription? sub;
    try {
      await _player.setAudioSource(_BytesAudioSource(bytes));
      if (_epoch != e) {
        if (!done.isCompleted) done.complete();
        return;
      }
      await _player.setSpeed(speed().clamp(0.5, 1.5));
      sub = _player.playerStateStream.listen((s) {
        if (s.processingState == ProcessingState.completed && !done.isCompleted) {
          done.complete();
        }
      });
      unawaited(_player.play());
      await done.future; // resolves on natural completion OR stopActive()
    } catch (_) {
      if (!done.isCompleted) done.complete();
    } finally {
      await sub?.cancel();
      _activeStep = null;
    }
  }

  Future<void> dispose() async {
    clearQueue();
    await _player.dispose();
  }
}

// Feeds in-memory MP3 bytes to just_audio without temp files or data: URLs.
class _BytesAudioSource extends StreamAudioSource {
  _BytesAudioSource(this._bytes);
  final Uint8List _bytes;

  @override
  Future<StreamAudioResponse> request([int? start, int? end]) async {
    start ??= 0;
    end ??= _bytes.length;
    return StreamAudioResponse(
      sourceLength: _bytes.length,
      contentLength: end - start,
      offset: start,
      stream: Stream.value(_bytes.sublist(start, end)),
      contentType: 'audio/mpeg',
    );
  }
}
