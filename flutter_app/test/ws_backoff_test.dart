// Reconnect backoff + permanent-close decisions (TODO §G "測試深度").
// `ws_manager` had zero assertions; both of these fail silently in production —
// wrong backoff either hammers the backend or stops reconnecting, and a missed
// permanent code retries a rejection forever.

import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/features/voice/services/ws_manager.dart';

void main() {
  group('wsRetryDelayMs', () {
    int d(int n) => wsRetryDelayMs(retryCount: n, initialMs: 1000, maxMs: 30000);

    test('doubles from the initial delay: 1s, 2s, 4s, 8s, 16s', () {
      expect([d(0), d(1), d(2), d(3), d(4)], [1000, 2000, 4000, 8000, 16000]);
    });

    test('clamps at maxMs instead of growing without bound', () {
      expect(d(5), 30000, reason: '32s 應被夾到 30s');
      expect(d(6), 30000);
      expect(d(20), 30000);
    });

    test('never returns 0 for the first attempt (would hammer the backend)', () {
      expect(d(0), greaterThan(0));
    });

    test('a huge retryCount cannot overflow the shift into a negative delay', () {
      // 1 << 63 wraps negative; without the guard the multiplication goes negative
      // before clamp() ever sees it.
      expect(d(31), 30000);
      expect(d(64), 30000);
      expect(d(1000), 30000);
    });

    test('a negative count degrades to the initial delay, not a crash', () {
      expect(d(-1), 1000);
    });
  });

  group('isPermanentCloseCode', () {
    test('4003 forbidden_role is permanent — retrying spams a rejection', () {
      expect(isPermanentCloseCode(4003, const {4003}), isTrue);
    });

    test('other codes reconnect', () {
      expect(isPermanentCloseCode(1006, const {4003}), isFalse);
      expect(isPermanentCloseCode(4001, const {4003}), isFalse,
          reason: '4001 是 auth 失敗，有專屬的 refresh-then-retry 復原路徑');
    });

    test('a missing code means an abrupt drop → reconnect', () {
      expect(isPermanentCloseCode(null, const {4003}), isFalse);
    });

    test('an empty permanent set never blocks reconnects', () {
      expect(isPermanentCloseCode(4003, const {}), isFalse);
    });
  });
}
