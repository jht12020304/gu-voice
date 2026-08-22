import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../data/api/complaints_api.dart';
import '../../data/models/session.dart';
import '../../shared/widgets/language_action.dart';
import '../../core/theme/app_tokens.dart';
import '../../shared/widgets/ui_kit.dart';
import 'intake_route.dart';

// ── Pure helpers ───────────────────────────────────────────────────────────────
// Medical-safety invariants (SelectComplaintPage.tsx): count by code points (runes) to
// match Python len(); complaint NAMES must never be mid-truncated, only the trailing
// custom note. TEXT_MAX=200 (backend chief_complaint_text), NAME_BUDGET=160 on joined names.
const complaintTextMax = 200;
const complaintNameBudget = 160;
const complaintMaxSelect = 5;

int _cp(String s) => s.runes.length;

String clampCp(String s, int max) {
  final runes = s.runes.toList();
  return runes.length <= max ? s : String.fromCharCodes(runes.take(max));
}

String complaintSeparator(String lng) =>
    lng.startsWith('zh') || lng.startsWith('ja') ? '、' : ', ';

/// Joined complaint names, EXCLUDING the 'Other' sentinel — the literal word 「其他」 is a
/// UI placeholder, not a symptom, so it must never reach the AI / SOAP as one.
String joinedComplaintNames(List<Complaint> selected, String lng) => selected
    .where((c) => c.id != otherComplaintId)
    .map((c) => c.name)
    .join(complaintSeparator(lng));

/// What the AI / Supervisor / SOAP / red-flag layer actually consumes.
/// When 'Other' is picked the patient's own words ARE the trace of that choice: the
/// sentinel is stripped from the names and the primary FK may be a real complaint, so
/// dropping the free text would erase the choice entirely. `complaintSelectionReady`
/// therefore refuses to leave the page while 'Other' is ticked with a blank note.
String buildComplaintText({
  required List<Complaint> selected,
  required String customText,
  required String lng,
}) {
  final cjk = lng.startsWith('zh') || lng.startsWith('ja');
  final open = cjk ? '（' : ' (';
  final close = cjk ? '）' : ')';
  final names = joinedComplaintNames(selected, lng);
  final custom = customText.trim();
  if (custom.isEmpty) return clampCp(names, complaintTextMax);
  if (names.isEmpty) return clampCp(custom, complaintTextMax); // only 'Other' -> patient's own words
  final full = '$names$open$custom$close';
  if (_cp(full) <= complaintTextMax) return full;
  // Tail-only truncation: keep names intact, clamp only the custom note.
  final room = complaintTextMax - _cp(names) - _cp(open) - _cp(close);
  if (room <= 0) return clampCp(names, complaintTextMax);
  return '$names$open${clampCp(custom, room)}$close';
}

/// CTA gate. 'Other' with a blank note would produce a chief complaint with no symptom
/// in it at all (names exclude the sentinel), so the whole session would start blind.
bool complaintSelectionReady({
  required List<Complaint> selected,
  required String customText,
}) {
  if (selected.isEmpty) return false;
  final hasOther = selected.any((c) => c.id == otherComplaintId);
  return !hasOther || customText.trim().isNotEmpty;
}

/// Re-map the current picks onto a freshly fetched (re-localized) list, by id.
/// Complaints come back pre-localized, so after a mid-intake language switch the old
/// objects still carried the PREVIOUS language's `name` — and that stale name is what
/// went into `chief_complaint_text`, i.e. into the prompt and the SOAP. Re-mapping keeps
/// the patient's picks (clearing them would silently throw away their work) and only
/// swaps in the new labels; ids that no longer exist are dropped.
List<Complaint> remapSelectionToLocale(List<Complaint> selected, List<Complaint> fresh) {
  final byId = {for (final c in fresh) c.id: c};
  return [
    for (final c in selected)
      if (byId[c.id] != null) byId[c.id]!,
  ];
}

// Port of SelectComplaintPage.tsx (core flow). Multi-select chief complaints (first =
// primary), optional free-text; 'Other' sentinel requires free text. Builds the
// chief_complaint_text the AI consumes (excludes the literal 'Other' word), clamped to
// 200 code points. ponytail: category grouping + the 160-cp name budget are deferred
// display niceties — not required to reach the conversation.
class SelectComplaintPage extends ConsumerStatefulWidget {
  const SelectComplaintPage({super.key, this.api});

  /// Test seam only; production passes nothing and gets the real client.
  final ComplaintsApi? api;

  @override
  ConsumerState<SelectComplaintPage> createState() => _SelectComplaintPageState();
}

class _SelectComplaintPageState extends ConsumerState<SelectComplaintPage> {
  List<Complaint> _complaints = [];
  final List<Complaint> _selected = [];
  final _customCtrl = TextEditingController();
  bool _loading = true;
  String? _loadedForLng;

  @override
  void dispose() {
    _customCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final list = await (widget.api ?? ComplaintsApi()).getComplaints();
      if (!mounted) return;
      setState(() {
        _complaints = list;
        // Re-localize the existing picks instead of leaving them on the old language's
        // strings (see remapSelectionToLocale). The patient's own free text is NOT
        // touched — those are their words, not a label.
        final remapped = remapSelectionToLocale(_selected, list);
        _selected
          ..clear()
          ..addAll(remapped);
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  bool get _hasOther => _selected.any((c) => c.id == otherComplaintId);
  bool get _otherNeedsText => _hasOther && _customCtrl.text.trim().isEmpty;
  bool get _ready =>
      complaintSelectionReady(selected: _selected, customText: _customCtrl.text);

  void _toggle(Complaint c) {
    final i = _selected.indexWhere((x) => x.id == c.id);
    if (i >= 0) {
      setState(() => _selected.removeAt(i));
      return;
    }
    if (_selected.length >= complaintMaxSelect) {
      _toast(t('intake.selectComplaint.maxReached', args: {'max': complaintMaxSelect}));
      return;
    }
    // First pick always allowed; a later pick that would push joined NAMES past the budget
    // is rejected so names are never silently truncated downstream.
    if (_selected.isNotEmpty && c.id != otherComplaintId) {
      final next = joinedComplaintNames([..._selected, c], currentLng);
      if (_cp(next) > complaintNameBudget) {
        _toast(t('intake.selectComplaint.nameLimitReached'));
        return;
      }
    }
    setState(() => _selected.add(c));
  }

  void _toast(String msg) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), duration: const Duration(seconds: 2)));

  void _start() {
    if (!_ready) return;
    // Display name includes the localized 'Other'; clamp to TEXT_MAX for the header.
    final displayName =
        clampCp(_selected.map((c) => c.name).join(complaintSeparator(currentLng)), complaintTextMax);
    // Query params, not `extra:` — `extra` is in-memory only, so a refresh or a deep link
    // handed MedicalInfoPage a null complaintId and POST /sessions 422'd (see intake_route.dart).
    // 醫師代病患問診：/patient/start?patientId=... 進來時把 id 一路帶到 intake。
    // 讀 URL 不read state（deep link / refresh 都不掉）。
    final patientId = GoRouterState.of(context).uri.queryParameters['patientId'];
    context.go(medicalInfoLocation(
      lng: currentLng,
      patientId: patientId,
      complaintId: _selected.first.id,
      complaintName: displayName,
      complaintText: buildComplaintText(
        selected: _selected,
        customText: _customCtrl.text,
        lng: currentLng,
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    // Fetch (and refetch on language change) — complaints come back pre-localized.
    if (_loadedForLng != currentLng) {
      _loadedForLng = currentLng;
      Future.microtask(_load);
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(t('intake.selectComplaint.title')),
        actions: const [LanguageAction()],
      ),
      body: _loading
          ? const SkeletonList()
          : Column(
              children: [
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      Text(t('intake.selectComplaint.multiHint'),
                          style: Theme.of(context).textTheme.bodySmall),
                      const SizedBox(height: 8),
                      for (final c in _complaints) _complaintTile(c),
                      if (_selected.isNotEmpty) ...[
                        const SizedBox(height: 16),
                        Padding(
                          padding: const EdgeInsets.only(left: 4, bottom: 6),
                          child: Text(
                            t(_hasOther
                                ? 'intake.selectComplaint.customLabelRequired'
                                : 'intake.selectComplaint.customLabel'),
                            style: Theme.of(context).textTheme.labelLarge,
                          ),
                        ),
                        TextField(
                          controller: _customCtrl,
                          maxLength: 200,
                          maxLines: 2,
                          onChanged: (_) => setState(() {}),
                          decoration: InputDecoration(
                            // Say WHY the button is dead. Previously the CTA just went grey
                            // with nothing on screen explaining it, so a patient who picked
                            // 「其他」 was simply stuck (TODO §G medium). Key already shipped.
                            errorText: _otherNeedsText
                                ? t('intake.selectComplaint.otherRequired')
                                : null,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                SafeArea(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: FilledButton(
                      onPressed: _ready ? _start : null,
                      child: Text(_selected.isEmpty
                          ? t('intake.selectComplaint.cta')
                          : t('intake.selectComplaint.ctaCount', args: {'count': _selected.length})),
                    ),
                  ),
                ),
              ],
            ),
    );
  }

  Widget _complaintTile(Complaint c) {
    final idx = _selected.indexWhere((x) => x.id == c.id);
    final selected = idx >= 0;
    final primary = Theme.of(context).colorScheme.primary;
    final tk = Theme.of(context).extension<AppTokens>()!;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      // 已選＝primary 細邊框（比只有 leading 圓點強的 affordance；kiosk 年長使用者要一眼看出選了什麼）
      shape: selected
          ? RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(8),
              side: BorderSide(color: primary, width: 1.5),
            )
          : null,
      child: ListTile(
        onTap: () => _toggle(c),
        leading: selected
            ? CircleAvatar(
                radius: 14,
                backgroundColor: primary,
                child: Text('${idx + 1}',
                    style: const TextStyle(fontSize: 13, color: Colors.white, fontWeight: FontWeight.w700)))
            : Icon(Icons.circle_outlined, color: tk.inkMuted),
        title: Text(c.name),
        subtitle: c.description != null ? Text(c.description!) : null,
        trailing: idx == 0 ? PillTag(t('intake.selectComplaint.primaryBadge'), color: primary) : null,
      ),
    );
  }
}
