import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/features/voice/services/audio_stream_service.dart';
import 'package:gu_voice/features/voice/services/pcm_ring_buffer.dart';
import 'package:gu_voice/features/voice/services/wav_encoder.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/features/voice/state/conversation_controller.dart';
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
  _languageSwitchPreservesQuery();
  _intakeFamilyHistory();
  _routerQueryPreservation();
  _blockerRegressions();
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

// ---------------------------------------------------------------------------
// Regressions for docs/TODO.md §G1 / §G2 (blockers found in the intake audit).
// ---------------------------------------------------------------------------

void _blockerRegressions() {
  group('G2: conversation controller must not outlive the page', () {
    test('provider is autoDispose, so each patient gets a fresh controller', () async {
      final container = ProviderContainer();
      addTearDown(container.dispose);

      final sub = container.listen(
        conversationControllerProvider,
        (_, _) {},
        fireImmediately: true,
      );
      final first = container.read(conversationControllerProvider.notifier);

      // Patient leaves the page: the last listener goes away.
      sub.close();
      await Future<void>.delayed(Duration.zero);

      // Next patient walks up to the same kiosk.
      final second = container.read(conversationControllerProvider.notifier);

      expect(
        second,
        isNot(same(first)),
        reason: 'controller survived page teardown → second patient would inherit '
            'the first patient session/transcript/red flags, and _started would '
            'make their start() a no-op. Keep the provider autoDispose.',
      );
      expect(container.read(conversationControllerProvider).session, isNull);
      expect(container.read(conversationControllerProvider).completed, isFalse);
    });
  });

  group('G1: red-flag abort must be observable with completion', () {
    test('the aborted transition carries both flags in one state', () {
      const running = ConversationState();
      expect(running.completed, isFalse);
      expect(running.abortedRedFlag, isFalse);

      // Mirrors _onSessionStatus's aborted_red_flag branch.
      final aborted = running.copyWith(completed: true, abortedRedFlag: true);

      // The page selects this exact projection; both fields must come off the same
      // emission, otherwise the listener reads a stale snapshot where
      // abortedRedFlag is still false and the patient gets the generic thank-you
      // page (+ its 8s auto-redirect home) instead of "tell the staff here".
      (bool, bool) project(ConversationState v) => (v.completed, v.abortedRedFlag);
      expect(project(aborted), (true, true));

      // A plain completion must NOT look like an abort.
      expect(project(running.copyWith(completed: true)), (true, false));
    });
  });
}

void _routerQueryPreservation() {
  group('G6: lng redirect must preserve query', () {
    // The redirect returns `state.uri.replace(path: prefixLngToPath(...)).toString()`.
    // Reproduce that projection here: returning a bare path (the old behaviour)
    // silently ate `?token=`, dead-ending the password-reset mail flow.
    String redirectTarget(String rawUri, String seed) {
      final uri = Uri.parse(rawUri);
      final path = uri.path;
      return uri.replace(path: prefixLngToPath(path == '/' ? '/' : path, seed)).toString();
    }

    test('reset-password token survives the lng prefix', () {
      expect(
        redirectTarget('/reset-password?token=abc123', 'zh-TW'),
        '/zh-TW/reset-password?token=abc123',
      );
    });

    test('multiple params and fragment survive', () {
      expect(
        redirectTarget('/patient?a=1&b=2#frag', 'en-US'),
        '/en-US/patient?a=1&b=2#frag',
      );
    });

    test('bare root still gets prefixed', () {
      expect(redirectTarget('/', 'ja-JP'), '/ja-JP');
    });

    test('a path with no query is unchanged apart from the prefix', () {
      expect(redirectTarget('/login', 'ko-KR'), '/ko-KR/login');
    });
  });
}

void _intakeFamilyHistory() {
  // Mirrors the payload projection in medical_info_page._submit(). Family history used to
  // be hardcoded `[]`, so a prostate-cancer family history could never reach the doctor
  // and "never asked" was indistinguishable from "patient denied it" (TODO G13).
  List<Map<String, String>> project(List<(String relation, String condition)> rows) => [
        for (final r in rows)
          if (r.$2.trim().isNotEmpty) {'relation': r.$1, 'condition': r.$2.trim()},
      ];

  group('G13: family history payload', () {
    test('rows reach the backend in {relation, condition} shape', () {
      expect(
        project([('father', 'Prostate cancer'), ('mother', '糖尿病')]),
        [
          {'relation': 'father', 'condition': 'Prostate cancer'},
          {'relation': 'mother', 'condition': '糖尿病'},
        ],
      );
    });

    test('blank and whitespace-only rows are dropped, not sent as empty strings', () {
      // Backend requires condition min_length=1 — sending "" would 422 the whole session.
      expect(project([('father', ''), ('sister', '   '), ('brother', 'BPH')]), [
        {'relation': 'brother', 'condition': 'BPH'},
      ]);
    });

    test('an untouched section still yields an empty list (not an error)', () {
      expect(project([]), isEmpty);
    });
  });
}

void _languageSwitchPreservesQuery() {
  // LanguageBar / patient settings both switch language by navigating to the same URI
  // under a new lng. Returning a bare path silently dropped query params — the same
  // class of bug as G6 (the reset-password token vanishing), just on a different edge.
  String switchTo(String rawUri, String lng) {
    final uri = Uri.parse(rawUri);
    return uri.replace(path: prefixLngToPath(uri.path, lng)).toString();
  }

  group('language switch keeps the rest of the URI', () {
    test('query params survive', () {
      expect(switchTo('/zh-TW/reset-password?token=abc', 'en-US'),
          '/en-US/reset-password?token=abc');
    });

    test('an already-prefixed path is re-prefixed, not double-prefixed', () {
      expect(switchTo('/zh-TW/patient/history', 'ja-JP'), '/ja-JP/patient/history');
    });

    test('root switches cleanly', () {
      expect(switchTo('/zh-TW', 'ko-KR'), '/ko-KR');
    });

    test('fragment survives too', () {
      expect(switchTo('/en-US/reports?page=2#top', 'vi-VN'), '/vi-VN/reports?page=2#top');
    });
  });
}
