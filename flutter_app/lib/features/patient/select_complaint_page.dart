import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../data/api/complaints_api.dart';
import '../../data/models/session.dart';

// Port of SelectComplaintPage.tsx (core flow). Multi-select chief complaints (first =
// primary), optional free-text; 'Other' sentinel requires free text. Builds the
// chief_complaint_text the AI consumes (excludes the literal 'Other' word), clamped to
// 200 code points. ponytail: category grouping + the 160-cp name budget are deferred
// display niceties — not required to reach the conversation.
class SelectComplaintPage extends ConsumerStatefulWidget {
  const SelectComplaintPage({super.key});

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
      final list = await ComplaintsApi().getComplaints();
      if (!mounted) return;
      setState(() {
        _complaints = list;
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  bool get _hasOther => _selected.any((c) => c.id == otherComplaintId);
  bool get _otherNeedsText => _hasOther && _customCtrl.text.trim().isEmpty;

  // Medical-safety invariants (SelectComplaintPage.tsx): count by code points (runes) to
  // match Python len(); complaint NAMES must never be mid-truncated, only the trailing
  // custom note. TEXT_MAX=200 (backend chief_complaint_text), NAME_BUDGET=160 on joined names.
  static const _textMax = 200;
  static const _nameBudget = 160;
  static const _maxSelect = 5;

  int _cp(String s) => s.runes.length;

  String _clampCp(String s, int max) {
    final runes = s.runes.toList();
    return runes.length <= max ? s : String.fromCharCodes(runes.take(max));
  }

  String _sep() => currentLng.startsWith('zh') || currentLng.startsWith('ja') ? '、' : ', ';

  String _joinedNames([List<Complaint>? sel]) =>
      (sel ?? _selected).where((c) => c.id != otherComplaintId).map((c) => c.name).join(_sep());

  String _buildComplaintText() {
    final cjk = currentLng.startsWith('zh') || currentLng.startsWith('ja');
    final open = cjk ? '（' : ' (';
    final close = cjk ? '）' : ')';
    final names = _joinedNames();
    final custom = _customCtrl.text.trim();
    if (custom.isEmpty) return _clampCp(names, _textMax);
    if (names.isEmpty) return _clampCp(custom, _textMax); // only 'Other' -> patient's own words
    final full = '$names$open$custom$close';
    if (_cp(full) <= _textMax) return full;
    // Tail-only truncation: keep names intact, clamp only the custom note.
    final room = _textMax - _cp(names) - _cp(open) - _cp(close);
    if (room <= 0) return _clampCp(names, _textMax);
    return '$names$open${_clampCp(custom, room)}$close';
  }

  void _toggle(Complaint c) {
    final i = _selected.indexWhere((x) => x.id == c.id);
    if (i >= 0) {
      setState(() => _selected.removeAt(i));
      return;
    }
    if (_selected.length >= _maxSelect) {
      _toast(t('intake.selectComplaint.maxReached', args: {'max': _maxSelect}));
      return;
    }
    // First pick always allowed; a later pick that would push joined NAMES past the budget
    // is rejected so names are never silently truncated downstream.
    if (_selected.isNotEmpty && c.id != otherComplaintId) {
      final next = _joinedNames([..._selected, c]);
      if (_cp(next) > _nameBudget) {
        _toast(t('intake.selectComplaint.nameLimitReached'));
        return;
      }
    }
    setState(() => _selected.add(c));
  }

  void _toast(String msg) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), duration: const Duration(seconds: 2)));

  void _start() {
    if (_selected.isEmpty || _otherNeedsText) return;
    // Display name includes the localized 'Other'; clamp to TEXT_MAX for the header.
    final displayName = _clampCp(_selected.map((c) => c.name).join(_sep()), _textMax);
    context.go(prefixLngToPath('/patient/medical-info', currentLng), extra: {
      'complaintId': _selected.first.id,
      'complaintName': displayName,
      'complaintText': _buildComplaintText(),
    });
  }

  @override
  Widget build(BuildContext context) {
    // Fetch (and refetch on language change) — complaints come back pre-localized.
    if (_loadedForLng != currentLng) {
      _loadedForLng = currentLng;
      Future.microtask(_load);
    }

    return Scaffold(
      appBar: AppBar(title: Text(t('intake.selectComplaint.title'))),
      body: _loading
          ? Center(child: Text(t('intake.selectComplaint.loading')))
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
                        TextField(
                          controller: _customCtrl,
                          maxLength: 200,
                          maxLines: 2,
                          onChanged: (_) => setState(() {}),
                          decoration: InputDecoration(
                            labelText: t(_hasOther
                                ? 'intake.selectComplaint.customLabelRequired'
                                : 'intake.selectComplaint.customLabel'),
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
                      onPressed: (_selected.isEmpty || _otherNeedsText) ? null : _start,
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
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        onTap: () => _toggle(c),
        leading: selected
            ? CircleAvatar(radius: 12, child: Text('${idx + 1}', style: const TextStyle(fontSize: 12)))
            : const Icon(Icons.circle_outlined),
        title: Text(c.name),
        subtitle: c.description != null ? Text(c.description!) : null,
        trailing: idx == 0 ? Text(t('intake.selectComplaint.primaryBadge')) : null,
      ),
    );
  }
}
