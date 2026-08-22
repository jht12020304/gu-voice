// D-5: the chief-complaint -> medical-info hop.
//
// (a) The three complaint params used to travel in go_router's `extra:` — an in-memory
//     object attached to ONE navigation. Reload the tab, restore the session, or open the
//     link directly and `extra` is null, so `complaintId` was null and POST /sessions
//     422'd with the patient stuck on a form that could never submit. On Flutter Web that
//     is a promote blocker: refresh is a normal thing to do. Params now live in the URL,
//     so the guard is "rebuild the page from the URL ALONE and the args are still there".
// (b) Switching language refetches the (pre-localized) complaint list; the selection kept
//     pointing at the OLD language's objects, so the stale name went into
//     chief_complaint_text -> prompt -> SOAP.
// (c) The 'Other' sentinel is stripped from the joined names and may not be the primary
//     FK, so the patient's free text is the ONLY surviving trace of that choice.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/core/theme/app_theme.dart';
import 'package:gu_voice/data/api/complaints_api.dart';
import 'package:gu_voice/data/models/session.dart';
import 'package:gu_voice/features/patient/intake_route.dart';
import 'package:gu_voice/features/patient/medical_info_page.dart';
import 'package:gu_voice/features/patient/select_complaint_page.dart';

const _c1 = Complaint(id: 'c1', name: '血尿', category: 'urinarySymptoms');
const _c1En = Complaint(id: 'c1', name: 'Blood in urine', category: 'urinarySymptoms');
const _c2 = Complaint(id: 'c2', name: '排尿困難', category: 'urinarySymptoms');
const _c2En = Complaint(id: 'c2', name: 'Difficulty urinating', category: 'urinarySymptoms');
const _other = Complaint(id: otherComplaintId, name: '其他', category: 'other');

class _FakeComplaintsApi extends ComplaintsApi {
  _FakeComplaintsApi(this.next);
  List<Complaint> next;
  int calls = 0;

  @override
  Future<List<Complaint>> getComplaints({bool activeOnly = true}) async {
    calls++;
    return next;
  }
}

void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    await Locales.loadAll();
  });

  group('D-5a: intake params survive a reload / deep link', () {
    test('the location keeps the lng prefix and carries all three params', () {
      final loc = medicalInfoLocation(
        lng: 'zh-TW',
        complaintId: 'c1',
        complaintName: '血尿',
        complaintText: '血尿（早上開始）',
      );
      expect(loc, startsWith('/zh-TW/patient/medical-info?'),
          reason: 'lng 前綴是語言的唯一權威，改走 query 參數不得把它弄丟');

      // Parsing the string back is exactly what go_router does on a cold load.
      final args = medicalInfoArgsFromUri(Uri.parse(loc));
      expect(args['complaintId'], 'c1');
      expect(args['complaintName'], '血尿');
      expect(args['complaintText'], '血尿（早上開始）');
    });

    test('CJK, spaces, & and # round-trip through the URL unharmed', () {
      const text = '血尿 & 夜尿 #2（自述：早上開始）';
      final args = medicalInfoArgsFromUri(Uri.parse(medicalInfoLocation(
        lng: 'ja-JP',
        complaintId: 'c1',
        complaintName: 'その他',
        complaintText: text,
      )));
      expect(args['complaintText'], text,
          reason: '未編碼的 & / # 會把自述文字從中間切斷（或整段掉進 fragment）');
      expect(args['complaintName'], 'その他');
    });

    test('every supported language produces its own prefixed link', () {
      for (final lng in supportedLanguages) {
        final loc = medicalInfoLocation(
          lng: lng,
          complaintId: 'c1',
          complaintName: 'n',
          complaintText: 't',
        );
        expect(Uri.parse(loc).path, '/$lng/patient/medical-info');
      }
    });

    test('a link with no params degrades to empty strings, not a crash', () {
      final args = medicalInfoArgsFromUri(Uri.parse('/zh-TW/patient/medical-info'));
      expect(args, {'complaintId': '', 'complaintName': '', 'complaintText': '', 'patientId': ''});
    });

    testWidgets('cold-loading the URL renders the intake page with the complaint', (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      setCurrentLng('zh-TW');

      // No prior navigation, so nothing could have been passed in `extra` — the same
      // situation as F5 on the kiosk browser.
      final router = GoRouter(
        initialLocation: medicalInfoLocation(
          lng: 'zh-TW',
          complaintId: 'c1',
          complaintName: '血尿',
          complaintText: '血尿（早上開始）',
        ),
        routes: [
          GoRoute(
            path: '/:lng/patient/medical-info',
            // Same one-liner as app_router.dart's medical-info route.
            builder: (context, state) => MedicalInfoPage(args: medicalInfoArgsFromUri(state.uri)),
          ),
        ],
      );
      addTearDown(router.dispose);

      await tester.pumpWidget(ProviderScope(
        child: MaterialApp.router(theme: AppTheme.light, routerConfig: router),
      ));
      await tester.pumpAndSettle();

      expect(find.text(t('intake.medicalInfo.complaintLabel', args: {'name': '血尿'})), findsOneWidget,
          reason: '重整後參數沒帶到——complaintId 為 null，送出必 422');
      expect(find.text(t('intake.medicalInfo.complaintLabel', args: {'name': t('intake.medicalInfo.complaintUnset')})),
          findsNothing);
    });
  });

  group('D-5: the real page hands the params over in the URL', () {
    // Guards the SENDING half (the deep-link test above guards the receiving half) and
    // the language-switch wiring in _load() — a pure-function test alone would stay green
    // if either call site were reverted.
    late _FakeComplaintsApi api;
    late GoRouter router;
    Uri? landed;

    Widget app() => ProviderScope(
          child: MaterialApp.router(theme: AppTheme.light, routerConfig: router),
        );

    // [lngKeyed] mirrors app_router's `_lngKeyed` wrapper. It is a parameter because the
    // two behaviours differ and both are worth pinning — see the tests below.
    void makeRouter({required bool lngKeyed}) {
      landed = null;
      api = _FakeComplaintsApi([_c1, _c2, _other]);
      router = GoRouter(
        initialLocation: '/zh-TW/patient/start',
        routes: [
          GoRoute(
            path: '/:lng/patient/start',
            builder: (context, state) {
              final page = SelectComplaintPage(api: api);
              return lngKeyed ? KeyedSubtree(key: ValueKey(currentLng), child: page) : page;
            },
          ),
          GoRoute(
            path: '/:lng/patient/medical-info',
            builder: (context, state) {
              landed = state.uri;
              return const Scaffold(body: Text('intake'));
            },
          ),
        ],
      );
    }

    setUp(() => makeRouter(lngKeyed: false));
    tearDown(() {
      router.dispose();
      setCurrentLng('zh-TW');
    });

    testWidgets('picking a complaint navigates with query params, not extra', (tester) async {
      setCurrentLng('zh-TW');
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();

      await tester.tap(find.text('血尿'));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(FilledButton));
      await tester.pumpAndSettle();

      expect(landed, isNotNull);
      expect(landed!.path, '/zh-TW/patient/medical-info');
      expect(landed!.queryParameters['complaintId'], 'c1',
          reason: 'extra: 傳參在重整後會變 null → complaintId null → POST /sessions 422');
      expect(landed!.queryParameters['complaintText'], '血尿');
    });

    testWidgets('a surviving page re-localizes its picks instead of keeping stale names',
        (tester) async {
      // _load()'s own contract, exercised with a state-preserving route: if the SAME page
      // state lives through a language change, the refetched list must replace the picks'
      // labels. Otherwise the previous language's name goes straight into
      // chief_complaint_text -> prompt -> SOAP.
      setCurrentLng('zh-TW');
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      await tester.tap(find.text('血尿'));
      await tester.pumpAndSettle();

      setCurrentLng('en-US');
      api.next = [_c1En, _c2En, _other];
      router.go('/en-US/patient/start');
      await tester.pumpAndSettle();
      expect(api.calls, 2, reason: '語言變了卻沒 refetch');
      expect(find.text('Blood in urine'), findsWidgets);

      await tester.tap(find.byType(FilledButton));
      await tester.pumpAndSettle();

      expect(landed!.path, '/en-US/patient/medical-info');
      expect(landed!.queryParameters['complaintText'], 'Blood in urine',
          reason: '殘留舊語言的主訴會原封不動進 prompt 與 SOAP');
      expect(landed!.queryParameters['complaintId'], 'c1',
          reason: '重新對映是照 id，病患已經選好的主訴不該被清掉');
    });

    testWidgets('under the production _lngKeyed wrapper the switch resets the page',
        (tester) async {
      // Documenting the real production path, because it is NOT what the stale-name
      // symptom assumes: `_lngKeyed(ValueKey(currentLng))` rebuilds the subtree from
      // scratch, so the page state — picks and the free-text note — is gone and the
      // patient re-picks in the new language. Nothing stale can survive that; the
      // re-mapping above is the safety net for any caller where it does.
      makeRouter(lngKeyed: true);
      setCurrentLng('zh-TW');
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      await tester.tap(find.text('血尿'));
      await tester.pumpAndSettle();

      setCurrentLng('en-US');
      api.next = [_c1En, _c2En, _other];
      router.go('/en-US/patient/start');
      await tester.pumpAndSettle();

      expect(find.text('Blood in urine'), findsWidgets, reason: '切語言後清單必須是新語言');
      expect(tester.widget<FilledButton>(find.byType(FilledButton)).onPressed, isNull,
          reason: '選擇被重置後 CTA 必須是停用的——否則會用空選擇建場次');
    });
  });

  group('D-5b: language switch re-localizes the selection', () {
    test('picks are kept but relabelled, in order', () {
      final remapped = remapSelectionToLocale([_c2, _c1], [_c1En, _c2En]);
      expect(remapped.map((c) => c.id).toList(), ['c2', 'c1'],
          reason: '順序＝primary FK（第一個選的），不得被重排');
      expect(remapped.map((c) => c.name).toList(),
          ['Difficulty urinating', 'Blood in urine'],
          reason: '舊語言的名稱會原封不動進 chief_complaint_text → prompt → SOAP');
    });

    test('an id that no longer exists is dropped, not carried as a stale label', () {
      final remapped = remapSelectionToLocale([_c1, _c2], [_c1En]);
      expect(remapped.map((c) => c.id).toList(), ['c1']);
    });

    test('an empty refetch clears rather than keeping the old language', () {
      expect(remapSelectionToLocale([_c1], const []), isEmpty);
    });

    test('the rebuilt complaint text is entirely in the new language', () {
      final remapped = remapSelectionToLocale([_c1, _other], [_c1En, _other]);
      final text = buildComplaintText(
        selected: remapped,
        customText: 'burning',
        lng: 'en-US',
      );
      expect(text, 'Blood in urine (burning)');
      expect(text.contains('血尿'), isFalse);
    });
  });

  group("D-5c: the 'Other' sentinel keeps the patient's own words", () {
    test('other-only sends the free text as the whole complaint', () {
      expect(
        buildComplaintText(selected: const [_other], customText: ' 尿完還想尿 ', lng: 'zh-TW'),
        '尿完還想尿',
      );
    });

    test('other alongside a real complaint appends the note, sentinel word excluded', () {
      final text = buildComplaintText(
        selected: const [_c1, _other],
        customText: '早上開始',
        lng: 'zh-TW',
      );
      expect(text, '血尿（早上開始）');
      expect(text.contains('其他'), isFalse,
          reason: '「其他」是 UI 佔位詞，不是症狀——進了 text 會被當成主訴餵給紅旗/SOAP');
    });

    test('other + blank note can never leave the page', () {
      // Otherwise the complaint text would be '' (other-only) or lose the choice entirely
      // (multi-select), i.e. a session starting with no symptom at all.
      expect(complaintSelectionReady(selected: const [_other], customText: ''), isFalse);
      expect(complaintSelectionReady(selected: const [_other], customText: '   '), isFalse);
      expect(complaintSelectionReady(selected: const [_c1, _other], customText: ' '), isFalse);
      expect(complaintSelectionReady(selected: const [], customText: 'anything'), isFalse);
    });

    test('the note is optional when the sentinel is not picked', () {
      expect(complaintSelectionReady(selected: const [_c1], customText: ''), isTrue);
      expect(complaintSelectionReady(selected: const [_c1, _other], customText: '自述'), isTrue);
    });

    test('a long note is tail-clamped, complaint names stay intact', () {
      final long = 'あ' * 400;
      final text = buildComplaintText(selected: const [_c1, _other], customText: long, lng: 'zh-TW');
      expect(text.runes.length, complaintTextMax);
      expect(text, startsWith('血尿（'));
      expect(text, endsWith('）'));
    });
  });
}
