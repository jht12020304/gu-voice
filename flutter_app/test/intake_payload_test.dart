// Payload-shape tests for the intake form (IN-1 / D-3 / D-10).
//
// WHY these assert raw JSON instead of driving the UI: the real-OpenAI e2e driver POSTs
// its own hand-written JSON to /sessions, so it can never see a front-end that builds the
// WRONG JSON. That blind spot is exactly where IN-1 lived — the page derived
// `noKnownAllergies` from `_noAllergies || allergies.isEmpty`, so a patient who simply
// left the section blank was reported to the backend as having DENIED allergies.
//
// Consequence of that (voice-pipeline-invariants #23): a `no_*` flag is an ANSWERED_NO —
// the topic goes on the §3b do-not-ask list and the SOAP records 「病患自述無」. Turning
// "not asked" into "patient denied" is a fabricated medical record, which is why this is
// the one file that pins the exact three-state behaviour:
//
//   ticked      -> true  + []      ("patient says none")
//   left blank  -> FALSE + []      ("we don't know" — still ask)
//   filled in   -> false + [rows]

import 'package:flutter_test/flutter_test.dart';

import 'package:gu_voice/core/i18n/loc.dart';
import 'package:gu_voice/core/i18n/locales_loader.dart';
import 'package:gu_voice/core/router/lng.dart';
import 'package:gu_voice/data/api/case_convert.dart';
import 'package:gu_voice/features/patient/intake_payload.dart';

void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    await Locales.loadAll();
  });

  Map<String, dynamic> build({
    bool noAllergies = false,
    List<AllergyEntry> allergies = const [],
    bool noMedications = false,
    List<MedicationEntry> medications = const [],
    bool noHistory = false,
    List<HistoryEntry> histories = const [],
    bool noFamilyHistory = false,
    List<FamilyEntry> families = const [],
    String lng = 'zh-TW',
  }) =>
      buildIntakePayload(
        noAllergies: noAllergies,
        allergies: allergies,
        noMedications: noMedications,
        medications: medications,
        noHistory: noHistory,
        histories: histories,
        noFamilyHistory: noFamilyHistory,
        families: families,
        lng: lng,
      );

  group('IN-1: no_* flags mean "the patient denied it", never "the box was blank"', () {
    test('untouched form sends every no_* as FALSE with empty lists', () {
      final p = build();

      // The whole point. `true` here = four fabricated denials in one POST.
      expect(p['noKnownAllergies'], isFalse,
          reason: '沒填 ≠ 病患否認：送 true 會讓後端把過敏移進 §3b 禁問清單、SOAP 寫「病患自述無過敏」');
      expect(p['noCurrentMedications'], isFalse, reason: '沒填的用藥不得當成「病患說沒吃藥」');
      expect(p['noPastMedicalHistory'], isFalse, reason: '沒填的病史不得當成「病患說沒病史」');
      expect(p['noFamilyHistory'], isFalse, reason: '沒填的家族史不得當成「病患說沒家族史」');

      expect(p['allergies'], isEmpty);
      expect(p['currentMedications'], isEmpty);
      expect(p['medicalHistory'], isEmpty);
      expect(p['familyHistory'], isEmpty);
    });

    test('explicitly ticked boxes send true and an empty list', () {
      final p = build(
        noAllergies: true,
        noMedications: true,
        noHistory: true,
        noFamilyHistory: true,
      );
      expect(p['noKnownAllergies'], isTrue);
      expect(p['noCurrentMedications'], isTrue);
      expect(p['noPastMedicalHistory'], isTrue);
      expect(p['noFamilyHistory'], isTrue);
      expect(p['allergies'], isEmpty);
      expect(p['currentMedications'], isEmpty);
      expect(p['medicalHistory'], isEmpty);
      expect(p['familyHistory'], isEmpty);
    });

    test('a ticked box wins over rows that somehow survived, and never leaks them', () {
      // Defence in depth: the UI clears the rows when the box is ticked, but if that ever
      // regresses the payload must still be internally consistent (flag true => list []).
      final p = build(
        noAllergies: true,
        allergies: const [AllergyEntry(allergen: 'Penicillin')],
        noFamilyHistory: true,
        families: const [FamilyEntry(relationKey: 'father', condition: '膀胱癌')],
      );
      expect(p['noKnownAllergies'], isTrue);
      expect(p['allergies'], isEmpty);
      expect(p['noFamilyHistory'], isTrue);
      expect(p['familyHistory'], isEmpty);
    });

    test('filled-in rows send false + the rows', () {
      final p = build(
        allergies: const [AllergyEntry(allergen: ' Penicillin ', hospitalized: true)],
        medications: const [MedicationEntry(name: 'Warfarin', frequencyKey: 'twiceDaily')],
        histories: const [
          HistoryEntry(condition: '高血壓', yearsAgoKey: 'oneToFive', stillHas: false),
        ],
        families: const [FamilyEntry(relationKey: 'father', condition: ' 膀胱癌 ')],
      );

      expect(p['noKnownAllergies'], isFalse);
      expect(p['noCurrentMedications'], isFalse);
      expect(p['noPastMedicalHistory'], isFalse);
      expect(p['noFamilyHistory'], isFalse);

      expect(p['allergies'], [
        {
          'allergen': 'Penicillin',
          'hadHospitalization': true,
          'reaction': t('intake.medicalInfo.allergy.hospitalized', lng: 'zh-TW'),
          'severity': 'severe',
        }
      ]);
      expect(p['currentMedications'], [
        {'name': 'Warfarin', 'frequency': t('intake.medicalInfo.frequency.twiceDaily', lng: 'zh-TW')},
      ]);
      expect(p['medicalHistory'], [
        {
          'condition': '高血壓',
          'yearsAgo': t('intake.medicalInfo.yearsAgo.oneToFive', lng: 'zh-TW'),
          'stillHas': false,
        }
      ]);
      expect(p['familyHistory'], [
        {'relation': t('intake.medicalInfo.relations.father', lng: 'zh-TW'), 'condition': '膀胱癌'},
      ]);
    });

    test('rows that filter down to nothing still leave the flag FALSE', () {
      // The exact shape the old bug keyed off: the list ends up empty AFTER filtering, so
      // `|| list.isEmpty` flipped the flag to a denial the patient never made.
      final p = build(
        allergies: const [AllergyEntry(allergen: '   ')],
        medications: const [MedicationEntry(name: '', frequencyKey: 'onceDaily')],
        histories: const [HistoryEntry(condition: ' ', yearsAgoKey: 'unsure')],
        families: const [FamilyEntry(relationKey: 'mother', condition: '')],
      );
      expect(p['allergies'], isEmpty);
      expect(p['currentMedications'], isEmpty);
      expect(p['medicalHistory'], isEmpty);
      expect(p['familyHistory'], isEmpty);

      expect(p['noKnownAllergies'], isFalse, reason: '空白列被濾掉不代表病患否認');
      expect(p['noCurrentMedications'], isFalse);
      expect(p['noPastMedicalHistory'], isFalse);
      expect(p['noFamilyHistory'], isFalse);
    });

    test('a no_* flag is independent per section', () {
      final p = build(
        noAllergies: true,
        medications: const [MedicationEntry(name: 'Aspirin', frequencyKey: 'onceDaily')],
      );
      expect(p['noKnownAllergies'], isTrue);
      expect(p['noCurrentMedications'], isFalse);
      expect(p['noPastMedicalHistory'], isFalse);
      expect(p['noFamilyHistory'], isFalse);
    });
  });

  group('D-3: enum-ish fields go on the wire LOCALIZED, not as raw keys', () {
    test('family relation is the localized display string in every language', () {
      const rows = [FamilyEntry(relationKey: 'father', condition: '膀胱癌')];
      for (final lng in const ['zh-TW', 'en-US', 'ja-JP', 'ko-KR', 'vi-VN']) {
        final relation = (build(families: rows, lng: lng)['familyHistory'] as List)
            .single['relation'] as String;
        expect(relation, t('intake.medicalInfo.relations.father', lng: lng));
        // The raw key leaking through is the bug: a zh-TW SOAP read `father：膀胱癌`.
        expect(relation, isNot('father'),
            reason: '$lng 送出原始 key，prompt/SOAP 會出現 father：膀胱癌');
      }
    });

    test('relation follows the same pattern frequency/yearsAgo already used', () {
      final zh = build(
        medications: const [MedicationEntry(name: 'M', frequencyKey: 'asNeeded')],
        histories: const [HistoryEntry(condition: 'C', yearsAgoKey: 'within1')],
        families: const [FamilyEntry(relationKey: 'maternalGrandmother', condition: 'X')],
        lng: 'zh-TW',
      );
      expect((zh['currentMedications'] as List).single['frequency'], isNot('asNeeded'));
      expect((zh['medicalHistory'] as List).single['yearsAgo'], isNot('within1'));
      expect((zh['familyHistory'] as List).single['relation'], isNot('maternalGrandmother'));
    });

    test('a different language yields a different relation string (no accidental pinning)', () {
      const rows = [FamilyEntry(relationKey: 'father', condition: 'Prostate cancer')];
      final zh = (build(families: rows, lng: 'zh-TW')['familyHistory'] as List).single['relation'];
      final en = (build(families: rows, lng: 'en-US')['familyHistory'] as List).single['relation'];
      expect(zh, isNot(en));
    });
  });

  group('D-10: no_family_history reaches the backend schema key', () {
    test('every no_* survives the camel->snake boundary the Dio interceptor applies', () {
      final wire = camelToSnake<Map<String, dynamic>>(build(noFamilyHistory: true));
      // `SessionIntake` in backend/app/schemas/session.py expects exactly these.
      expect(wire.keys, containsAll(<String>[
        'no_known_allergies',
        'allergies',
        'no_current_medications',
        'current_medications',
        'no_past_medical_history',
        'medical_history',
        'no_family_history',
        'family_history',
      ]));
      expect(wire['no_family_history'], isTrue,
          reason: 'patient_context.build_patient_info 讀 no_family_history；'
              '送不出這個 key 時那條分支是死碼');
    });

    test('the new noneLabel exists in all five locale files, not via fallback', () {
      // t() falls back ja/ko/vi -> en-US -> zh-TW, so a missing key looks translated.
      // Read the raw store instead, the way the patientUnsupported copy test does.
      for (final lng in supportedLanguages) {
        final v = ((Locales.forLng(lng)!['intake'] as Map)['medicalInfo'] as Map)['family']
            as Map;
        expect(v['noneLabel'], isA<String>(), reason: '$lng 缺 intake.medicalInfo.family.noneLabel');
        expect((v['noneLabel'] as String).trim(), isNotEmpty, reason: '$lng 的 noneLabel 是空字串');
      }
    });

    test('family rows keep the {relation, condition} shape the schema requires', () {
      final wire = camelToSnake<Map<String, dynamic>>(build(
        families: const [FamilyEntry(relationKey: 'brother', condition: 'BPH')],
      ));
      expect((wire['family_history'] as List).single.keys, containsAll(['relation', 'condition']));
    });
  });
}
