import 'dart:typed_data';

// Verbatim port of frontend/src/services/pcmRingBuffer.ts.
// Keeps only the most-recent `capacity` samples (ring-overwrites oldest). Used to
// prepend ~0.4s of pre-roll before detected speech so the utterance onset isn't clipped.
//
// Native `record` streams PCM16, so this holds Int16 samples directly (the TS Float32
// path is the web-only concern we defer). capacity = sampleRate * preRollSeconds.
class PcmRingBuffer {
  final Int16List _buf;
  final int capacity;
  int _writePos = 0;
  int _filled = 0;

  PcmRingBuffer(this.capacity) : _buf = Int16List(capacity) {
    if (capacity <= 0) {
      throw ArgumentError('PcmRingBuffer capacity must be a positive integer');
    }
  }

  void write(Int16List samples) {
    for (var i = 0; i < samples.length; i++) {
      _buf[_writePos] = samples[i];
      _writePos = (_writePos + 1) % capacity;
      if (_filled < capacity) _filled++;
    }
  }

  int available() => _filled;

  /// Most-recent `n` samples in time order (old -> new). Non-destructive.
  Int16List readLast(int n) {
    final count = n < _filled ? n : _filled;
    final out = Int16List(count);
    if (count == 0) return out;
    final start = (_writePos - count) % capacity; // Dart % is non-negative for positive divisor
    for (var i = 0; i < count; i++) {
      out[i] = _buf[(start + i) % capacity];
    }
    return out;
  }

  void clear() {
    _writePos = 0;
    _filled = 0;
  }
}
