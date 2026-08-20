// 平台分工的路由閘門：Web＝病患語音問診 kiosk，原生 iOS＝醫師專用 App（只看報告與通知）。
// 這層判斷錯任一邊的代價都是產品級的：
//   - iOS 沒擋住 /conversation → 醫師 App 出現一個沒有 kiosk 麥克風環境的問診頁
//   - iOS 病患落在 /patient    → 病患拿醫師 App 做問診，繞過現場流程
//   - 誤判 web（iPad Safari 的 kiosk 也回報 TargetPlatform.iOS）→ 現場病患被鎖在提示頁
// redirect 規則的權威是 route_guard.dart 的純函式，app_router 的 redirect 只是轉呼叫它。

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/app_router.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/core/router/route_guard.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/features/patient/patient_unsupported_page.dart';

void main() {
  // 三種角色 × 兩種平台的 redirect。回傳 null＝放行。
  String? go(
    String path, {
    bool ios = true,
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
        doctorOnlyPlatform: ios,
      );

  group('isDoctorOnlyPlatform', () {
    tearDown(() => debugDefaultTargetPlatformOverride = null);

    test('原生 iOS ＝ 醫師專用平台', () {
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
      expect(isDoctorOnlyPlatform, isTrue);
    });

    test('其他原生平台照舊（Android/macOS 不套醫師專用規則）', () {
      for (final p in [TargetPlatform.android, TargetPlatform.macOS, TargetPlatform.windows]) {
        debugDefaultTargetPlatformOverride = p;
        expect(isDoctorOnlyPlatform, isFalse, reason: '$p 不該被當成醫師專用 App');
      }
    });

    test('判斷式含 !kIsWeb —— iPad Safari 上的 kiosk 網頁也回報 TargetPlatform.iOS', () {
      // kIsWeb 在 `flutter test`（VM）恆為 false，web 那一側只能靠純函式的參數表達；
      // 這裡守住「不是只看 defaultTargetPlatform」這件事本身。
      expect(kIsWeb, isFalse);
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
      expect(isDoctorOnlyPlatform, !kIsWeb);
    });
  });

  group('iOS：病患帳號只能待在提示頁', () {
    test('landing 是 patient-unsupported，不是病患首頁', () {
      expect(landingPath(lng: 'zh-TW', isPatient: true, doctorOnlyPlatform: true),
          '/zh-TW/patient-unsupported');
    });

    test('root / login / 病患端各頁都導到提示頁', () {
      for (final path in [
        '/zh-TW',
        '/zh-TW/',
        '/zh-TW/login',
        '/zh-TW/patient',
        '/zh-TW/patient/start',
        '/zh-TW/patient/medical-info',
        '/zh-TW/patient/history',
        '/zh-TW/patient/settings',
        '/zh-TW/conversation/abc-123',
        '/zh-TW/dashboard',
        '/zh-TW/reports',
      ]) {
        expect(go(path, role: 'patient'), '/zh-TW/patient-unsupported', reason: '$path 沒被導到提示頁');
      }
    });

    test('停在提示頁本身不再 redirect（否則 go_router 迴圈）', () {
      for (final lng in supportedLanguages) {
        expect(go('/$lng/patient-unsupported', role: 'patient'), isNull, reason: '$lng 進了 redirect 迴圈');
      }
    });

    test('五種語言前綴都一致', () {
      for (final lng in supportedLanguages) {
        expect(go('/$lng/patient/start', role: 'patient'), '/$lng/patient-unsupported');
      }
    });
  });

  group('iOS：醫師/管理員以通知為首頁', () {
    test('landing ＝ /notifications（不是 dashboard 統計）', () {
      expect(landingPath(lng: 'zh-TW', isPatient: false, doctorOnlyPlatform: true), '/zh-TW/notifications');
      for (final path in ['/zh-TW', '/zh-TW/', '/zh-TW/login']) {
        expect(go(path), '/zh-TW/notifications', reason: '$path 的 landing 不是通知頁');
        expect(go(path, role: 'admin'), '/zh-TW/notifications');
      }
    });

    test('報告與通知等醫師端頁面照常可進', () {
      for (final path in [
        '/zh-TW/notifications',
        '/zh-TW/reports',
        '/zh-TW/reports/abc-123',
        '/zh-TW/sessions',
        '/zh-TW/sessions/abc-123',
        '/zh-TW/alerts',
        '/zh-TW/patients',
        '/zh-TW/patients/abc-123',
        '/zh-TW/settings',
      ]) {
        expect(go(path), isNull, reason: '醫師 App 把自己的 $path 擋掉了');
      }
    });

    test('提示頁不是給醫護看的，導回通知頁', () {
      expect(go('/zh-TW/patient-unsupported'), '/zh-TW/notifications');
      expect(go('/zh-TW/patient-unsupported', role: 'admin'), '/zh-TW/notifications');
    });

    test('admin 子樹的角色守衛不受平台影響', () {
      expect(go('/zh-TW/admin/users', role: 'admin'), isNull);
      expect(go('/zh-TW/admin/users'), '/zh-TW/notifications', reason: '醫師不該進 admin');
    });
  });

  group('iOS：問診/病患端 deep link 一律擋掉（任何角色）', () {
    test('醫師點到問診或病患端連結也被導回通知頁', () {
      for (final path in [
        '/zh-TW/conversation/abc-123',
        '/zh-TW/conversation',
        '/zh-TW/patient',
        '/zh-TW/patient/start',
        '/zh-TW/patient/session/abc-123/complete',
        '/zh-TW/patient/session/abc-123/thank-you',
      ]) {
        expect(go(path), '/zh-TW/notifications', reason: '$path 在醫師 App 上沒被擋住');
        expect(go(path, role: 'admin'), '/zh-TW/notifications');
      }
    });

    test('/patients 不是 /patient —— 醫師的病患清單必須留著', () {
      // 用 startsWith('/patient') 判斷會把清單頁一起關掉，這裡守住整段比對。
      expect(isConsultationArea('/patients'), isFalse);
      expect(isConsultationArea('/patients/abc-123'), isFalse);
      expect(isConsultationArea('/patient-unsupported'), isFalse);
      expect(isConsultationArea('/patient'), isTrue);
      expect(isConsultationArea('/patient/start'), isTrue);
      expect(isConsultationArea('/conversation/abc-123'), isTrue);
    });

    test('未登入時仍先走登入頁（平台規則不搶在 auth 前面）', () {
      expect(go('/zh-TW/conversation/abc-123', authed: false), '/zh-TW/login');
      expect(go('/zh-TW/login', authed: false), isNull);
      expect(go('/zh-TW/forgot-password', authed: false), isNull);
      expect(go('/zh-TW/reset-password', authed: false), isNull);
    });
  });

  group('非 iOS（web／Android）行為完全不變', () {
    test('landing 仍是 patient / dashboard', () {
      expect(landingPath(lng: 'zh-TW', isPatient: true, doctorOnlyPlatform: false), '/zh-TW/patient');
      expect(landingPath(lng: 'zh-TW', isPatient: false, doctorOnlyPlatform: false), '/zh-TW/dashboard');
      expect(go('/zh-TW', ios: false, role: 'patient'), '/zh-TW/patient');
      expect(go('/zh-TW/login', ios: false), '/zh-TW/dashboard');
    });

    test('病患的問診全流程照常', () {
      for (final path in [
        '/zh-TW/patient',
        '/zh-TW/patient/start',
        '/zh-TW/patient/medical-info',
        '/zh-TW/patient/history',
        '/zh-TW/conversation/abc-123',
      ]) {
        expect(go(path, ios: false, role: 'patient'), isNull, reason: 'kiosk 的 $path 被誤擋');
      }
    });

    test('醫師端與角色守衛照舊', () {
      expect(go('/zh-TW/dashboard', ios: false), isNull);
      expect(go('/zh-TW/reports', ios: false), isNull);
      expect(go('/zh-TW/dashboard', ios: false, role: 'patient'), '/zh-TW/patient');
      expect(go('/zh-TW/admin/users', ios: false), '/zh-TW/dashboard');
      expect(go('/zh-TW/admin/users', ios: false, role: 'admin'), isNull);
      expect(go('/zh-TW/dashboard', ios: false, authed: false), '/zh-TW/login');
    });

    test('提示頁是 iOS 專屬 —— 其他平台當作不存在', () {
      expect(go('/zh-TW/patient-unsupported', ios: false, role: 'patient'), '/zh-TW/patient');
      expect(go('/zh-TW/patient-unsupported', ios: false), '/zh-TW/dashboard');
    });
  });

  group('路由表', () {
    test('patient-unsupported 這條 route 真的接上了（redirect 才有地方去）', () {
      TestWidgetsFlutterBinding.ensureInitialized();
      final container = ProviderContainer();
      addTearDown(container.dispose);

      final paths = <String>[];
      void walk(List<RouteBase> routes) {
        for (final r in routes) {
          if (r is GoRoute) paths.add(r.path);
          walk(r.routes);
        }
      }

      walk(container.read(routerProvider).configuration.routes);
      expect(paths, contains('patient-unsupported'));
    });
  });

  group('提示頁文案', () {
    setUpAll(() async {
      TestWidgetsFlutterBinding.ensureInitialized();
      await Locales.loadAll();
    });

    // 直接查該語言自己的 JSON：t() 有 fallback chain，ja/ko/vi 缺 key 會回英文而假通過。
    String? read(String lng, String key) {
      final node = Locales.forLng(lng)?['common'];
      if (node is! Map) return null;
      final section = node['patientUnsupported'];
      if (section is! Map) return null;
      final value = section[key];
      return value is String ? value : null;
    }

    test('五語系都有自己的 patientUnsupported 文案', () {
      for (final lng in supportedLanguages) {
        for (final key in ['title', 'message', 'kioskHint', 'logoutAction']) {
          final value = read(lng, key);
          expect(value, isA<String>(), reason: '$lng 缺 common.patientUnsupported.$key');
          expect(value!.trim(), isNotEmpty, reason: '$lng 的 $key 是空字串');
        }
      }
    });

    testWidgets('提示頁把三段文案與登出按鈕都畫出來（切語言後 t() 重解析靠 _lngKeyed）', (tester) async {
      setCurrentLng('zh-TW');
      await tester.pumpWidget(ProviderScope(
        child: MaterialApp(theme: AppTheme.light, home: const PatientUnsupportedPage()),
      ));
      for (final key in ['title', 'message', 'kioskHint', 'logoutAction']) {
        expect(find.text(read('zh-TW', key)!), findsOneWidget, reason: '$key 沒顯示出來');
      }
      expect(find.byIcon(Icons.logout), findsOneWidget, reason: '病患沒有登出的出口');
    });

    test('不得出現含糊的「盡速就醫」（病患已在院內候診）', () {
      const banned = ['盡速就醫', '尽速就医', '儘速就醫', '就医', 'seek medical attention'];
      for (final lng in supportedLanguages) {
        for (final key in ['title', 'message', 'kioskHint', 'logoutAction']) {
          final value = read(lng, key)!.toLowerCase();
          for (final phrase in banned) {
            expect(value.contains(phrase.toLowerCase()), isFalse, reason: '$lng.$key 用了被禁止的措辭「$phrase」');
          }
        }
      }
    });
  });
}
