import 'dart:convert';
import 'dart:typed_data';

// Port of frontend/src/services/wavEncoder.ts. Concatenates PCM16 frames into a single
// 44-byte-header RIFF/WAVE mono WAV. Backend sniffs only the leading 'RIFF' magic
// (conversation_handler.py _AUDIO_MAGIC_WAV); Whisper decodes WAV natively.
//
// LOAD-BEARING INVARIANT: sampleRate MUST equal the real capture rate or Whisper hears
// pitch/speed-shifted audio. Native `record` gives PCM16 at the rate we requested
// (16000), so we pass that same rate here — no getUserMedia hint mismatch.
Uint8List encodeWav(List<Int16List> frames, int sampleRate) {
  final totalSamples = frames.fold<int>(0, (n, f) => n + f.length);
  final dataBytes = totalSamples * 2; // 16-bit = 2 bytes/sample
  final bytes = Uint8List(44 + dataBytes);
  final view = ByteData.view(bytes.buffer);

  void writeAscii(int offset, String s) {
    for (var i = 0; i < s.length; i++) {
      view.setUint8(offset + i, s.codeUnitAt(i));
    }
  }

  const numChannels = 1;
  const bitsPerSample = 16;
  final byteRate = sampleRate * numChannels * bitsPerSample ~/ 8;
  const blockAlign = numChannels * bitsPerSample ~/ 8;

  // RIFF chunk descriptor
  writeAscii(0, 'RIFF');
  view.setUint32(4, 36 + dataBytes, Endian.little);
  writeAscii(8, 'WAVE');
  // fmt subchunk
  writeAscii(12, 'fmt ');
  view.setUint32(16, 16, Endian.little); // Subchunk1Size = 16 (PCM)
  view.setUint16(20, 1, Endian.little); // AudioFormat = 1 (PCM)
  view.setUint16(22, numChannels, Endian.little);
  view.setUint32(24, sampleRate, Endian.little);
  view.setUint32(28, byteRate, Endian.little);
  view.setUint16(32, blockAlign, Endian.little);
  view.setUint16(34, bitsPerSample, Endian.little);
  // data subchunk
  writeAscii(36, 'data');
  view.setUint32(40, dataBytes, Endian.little);

  // Samples are already Int16 (native PCM16) — write directly, no float clamp.
  var offset = 44;
  for (final frame in frames) {
    for (var i = 0; i < frame.length; i++) {
      view.setInt16(offset, frame[i], Endian.little);
      offset += 2;
    }
  }
  return bytes;
}

String bytesToBase64(Uint8List bytes) => base64Encode(bytes);
