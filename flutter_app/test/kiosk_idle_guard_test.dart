// The three guards on the kiosk idle timer (TODO G11). Each one, if wrong, fails
// silently in a way nobody notices until it hurts someone:
//   - wrong role        → a doctor gets logged out mid report review
//   - no /conversation  → a live voice consultation is killed under the patient
//   - env switch missed → a doctor's laptop inherits kiosk auto-logout

import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/features/patient/kiosk_idle_guard.dart';

void main() {
  bool arm({
    int timeout = 180,
    bool authed = true,
    bool patient = true,
    String location = '/zh-TW/patient',
  }) =>
      shouldArmKioskIdleTimer(
        timeoutSeconds: timeout,
        isAuthenticated: authed,
        isPatient: patient,
        location: location,
      );

  group('kiosk idle timer guards', () {
    test('armed for an authenticated patient outside the conversation', () {
      expect(arm(), isTrue);
      expect(arm(location: '/en-US/patient/medical-info'), isTrue);
      expect(arm(location: '/vi-VN/patient/history'), isTrue);
    });

    test('timeout of 0 disables it entirely', () {
      expect(arm(timeout: 0), isFalse);
      expect(arm(timeout: -1), isFalse);
    });

    test('never for anonymous or non-patient roles', () {
      expect(arm(authed: false), isFalse);
      expect(arm(patient: false), isFalse,
          reason: '醫師/管理員不可被閒置登出——審報告會被打斷');
    });

    test('never during a consultation, in any language prefix', () {
      for (final lng in ['zh-TW', 'en-US', 'ja-JP', 'ko-KR', 'vi-VN']) {
        expect(arm(location: '/$lng/conversation/abc-123'), isFalse,
            reason: '語音問診中病患可能長時間不觸控螢幕，登出會殺掉進行中的問診');
      }
    });

    test('a path merely containing the word conversation is NOT exempt', () {
      // Guard against a sloppier `contains('conversation')` that would exempt
      // unrelated routes and quietly disable the whole feature there.
      expect(arm(location: '/zh-TW/patient/conversations-archive'), isTrue);
    });
  });
}
