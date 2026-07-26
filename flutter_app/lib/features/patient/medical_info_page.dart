import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../data/api/sessions_api.dart';

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

  bool _noAllergies = false;
  bool _noMedications = false;
  bool _noHistory = false;
  final List<_Allergy> _allergies = [];
  final List<_Medication> _medications = [];
  final List<_History> _histories = [];
  final List<_Family> _families = [];

  // Optional section: no "none" checkbox, matching the React page (family history is
  // 選填 there too). Backend shape is {relation, condition}.
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

    // Intake enum fields are sent as TRANSLATED display strings (backend legacy schema).
    final allergies = _noAllergies
        ? []
        : [
            for (final a in _allergies)
              if (a.ctrl.text.trim().isNotEmpty)
                {
                  'allergen': a.ctrl.text.trim(),
                  'hadHospitalization': a.hospitalized,
                  if (a.hospitalized) 'reaction': t('intake.medicalInfo.allergy.hospitalized'),
                  if (a.hospitalized) 'severity': 'severe',
                },
          ];
    final medications = _noMedications
        ? []
        : [
            for (final m in _medications)
              if (m.ctrl.text.trim().isNotEmpty)
                {'name': m.ctrl.text.trim(), 'frequency': t('intake.medicalInfo.frequency.${m.frequency}')},
          ];
    final history = _noHistory
        ? []
        : [
            for (final h in _histories)
              if (h.ctrl.text.trim().isNotEmpty)
                {
                  'condition': h.ctrl.text.trim(),
                  'yearsAgo': t('intake.medicalInfo.yearsAgo.${h.yearsAgo}'),
                  'stillHas': h.stillHas,
                },
          ];

    final payload = {
      'chiefComplaintId': widget.args['complaintId'],
      'chiefComplaintText': widget.args['complaintText'] ?? widget.args['complaintName'],
      'language': _sessionLanguage(),
      'patientInfo': {
        'name': _nameCtrl.text.trim(),
        'gender': _gender,
        'dateOfBirth': '${dob.year.toString().padLeft(4, '0')}-${two(dob.month)}-${two(dob.day)}',
        'phone': _phoneCtrl.text.trim().isEmpty ? null : _phoneCtrl.text.trim(),
      },
      'intake': {
        'noKnownAllergies': _noAllergies || allergies.isEmpty,
        'allergies': allergies,
        'noCurrentMedications': _noMedications || medications.isEmpty,
        'currentMedications': medications,
        'noPastMedicalHistory': _noHistory || history.isEmpty,
        'medicalHistory': history,
        // Was hardcoded `[]`, so prostate-cancer family history was ALWAYS blank and the
        // doctor could not tell "never asked" from "patient denied it" (TODO G13).
        'familyHistory': [
          for (final f in _families)
            if (f.ctrl.text.trim().isNotEmpty)
              {'relation': f.relation, 'condition': f.ctrl.text.trim()},
        ],
      },
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
            args: {'name': widget.args['complaintName'] ?? t('intake.medicalInfo.complaintUnset')})),
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
            (v) => setState(() => _noAllergies = v)),
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
            (v) => setState(() => _noMedications = v)),
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
          child: Row(children: [
            Text(t('intake.medicalInfo.family.title'),
                style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(width: 8),
            Text(t('intake.medicalInfo.family.optional'),
                style: Theme.of(context).textTheme.bodySmall),
          ]),
        ),
        Text(t('intake.medicalInfo.family.hint'), style: Theme.of(context).textTheme.bodySmall),
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
      ]);

  Widget _historySection(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _sectionHeader(context, t('intake.medicalInfo.history.title'), t('intake.medicalInfo.history.noneLabel'), _noHistory,
            (v) => setState(() => _noHistory = v)),
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
