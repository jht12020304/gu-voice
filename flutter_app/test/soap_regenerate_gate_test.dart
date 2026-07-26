// The "generate report" gate (TODO §G medium). The old rule keyed off mere existence of
// a report row, so a FAILED generation could never be retried — the button disappeared
// and the doctor had no way to get a report for that consultation at all.

import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/features/doctor/screens/session_detail_page.dart';

void main() {
  bool can(String session, String? report) =>
      canGenerateSoapReport(sessionStatus: session, reportStatus: report);

  group('canGenerateSoapReport', () {
    test('offered for a completed session with no report yet', () {
      expect(can('completed', null), isTrue);
    });

    test('offered again after a FAILED generation — this was the dead end', () {
      expect(can('completed', 'failed'), isTrue);
    });

    test('not offered while generating (avoid double-dispatching the Celery task)', () {
      expect(can('completed', 'generating'), isFalse);
    });

    test('not offered once generated', () {
      expect(can('completed', 'generated'), isFalse);
    });

    test('never offered for a non-terminal or aborted session', () {
      for (final st in ['waiting', 'in_progress', 'cancelled', 'aborted_red_flag']) {
        expect(can(st, null), isFalse, reason: '$st 不該能產生報告');
      }
    });
  });
}
