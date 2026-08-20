import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../data/api/sessions_api.dart';
import '../../shared/widgets/language_action.dart';
import 'intake_payload.dart';

// Port of MedicalInfoPage.tsx — identity + intake (allergies / medications / past history)
// then createSession, into the conversation. ponytail: the 2-step wizard chrome (progress
// bar / next-prev / summary card) and family history are folded to a single scroll page,
// but the clinical intake DATA is collected and sent (no more all-negative hardcode).
class _Allergy {
  final ctrl = TextEditingController();
  bool hospitalized = false;
}

class _Medication {
  final ctrl = TextEditingController();
  String frequency = 'onceDaily';
}

class _History {
  final ctrl = TextEditingController();
  String yearsAgo = 'unsure';
  bool stillHas = true;
}

class _Family {
  final ctrl = TextEditingController();
  String relation = 'father';
}

class MedicalInfoPage extends ConsumerStatefulWidget {
  const MedicalInfoPage({super.key, required this.args});
  final Map args; // {complaintId, complaintName, complaintText}

  @override
  ConsumerState<MedicalInfoPage> createState() => _MedicalInfoPageState();
}

class _MedicalInfoPageState extends ConsumerState<MedicalInfoPage> {
  final _nameCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();
  String? _gender;
  DateTime? _dob;
  bool _creating = false;
  String? _error;
  bool _showErrors = false;

  // These four are the ONLY source of the backend's `no_*` flags. A flag means "the
  // patient explicitly denied it" (backend puts the topic on the §3b do-not-ask list and
  // the SOAP writes 「病患自述無」), so it must never be inferred from an empty list.
  bool _noAllergies = false;
  bool _noMedications = false;
  bool _noHistory = false;
  bool _noFamilyHistory = false;
  final List<_Allergy> _allergies = [];
  final List<_Medication> _medications = [];
  final List<_History> _histories = [];
  final List<_Family> _families = [];

  // Optional section, but it does carry a "none" checkbox now: without it the backend
  // could not tell 「沒填」 from 「病患說沒有」 and §3b re-asked the urological-cancer
  // family history every time (D-10). Backend shape is {relation, condition}.
  static const _relationKeys = [
    'father',
    'mother',
    'brother',
    'sister',
    'paternalGrandfather',
    'paternalGrandmother',
    'maternalGrandfather',
    'maternalGrandmother',
  ];

  static const _frequencyKeys = ['onceDaily', 'twiceDaily', 'thriceDaily', 'asNeeded', 'weekly', 'other'];
  static const _yearsAgoKeys = ['within1', 'oneToFive', 'overFive', 'unsure'];

  @override
  void dispose() {
    _nameCtrl.dispose();
    _phoneCtrl.dispose();
    for (final a in _allergies) {
      a.ctrl.dispose();
    }
    for (final m in _medications) {
      m.ctrl.dispose();
    }
    for (final h in _histories) {
      h.ctrl.dispose();
    }
    for (final f in _families) {
      f.ctrl.dispose();
    }
    super.dispose();
  }

  bool get _valid => _nameCtrl.text.trim().isNotEmpty && _gender != null && _dob != null;

  // Args now arrive as URL query params (see intake_route.dart), where "missing" reads
  // back as '' rather than null. Collapse both to null so the `??` fallbacks still work.
  String? _arg(String key) {
    final v = widget.args[key];
    if (v is! String) return null;
    return v.trim().isEmpty ? null : v;
  }

  String _sessionLanguage() => supportedLanguages.contains(currentLng) ? currentLng : 'zh-TW';

  Future<void> _submit() async {
    setState(() => _showErrors = true);
    if (!_valid) return;
    setState(() {
      _creating = true;
      _error = null;
    });
    final dob = _dob!;
    two(int n) => n.toString().padLeft(2, '0');

    final payload = {
      'chiefComplaintId': _arg('complaintId'),
      // The AI/SOAP-facing text; fall back to the display name only when it is genuinely
      // absent (an empty query param is "not provided", not an empty complaint).
      'chiefComplaintText': _arg('complaintText') ?? _arg('complaintName'),
      'language': _sessionLanguage(),
      'patientInfo': {
        'name': _nameCtrl.text.trim(),
        'gender': _gender,
        'dateOfBirth': '${dob.year.toString().padLeft(4, '0')}-${two(dob.month)}-${two(dob.day)}',
        'phone': _phoneCtrl.text.trim().isEmpty ? null : _phoneCtrl.text.trim(),
      },
      // Pure projection (intake_payload.dart) so the exact JSON is unit-testable.
      'intake': buildIntakePayload(
        noAllergies: _noAllergies,
        allergies: [
          for (final a in _allergies) AllergyEntry(allergen: a.ctrl.text, hospitalized: a.hospitalized),
        ],
        noMedications: _noMedications,
        medications: [
          for (final m in _medications) MedicationEntry(name: m.ctrl.text, frequencyKey: m.frequency),
        ],
        noHistory: _noHistory,
        histories: [
          for (final h in _histories)
            HistoryEntry(condition: h.ctrl.text, yearsAgoKey: h.yearsAgo, stillHas: h.stillHas),
        ],
        noFamilyHistory: _noFamilyHistory,
        families: [
          for (final f in _families) FamilyEntry(relationKey: f.relation, condition: f.ctrl.text),
        ],
      ),
    };
    try {
      final session = await SessionsApi().createSession(payload);
      if (!mounted) return;
      context.go(prefixLngToPath('/conversation/${session.id}', currentLng), extra: session);
    } catch (_) {
      if (mounted) {
        setState(() {
          _creating = false;
          _error = t('intake.medicalInfo.errors.createSession');
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final err = Theme.of(context).colorScheme.error;
    return Scaffold(
      appBar: AppBar(
        title: Text(t('intake.medicalInfo.complaintLabel',
            args: {'name': _arg('complaintName') ?? t('intake.medicalInfo.complaintUnset')})),
        actions: const [LanguageAction()],
      ),
      body: AbsorbPointer(
        absorbing: _creating,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(t('intake.medicalInfo.patient.title'), style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 16),
            TextField(
              controller: _nameCtrl,
              maxLength: 100,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(
                labelText: t('intake.medicalInfo.patient.nameLabel'),
                errorText: _showErrors && _nameCtrl.text.trim().isEmpty ? t('intake.medicalInfo.patient.nameError') : null,
              ),
            ),
            const SizedBox(height: 8),
            Text(t('intake.medicalInfo.patient.genderLabel')),
            Wrap(spacing: 8, children: [
              for (final g in const ['male', 'female', 'other'])
                ChoiceChip(
                  selected: _gender == g,
                  label: Text(t('intake.medicalInfo.patient.gender${g[0].toUpperCase()}${g.substring(1)}')),
                  onSelected: (_) => setState(() => _gender = g),
                ),
            ]),
            if (_showErrors && _gender == null) Text(t('intake.medicalInfo.patient.genderError'), style: TextStyle(color: err)),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              icon: const Icon(Icons.calendar_today),
              label: Text(_dob == null
                  ? t('intake.medicalInfo.patient.dobLabel')
                  : '${_dob!.year}-${_dob!.month}-${_dob!.day}'),
              onPressed: () async {
                final picked = await showDatePicker(
                  context: context,
                  firstDate: DateTime(1900),
                  lastDate: DateTime.now(),
                  initialDate: DateTime(1980),
                );
                if (picked != null) setState(() => _dob = picked);
              },
            ),
            if (_showErrors && _dob == null) Text(t('intake.medicalInfo.patient.dobError'), style: TextStyle(color: err)),
            const SizedBox(height: 8),
            TextField(
              controller: _phoneCtrl,
              maxLength: 20,
              keyboardType: TextInputType.phone,
              decoration: InputDecoration(labelText: t('intake.medicalInfo.patient.phoneLabel')),
            ),
            const Divider(height: 32),
            _allergySection(context),
            const Divider(height: 32),
            _medicationSection(context),
            const Divider(height: 32),
            _historySection(context),
            const Divider(height: 32),
            _familySection(context),
            if (_error != null) ...[
              const SizedBox(height: 16),
              Text(_error!, style: TextStyle(color: err)),
            ],
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _creating ? null : _submit,
              child: _creating
                  ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                  : Text(t('intake.medicalInfo.nav.submit')),
            ),
          ],
        ),
      ),
    );
  }

  Widget _sectionHeader(BuildContext context, String title, String noneLabel, bool none, ValueChanged<bool> onNone) => Row(
        children: [
          Expanded(child: Text(title, style: Theme.of(context).textTheme.titleSmall)),
          Row(mainAxisSize: MainAxisSize.min, children: [
            Checkbox(value: none, onChanged: (v) => onNone(v ?? false)),
            Text(noneLabel),
          ]),
        ],
      );

  Widget _allergySection(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _sectionHeader(context, t('intake.medicalInfo.allergy.title'), t('intake.medicalInfo.allergy.noneLabel'), _noAllergies,
            (v) => setState(() {
                  _noAllergies = v;
                  // Clear, don't just hide (React does the same). Rows kept alive behind
                  // a ticked box are invisible data that submit() silently drops, and the
                  // payload would then claim the patient denied what they had typed.
                  if (v) _allergies.clear();
                })),
        if (!_noAllergies) ...[
          for (var i = 0; i < _allergies.length; i++)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(children: [
                Expanded(
                  child: TextField(
                    controller: _allergies[i].ctrl,
                    maxLength: 100,
                    decoration: InputDecoration(labelText: t('intake.medicalInfo.allergy.placeholder'), counterText: ''),
                  ),
                ),
                Column(mainAxisSize: MainAxisSize.min, children: [
                  Checkbox(value: _allergies[i].hospitalized, onChanged: (v) => setState(() => _allergies[i].hospitalized = v ?? false)),
                  Text(t('intake.medicalInfo.allergy.hospitalized'), style: Theme.of(context).textTheme.labelSmall),
                ]),
                IconButton(icon: const Icon(Icons.remove_circle_outline), onPressed: () => setState(() => _allergies.removeAt(i))),
              ]),
            ),
          TextButton.icon(
            icon: const Icon(Icons.add),
            label: Text(t('intake.medicalInfo.allergy.add')),
            onPressed: () => setState(() => _allergies.add(_Allergy())),
          ),
        ],
      ]);

  Widget _medicationSection(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _sectionHeader(context, t('intake.medicalInfo.medication.title'), t('intake.medicalInfo.medication.noneLabel'), _noMedications,
            (v) => setState(() {
                  _noMedications = v;
                  if (v) _medications.clear();
                })),
        if (!_noMedications) ...[
          for (var i = 0; i < _medications.length; i++)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(children: [
                Expanded(
                  child: TextField(
                    controller: _medications[i].ctrl,
                    maxLength: 100,
                    decoration: InputDecoration(labelText: t('intake.medicalInfo.medication.placeholder'), counterText: ''),
                  ),
                ),
                const SizedBox(width: 8),
                DropdownButton<String>(
                  value: _medications[i].frequency,
                  items: [for (final f in _frequencyKeys) DropdownMenuItem(value: f, child: Text(t('intake.medicalInfo.frequency.$f')))],
                  onChanged: (v) => setState(() => _medications[i].frequency = v ?? 'onceDaily'),
                ),
                IconButton(icon: const Icon(Icons.remove_circle_outline), onPressed: () => setState(() => _medications.removeAt(i))),
              ]),
            ),
          TextButton.icon(
            icon: const Icon(Icons.add),
            label: Text(t('intake.medicalInfo.medication.add')),
            onPressed: () => setState(() => _medications.add(_Medication())),
          ),
        ],
      ]);

  // Optional, collapsible-free (kept flat to match the other sections here). Relation
  // dropdown + free-text condition; empty rows are dropped on submit.
  Widget _familySection(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
          padding: const EdgeInsets.only(top: 8, bottom: 4),
          // Same "none" affordance as the other three sections: without it the patient
          // has no way to say 「沒有家族病史」 and §3b keeps asking (D-10).
          child: Row(children: [
            Expanded(
              child: Row(children: [
                Flexible(
                  child: Text(t('intake.medicalInfo.family.title'),
                      style: Theme.of(context).textTheme.titleSmall),
                ),
                const SizedBox(width: 8),
                Text(t('intake.medicalInfo.family.optional'),
                    style: Theme.of(context).textTheme.bodySmall),
              ]),
            ),
            Row(mainAxisSize: MainAxisSize.min, children: [
              Checkbox(
                value: _noFamilyHistory,
                onChanged: (v) => setState(() {
                  _noFamilyHistory = v ?? false;
                  if (_noFamilyHistory) _families.clear();
                }),
              ),
              Text(t('intake.medicalInfo.family.noneLabel')),
            ]),
          ]),
        ),
        Text(t('intake.medicalInfo.family.hint'), style: Theme.of(context).textTheme.bodySmall),
        if (!_noFamilyHistory) ...[
          for (var i = 0; i < _families.length; i++)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(children: [
                DropdownButton<String>(
                  value: _families[i].relation,
                  items: [
                    for (final r in _relationKeys)
                      DropdownMenuItem(value: r, child: Text(t('intake.medicalInfo.relations.$r')))
                  ],
                  onChanged: (v) => setState(() => _families[i].relation = v ?? 'father'),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextField(
                    controller: _families[i].ctrl,
                    maxLength: 100,
                    decoration: InputDecoration(
                      labelText: t('intake.medicalInfo.family.conditionPlaceholder'),
                      counterText: '',
                    ),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.remove_circle_outline),
                  onPressed: () => setState(() => _families.removeAt(i)),
                ),
              ]),
            ),
          TextButton.icon(
            icon: const Icon(Icons.add),
            label: Text(t('intake.medicalInfo.family.add')),
            onPressed: () => setState(() => _families.add(_Family())),
          ),
        ],
      ]);

  Widget _historySection(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _sectionHeader(context, t('intake.medicalInfo.history.title'), t('intake.medicalInfo.history.noneLabel'), _noHistory,
            (v) => setState(() {
                  _noHistory = v;
                  if (v) _histories.clear();
                })),
        if (!_noHistory) ...[
          for (var i = 0; i < _histories.length; i++)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(children: [
                Expanded(
                  child: TextField(
                    controller: _histories[i].ctrl,
                    maxLength: 100,
                    decoration: InputDecoration(labelText: t('intake.medicalInfo.history.placeholder'), counterText: ''),
                  ),
                ),
                const SizedBox(width: 8),
                DropdownButton<String>(
                  value: _histories[i].yearsAgo,
                  items: [for (final y in _yearsAgoKeys) DropdownMenuItem(value: y, child: Text(t('intake.medicalInfo.yearsAgo.$y')))],
                  onChanged: (v) => setState(() => _histories[i].yearsAgo = v ?? 'unsure'),
                ),
                // `stillHas` was hardcoded true with no way to say otherwise, so every
                // resolved condition reached the doctor as ongoing — silently wrong
                // clinical data, which is worse than a missing field (TODO §G medium).
                // Key `history.stillHas` was already in all five locales.
                Tooltip(
                  message: t('intake.medicalInfo.history.stillHas'),
                  child: Checkbox(
                    value: _histories[i].stillHas,
                    onChanged: (v) => setState(() => _histories[i].stillHas = v ?? true),
                  ),
                ),
                IconButton(icon: const Icon(Icons.remove_circle_outline), onPressed: () => setState(() => _histories.removeAt(i))),
              ]),
            ),
          TextButton.icon(
            icon: const Icon(Icons.add),
            label: Text(t('intake.medicalInfo.history.add')),
            onPressed: () => setState(() => _histories.add(_History())),
          ),
        ],
      ]);
}
