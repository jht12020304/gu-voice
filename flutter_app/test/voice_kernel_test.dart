import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/features/voice/services/audio_stream_service.dart';
import 'package:gu_voice/features/voice/services/pcm_ring_buffer.dart';
import 'package:gu_voice/features/voice/services/wav_encoder.dart';
import 'package:gu_voice/features/voice/state/vad_logic.dart';

// Independent expected-table (mirrors shouldUnmuteVAD.test.mts) so the test doesn't
// just restate the implementation.
bool _expected(VadResumeTrigger t, VadResumeContext c) {
  if (t == VadResumeTrigger.reconnected) return !c.userPaused;
  if (t == VadResumeTrigger.userResume) return !c.aiTurnLocked && !c.wsDown;
  if (t == VadResumeTrigger.replayEnd) {
    return !c.userPaused && !c.aiTurnLocked && !c.wsDown;
  }
  return !c.userPaused && !c.wsDown;
}

void main() {
  group('shouldUnmuteVAD matrix', () {
    test('exhaustive 8 triggers x 2^3 ctx = 64 combinations', () {
      var count = 0;
      for (final t in VadResumeTrigger.values) {
        for (final userPaused in [false, true]) {
          for (final aiTurnLocked in [false, true]) {
            for (final wsDown in [false, true]) {
              final ctx = VadResumeContext(
                  userPaused: userPaused, aiTurnLocked: aiTurnLocked, wsDown: wsDown);
              expect(shouldUnmuteVAD(t, ctx), _expected(t, ctx), reason: '$t $userPaused$aiTurnLocked$wsDown');
              count++;
            }
          }
        }
      }
      expect(count, 64);
    });

    test('named invariants', () {
      const clear = VadResumeContext(userPaused: false, aiTurnLocked: false, wsDown: false);
      // (a) manual pause blocks AI-turn-done auto-open
      expect(shouldUnmuteVAD(VadResumeTrigger.aiTtsDone,
          const VadResumeContext(userPaused: true, aiTurnLocked: false, wsDown: false)), false);
      // (b) user_resume must NOT break the AI hard-lock
      expect(shouldUnmuteVAD(VadResumeTrigger.userResume,
          const VadResumeContext(userPaused: false, aiTurnLocked: true, wsDown: false)), false);
      // (c) paused + reconnected stays paused
      expect(shouldUnmuteVAD(VadResumeTrigger.reconnected,
          const VadResumeContext(userPaused: true, aiTurnLocked: false, wsDown: false)), false);
      // (d) no blockers -> every trigger unmutes (no path stuck muted)
      for (final t in VadResumeTrigger.values) {
        expect(shouldUnmuteVAD(t, clear), true, reason: '$t');
      }
      // (e) replay_end yields to a still-running AI turn
      expect(shouldUnmuteVAD(VadResumeTrigger.replayEnd,
          const VadResumeContext(userPaused: false, aiTurnLocked: true, wsDown: false)), false);
    });
  });

  test('normalizeSupervisorGuidance defaults and passthrough', () {
    expect(normalizeSupervisorGuidance(null), isNull);
    final g = normalizeSupervisorGuidance({'next_focus': 'hpi', 'missing_hpi': ['onset'], 'fallback': true})!;
    expect(g.nextFocus, 'hpi');
    expect(g.missingHpi, ['onset']);
    expect(g.hpiCompletionPercentage, 0); // absent -> 0
    expect(g.fallback, true);
  });

  group('PcmRingBuffer', () {
    test('readLast returns most-recent samples in time order with wraparound', () {
      final rb = PcmRingBuffer(4);
      rb.write(Int16List.fromList([1, 2, 3, 4, 5, 6])); // 5,6 overwrite 1,2
      expect(rb.available(), 4);
      expect(rb.readLast(4).toList(), [3, 4, 5, 6]);
      expect(rb.readLast(2).toList(), [5, 6]);
      expect(rb.readLast(99).toList(), [3, 4, 5, 6]); // clamps to available
    });
    test('clear resets', () {
      final rb = PcmRingBuffer(4)..write(Int16List.fromList([1, 2, 3]));
      rb.clear();
      expect(rb.available(), 0);
      expect(rb.readLast(4).toList(), isEmpty);
    });
  });

  test('pcmRms domain 0..1 lines up with the VAD thresholds', () {
    expect(pcmRms(Int16List.fromList([0, 0, 0, 0])), 0);
    expect(pcmRms(Int16List.fromList(List.filled(100, 32767))), closeTo(1.0, 0.001));
    expect(pcmRms(Int16List.fromList(List.filled(100, 16384))), closeTo(0.5, 0.001));
    expect(pcmRms(Int16List.fromList(List.filled(100, 500))) < 0.035, true); // quiet < gate
  });

  test('encodeWav writes a RIFF/WAVE 16-bit header at the real sample rate', () {
    final wav = encodeWav([Int16List.fromList([0, 100, -100])], 16000);
    // magic: backend sniffs leading 'RIFF'
    expect(String.fromCharCodes(wav.sublist(0, 4)), 'RIFF');
    expect(String.fromCharCodes(wav.sublist(8, 12)), 'WAVE');
    final view = ByteData.view(wav.buffer);
    expect(view.getUint32(24, Endian.little), 16000); // sample rate in header (load-bearing)
    expect(view.getUint16(34, Endian.little), 16); // bits per sample
    expect(view.getUint32(40, Endian.little), 6); // data bytes = 3 samples * 2
    expect(wav.length, 44 + 6);
    expect(view.getInt16(44 + 2, Endian.little), 100); // second sample round-trips
  });
}
