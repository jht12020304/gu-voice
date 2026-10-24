// Native AOT host benchmark; this does not measure iPhone frames or microphone I/O.
// fvm dart compile exe tool/voice_encode_benchmark.dart -o /tmp/gu-voice-encode
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:gu_voice/features/voice/services/wav_encoder.dart';

void main() {
  final result = <Map<String, Object>>[];
  for (final seconds in [10, 30, 60]) {
    final frames = List.generate(seconds * 50, (_) => Int16List(320));
    final times = <int>[];
    var bytes = 0;
    for (var i = 0; i < 35; i++) {
      final watch = Stopwatch()..start();
      final encoded = bytesToBase64(encodeWav(frames, 16000));
      watch.stop();
      bytes = encoded.length;
      if (i >= 5) times.add(watch.elapsedMicroseconds);
    }
    times.sort();
    result.add({
      'seconds': seconds,
      'samples': times.length,
      'base64_bytes': bytes,
      'p50_ms': times[times.length ~/ 2] / 1000,
      'p95_ms': times[(times.length * .95).ceil() - 1] / 1000,
    });
  }
  stdout.writeln(jsonEncode(result));
}
