// 病患端報告顯示的三道缺陷守衛：
//
//   D-A  ICD-10 碼與 AI 信心分數不得出現在病患端。ICD-10 未經醫師確認就被讀成「診斷」，
//        信心百分比則讓病患拿一個數字去衡量還沒審閱過的 AI 判斷。兩者都是醫師向。
//   D-B  非中文場次不得顯示中文病歷原文。SOAP 報告本體語言固定跟著醫療機構（中文），
//        英/日/韓/越場次的病患全程講自己的語言，最後卻拿到一段中文摘要。修法是後端另存
//        `patient_facing_localized`，前端只在其 language 與**場次語言**相符時顯示，
//        否則退回在地化通用訊息。
//   D-C  通用訊息受 kiosk 措辭鐵律拘束：病患已在候診區，只能請他稍候等看診。
//
// 三態（有值且語言相符 / 非中文 fallback / zh-TW 現行為）在 pure function 與真 widget
// 兩層都測：pure function 釘住決策，widget 釘住「決策真的接到畫面上」。

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/data/models/soap_report.dart';
import 'package:gu_voice/features/patient/patient_facing_summary.dart';
import 'package:gu_voice/features/patient/patient_session_detail_page.dart';
import 'package:gu_voice/features/patient/session_complete_page.dart';

import 'support/api_stub.dart';

/// flutter test 的 cwd 是 flutter_app/。
File _appFile(String relative) => File('${Directory.current.path}/$relative');

/// 去掉註解後的原始碼——註解會提到被禁的識別字（本輪就是在說明「不再顯示 icd10Codes」），
/// 那不算違規，只有真正的程式碼才受檢。
String _codeOnly(String src) {
  final noBlock = src.replaceAll(RegExp(r'/\*.*?\*/', dotAll: true), '');
  return noBlock
      .split('\n')
      .where((l) => !l.trimLeft().startsWith('//'))
      .join('\n');
}

/// 病患面禁語（不變式 #11）：部署情境是院內候診 kiosk，病患已坐在候診區。
const _bannedPatientWording = <String>[
  '盡速就醫', '儘速就醫', '尽速就医', '立即就醫', '立刻就醫', '就醫', '就医',
  '立即急診', '立刻急診', '趕快去醫院', '前往急診', '掛急診',
  'emergency room', 'go to the er', 'seek emergency', 'urgent care',
  'seek medical attention', 'see a doctor immediately',
  '救急外来', '応急室', '急诊', '응급실', 'cấp cứu',
];

/// 直接查該語言自己的 JSON：t() 有 fallback chain，ja/ko/vi 缺 key 會回英文而假通過。
String? _notice(String lng) {
  final ns = Locales.forLng(lng)?['session'];
  if (ns is! Map) return null;
  final section = ns['patientFacing'];
  if (section is! Map) return null;
  final v = section['notice'];
  return v is String ? v : null;
}

// ── stub 資料 ────────────────────────────────────────────
const _sessionId = 'sess-1';
const _reportId = 'rep-1';
const _zhSummary = '病患主訴排尿灼熱三日，無發燒。';

Map<String, Object?> _sessionJson(String language) => {
      'id': _sessionId,
      'status': 'completed',
      'language': language,
      'red_flag': false,
      'chief_complaint_text': 'Dysuria',
      'created_at': '2026-08-20T02:00:00Z',
      'started_at': '2026-08-20T02:00:00Z',
      'duration_seconds': 300,
    };

Map<String, Object?> _reportJson({Map<String, Object?>? patientFacing}) => {
      'id': _reportId,
      'session_id': _sessionId,
      'status': 'generated',
      'review_status': 'pending',
      'summary': _zhSummary,
      // 這兩個是醫師向欄位：後端仍會回，病患端**不得**渲染。
      'icd10_codes': ['N39.0', 'R30.0'],
      'ai_confidence_score': 0.87,
      'plan': {
        'patientEducation': ['多喝水', '避免憋尿'],
      },
      'patient_facing_localized': patientFacing,
    };

void _installStub({required String language, Map<String, Object?>? patientFacing}) {
  installApiStub((options) {
    final path = options.path;
    if (path == '/sessions/$_sessionId') return _sessionJson(language);
    if (path == '/sessions/$_sessionId/conversations') return [];
    if (path == '/reports') {
      return {
        'data': [
          {'id': _reportId}
        ],
        'pagination': {'hasMore': false, 'totalCount': 1},
      };
    }
    if (path == '/reports/$_reportId') return _reportJson(patientFacing: patientFacing);
    return null;
  });
}

Future<void> _pumpDetail(WidgetTester tester) async {
  await tester.pumpWidget(ProviderScope(
    child: MaterialApp(
      theme: AppTheme.light,
      home: const PatientSessionDetailPage(sessionId: _sessionId),
    ),
  ));
  await tester.pumpAndSettle();
}

Future<void> _pumpComplete(WidgetTester tester) async {
  await tester.pumpWidget(ProviderScope(
    child: MaterialApp(
      theme: AppTheme.light,
      home: const SessionCompletePage(sessionId: _sessionId),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('PatientFacingLocalized.tryParse：缺欄位／形狀不對一律當作沒有', () {
    test('null / 非 Map / 缺 language / language 空白 → null', () {
      expect(PatientFacingLocalized.tryParse(null), isNull);
      expect(PatientFacingLocalized.tryParse('en-US'), isNull);
      expect(PatientFacingLocalized.tryParse(const []), isNull);
      expect(PatientFacingLocalized.tryParse(const {'summary': 'hi'}), isNull);
      expect(PatientFacingLocalized.tryParse(const {'language': '   ', 'summary': 'hi'}), isNull);
      expect(PatientFacingLocalized.tryParse(const {'language': 42}), isNull);
    });

    test('summary 空白視為沒有；education 濾掉非字串與空白項', () {
      final parsed = PatientFacingLocalized.tryParse({
        'language': 'en-US',
        'summary': '   ',
        'patientEducation': ['  Drink water ', '', 7, null, 'Rest'],
      })!;
      expect(parsed.summary, isNull);
      expect(parsed.patientEducation, ['Drink water', 'Rest']);
    });

    test('報告 JSON 缺整個欄位不會炸（舊報告的常態）', () {
      final r = SoapReport.fromJson({'id': 'x', 'sessionId': _sessionId, 'status': 'generated'});
      expect(r.patientFacingLocalized, isNull);
    });

    test('經 Dio interceptor 轉 camelCase 後解析得到（snake 原樣也要能讀）', () {
      final camel = SoapReport.fromJson({
        'id': 'x',
        'patientFacingLocalized': {'language': 'ja-JP', 'summary': 'こんにちは'},
      });
      expect(camel.patientFacingLocalized?.language, 'ja-JP');
      final snake = SoapReport.fromJson({
        'id': 'x',
        'patient_facing_localized': {'language': 'ja-JP', 'patient_education': ['水分補給']},
      });
      expect(snake.patientFacingLocalized?.patientEducation, ['水分補給']);
    });
  });

  group('resolvePatientFacingSummary：三態', () {
    test('① 有在地化版本且語言符合場次 → 顯示它', () {
      final v = resolvePatientFacingSummary(
        sessionLanguage: 'en-US',
        reportSummary: _zhSummary,
        reportEducation: const ['多喝水'],
        localized: const PatientFacingLocalized(
          language: 'en-US',
          summary: 'Burning on urination for three days.',
          patientEducation: ['Drink more water'],
        ),
      );
      expect(v.mode, PatientSummaryMode.localized);
      expect(v.summary, 'Burning on urination for three days.');
      expect(v.education, ['Drink more water']);
      expect(v.useGenericNotice, isFalse);
    });

    test('語言變體（en / zh-Hant）正規化後仍算相符', () {
      final v = resolvePatientFacingSummary(
        sessionLanguage: 'en',
        localized: const PatientFacingLocalized(language: 'en-US', summary: 'ok'),
      );
      expect(v.mode, PatientSummaryMode.localized);
    });

    test('② 沒有在地化版本 + 非中文場次 → 通用訊息，且不得帶出中文原文', () {
      for (final lng in ['en-US', 'ja-JP', 'ko-KR', 'vi-VN']) {
        final v = resolvePatientFacingSummary(
          sessionLanguage: lng,
          reportSummary: _zhSummary,
          reportEducation: const ['多喝水', '避免憋尿'],
        );
        expect(v.mode, PatientSummaryMode.genericNotice, reason: '$lng 沒退回通用訊息');
        expect(v.useGenericNotice, isTrue);
        expect(v.summary, isNull, reason: '$lng 仍把中文病歷摘要帶了出去');
        expect(v.education, isEmpty, reason: '$lng 仍把中文衛教帶了出去');
      }
    });

    test('②b 在地化版本語言與場次不符（報告先產、病患後切語言）→ 同樣退回通用訊息', () {
      final v = resolvePatientFacingSummary(
        sessionLanguage: 'ja-JP',
        reportSummary: _zhSummary,
        localized: const PatientFacingLocalized(language: 'en-US', summary: 'English text'),
      );
      expect(v.mode, PatientSummaryMode.genericNotice);
      expect(v.summary, isNull);
    });

    test('②c 在地化版本語言相符但整份空 → 視為沒有', () {
      final v = resolvePatientFacingSummary(
        sessionLanguage: 'ko-KR',
        localized: const PatientFacingLocalized(language: 'ko-KR'),
      );
      expect(v.mode, PatientSummaryMode.genericNotice);
    });

    test('③ zh-TW 場次維持現行為：顯示報告原文', () {
      final v = resolvePatientFacingSummary(
        sessionLanguage: 'zh-TW',
        reportSummary: '  $_zhSummary  ',
        reportEducation: const ['多喝水', '  ', '避免憋尿'],
      );
      expect(v.mode, PatientSummaryMode.reportNative);
      expect(v.summary, _zhSummary);
      expect(v.education, ['多喝水', '避免憋尿']);
      expect(v.useGenericNotice, isFalse);
    });

    test('③b zh-TW 場次也吃在地化版本（後端若為中文另存一份）', () {
      final v = resolvePatientFacingSummary(
        sessionLanguage: 'zh-TW',
        reportSummary: _zhSummary,
        localized: const PatientFacingLocalized(language: 'zh-TW', summary: '白話版摘要'),
      );
      expect(v.mode, PatientSummaryMode.localized);
      expect(v.summary, '白話版摘要');
    });

    test('場次語言缺失／無法辨識 → 當 zh-TW（不會誤把中文場次擋成通用訊息）', () {
      for (final lng in [null, '', 'klingon']) {
        final v = resolvePatientFacingSummary(sessionLanguage: lng, reportSummary: _zhSummary);
        expect(v.mode, PatientSummaryMode.reportNative, reason: '$lng');
        expect(v.summary, _zhSummary);
      }
    });

    test('空 summary / 惰性 cast 拋 TypeError 都退成空值而不是白畫面', () {
      final v = resolvePatientFacingSummary(sessionLanguage: 'zh-TW', reportSummary: '   ');
      expect(v.summary, isNull);

      // `edu is List ? edu.cast<String>()` 對非字串元素會在**取值時**才丟。
      final rotten = <dynamic>['ok', 42].cast<String>();
      final v2 = resolvePatientFacingSummary(sessionLanguage: 'zh-TW', reportEducation: rotten);
      expect(v2.education, isEmpty);
    });
  });

  group('通用訊息文案：五語齊備 × 措辭合規', () {
    setUpAll(() async {
      TestWidgetsFlutterBinding.ensureInitialized();
      await Locales.loadAll();
    });

    test('五語都有自己的 session.patientFacing.notice（不是靠 fallback 回英文）', () {
      for (final lng in supportedLanguages) {
        final v = _notice(lng);
        expect(v, isA<String>(), reason: '$lng 缺 session.patientFacing.notice');
        expect(v!.trim(), isNotEmpty, reason: '$lng 的 notice 是空字串 → 病患看到空白');
        expect(t('session.patientFacing.notice', lng: lng), v);
      }
    });

    test('不得含糊叫病患自己去就醫／跑急診（病患已在候診區）', () {
      for (final lng in supportedLanguages) {
        final v = _notice(lng)!.toLowerCase();
        for (final phrase in _bannedPatientWording) {
          expect(v.contains(phrase.toLowerCase()), isFalse,
              reason: '$lng 的 patientFacing.notice 用了被禁止的措辭「$phrase」');
        }
      }
    });

    test('assets/locales 檔案內容與 runtime 載到的一致（pubspec 漏宣告會在這裡爆）', () {
      for (final lng in supportedLanguages) {
        final raw = json.decode(_appFile('assets/locales/$lng/session.json').readAsStringSync());
        expect((raw as Map)['patientFacing']?['notice'], _notice(lng), reason: '$lng 不一致');
      }
    });
  });

  group('靜態守衛：病患端不得渲染 ICD-10 / AI 信心分數', () {
    for (final page in const [
      'lib/features/patient/session_complete_page.dart',
      'lib/features/patient/patient_session_detail_page.dart',
    ]) {
      test(page.split('/').last, () {
        final code = _codeOnly(_appFile(page).readAsStringSync());
        expect(RegExp(r'\bicd10Codes\b').hasMatch(code), isFalse,
            reason: '$page 渲染了 ICD-10 碼（未經醫師確認的碼會被病患讀成診斷）');
        expect(RegExp(r'\baiConfidenceScore\b').hasMatch(code), isFalse,
            reason: '$page 渲染了 AI 信心分數（醫師向指標）');
        expect(code.contains('aiConfidence'), isFalse,
            reason: '$page 仍引用 session.complete.aiConfidence 文案');
      });
    }
  });

  group('widget：病患場次詳情頁', () {
    setUpAll(() async {
      TestWidgetsFlutterBinding.ensureInitialized();
      await Locales.loadAll();
    });
    tearDown(() => setCurrentLng('zh-TW'));

    testWidgets('en-US 場次 + 沒有在地化版本 → 顯示英文通用訊息，中文原文不得出現', (tester) async {
      setCurrentLng('en-US');
      _installStub(language: 'en-US');
      await _pumpDetail(tester);

      expect(find.text(_notice('en-US')!), findsOneWidget);
      expect(find.textContaining(_zhSummary), findsNothing, reason: '中文病歷摘要洩漏給非中文病患');
      expect(find.textContaining('多喝水'), findsNothing, reason: '中文衛教洩漏給非中文病患');
    });

    testWidgets('en-US 場次 + 在地化版本語言相符 → 顯示在地化摘要與衛教', (tester) async {
      setCurrentLng('en-US');
      _installStub(language: 'en-US', patientFacing: {
        'language': 'en-US',
        'summary': 'Burning on urination for three days, no fever.',
        'patient_education': ['Drink more water', 'Do not hold urine'],
      });
      await _pumpDetail(tester);

      expect(find.text('Burning on urination for three days, no fever.'), findsOneWidget);
      expect(find.textContaining('Drink more water'), findsOneWidget);
      expect(find.text(_notice('en-US')!), findsNothing);
      expect(find.textContaining(_zhSummary), findsNothing);
    });

    testWidgets('en-US 場次 + 在地化版本是別的語言 → 退回通用訊息', (tester) async {
      setCurrentLng('en-US');
      _installStub(language: 'en-US', patientFacing: {
        'language': 'ja-JP',
        'summary': '三日間の排尿時痛。',
      });
      await _pumpDetail(tester);

      expect(find.text(_notice('en-US')!), findsOneWidget);
      expect(find.textContaining('三日間の排尿時痛'), findsNothing);
    });

    testWidgets('zh-TW 場次維持現行為：顯示報告原文', (tester) async {
      setCurrentLng('zh-TW');
      _installStub(language: 'zh-TW');
      await _pumpDetail(tester);

      expect(find.text(_zhSummary), findsOneWidget);
      expect(find.textContaining('多喝水'), findsOneWidget);
      expect(find.text(_notice('zh-TW')!), findsNothing);
    });
  });

  group('widget：問診完成頁', () {
    setUpAll(() async {
      TestWidgetsFlutterBinding.ensureInitialized();
      await Locales.loadAll();
    });
    tearDown(() => setCurrentLng('zh-TW'));

    testWidgets('不渲染 ICD-10 碼與 AI 信心分數（後端仍會回這兩個欄位）', (tester) async {
      setCurrentLng('zh-TW');
      _installStub(language: 'zh-TW');
      await _pumpComplete(tester);

      expect(find.text(_zhSummary), findsOneWidget, reason: 'zh-TW 場次的摘要應照舊顯示');
      expect(find.text('N39.0'), findsNothing, reason: 'ICD-10 碼出現在病患端');
      expect(find.text('R30.0'), findsNothing);
      expect(find.byType(Chip), findsNothing, reason: 'ICD-10 chip 仍在病患端');
      expect(find.textContaining('87'), findsNothing, reason: 'AI 信心分數出現在病患端');
      // 審閱狀態 pill 是病患該看到的，別一起砍掉。
      expect(find.text(t('session.complete.reviewStatusPending')), findsOneWidget);
    });

    testWidgets('ja-JP 場次沒有在地化版本 → 顯示日文通用訊息', (tester) async {
      setCurrentLng('ja-JP');
      _installStub(language: 'ja-JP');
      await _pumpComplete(tester);

      expect(find.text(_notice('ja-JP')!), findsOneWidget);
      expect(find.textContaining(_zhSummary), findsNothing);
    });

    testWidgets('vi-VN 場次有在地化版本 → 顯示在地化摘要', (tester) async {
      setCurrentLng('vi-VN');
      _installStub(language: 'vi-VN', patientFacing: {
        'language': 'vi-VN',
        'summary': 'Tiểu buốt ba ngày, không sốt.',
      });
      await _pumpComplete(tester);

      expect(find.text('Tiểu buốt ba ngày, không sốt.'), findsOneWidget);
      expect(find.text(_notice('vi-VN')!), findsNothing);
    });
  });
}
