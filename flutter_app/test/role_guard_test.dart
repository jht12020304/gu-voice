// 角色守衛（2026-08-22 平台分工推翻後的權威測試）。
//
// 歷史：這個檔取代 ios_doctor_platform_gate_test.dart。舊檔釘的是 2026-08-20 的分工
// （iOS＝醫師專用、問診整片關閉），該分工於 2026-08-22 被產品推翻——iOS 成為唯一 App，
// kiosk iPad 跑病患語音問診，醫師用自己的裝置跑同一顆。平台閘門拆除，這裡釘新規則：
//
//   1. 角色守衛與平台無關：病患進不了醫師/admin 區——**包括 `/patients`**（醫師的
//      病患清單）。舊版 `startsWith('/patient')` 會把它誤放行，病患能讀全院病歷；
//      這個洞在 iOS 上一直被平台閘門蓋住，拆閘門前必須先修，這裡就是釘子。
//   2. 醫師 landing 依平台：原生→/notifications（開 App 是看有沒有新報告），web→/dashboard。
//   3. 問診區在**所有**平台開放（這正是這次推翻的內容）。
//   4. 已刪除的 patient-unsupported 路徑當作不存在（舊推播/書籤可能還存著）。

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/core/router/route_guard.dart';

void main() {
  String? go(
    String path, {
    bool native = false,
    String role = 'doctor',
    bool authed = true,
  }) =>
      resolveGuardRedirect(
        path: path,
        lng: extractLngFromPath(path) ?? defaultLanguage,
        rest: stripLngFromPath(path),
        isAuthenticated: authed,
        isPatient: role == 'patient',
        isAdmin: role == 'admin',
        nativeMobile: native,
      );

  group('isNativeMobile', () {
    tearDown(() => debugDefaultTargetPlatformOverride = null);

    test('iOS 與 Android 都算原生行動平台', () {
      for (final p in [TargetPlatform.iOS, TargetPlatform.android]) {
        debugDefaultTargetPlatformOverride = p;
        expect(isNativeMobile, isTrue, reason: '$p');
      }
    });

    test('桌面平台不算', () {
      for (final p in [TargetPlatform.macOS, TargetPlatform.windows, TargetPlatform.linux]) {
        debugDefaultTargetPlatformOverride = p;
        expect(isNativeMobile, isFalse, reason: '$p');
      }
    });

    test('判斷式含 !kIsWeb —— iPad Safari 的 kiosk 網頁也回報 TargetPlatform.iOS', () {
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
      expect(isNativeMobile, !kIsWeb);
    });
  });

  group('問診區在所有平台開放（2026-08-22 推翻的核心）', () {
    test('病患在原生 App 走完整問診流程', () {
      for (final r in ['/patient', '/patient/start', '/patient/medical-info', '/conversation/abc']) {
        expect(go('/zh-TW$r', role: 'patient', native: true), isNull, reason: '$r 必須放行');
      }
    });

    test('病患 landing 一律是病患首頁，不再有提示頁', () {
      expect(go('/zh-TW/login', role: 'patient', native: true), '/zh-TW/patient');
      expect(go('/zh-TW', role: 'patient', native: true), '/zh-TW/patient');
    });

    test('五種語言前綴一致', () {
      for (final lng in supportedLanguages) {
        expect(go('/$lng/patient/start', role: 'patient', native: true), isNull);
      }
    });
  });

  group('角色守衛：病患進不了醫師/admin 區（與平台無關）', () {
    for (final native in [true, false]) {
      final label = native ? '原生' : 'web';

      test('[$label] 醫師/admin 區一律擋掉', () {
        for (final r in ['/dashboard', '/reports', '/sessions', '/alerts', '/notifications', '/admin/users']) {
          expect(go('/zh-TW$r', role: 'patient', native: native), '/zh-TW/patient',
              reason: '$r 不得讓病患進入');
        }
      });

      test('[$label] ⚠️ /patients 是醫師的病患清單，不是病患自己的區域', () {
        // 舊版 startsWith('/patient') 在這裡誤放行 —— 病患能讀全院病患姓名與病歷。
        // 平台閘門拆掉之後這一條是唯一防線，回歸測試釘死。
        expect(go('/zh-TW/patients', role: 'patient', native: native), '/zh-TW/patient');
        expect(go('/zh-TW/patients/some-id', role: 'patient', native: native), '/zh-TW/patient');
      });

      test('[$label] 病患自己的區域照常', () {
        for (final r in ['/patient', '/patient/history', '/conversation/xyz']) {
          expect(go('/zh-TW$r', role: 'patient', native: native), isNull, reason: r);
        }
      });
    }

    test('admin 子樹：醫師＝管理員（2026-08-22 拍板），病患仍然進不來', () {
      // 本診所的醫師就是管理者；後端 admin router 同步收 doctor。
      expect(go('/zh-TW/admin/users', role: 'doctor'), isNull);
      expect(go('/zh-TW/admin/users', role: 'admin'), isNull);
      // 病患被自己的區域限制擋住（不是靠 admin 條件）——這條是 PHI 防線，釘死。
      expect(go('/zh-TW/admin/users', role: 'patient'), '/zh-TW/patient');
      expect(go('/zh-TW/admin', role: 'patient'), '/zh-TW/patient');
    });
  });

  group('醫師 landing 依平台', () {
    test('原生 → 通知頁（開 App 是看有沒有新報告，不是看統計）', () {
      expect(go('/zh-TW/login', native: true), '/zh-TW/notifications');
      expect(go('/zh-TW', native: true), '/zh-TW/notifications');
    });

    test('web（過渡期）→ dashboard，行為不變', () {
      expect(go('/zh-TW/login', native: false), '/zh-TW/dashboard');
      expect(go('/zh-TW', native: false), '/zh-TW/dashboard');
    });

    test('醫師端各頁在兩種平台都可進', () {
      for (final native in [true, false]) {
        for (final r in ['/reports', '/sessions', '/patients', '/alerts', '/notifications', '/dashboard']) {
          expect(go('/zh-TW$r', native: native), isNull, reason: '$r native=$native');
        }
      }
    });

    test('醫師也能進問診區（協助病患操作 kiosk 的情境）', () {
      expect(go('/zh-TW/conversation/abc', native: true), isNull);
    });
  });

  group('已刪除的提示頁路徑', () {
    test('舊書籤/推播存的 /patient-unsupported 當作不存在，導回角色 landing', () {
      expect(go('/zh-TW/patient-unsupported', role: 'patient', native: true), '/zh-TW/patient');
      expect(go('/zh-TW/patient-unsupported', role: 'doctor', native: true), '/zh-TW/notifications');
      expect(go('/zh-TW/patient-unsupported', role: 'doctor', native: false), '/zh-TW/dashboard');
    });
  });

  group('未登入', () {
    test('公開頁放行，其餘導登入', () {
      expect(go('/zh-TW/login', authed: false), isNull);
      // 登入頁上有「建立新帳號」按鈕；register 不公開的話那顆按鈕就是死路。
      expect(go('/zh-TW/register', authed: false), isNull);
      expect(go('/zh-TW/forgot-password', authed: false), isNull);
      expect(go('/zh-TW/reset-password?x=1', authed: false, native: true), isNull);
      expect(go('/zh-TW/patient', authed: false, native: true), '/zh-TW/login');
      expect(go('/zh-TW/notifications', authed: false, native: true), '/zh-TW/login');
    });
  });
}
