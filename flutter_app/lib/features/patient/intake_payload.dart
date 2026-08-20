import '../../core/i18n/loc.dart';

// Pure projection of the intake form into the `intake` object of POST /sessions.
//
// It lives OUTSIDE the widget on purpose: the payload SHAPE is the thing that has to be
// right, and a real-OpenAI e2e (which posts raw JSON itself) can never see a front-end
// that fabricates it. Keeping the projection pure lets a unit test assert the exact JSON
// for "checked", "left blank" and "filled in".
//
// The one rule that matters clinically (voice-pipeline-invariants #23):
//
//   `no*` is TRUE ONLY WHEN THE PATIENT EXPLICITLY TICKED THE BOX.
//
// The backend treats a `no_*` flag as an ANSWERED_NO: the topic goes onto the §3b
// do-not-ask list and the SOAP records 「病患自述無」. Deriving it from "the list came
// back empty" (the old `_noAllergies || allergies.isEmpty`) turns "we never asked" into
// "the patient denied it" — a fabricated medical record, and the §3b gate then skips the
// risk factor entirely. Blank must stay blank: three-state, not two.

class AllergyEntry {
  const AllergyEntry({required this.allergen, this.hospitalized = false});
  final String allergen;
  final bool hospitalized;
}

class MedicationEntry {
  const MedicationEntry({required this.name, required this.frequencyKey});
  final String name;
  final String frequencyKey;
}

class HistoryEntry {
  const HistoryEntry({
    required this.condition,
    required this.yearsAgoKey,
    this.stillHas = true,
  });
  final String condition;
  final String yearsAgoKey;
  final bool stillHas;
}

class FamilyEntry {
  const FamilyEntry({required this.relationKey, required this.condition});
  final String relationKey;
  final String condition;
}

/// Builds the `intake` object. Enum-ish fields (frequency / yearsAgo / relation) are sent
/// as TRANSLATED display strings because the backend schema is free text and the strings
/// land verbatim in the prompt and the SOAP — the same contract as React's
/// `MedicalInfoPage.tsx`. Sending the raw key put `father：膀胱癌` into a zh-TW report.
///
/// [lng] overrides the active language (tests only; production reads the URL authority).
Map<String, dynamic> buildIntakePayload({
  required bool noAllergies,
  required List<AllergyEntry> allergies,
  required bool noMedications,
  required List<MedicationEntry> medications,
  required bool noHistory,
  required List<HistoryEntry> histories,
  required bool noFamilyHistory,
  required List<FamilyEntry> families,
  String? lng,
}) {
  String tr(String key) => t(key, lng: lng);

  return <String, dynamic>{
    // NOT `|| allergies.isEmpty` — see the header comment.
    'noKnownAllergies': noAllergies,
    'allergies': <Map<String, dynamic>>[
      if (!noAllergies)
        for (final a in allergies)
          if (a.allergen.trim().isNotEmpty)
            {
              'allergen': a.allergen.trim(),
              'hadHospitalization': a.hospitalized,
              if (a.hospitalized) 'reaction': tr('intake.medicalInfo.allergy.hospitalized'),
              if (a.hospitalized) 'severity': 'severe',
            },
    ],
    'noCurrentMedications': noMedications,
    'currentMedications': <Map<String, dynamic>>[
      if (!noMedications)
        for (final m in medications)
          if (m.name.trim().isNotEmpty)
            {
              'name': m.name.trim(),
              'frequency': tr('intake.medicalInfo.frequency.${m.frequencyKey}'),
            },
    ],
    'noPastMedicalHistory': noHistory,
    'medicalHistory': <Map<String, dynamic>>[
      if (!noHistory)
        for (final h in histories)
          if (h.condition.trim().isNotEmpty)
            {
              'condition': h.condition.trim(),
              'yearsAgo': tr('intake.medicalInfo.yearsAgo.${h.yearsAgoKey}'),
              'stillHas': h.stillHas,
            },
    ],
    // Was hardcoded `[]`, so prostate-cancer family history was ALWAYS blank and the
    // doctor could not tell "never asked" from "patient denied it" (TODO G13). The
    // `noFamilyHistory` flag is the third state the backend schema already models
    // (`SessionIntake.no_family_history`) but neither front-end could send (D-10).
    'noFamilyHistory': noFamilyHistory,
    'familyHistory': <Map<String, dynamic>>[
      if (!noFamilyHistory)
        for (final f in families)
          if (f.condition.trim().isNotEmpty)
            {
              'relation': tr('intake.medicalInfo.relations.${f.relationKey}'),
              'condition': f.condition.trim(),
            },
    ],
  };
}
